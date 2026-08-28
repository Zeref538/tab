"""Reading a PDF that already contains text, with the basket as the hard part.

`item_sum` — do the items add up to the subtotal — is the strongest guard TAB
has, and until line items were parsed it skipped on every single PDF. These are
the checks that keep it working.

Run: pytest tests/test_pdftext.py -q     (or: python tests/test_pdftext.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import pdftext  # noqa: E402
from tab.checks import run as run_checks  # noqa: E402
from tab.receipt import normalise  # noqa: E402
from tests.fixtures import (BAD_LINE_MATH, CLEAN, ITEMISED,  # noqa: E402
                            RESTAURANT, write_receipt_pdf)


def parse(text: str) -> dict:
    return normalise(pdftext.parse(text))


def checks(receipt: dict) -> dict:
    return {c.name: c for c in run_checks(receipt)}


def test_the_basket_is_read(tmp_path):
    r = parse(CLEAN)
    assert [i["description"] for i in r["line_items"]] == ["Rice 5kg", "Milk 1L"]
    assert [i["amount"] for i in r["line_items"]] == [70000, 49000]


def test_the_items_are_checked_against_the_subtotal(tmp_path):
    """The whole reason line items are worth parsing."""
    c = checks(parse(CLEAN))
    assert c["item_sum"].status == "pass"
    assert "₱1,190.00" in c["item_sum"].detail


def test_a_quantity_is_only_believed_when_the_receipt_states_one(tmp_path):
    """Columns are not labelled on paper. Deciding that the 2 in

        Milk 1L        2      245.00      490.00

    is a quantity means picking the reading that makes 2 x 245 = 490 work - and
    then line_math is checking a parse that was chosen to satisfy it, which
    proves nothing at all. So an unlabelled column is left empty and line_math
    skips the line. An explicit "2 @ 245.00" is a different matter: the receipt
    said it.
    """
    ambiguous = CLEAN.replace("Milk 1L                       490.00",
                              "Milk 1L        2      245.00      490.00")
    milk = [i for i in parse(ambiguous)["line_items"] if "Milk" in i["description"]][0]
    assert milk["qty"] is None, "a bare column is not a quantity"
    assert milk["amount"] == 49000, "the last amount is still the line total"

    stated = [i for i in parse(ITEMISED)["line_items"]
              if i["description"] == "Chickenjoy"][0]
    assert stated["qty"] == 2.0
    assert stated["unit_price"] == 8200


def test_a_line_that_does_not_multiply_out_is_named(tmp_path):
    c = checks(parse(BAD_LINE_MATH))
    assert c["line_math"].status == "fail"
    assert "line 3" in c["line_math"].detail
    assert "₱90.00" in c["line_math"].detail and "₱80.00" in c["line_math"].detail
    # The header totals are untouched, so the receipt is not broken everywhere.
    assert c["total_math"].status == "pass"
    assert c["vat_rate"].status == "pass"


def test_the_totals_block_is_not_the_basket(tmp_path):
    """SUBTOTAL, VAT, CASH and CHANGE are all lines with an amount on them.
    Counting them as items would double the basket and fail every receipt."""
    descriptions = [i["description"] for i in parse(CLEAN)["line_items"]]
    for word in ("SUBTOTAL", "VAT", "CASH", "CHANGE", "TOTAL", "Discount"):
        assert not any(word.lower() in d.lower() for d in descriptions), word


def test_the_header_is_not_the_basket(tmp_path):
    """A TIN is a long run of digits and a date is three numbers. Neither is
    money, and the two-decimal rule is what keeps them out."""
    descriptions = [i["description"] for i in parse(CLEAN)["line_items"]]
    assert not any("TIN" in d or "OR No" in d or "Date" in d for d in descriptions)


def test_a_receipt_with_no_basket_skips_rather_than_inventing_one(tmp_path):
    """RESTAURANT prints only totals. A check that could not run has not
    passed, and it must not quietly pass by summing nothing."""
    c = checks(parse(RESTAURANT))
    assert parse(RESTAURANT)["line_items"] == []
    assert c["item_sum"].status == "skip"
    assert c["line_math"].status == "skip"


def test_the_description_is_what_is_left_when_the_numbers_go(tmp_path):
    item = parse(ITEMISED)["line_items"][2]
    assert item["description"] == "Peach Mango Pie"
    assert item["qty"] == 3.0 and item["amount"] == 9000


def test_it_survives_a_real_pdf_round_trip(tmp_path):
    """Everything above parses a string. This one goes through pymupdf, which
    is where column spacing turns into whatever it turns into."""
    path = write_receipt_pdf(tmp_path / "itemised.pdf", ITEMISED)
    receipt, meta = pdftext.extract(path)
    receipt = normalise(receipt)
    assert meta["method"] == "text_layer"
    assert len(receipt["line_items"]) == 3
    assert checks(receipt)["item_sum"].status == "pass"


if __name__ == "__main__":
    import tempfile

    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                fn(Path(d))
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
