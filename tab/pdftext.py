"""Read a PDF that already contains real text — no model, no OCR, no guessing.

An e-receipt, an emailed invoice or a bank statement stores its characters as
characters. Sending that to a vision model throws away perfect data and replaces
it with a guess, slowly. So TAB looks for a text layer first and only reaches for
the model when there is nothing to read. See
docs/adr/0002-text-layer-before-vision.md.

Line items are read too, because `item_sum` — do the items add up to the
subtotal — is the strongest guard TAB has, and it cannot run without them.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
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
    # "DISC" is how a till abbreviates it once the paper is narrow, and a line
    # reading "TOTAL DISC" is a discount, not a total.
    "discount_total": (r"total\s*disc", r"\bdiscount\b", r"less\s*disc",
                       r"\bdisc\b"),
}

# "TOTAL" is a substring of "SUBTOTAL", so a naive search for the first finds
# the second. Each field therefore refuses lines that belong to another field.
_EXCLUDE: dict[str, tuple[str, ...]] = {
    "total": (r"sub[\s-]*total", r"vat", r"\bdisc", r"service", r"change", r"cash"),
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


# The word each field is really looking for, letters only, for when the regex
# above misses. Measured on 100 real Philippine receipt photographs: OCR prints
# "Sabtotal" for SUBTOTAL, "UAI Amount" for VAT AMOUNT and "VAtable" for
# VATABLE, and a regex is exact, so one wrong letter silences the check. 79 of
# those 100 lost their subtotal that way - and the item-sum guard, the strongest
# one TAB has, cannot run without a subtotal. See docs/ph-first-look.md.
_FUZZY: dict[str, str] = {
    "subtotal": "SUBTOTAL",
    "vatable_sales": "VATABLESALES",
    "vat_exempt_sales": "VATEXEMPTSALES",
    "zero_rated_sales": "ZERORATEDSALES",
    "vat_amount": "VATAMOUNT",
    "service_charge": "SERVICECHARGE",
}

# How alike a mangled word has to be. 0.8 lets one letter in five be wrong,
# which covers every misspelling seen in the sample; 0.7 started matching
# "TOTAL" as "SUBTOTAL" and would have written the wrong number into a ledger.
FUZZY_RATIO = 0.8


def _looks_like(line: str, word: str) -> bool:
    """Does any run of letters in this line nearly spell `word`?

    difflib is standard library and does the whole job: it scores two strings
    for likeness, so "SABTOTAL" against "SUBTOTAL" comes back 0.875 without
    anyone having to guess in advance which letter OCR will get wrong.
    """
    letters = "".join(c for c in line.upper() if c.isalpha())
    span = len(word)
    if len(letters) < span - 2:
        return False
    # Slide a window the length of the word across the line: the label sits in
    # the middle of "7 ITEN(S) SABTOTAL 227.00", not at either end.
    for start in range(len(letters) - span + 3):
        chunk = letters[start:start + span + 2]
        if SequenceMatcher(None, chunk, word).ratio() >= FUZZY_RATIO:
            return True
    return False


def _find_amount(lines: list[str], field: str) -> int | None:
    """First line whose label matches and which is not another field's line."""
    excludes = [re.compile(p, re.IGNORECASE) for p in _EXCLUDE.get(field, ())]
    patterns = [re.compile(p, re.IGNORECASE) for p in _LABELS[field]]
    fuzzy = _FUZZY.get(field)
    for label in patterns + ([fuzzy] if fuzzy else []):
        for line in lines:
            hit = (_looks_like(line, label) if isinstance(label, str)
                   else label.search(line))
            if not hit:
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


# An item's amount, as printed: 1,190.00 — a comma group and exactly two
# decimals. Deliberately stricter than _AMOUNT, which is used for labelled
# fields where the label already proves the line is about money. Here there is
# no label, so the shape of the number is the only evidence, and "000-123-456"
# in a TIN would otherwise become an item worth nothing.
_ITEM_AMOUNT = re.compile(r"(?<![\d.,])(\d[\d,]*\.\d{2})(?![\d])")

