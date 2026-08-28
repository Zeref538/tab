"""The whole slice, the way a person uses it: receipts in, ledger row out.

No model is called anywhere here — every fixture is a PDF with a real text
layer, which is the point of that route existing.

Run: pytest tests/test_cli.py -q      (or: python tests/test_cli.py)
"""

import csv
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import store  # noqa: E402
from tab.cli import main  # noqa: E402
from tests.fixtures import (CLEAN, RESTAURANT, WRONG_TOTAL,  # noqa: E402
                            write_image_only_pdf, write_receipt_pdf)


def build(tmp_path) -> Path:
    folder = tmp_path / "receipts"
    write_receipt_pdf(folder / "clean.pdf", CLEAN)
    write_receipt_pdf(folder / "restaurant.pdf", RESTAURANT)
    write_receipt_pdf(folder / "wrong-total.pdf", WRONG_TOTAL)
    write_image_only_pdf(folder / "scanned.pdf")
    return folder


def run(args) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(args)
    assert code == 0, f"{args} exited {code}"
    return buffer.getvalue()


def test_a_folder_of_receipts_becomes_a_ledger(tmp_path):
    db = str(tmp_path / "tab.db")
    folder = build(tmp_path)

    out = run(["--db", db, "ingest", str(folder), "--no-model"])
    assert "2 committed" in out
    assert "1 needs review" in out
    assert "1 unreadable" in out, "the image-only PDF needs the model, which is off"

    conn = store.connect(db)
    try:
        assert len(store.ledger(conn)) == 2
        assert len(store.queue(conn)) == 1
    finally:
        conn.close()


def test_the_fifty_centavo_error_reaches_the_queue_with_its_reason(tmp_path):
    """The whole product in one assertion: a wrong total does not silently
    become a ledger row, and the person is told what does not add up."""
    db = str(tmp_path / "tab.db")
    run(["--db", db, "ingest", str(build(tmp_path)), "--no-model"])

    out = run(["--db", db, "queue"])
    assert "wrong-total.pdf" in out
    assert "0.50" in out, "the queue names the actual discrepancy"


def test_export_writes_pesos_not_centavos(tmp_path):
    db = str(tmp_path / "tab.db")
    run(["--db", db, "ingest", str(build(tmp_path)), "--no-model"])

    out = run(["--db", db, "export", "--csv", "-"])
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == 2, "only committed receipts are exported"

    by_merchant = {r["merchant"]: r for r in rows}
    sm = by_merchant["SM SUPERMARKET"]
    assert sm["total"] == "1190.00", "divided by 100 exactly once, at the edge"
    assert sm["vat_amount"] == "127.50"
    assert sm["tin"] == "000-123-456-000"
    assert sm["source"] == "clean.pdf", "every row points back at its document"

    restaurant = by_merchant["MANG INASAL"]
    assert restaurant["service_charge"] == "100.00"
    assert restaurant["total"] == "1232.00"


def test_running_twice_changes_nothing(tmp_path):
    """The orchestrator will be killed mid-batch one day. Re-running must be
    safe, not a second set of rows in someone's tax filing."""
    db = str(tmp_path / "tab.db")
    folder = build(tmp_path)
    run(["--db", db, "ingest", str(folder), "--no-model"])
    first = run(["--db", db, "export", "--csv", "-"])

    again = run(["--db", db, "ingest", str(folder), "--no-model"])
    assert "4 already imported" in again
    assert run(["--db", db, "export", "--csv", "-"]) == first


def test_a_copy_under_a_new_name_is_still_a_duplicate(tmp_path):
    db = str(tmp_path / "tab.db")
    folder = build(tmp_path)
    (folder / "clean-copy.pdf").write_bytes((folder / "clean.pdf").read_bytes())

    out = run(["--db", db, "ingest", str(folder), "--no-model"])
    assert "already imported" in out
    conn = store.connect(db)
    try:
        assert len(store.ledger(conn)) == 2, "the copy did not become a second row"
    finally:
        conn.close()


def test_empty_queue_says_so_plainly(tmp_path):
    db = str(tmp_path / "tab.db")
    folder = tmp_path / "only-good"
    write_receipt_pdf(folder / "clean.pdf", CLEAN)
    run(["--db", db, "ingest", str(folder), "--no-model"])

    out = run(["--db", db, "queue"])
    assert "Nothing needs you" in out, "the success state should look like one"
    assert "1 receipts in the ledger" not in out, "count reads as English"


def test_the_reason_for_every_decision_is_recorded(tmp_path):
    db = str(tmp_path / "tab.db")
    run(["--db", db, "ingest", str(build(tmp_path)), "--no-model"])

    conn = store.connect(db)
    try:
        reasons = [r["why"] for r in conn.execute("SELECT why FROM decisions")]
    finally:
        conn.close()
    assert any("text layer" in r for r in reasons), "the route explains itself"
    assert any("0.50" in r for r in reasons), "so does the escalation"


def test_a_file_that_could_not_be_read_is_not_forgotten(tmp_path):
    """scanned.pdf has no text layer, so with the model off nothing can be read
    from it. It never becomes a receipt, so it is not in the review queue - and
    before this it was mentioned once, by the run that failed on it, and was
    then invisible for good. `tab watch` prints that line at three in the
    morning to nobody.
    """
    db = str(tmp_path / "tab.db")
    run(["--db", db, "ingest", str(build(tmp_path)), "--no-model"])

    out = run(["--db", db, "queue"])
    assert "scanned.pdf" in out, "an unreadable file must still be findable"
    assert "could not be read" in out
    assert "no text layer" in out, "and it must say why"


def test_the_queue_does_not_claim_all_is_well_while_a_file_is_stuck(tmp_path):
    """"Nothing needs you" has to mean it."""
    db = str(tmp_path / "tab.db")
    folder = tmp_path / "receipts"
    write_receipt_pdf(folder / "clean.pdf", CLEAN)
    write_image_only_pdf(folder / "scanned.pdf")
    run(["--db", db, "ingest", str(folder), "--no-model"])

    out = run(["--db", db, "queue"])
    assert "Nothing needs you." not in out
    assert "Nothing needs reviewing." in out
    assert "scanned.pdf" in out


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
