"""The one shape a receipt takes, everywhere.

The gold labels, the model output and the scorer all read this. Three formats
would be three bugs, so there is exactly one.

**Every amount is an integer number of centavos.** Floats do not represent
PHP 0.10 exactly, and the whole product is an equality test on money. A float
subtotal would make the arithmetic guard fail on rounding noise it invented
itself. Display divides by 100 at the very edge and nowhere else.
"""

from __future__ import annotations

import re

# Fields carrying money, all in centavos. Kept as a list because the checks,
# the scorer and the SQLite writer all need to agree on which fields are money.
AMOUNT_FIELDS = [
    "subtotal",
    "vatable_sales",
    "vat_exempt_sales",
    "zero_rated_sales",
    "vat_amount",
    "service_charge",
    "discount_total",
    "total",
]

TEXT_FIELDS = ["merchant", "tin", "or_number", "date", "currency"]

# Philippine VAT rate. Not a setting — it is the law, and a receipt that
# disagrees with it is a receipt that was misread.
VAT_RATE_PERCENT = 12

_AMOUNT = {"type": ["integer", "null"], "description": "centavos"}

RECEIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["merchant", "date", "total", "currency"],
    "properties": {
        "merchant": {"type": ["string", "null"]},
        "tin": {"type": ["string", "null"]},
        "or_number": {"type": ["string", "null"]},
        "date": {"type": ["string", "null"], "description": "ISO 8601 date, no time"},
        "currency": {"type": "string", "default": "PHP"},
        "subtotal": _AMOUNT,
        "vatable_sales": _AMOUNT,
        "vat_exempt_sales": _AMOUNT,
        "zero_rated_sales": _AMOUNT,
        "vat_amount": _AMOUNT,
        "service_charge": _AMOUNT,
        "discount_total": _AMOUNT,
        "total": _AMOUNT,
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["line_no", "description"],
                "properties": {
                    "line_no": {"type": "integer", "minimum": 1},
                    "description": {"type": ["string", "null"]},
                    "qty": {"type": ["number", "null"], "description": "0.5 kg is a real quantity"},
                    "unit_price": _AMOUNT,
                    "amount": _AMOUNT,
                    "discount": _AMOUNT,
                },
            },
        },
    },
}

# Currency symbols and codes that show up on receipts, stripped before parsing.
_CURRENCY_JUNK = re.compile(r"[₱$€£¥]|\b(?:php|pesos?|usd)\b", re.IGNORECASE)
_NOT_NUMBER = re.compile(r"[^0-9.,\-()]")


def to_centavos(value) -> int | None:
    """Parse a printed amount into centavos.

    Handles what actually appears on paper: "₱1,190.00", "1 190,00", "P 45",
    "(12.50)" for a negative, and a bare number. Returns None when there is no
    number in there at all — never 0, because a missing total and a zero total
    are different facts and confusing them is how a wrong row gets committed.
    """
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value * 100)

    s = _CURRENCY_JUNK.sub("", str(value)).strip()
    negative = s.startswith("(") and s.endswith(")")
    s = _NOT_NUMBER.sub("", s).strip("()")
    if not s or s in {"-", ".", ","}:
        return None

    # Decide which separator is the decimal point. The last one wins if it is
    # followed by exactly two digits; otherwise both are thousands separators.
    last_dot, last_comma = s.rfind("."), s.rfind(",")
    cut = max(last_dot, last_comma)
    if cut != -1 and len(s) - cut - 1 == 2:
        whole, frac = s[:cut], s[cut + 1:]
    else:
        whole, frac = s, "00"
    whole = re.sub(r"[.,]", "", whole) or "0"
    try:
        centavos = int(whole) * 100 + int(frac.ljust(2, "0")[:2])
    except ValueError:
        return None
    if negative or whole.startswith("-"):
        centavos = -abs(centavos)
    return centavos


def pesos(centavos: int | None) -> str:
    """Centavos to something a person reads. The only place we divide by 100."""
    if centavos is None:
        return "—"
    sign = "-" if centavos < 0 else ""
    return f"{sign}₱{abs(centavos) // 100:,}.{abs(centavos) % 100:02d}"


def normalise(raw: dict) -> dict:
    """Coerce whatever came back into the one shape, without inventing values.

    Anything unparseable becomes None so it fails a check loudly, rather than
    becoming 0 and passing one quietly.
    """
    out = {f: (str(raw[f]).strip() or None) if raw.get(f) is not None else None
           for f in TEXT_FIELDS}
    out["currency"] = out.get("currency") or "PHP"
    for f in AMOUNT_FIELDS:
        out[f] = to_centavos(raw.get(f))

    items = []
    for i, item in enumerate(raw.get("line_items") or [], start=1):
        if not isinstance(item, dict):
            continue
        qty = item.get("qty")
        try:
            qty = float(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty = None
        items.append({
            "line_no": int(item.get("line_no") or i),
            "description": (str(item["description"]).strip() or None)
                           if item.get("description") is not None else None,
            "qty": qty,
            "unit_price": to_centavos(item.get("unit_price")),
            "amount": to_centavos(item.get("amount")),
            "discount": to_centavos(item.get("discount")),
        })
    out["line_items"] = items
    return out


def demo() -> None:
    """Self-check. Run: python -m tab.receipt"""
    assert to_centavos("₱1,190.00") == 119000
    assert to_centavos("1190") == 119000
    assert to_centavos("1,190") == 119000
    assert to_centavos("P 45.50") == 4550
    assert to_centavos("0.05") == 5
    assert to_centavos("(12.50)") == -1250
    assert to_centavos("1.190,00") == 119000, "European separators"
    assert to_centavos(1190.0) == 119000
    assert to_centavos(119000) == 119000
    assert to_centavos("") is None
    assert to_centavos("n/a") is None
    assert to_centavos(None) is None
    # A missing amount must never become zero.
    assert to_centavos("—") is None

    assert pesos(119000) == "₱1,190.00"
    assert pesos(5) == "₱0.05"
    assert pesos(None) == "—"

    r = normalise({"merchant": " SM ", "total": "₱1,190.00", "date": "2026-08-12",
                   "line_items": [{"description": "Rice", "qty": "2", "amount": "50.00"}]})
    assert r["merchant"] == "SM"
    assert r["total"] == 119000
    assert r["currency"] == "PHP"
    assert r["subtotal"] is None, "absent stays absent, never 0"
    assert r["line_items"][0]["line_no"] == 1
    assert r["line_items"][0]["qty"] == 2.0
    assert r["line_items"][0]["amount"] == 5000
    print("tab.receipt: all checks passed")


if __name__ == "__main__":
    demo()
