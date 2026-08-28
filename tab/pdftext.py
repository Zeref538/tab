"""Read a PDF that already contains real text — no model, no OCR, no guessing.

An e-receipt, an emailed invoice or a bank statement stores its characters as
characters. Sending that to a vision model throws away perfect data and replaces
it with a guess, slowly. So TAB looks for a text layer first and only reaches for
the model when there is nothing to read. See
docs/adr/0002-text-layer-before-vision.md.

Scope for now: the header fields. Line items from a text layer are their own
problem — every merchant lays them out differently — and they arrive in a later
slice. Until then `item_sum` simply skips, which is honest: a check that could
not run has not passed.
"""

from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path

import pymupdf

from tab.receipt import to_centavos

# How many characters a PDF must yield before it counts as having a real text
# layer. A scanned page often carries a handful of stray characters from a
# header stamp or a watermark, so "has any text" is the wrong test and "has
# enough text to be a receipt" is the right one. A calibration knob.
MIN_TEXT_CHARS = 60

# Money as it appears on paper: 1,190.00 / 1190 / 1.190,00 / 60.000
# No whitespace inside the number. Allowing it made "Milk x2    490.00" parse
# as the single value 2490.00, by swallowing the gap between two columns.
_AMOUNT = r"[-+]?\(?\d[\d.,]*\)?"

# Labels seen on Philippine receipts. Order matters inside each tuple: the
# first match wins, so the most specific label is listed first.
_LABELS: dict[str, tuple[str, ...]] = {
    "total": (r"amount\s*due", r"total\s*amount", r"grand\s*total", r"\btotal\b"),
    "subtotal": (r"sub[\s-]*total", r"amount\s*before\s*vat"),
    "vatable_sales": (r"vat[\s-]*able\s*sales", r"vatable\s*amount"),
    "vat_exempt_sales": (r"vat[\s-]*exempt\s*sales", r"vat[\s-]*exempt"),
    "zero_rated_sales": (r"zero[\s-]*rated\s*sales", r"zero[\s-]*rated"),
    "vat_amount": (r"\bvat\s*\(?12%?\)?", r"\bvat\s*amount", r"\bvat\b", r"\btax\b"),
    "service_charge": (r"service\s*charge", r"\bservice\b"),
    "discount_total": (r"\bdiscount\b", r"less\s*discount"),
}

# "TOTAL" is a substring of "SUBTOTAL", so a naive search for the first finds
# the second. Each field therefore refuses lines that belong to another field.
_EXCLUDE: dict[str, tuple[str, ...]] = {
    "total": (r"sub[\s-]*total", r"vat", r"discount", r"service", r"change", r"cash"),
    "vat_amount": (r"vat[\s-]*able", r"exempt", r"zero"),
}

_TIN = re.compile(r"\bTIN\b[^0-9]{0,12}([\d][\d\s\-]{6,})", re.IGNORECASE)
# "OR No.: 0099123" carries two punctuation marks in a row, so a single optional
# one is not enough. The captured number must also contain a digit, otherwise a
# heading like "OFFICIAL RECEIPT" earlier on the page grabs the word after it.
_OR = re.compile(
    r"\b(?:OR|O\.R\.|SI|INVOICE|RECEIPT)\s*(?:NO|NUM|NUMBER|#)?[\s:.#-]*([A-Z0-9-]{3,})",
    re.IGNORECASE)

_DATE_PATTERNS = (
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), ("y", "m", "d")),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), ("m", "d", "y")),
    (re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b"), ("m", "d", "y")),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b"), ("d", "mon", "y")),
    (re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b"), ("mon", "d", "y")),
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def read_text(path: str | Path) -> tuple[str, int]:
    """Return (text, page count) from the PDF's own text layer."""
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc), doc.page_count


def has_text_layer(text: str) -> bool:
    """Enough real characters to be worth parsing, and some of them digits.

    A receipt without digits is not a receipt, so the digit test rules out a
    scanned page whose only text is a watermark.
    """
    stripped = "".join(text.split())
    return len(stripped) >= MIN_TEXT_CHARS and any(c.isdigit() for c in stripped)


def _find_amount(lines: list[str], field: str) -> int | None:
    """First line whose label matches and which is not another field's line."""
    excludes = [re.compile(p, re.IGNORECASE) for p in _EXCLUDE.get(field, ())]
    for pattern in _LABELS[field]:
        label = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            if not label.search(line):
                continue
            if any(e.search(line) for e in excludes):
                continue
            # Take the LAST number on the line: labels sometimes carry a rate,
            # as in "VAT (12%)  127.50", and the amount is what sits at the end.
            numbers = re.findall(_AMOUNT, line)
            numbers = [n for n in (n.strip() for n in numbers) if any(c.isdigit() for c in n)]
            if not numbers:
                continue
            value = to_centavos(numbers[-1])
            if value is not None:
                return value
    return None


def _find_date(text: str) -> str | None:
    """First date that is a real calendar date and not in the future."""
    for pattern, order in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            parts = dict(zip(order, match.groups()))
            try:
                month = (_MONTHS[parts["mon"][:3].lower()] if "mon" in parts
                         else int(parts["m"]))
                found = _date(int(parts["y"]), month, int(parts["d"]))
            except (KeyError, ValueError):
                continue
            if found <= _date.today():
                return found.isoformat()
    return None


def _find_merchant(lines: list[str]) -> str | None:
    """The shop name is the first substantial line that is not a number.

    Crude, and deliberately so: a wrong merchant fails `total_sane` and the
    receipt goes to a human, which is the right outcome for a guess.
    """
    for line in lines[:8]:
        cleaned = line.strip(" \t*-=_")
        if len(cleaned) < 3:
            continue
        letters = sum(c.isalpha() for c in cleaned)
        if letters >= 3 and letters >= len(cleaned) * 0.4:
            return cleaned[:120]
    return None


def parse(text: str) -> dict:
    """Text from a receipt PDF into the one TAB receipt shape."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tin = _TIN.search(text)
    or_number = next((m for m in _OR.finditer(text)
                      if any(c.isdigit() for c in m.group(1))), None)

    receipt = {
        "merchant": _find_merchant(lines),
        "tin": re.sub(r"\s+", "", tin.group(1)).strip("-") if tin else None,
        "or_number": or_number.group(1) if or_number else None,
        "date": _find_date(text),
        "currency": "PHP",
        "line_items": [],  # a later slice; skipping is honest, guessing is not
    }
    for field in _LABELS:
        receipt[field] = _find_amount(lines, field)
    return receipt


def extract(path: str | Path) -> tuple[dict, dict] | None:
    """Read a PDF via its text layer, or return None if it has no usable one.

    None means "not my job" — the caller routes to the vision model instead.
    """
    text, pages = read_text(path)
    if not has_text_layer(text):
        return None
    return parse(text), {
        "method": "text_layer",
        "pages": pages,
        "characters": len("".join(text.split())),
        "raw": text,
    }
