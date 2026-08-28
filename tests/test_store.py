"""The ledger is the artefact. These are the rules that must hold in the file
itself, not merely in the code that happens to write it today.

Run: pytest tests/test_store.py -q      (or: python tests/test_store.py)
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import store  # noqa: E402
from tab.checks import run  # noqa: E402

RECEIPT = {
    "merchant": "SM Supermarket", "tin": "000-123-456-000", "or_number": "0099123",
    "date": "2026-08-12", "currency": "PHP",
    "subtotal": 119000, "vatable_sales": 106250, "vat_exempt_sales": 0,
    "zero_rated_sales": 0, "vat_amount": 12750, "service_charge": None,
    "discount_total": 0, "total": 119000,
    "line_items": [
        {"line_no": 1, "description": "Rice 5kg", "qty": 1, "unit_price": 70000,
         "amount": 70000, "discount": None},
        {"line_no": 2, "description": "Milk 1L", "qty": 2, "unit_price": 24500,
         "amount": 49000, "discount": None},
    ],
}


_OPEN = []


def fresh(tmp_path, name="tab.db"):
    """Open a ledger and remember it, so the standalone runner can close it.

    Windows will not delete a file that still has an open handle, so a leaked
    connection turns into a confusing cleanup error rather than a test failure.
    """
    conn = store.connect(tmp_path / name)
    _OPEN.append(conn)
    return conn


def a_file(tmp_path, name="receipt.pdf", body=b"pretend pdf"):
    p = tmp_path / name
    p.write_bytes(body)
    return p


def test_same_file_twice_is_one_document(tmp_path):
    """The exact-duplicate guard, which runs before any model does."""
    conn = fresh(tmp_path)
    first, new1 = store.register_document(conn, a_file(tmp_path))
    second, new2 = store.register_document(conn, a_file(tmp_path, "copy.pdf"))
    assert new1 is True
    assert new2 is False, "same bytes, different name, still the same receipt"
    assert first == second


def test_different_bytes_are_different_documents(tmp_path):
    conn = fresh(tmp_path)
    a, _ = store.register_document(conn, a_file(tmp_path, "a.pdf", b"one"))
    b, new = store.register_document(conn, a_file(tmp_path, "b.pdf", b"two"))
    assert a != b and new is True


def test_committed_row_survives_a_round_trip(tmp_path):
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    checks = run(RECEIPT)
    store.save(conn, doc, RECEIPT, checks, "committed", "text_layer", "{}")

    rows = store.ledger(conn)
    assert len(rows) == 1
    row = rows[0]
    assert row["total"] == 119000, "centavos, exactly, no float anywhere"
    assert row["merchant"] == "SM Supermarket"
    assert row["committed_at"] is not None
    items = conn.execute("SELECT * FROM line_items ORDER BY line_no").fetchall()
    assert [i["amount"] for i in items] == [70000, 49000]
    saved = conn.execute("SELECT name, status FROM checks").fetchall()
    assert {c["name"] for c in saved} == {c.name for c in checks}


def test_a_second_pass_replaces_items_rather_than_doubling_them(tmp_path):
    """The bug this guards against would make item_sum fail on a correct
    receipt - the guard blaming good data, which is the worst kind."""
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    store.save(conn, doc, RECEIPT, run(RECEIPT), "needs_review", "vision", "{}")
    store.save(conn, doc, RECEIPT, run(RECEIPT), "committed", "vision", "{}", pass_no=2)

    assert len(store.ledger(conn)) == 1, "one receipt per document"
    total_items = conn.execute("SELECT COUNT(*) c FROM line_items").fetchone()["c"]
    assert total_items == 2, "items replaced, not appended"
    assert conn.execute("SELECT COUNT(*) c FROM extractions").fetchone()["c"] == 2, \
        "both attempts kept as evidence"


def test_database_refuses_a_committed_row_with_no_total(tmp_path):
    """Enforced by the schema, so a future entry point cannot forget it."""
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    blank = dict(RECEIPT, total=None, line_items=[])
    try:
        store.save(conn, doc, blank, [], "committed", "vision", "{}")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("the database allowed a committed row with no total")


def test_database_refuses_an_unknown_status(tmp_path):
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    try:
        conn.execute("INSERT INTO receipts (document_id, status) VALUES (?, 'nonsense')",
                     (doc,))
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("a typo in a status string would vanish from every queue")


def test_soft_duplicate_is_found_by_shop_day_and_amount(tmp_path):
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path, "a.pdf", b"one"))
    store.save(conn, doc, RECEIPT, run(RECEIPT), "committed", "text_layer", "{}")

    other, _ = store.register_document(conn, a_file(tmp_path, "b.pdf", b"two"))
    assert store.find_soft_duplicate(conn, RECEIPT, exclude_document_id=other)
    assert store.find_soft_duplicate(conn, dict(RECEIPT, total=99900),
                                     exclude_document_id=other) is None


def test_decisions_record_why(tmp_path):
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    store.log_decision(conn, doc, "route", "text_layer", "PDF has a real text layer")
    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["why"] == "PDF has a real text layer"


def test_deleting_a_document_takes_its_receipt_but_not_the_record_of_why(tmp_path):
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    store.save(conn, doc, RECEIPT, run(RECEIPT), "committed", "text_layer", "{}")
    store.log_decision(conn, doc, "commit", "committed", "checks passed")

    conn.execute("DELETE FROM documents WHERE id = ?", (doc,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM line_items").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"] == 1, \
        "what happened survives the row it describes"


def test_queue_holds_what_needs_a_human(tmp_path):
    conn = fresh(tmp_path)
    good, _ = store.register_document(conn, a_file(tmp_path, "a.pdf", b"one"))
    bad, _ = store.register_document(conn, a_file(tmp_path, "b.pdf", b"two"))
    store.save(conn, good, RECEIPT, run(RECEIPT), "committed", "text_layer", "{}")
    wrong = dict(RECEIPT, total=119050)
    store.save(conn, bad, wrong, run(wrong), "needs_review", "text_layer", "{}")

    assert len(store.ledger(conn)) == 1
    q = store.queue(conn)
    assert len(q) == 1 and q[0]["total"] == 119050
    assert q[0]["path"].endswith("b.pdf"), "the queue can show the source document"


def test_a_failed_save_leaves_nothing_behind(tmp_path):
    """All of it or none of it. Half a receipt is worse than no receipt."""
    conn = fresh(tmp_path)
    doc, _ = store.register_document(conn, a_file(tmp_path))
    broken = dict(RECEIPT, line_items=[
        {"line_no": 1, "description": "ok", "qty": 1, "unit_price": 1, "amount": 1},
        {"line_no": 1, "description": "duplicate line number", "qty": 1,
         "unit_price": 1, "amount": 1},
    ])
    try:
        store.save(conn, doc, broken, [], "committed", "text_layer", "{}")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("two lines with the same number should not be allowed")
    assert conn.execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM extractions").fetchone()["c"] == 0


if __name__ == "__main__":
    import tempfile

    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                try:
                    fn(Path(d))
                finally:
                    while _OPEN:
                        _OPEN.pop().close()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
