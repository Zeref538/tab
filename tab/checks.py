"""The arithmetic guard — the cheapest and strongest thing in this project.

A receipt is a document that checks itself: the merchant printed the parts and
the sum side by side. If they disagree, something was misread, and we know it
without asking any model how confident it feels. Model confidence measures
fluency, not correctness — see docs/adr/0003.

Every check here is decidable with addition. No model is consulted.

One Philippine wrinkle drives the design: displayed prices here include VAT by
law, so `subtotal + VAT = total` is frequently WRONG — the VAT is already inside
the total. Both conventions are accepted, and the check reports which one
matched rather than silently assuming.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from tab.receipt import VAT_RATE_PERCENT, pesos

# Centavos of slack allowed in any comparison. A calibration knob, not a magic
# number: real receipts round in ways a clean model does not predict. Too loose
# lets wrong receipts through (silent errors); too tight escalates everything
# (useless tool). Both directions are measured on the labelled set.
DEFAULT_TOLERANCE = 5  # ₱0.05

PASS, FAIL, SKIP = "pass", "fail", "skip"

# Checks that constitute actual arithmetic verification. A receipt where every
# one of these skipped has not been verified at all, however clean it looks.
ARITHMETIC_CHECKS = {"line_math", "item_sum", "vat_split", "vat_rate", "total_math"}

# Which fields a failing check is actually accusing. This is what the review
# screen highlights, so it lives next to the checks rather than in the browser -
# a check and the field it points at drifting apart is how a person ends up
# "correcting" a number that was right all along.
FIELDS_BY_CHECK: dict[str, tuple[str, ...]] = {
    "total_math": ("total",),
    "item_sum": ("subtotal",),
    "vat_rate": ("vat_amount", "vatable_sales"),
    "vat_split": ("vatable_sales", "vat_exempt_sales", "zero_rated_sales"),
    "total_sane": ("total", "merchant"),
    "date_sane": ("date",),
    "line_math": (),        # named per line by accused(), below
}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def _within(a: int | None, b: int | None, tol: int) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _sum_or_none(values) -> int | None:
    """Sum the present values. None if none of them were present at all.

    Missing is not zero. A receipt with no VAT breakdown extracted must skip the
    VAT checks, not pass them by summing nothing to zero.
    """
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _first_match(actual: int | None, candidates: list[tuple[str, int | None]], tol: int):
    """Return the label of the first candidate within tolerance, or None."""
    for label, value in candidates:
        if _within(actual, value, tol):
            return label
    return None


def run(r: dict, tolerance: int = DEFAULT_TOLERANCE) -> list[Check]:
    """Run every check that has the data to run. Order is display order."""
    out: list[Check] = []
    total = r.get("total")
    subtotal = r.get("subtotal")
    vat = r.get("vat_amount")
    discount = r.get("discount_total") or 0
    service = r.get("service_charge") or 0
    items = r.get("line_items") or []
    parts = _sum_or_none([r.get("vatable_sales"), r.get("vat_exempt_sales"),
                          r.get("zero_rated_sales")])

    # --- format sanity -------------------------------------------------
    if total is None:
        out.append(Check("total_sane", FAIL, "no total was read from this receipt"))
    elif total <= 0:
        out.append(Check("total_sane", FAIL, f"total is {pesos(total)}, which cannot be right"))
    elif not r.get("merchant"):
        out.append(Check("total_sane", FAIL, "no merchant name was read"))
    else:
        out.append(Check("total_sane", PASS, f"total {pesos(total)}, merchant present"))

    date = r.get("date")
    if not date:
        out.append(Check("date_sane", FAIL, "no date was read from this receipt"))
    else:
        try:
            parsed = _dt.date.fromisoformat(str(date)[:10])
        except ValueError:
            out.append(Check("date_sane", FAIL, f"date {date!r} is not a real date"))
        else:
            if parsed > _dt.date.today():
                out.append(Check("date_sane", FAIL, f"date {parsed} is in the future"))
            else:
                out.append(Check("date_sane", PASS, str(parsed)))

    # --- per-line arithmetic -------------------------------------------
    checkable = [i for i in items
                 if i.get("qty") is not None and i.get("unit_price") is not None
                 and i.get("amount") is not None]
    if not checkable:
        out.append(Check("line_math", SKIP, "no line has quantity, unit price and amount"))
    else:
        bad = [i for i in checkable
               if not _within(round(i["qty"] * i["unit_price"]), i["amount"], tolerance)]
        if bad:
            first = bad[0]
            out.append(Check("line_math", FAIL,
                             f"line {first['line_no']}: {first['qty']} × "
                             f"{pesos(first['unit_price'])} is "
                             f"{pesos(round(first['qty'] * first['unit_price']))}, "
                             f"but the line reads {pesos(first['amount'])}"
                             + (f" ({len(bad)} lines disagree)" if len(bad) > 1 else "")))
        else:
            out.append(Check("line_math", PASS, f"{len(checkable)} lines multiply correctly"))

    # --- items against the subtotal ------------------------------------
    # A line discount belongs to its line: a buy-one-get-one prints both lines
    # at full price and knocks one off, so the subtotal is the NET of the two.
    item_total = _sum_or_none([
        None if i.get("amount") is None else i["amount"] - abs(i.get("discount") or 0)
        for i in items])
    if item_total is None or subtotal is None:
        out.append(Check("item_sum", SKIP, "no line amounts, or no subtotal, to compare"))
    elif _within(item_total, subtotal, tolerance):
        out.append(Check("item_sum", PASS, f"{len(items)} items add up to {pesos(subtotal)}"))
    else:
        out.append(Check("item_sum", FAIL,
                         f"items add up to {pesos(item_total)} but the receipt says "
                         f"{pesos(subtotal)}. Difference: {pesos(abs(item_total - subtotal))}"))

    # --- the VAT breakdown ---------------------------------------------
    if parts is None or subtotal is None:
        out.append(Check("vat_split", SKIP, "no VAT breakdown to check"))
    else:
        # A service charge is itself VATable here, so on a restaurant bill the
        # VATable base is subtotal + service, not subtotal. Both bases are
        # offered, in both VAT conventions.
        bases = [("subtotal", subtotal)]
        if service:
            bases.append(("subtotal + service charge", subtotal + service))
        candidates: list[tuple[str, int | None]] = []
        for label, base in bases:
            candidates.append((f"VAT-exclusive, {label}", base))
            if vat is not None:
                candidates.append((f"VAT-inclusive, {label}", base - vat))

        matched = _first_match(parts, candidates, tolerance)
        if matched:
            out.append(Check("vat_split", PASS,
                             f"VATable + exempt + zero-rated reach {pesos(parts)} "
                             f"({matched})"))
        else:
            out.append(Check("vat_split", FAIL,
                             f"VAT breakdown adds to {pesos(parts)}, which does not "
                             f"match the subtotal of {pesos(subtotal)}"))

    vatable = r.get("vatable_sales")
    currency = (r.get("currency") or "PHP").upper()
    if vat is None or vatable is None:
        out.append(Check("vat_rate", SKIP, "no VAT amount or no VATable sales stated"))
    elif currency != "PHP":
        # 12% is Philippine law, not arithmetic. Judging an Indonesian or
        # Singaporean receipt by it guarantees a failure that says nothing
        # about whether the receipt was read correctly.
        out.append(Check("vat_rate", SKIP,
                         f"{currency} receipt — the {VAT_RATE_PERCENT}% rule is "
                         f"Philippine and does not apply"))
    else:
        expected = round(vatable * VAT_RATE_PERCENT / 100)
        if _within(vat, expected, tolerance):
            out.append(Check("vat_rate", PASS,
                             f"VAT {pesos(vat)} is {VAT_RATE_PERCENT}% of {pesos(vatable)}"))
        else:
            out.append(Check("vat_rate", FAIL,
                             f"VAT should be {pesos(expected)} "
                             f"({VAT_RATE_PERCENT}% of {pesos(vatable)}) "
                             f"but the receipt says {pesos(vat)}"))

    # --- the whole receipt ---------------------------------------------
    # Both Philippine conventions are legitimate, so both are offered.
    # A service charge is added, never optional: if one was read, it must be in
    # the sum. No "maybe without it" candidate — that would just be a second way
    # for a misread receipt to pass.
    candidates: list[tuple[str, int | None]] = []
    if subtotal is not None:
        candidates.append(("VAT-inclusive", subtotal + service - discount))
        if vat is not None:
            candidates.append(("VAT-exclusive", subtotal + service + vat - discount))
    if parts is not None:
        if vat is not None:
            candidates.append(("VAT-inclusive breakdown", parts + service + vat - discount))
        candidates.append(("VAT-exclusive breakdown", parts + service - discount))

    if total is None or not candidates:
        out.append(Check("total_math", SKIP, "not enough parts to rebuild the total"))
    else:
        matched = _first_match(total, candidates, tolerance)
        if matched:
            out.append(Check("total_math", PASS, f"the parts reach {pesos(total)} ({matched})"))
        else:
            label, best = min(candidates, key=lambda c: abs(total - c[1]) if c[1] is not None
                              else 10 ** 12)
            out.append(Check("total_math", FAIL,
                             f"the parts add up to {pesos(best)} but the receipt says "
                             f"{pesos(total)}. Difference: {pesos(abs(total - best))}"))
    return out


def accused(checks: list[Check], receipt: dict,
            tolerance: int = DEFAULT_TOLERANCE) -> list[str]:
    """The fields a person should look at, given what failed.

    `line_math` names the exact line rather than the subtotal, because the two
    point in opposite directions. A receipt whose third line reads 80.00 where
    3 x 30.00 should be 90.00 has a *correct* subtotal - highlighting it would
    walk someone into changing a right number into a wrong one.
    """
    out: list[str] = []
    failed = {c.name for c in checks if c.status == FAIL}
    for name in sorted(failed):
        out.extend(FIELDS_BY_CHECK.get(name, ()))

    if "line_math" in failed:
        for item in receipt.get("line_items") or []:
            qty, unit, amount = (item.get("qty"), item.get("unit_price"),
                                 item.get("amount"))
            if qty is None or unit is None or amount is None:
                continue
            if not _within(round(qty * unit), amount, tolerance):
                out.append(f"item.{item['line_no']}.amount")
    return out


def verdict(checks: list[Check]) -> tuple[str, str]:
    """`commit` or `needs_review`, with the reason in words for the screen."""
    failed = [c for c in checks if c.failed]
    if failed:
        return "needs_review", failed[0].detail

    verified = [c for c in checks if c.name in ARITHMETIC_CHECKS and c.status == PASS]
    if not verified:
        # The blind spot, made loud. Nothing arithmetic could run, so nothing was
        # actually verified — committing here is exactly how a silent error gets
        # written into a tax record.
        return "needs_review", "nothing on this receipt could be checked against itself"

    return "commit", f"{len(verified)} arithmetic checks passed"
