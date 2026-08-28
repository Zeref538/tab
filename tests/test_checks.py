"""The arithmetic guard is the floor this whole project stands on.

If these ever go green while the logic is broken, TAB has no floor at all — it
becomes a confident guesser writing numbers into someone tax records. So the
cases here are the ones that must never regress.

Run: pytest tests/test_checks.py -q      (or: python tests/test_checks.py)
"""

import copy
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab.checks import DEFAULT_TOLERANCE, accused, run, verdict  # noqa: E402


def named(checks):
    return {c.name: c for c in checks}


# A real-shaped Philippine receipt: prices include VAT, which is the legal
# default here. Total 1,190.00 = VATable 1,062.50 + VAT 127.50.
CLEAN = {
    "merchant": "SM Supermarket",
    "tin": "000-123-456-000",
    "or_number": "0099123",
    "date": "2026-08-12",
    "currency": "PHP",
    "subtotal": 119000,
    "vatable_sales": 106250,
    "vat_exempt_sales": 0,
    "zero_rated_sales": 0,
    "vat_amount": 12750,
    "discount_total": 0,
    "total": 119000,
    "line_items": [
        {"line_no": 1, "description": "Rice 5kg", "qty": 1, "unit_price": 70000, "amount": 70000},
        {"line_no": 2, "description": "Milk 1L", "qty": 2, "unit_price": 24500, "amount": 49000},
    ],
}


def receipt(**overrides):
    r = copy.deepcopy(CLEAN)
    r.update(overrides)
    return r


def test_clean_receipt_commits():
    checks = run(CLEAN)
    assert [c.name for c in checks if c.failed] == []
    action, why = verdict(checks)
    assert action == "commit", why
    # It was genuinely verified, not merely un-failed.
    assert named(checks)["item_sum"].status == "pass"
    assert named(checks)["vat_rate"].status == "pass"
    assert named(checks)["total_math"].status == "pass"


def test_total_off_by_fifty_centavos_escalates():
    """The headline case. Fifty centavos wrong is still wrong."""
    checks = run(receipt(total=119050))
    assert named(checks)["total_math"].failed
    action, why = verdict(checks)
    assert action == "needs_review"
    assert "₱0.50" in named(checks)["total_math"].detail


def test_items_that_do_not_reach_the_subtotal_escalate():
    bad = receipt()
    bad["line_items"][1]["amount"] = 44000  # 50.00 short
    checks = run(bad)
    assert named(checks)["item_sum"].failed
    assert "₱50.00" in named(checks)["item_sum"].detail
    assert verdict(checks)[0] == "needs_review"


def test_line_that_does_not_multiply_escalates():
    bad = receipt()
    bad["line_items"][1]["qty"] = 3  # 3 x 245 is not 490
    checks = run(bad)
    assert named(checks)["line_math"].failed
    assert verdict(checks)[0] == "needs_review"


def test_vat_that_is_not_twelve_percent_escalates():
    checks = run(receipt(vat_amount=12000))
    assert named(checks)["vat_rate"].failed
    assert verdict(checks)[0] == "needs_review"


def test_vat_rate_rule_is_philippine_only():
    """12% is Philippine law, not arithmetic.

    Measured on CORD: this check passed 0 times and failed 16, purely because
    Indonesian receipts do not use a 12% rate. That is a broken check, not a
    misread receipt, and it was inflating the escalation count.
    """
    foreign = receipt(currency="IDR")
    assert named(run(foreign))["vat_rate"].status == "skip"
    assert named(run(receipt(currency="PHP")))["vat_rate"].status == "pass"


def test_vat_exclusive_receipt_also_commits():
    """The other legal convention: VAT added on top rather than baked in."""
    r = receipt(subtotal=106250, vat_amount=12750, total=119000,
                line_items=[{"line_no": 1, "description": "Service", "qty": 1,
                             "unit_price": 106250, "amount": 106250}])
    checks = run(r)
    assert [c.name for c in checks if c.failed] == []
    assert verdict(checks)[0] == "commit"
    assert "VAT-exclusive" in named(checks)["total_math"].detail


def test_discount_is_subtracted():
    r = receipt(discount_total=10000, total=109000)
    assert not named(run(r))["total_math"].failed


