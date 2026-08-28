"""The review screen, served by the standard library.

Five endpoints and one page, bound to 127.0.0.1. No framework: see
docs/adr/0007-stdlib-http-server-for-the-review-page.md for what that saved and
what it costs.

The cost is that nothing validates a request for us, so input handling here is
deliberate. Unknown fields are ignored rather than written. Amounts typed by a
person are parsed by exactly the same code that parses amounts read by the
model, so a comma or a peso sign behaves identically either way.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tab import store
from tab.checks import run as run_checks
from tab.receipt import AMOUNT_FIELDS, TEXT_FIELDS, to_centavos

STATIC = Path(__file__).resolve().parent / "static"

# Only these can be changed from the browser. Anything else in the request body
# is ignored rather than written — the page is not the authority on what the
# schema contains.
EDITABLE_TEXT = [f for f in TEXT_FIELDS]
EDITABLE = set(EDITABLE_TEXT) | set(AMOUNT_FIELDS)


def clean_edits(body: dict) -> dict:
    """Turn what the browser sent into values the ledger will accept.

    An empty box means "not on this receipt", which is None — never 0. A total
    that is missing and a total that is zero are different facts, and confusing
    them is how a wrong row gets committed.
    """
    edits: dict = {}
    for field, value in (body or {}).items():
        if field not in EDITABLE:
            continue
        if isinstance(value, str) and not value.strip():
            edits[field] = None
        elif field in AMOUNT_FIELDS:
            edits[field] = to_centavos(value)
        else:
            edits[field] = str(value).strip() or None
    return edits


class Handler(BaseHTTPRequestHandler):
    server_version = "tab"

    # The default logs every request to stderr, which buries the one line the
    # user actually needs (the URL to open).
    def log_message(self, *args) -> None:
        pass

    # ---- plumbing ----------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    @property
    def conn(self):
        return self.server.conn  # type: ignore[attr-defined]

    @property
    def lock(self):
        return self.server.lock  # type: ignore[attr-defined]

    # ---- routes ------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 — http.server names it this
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            page = (STATIC / "review.html").read_bytes()
            return self._send(200, page, "text/html; charset=utf-8")

        if path == "/api/queue":
            with self.lock:
                rows = store.queue(self.conn)
                committed = len(store.ledger(self.conn))
            return self._json({
                "queue": [{"id": r["id"], "merchant": r["merchant"],
                           "date": r["date"], "total": r["total"],
                           "currency": r["currency"],
                           "source": Path(r["path"]).name} for r in rows],
                "committed": committed,
            })

        if path.startswith("/api/receipt/"):
            with self.lock:
                found = store.receipt_with_checks(self.conn, self._id(path))
            if found is None:
                return self._json({"error": "no such receipt"}, 404)
            return self._json(found)

        if path.startswith("/api/image/"):
            return self._image(self._id(path))

        return self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]

        if path.startswith("/api/approve/"):
            receipt_id = self._id(path)
            body = self._body()
            edits = clean_edits(body)
            with self.lock:
                existing = store.receipt_with_checks(self.conn, receipt_id)
                if existing is None:
                    return self._json({"error": "no such receipt"}, 404)

                # An edit can turn a receipt INTO a duplicate of one already in
                # the ledger — fix a mistyped total and it may now match a slip
                # photographed twice. Ingest guards that; correcting did not,
                # and a guard on one entry path is no guard at all.
                proposed = {**existing["receipt"], **edits}
                twin = store.find_soft_duplicate(
                    self.conn, proposed,
                    exclude_document_id=existing["document_id"])
                if twin is not None and not body.get("confirm_duplicate"):
                    return self._json({
                        "duplicate_of": twin,
                        "message": (f"With those values this matches receipt "
                                    f"#{twin} already in the ledger — same "
                                    f"merchant, date and total. Approve again "
                                    f"to keep both, or discard this one."),
                    })

                try:
                    result = store.apply_corrections(
                        self.conn, receipt_id, edits, run_checks)
                except KeyError:
                    return self._json({"error": "no such receipt"}, 404)
                store.log_decision(
                    self.conn, result["document_id"], "review", "committed",
                    ("approved by a person, no edits" if not result["changed"]
                     else "approved by a person after correcting "
                          + ", ".join(result["changed"]))
                    + (f"; still failing: {', '.join(result['still_failing'])}"
                       if result["still_failing"] else ""))
            return self._json({"ok": True, "changed": result["changed"],
                               "still_failing": result["still_failing"]})

        if path.startswith("/api/discard/"):
            receipt_id = self._id(path)
            with self.lock:
                try:
                    document_id = store.discard(self.conn, receipt_id)
                except KeyError:
                    return self._json({"error": "no such receipt"}, 404)
                store.log_decision(self.conn, document_id, "review", "discarded",
                                   "a person said this is not a receipt to keep")
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)

    # ---- helpers -----------------------------------------------------
    def _id(self, path: str) -> int:
        tail = path.rstrip("/").rsplit("/", 1)[-1]
        return int(tail) if tail.isdigit() else -1

    def _image(self, receipt_id: int) -> None:
        """Show the paper. A thumbnail would make the whole screen pointless —
        someone is trying to read a faded thermal total."""
        with self.lock:
            found = store.receipt_with_checks(self.conn, receipt_id)
        if found is None:
            return self._json({"error": "no such receipt"}, 404)

        source = Path(found["path"])
        if not source.exists():
            return self._json({"error": "the source file has moved"}, 410)

        if source.suffix.lower() == ".pdf":
            import pymupdf

            with pymupdf.open(source) as doc:
                png = doc[0].get_pixmap(dpi=150).tobytes("png")
            return self._send(200, png, "image/png")

        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return self._send(200, source.read_bytes(), mime)


def serve(db_path: str, port: int = 8000, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    # ThreadingHTTPServer runs every request on its own thread, and a SQLite
    # connection refuses to be used outside the thread that opened it. So the
    # connection is opened with that check off and one lock serialises access
    # instead.
    # ponytail: one global lock. Fine for one person clicking through a queue -
    # swap for a connection per request if this ever serves more than that.
    httpd.conn = store.connect(db_path, check_same_thread=False)  # type: ignore[attr-defined]
    httpd.lock = threading.Lock()  # type: ignore[attr-defined]
    httpd.conn.execute("PRAGMA journal_mode = WAL")

    url = f"http://127.0.0.1:{port}"
    print(f"Review screen at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.conn.close()  # type: ignore[attr-defined]
        httpd.server_close()