# A quantity is only believed when the receipt says so out loud: "2 x Milk" or
# "2 @ 245.00". Guessing which column is the quantity from a line like
# "Milk 2 245.00 490.00" means picking the reading that makes the arithmetic
# work — which would make line_math prove nothing, since it would be checking a
# parse chosen to satisfy it. Unlabelled columns are left empty and line_math
# skips them, which is the honest answer.
_QTY_UNIT = re.compile(r"(?<![\d.,])(\d+(?:\.\d+)?)\s*[xX@]\s*(\d[\d,]*\.\d{2})?")

# Lines that are part of the totals block or the payment block, not the basket.
_NOT_AN_ITEM = re.compile(
    r"sub[\s-]*total|total|amount\s*due|vat|vat[\s-]*able|exempt|"
    r"zero[\s-]*rated|tax|discount|service\s*charge|cash|change|"
    r"tender|balance|change\s*due|TIN|OR\s*No",
    re.IGNORECASE)

# Reaching one of these means the basket is over. Anything after it is totals,
# payment or a thank-you, and treating those as items is how a receipt gets a
# phantom line.
_END_OF_ITEMS = re.compile(r"sub[\s-]*total|total|amount\s*due", re.IGNORECASE)


# The same words again, spelled plainly, for when OCR mangles them. The regexes
# above are exact, and a photographed receipt gives you "IOTAL. DUE", "CHWHGE",
# "UAT Exenpt Sales" and "Vetable Sales" - so the basket ran on past its end and
# counted the totals block as things somebody bought. Measured on 100 real
# Philippine receipts: one showed six "items", of which three were the total,
# the cash tendered and the VAT-exempt line.
_END_WORDS = ("SUBTOTAL", "AMOUNTDUE", "TOTALDUE", "TOTAL")
_NOT_ITEM_WORDS = ("VATABLESALES", "VATEXEMPT", "ZERORATED", "VATAMOUNT",
                   "CHANGE", "TENDERED", "CASH")


def _nearly(line: str, words: tuple[str, ...]) -> bool:
    return any(_looks_like(line, w) for w in words)


def _find_line_items(lines: list[str]) -> list[dict]:
    """The basket: every line that names something and gives its amount.

    A misread here is not silent. If the amounts do not reach the subtotal,
    `item_sum` fails and the receipt goes to a person — which is the right
    outcome for a guess, and the reason this parser is allowed to be simple.
    """
    items: list[dict] = []
    for line in lines:
        if _END_OF_ITEMS.search(line) or _nearly(line, _END_WORDS):
            break
        if _NOT_AN_ITEM.search(line) or _nearly(line, _NOT_ITEM_WORDS):
            continue

        amounts = _ITEM_AMOUNT.findall(line)
        if not amounts:
            continue

        amount = to_centavos(amounts[-1])
        qty = unit_price = None
        stated = _QTY_UNIT.search(line)
        if stated:
            qty = float(stated.group(1))
            if stated.group(2):
                unit_price = to_centavos(stated.group(2))

        # Whatever is left once the numbers are taken out is the thing bought.
        description = _ITEM_AMOUNT.sub("", line)
        description = _QTY_UNIT.sub("", description).strip(" 	.-:*x@")
        if sum(c.isalpha() for c in description) < 2:
            continue        # a bare number is a column, not a purchase

        items.append({
            "line_no": len(items) + 1,
            "description": description[:200],
            "qty": qty,
            "unit_price": unit_price,
            "amount": amount,
        })
    return items


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
        "line_items": _find_line_items(lines),
    }
    for field in _LABELS:
        receipt[field] = _find_amount(lines, field)

    # A discount is printed as a deduction - "-60.000" - but every check here
    # SUBTRACTS it, so storing the minus sign would add the discount back on and
    # the totals would stop reaching each other. The magnitude is the fact; the
    # sign is just how the till renders "take this off".
    if receipt["discount_total"] is not None:
        receipt["discount_total"] = abs(receipt["discount_total"])
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