def test_service_charge_is_part_of_the_total():
    """A restaurant bill is subtotal + service charge + VAT.

    Found by running the guard against CORD gold labels: 12 of 100 receipts
    carried a service charge that the mapping was dropping, so correct receipts
    were being escalated. The receipt had more parts than the model of it did.
    """
    r = receipt(subtotal=119000, service_charge=8925, total=127925)
    assert not named(run(r))["total_math"].failed
    # And it is not optional: a service charge that is read must be in the sum.
    assert named(run(receipt(service_charge=8925)))["total_math"].failed


def test_service_charge_is_itself_vatable():
    """A restaurant bill: 1,000 + 100 service, and the VAT is 12% of 1,100.

    Found with a generated fixture receipt. The VATable base on a bill with a
    service charge is subtotal + service, not subtotal, so checking the VAT
    split against the bare subtotal escalated a perfectly correct bill.
    """
    bill = {
        "merchant": "Mang Inasal", "date": "2026-07-30", "currency": "PHP",
        "subtotal": 100000, "service_charge": 10000,
        "vatable_sales": 110000, "vat_amount": 13200, "total": 123200,
        "line_items": [],
    }
    checks = named(run(bill))
    assert not checks["vat_split"].failed, checks["vat_split"].detail
    assert not checks["vat_rate"].failed, "13,200 is 12% of 110,000"
    assert not checks["total_math"].failed
    assert verdict(run(bill))[0] == "commit"


def test_tolerance_boundary():
    """At the knob, one centavo either side of it."""
    assert not named(run(receipt(total=119000 + DEFAULT_TOLERANCE)))["total_math"].failed
    assert named(run(receipt(total=119000 + DEFAULT_TOLERANCE + 1)))["total_math"].failed


def test_nothing_checkable_does_not_commit():
    """The blind spot, guarded.

    Merchant, date and total only — nothing to check them against. No check
    FAILS, so a naive verdict would happily commit an unverified number. That
    is precisely how a silent error reaches a tax record.
    """
    thin = {"merchant": "Sari-sari Store", "date": "2026-08-12", "currency": "PHP",
            "total": 5000, "line_items": []}
    checks = run(thin)
    assert [c.name for c in checks if c.failed] == [], "nothing should fail here"
    action, why = verdict(checks)
    assert action == "needs_review"
    assert "could be checked" in why


def test_missing_total_fails_loudly():
    checks = run(receipt(total=None))
    assert named(checks)["total_sane"].failed
    assert verdict(checks)[0] == "needs_review"


def test_zero_is_not_the_same_as_missing():
    """A missing VAT must skip its check, not pass it by summing to zero."""
    r = receipt(vat_amount=None, vatable_sales=None)
    checks = named(run(r))
    assert checks["vat_rate"].status == "skip"
    assert not checks["vat_rate"].failed


def test_future_date_escalates():
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    checks = run(receipt(date=tomorrow))
    assert named(checks)["date_sane"].failed
    assert verdict(checks)[0] == "needs_review"


def test_unparseable_date_escalates():
    assert named(run(receipt(date="12/08/2026")))["date_sane"].failed


def test_a_broken_line_accuses_the_line_and_not_only_the_subtotal():
    """The screen highlights whatever this returns, so getting it wrong sends
    someone to change a number that was right. A receipt whose third line reads
    80.00 where 3 x 30.00 should be 90.00 has a CORRECT subtotal."""
    receipt = {
        "subtotal": 31400, "total": 31400, "currency": "PHP",
        "merchant": "JOLLIBEE", "date": "2026-07-22",
        "line_items": [
            {"line_no": 1, "qty": 2.0, "unit_price": 8200, "amount": 16400},
            {"line_no": 2, "qty": 1.0, "unit_price": 6000, "amount": 6000},
            {"line_no": 3, "qty": 3.0, "unit_price": 3000, "amount": 8000},
        ],
    }
    named = accused(run(receipt), receipt)
    assert "item.3.amount" in named, "the line that does not multiply out"
    assert "item.1.amount" not in named and "item.2.amount" not in named


def test_nothing_is_accused_when_nothing_failed():
    receipt = {"subtotal": 119000, "total": 119000, "currency": "PHP",
               "merchant": "SM", "date": "2026-08-12", "line_items": []}
    assert accused(run(receipt), receipt) == []


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
