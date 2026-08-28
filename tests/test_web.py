"""The review screen, exercised over a real socket against a real server.

Nothing is mocked. The handler is the thing being tested, so it runs on an
ephemeral port and urllib talks to it — both from the same standard library
that serves the page, which is the point of ADR 0007.

Run: pytest tests/test_web.py -q      (or: python tests/test_web.py)
"""

import contextlib
import io as _io
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import store, web  # noqa: E402
from tab.cli import main as cli_main  # noqa: E402
from tests.fixtures import (CLEAN, SAME_DAY_TYPO, WRONG_TOTAL,  # noqa: E402
                            write_receipt_pdf)


class Server:
    """Start the real handler on a free port, stop it afterwards."""

    def __init__(self, db_path: Path):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.httpd.conn = store.connect(db_path, check_same_thread=False)
        self.httpd.lock = threading.Lock()
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        with urllib.request.urlopen(self.url(path), timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type")

    def get_json(self, path: str):
        return json.loads(self.get(path)[1])

    def post(self, path: str, payload: dict):
        req = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def close(self):
        self.httpd.shutdown()
        self.httpd.conn.close()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def prepared(tmp_path, held: str = WRONG_TOTAL) -> tuple[Server, str]:
    """A ledger with one clean receipt committed and one held for review."""
    db = str(tmp_path / "tab.db")
    folder = tmp_path / "receipts"
    write_receipt_pdf(folder / "clean.pdf", CLEAN)
    write_receipt_pdf(folder / "wrong-total.pdf", held)
    with contextlib.redirect_stdout(_io.StringIO()):  # the CLI narrates; tests should not
        cli_main(["--db", db, "ingest", str(folder), "--no-model"])
    return Server(Path(db)), db


def test_the_page_is_served(tmp_path):
    server, _ = prepared(tmp_path)
    try:
        status, body, ctype = server.get("/")
        assert status == 200
        assert "text/html" in ctype
        assert b"TAB" in body
    finally:
        server.close()


def test_the_queue_holds_only_what_needs_a_person(tmp_path):
    server, _ = prepared(tmp_path)
    try:
        data = server.get_json("/api/queue")
        assert len(data["queue"]) == 1
        assert data["committed"] == 1
        assert data["queue"][0]["source"] == "wrong-total.pdf"
    finally:
        server.close()


def test_a_receipt_arrives_with_the_reason_it_was_held(tmp_path):
    server, _ = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        data = server.get_json(f"/api/receipt/{rid}")
        failed = [c for c in data["checks"] if c["status"] == "fail"]
        assert failed, "the screen must be able to say what is wrong"
        assert "0.50" in failed[0]["detail"]
        assert data["receipt"]["total"] == 119050, "centavos all the way to the browser"
    finally:
        server.close()


def test_the_source_document_can_be_seen(tmp_path):
    """A person cannot check a number against paper they cannot look at."""
    server, _ = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        status, body, ctype = server.get(f"/api/image/{rid}")
        assert status == 200
        assert ctype == "image/png", "a PDF page is rendered for the browser"
        assert body[:4] == b"\x89PNG"
    finally:
        server.close()


def test_correcting_a_total_commits_it_and_records_the_change(tmp_path):
    server, db = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        result = server.post(f"/api/approve/{rid}", {"total": "1,190.00"})
        assert result["ok"] is True
        assert result["changed"] == ["total"]
        assert result["still_failing"] == [], "fixing the total makes it add up"
        assert server.get_json("/api/queue")["queue"] == []
    finally:
        server.close()

    conn = store.connect(db)
    try:
        rows = store.ledger(conn)
        assert len(rows) == 2
        correction = conn.execute("SELECT * FROM corrections").fetchone()
        assert correction["field"] == "total"
        assert correction["old_value"] == "119050"
        assert correction["new_value"] == "119000", "typed with a comma, stored exactly"
    finally:
        conn.close()


def test_an_edit_that_creates_a_duplicate_is_refused_first(tmp_path):
    """SAME_DAY_TYPO is the same shop on the same day as CLEAN, with the total
    mistyped. Correcting it makes this receipt identical to one already filed,
    and a duplicated row in a tax filing is expensive and silent. Ingest guarded
    that from the start; correcting did not, until it did."""
    server, db = prepared(tmp_path, held=SAME_DAY_TYPO)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        first = server.post(f"/api/approve/{rid}", {"total": "1190.00"})
        assert "duplicate_of" in first, "it should have stopped and asked"
        assert first.get("ok") is None
        assert len(server.get_json("/api/queue")["queue"]) == 1, "still waiting"

        # The person looked and said keep both. That is their call.
        second = server.post(f"/api/approve/{rid}",
                             {"total": "1190.00", "confirm_duplicate": True})
        assert second["ok"] is True
    finally:
        server.close()

    conn = store.connect(db)
    try:
        assert len(store.ledger(conn)) == 2
    finally:
        conn.close()


def test_a_person_can_approve_something_that_still_does_not_add_up(tmp_path):
    """They looked at the paper. The override is recorded, not prevented."""
    server, db = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        result = server.post(f"/api/approve/{rid}", {})
        assert result["ok"] is True
        assert "total_math" in result["still_failing"]
    finally:
        server.close()

    conn = store.connect(db)
    try:
        why = [r["why"] for r in conn.execute(
            "SELECT why FROM decisions WHERE step = 'review'")]
        assert any("still failing" in w for w in why), "the override is written down"
    finally:
        conn.close()


def test_an_empty_box_means_absent_not_zero(tmp_path):
    """A missing discount and a zero discount are different facts."""
    server, db = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        server.post(f"/api/approve/{rid}", {"total": "1190.00", "discount_total": ""})
    finally:
        server.close()

    conn = store.connect(db)
    try:
        row = conn.execute("SELECT discount_total FROM receipts WHERE id = ?",
                           (rid,)).fetchone()
        assert row["discount_total"] is None
    finally:
        conn.close()


def test_fields_the_page_should_not_touch_are_ignored(tmp_path):
    """The browser is not the authority on what the schema contains."""
    assert web.clean_edits({"total": "1.00", "status": "committed",
                            "id": 99, "document_id": 5}) == {"total": 100}


def test_discarding_takes_it_out_of_the_queue_for_good(tmp_path):
    server, db = prepared(tmp_path)
    try:
        rid = server.get_json("/api/queue")["queue"][0]["id"]
        assert server.post(f"/api/discard/{rid}", {})["ok"] is True
        assert server.get_json("/api/queue")["queue"] == []
    finally:
        server.close()

    conn = store.connect(db)
    try:
        assert len(store.ledger(conn)) == 1, "discarding is not committing"
        row = conn.execute("SELECT status FROM receipts WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "discarded"
    finally:
        conn.close()


def test_a_receipt_that_does_not_exist_says_so(tmp_path):
    server, _ = prepared(tmp_path)
    try:
        for path in ("/api/receipt/9999", "/api/image/9999"):
            try:
                server.get(path)
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError(f"{path} should have been a 404")
    finally:
        server.close()


def test_it_listens_on_localhost_only(tmp_path):
    """Receipts are personal data. The server must not be reachable from the
    network, and that is a property of the socket, not a promise in a README."""
    server, _ = prepared(tmp_path)
    try:
        host = server.httpd.server_address[0]
        assert host == "127.0.0.1"
        probe = socket.socket()
        probe.settimeout(1)
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            local_ip = None
        if local_ip and local_ip != "127.0.0.1":
            try:
                probe.connect((local_ip, server.port))
                raise AssertionError("the review server answered on a network address")
            except (ConnectionRefusedError, OSError):
                pass
        probe.close()
    finally:
        server.close()


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
