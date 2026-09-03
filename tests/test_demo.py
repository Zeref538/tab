"""The public demo endpoint.

This is the one part of TAB that strangers can reach, so the tests here are
mostly about what it refuses. The reading itself is already covered by
test_checks and test_pdftext; what is new is a socket open to the internet.

Run: pytest tests/test_demo.py -q      (or: python tests/test_demo.py)
"""

import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tab import demo  # noqa: E402
from tests import fixtures  # noqa: E402


def test_a_receipt_pdf_is_read_and_nothing_is_written():
    """The text-layer route needs no OCR, so this runs anywhere."""
    buf = io.BytesIO()
    pdf = ROOT / "build" / "test-clean.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    fixtures.write_receipt_pdf(pdf, fixtures.CLEAN)
    try:
        out = demo.check_bytes(pdf.read_bytes(), "clean.pdf")
    finally:
        pdf.unlink(missing_ok=True)

    assert out["verdict"] == "commit", out["why"]
    assert out["route"] == "text_layer"
    assert out["receipt"]["total"] == 119000
    assert out["stored"] is False
    assert out["flagged"] == []
    assert buf.getvalue() == b""


def test_a_receipt_that_disagrees_with_itself_is_held_and_the_line_is_named():
    pdf = ROOT / "build" / "test-bad.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    fixtures.write_receipt_pdf(pdf, fixtures.BAD_LINE_MATH)
    try:
        out = demo.check_bytes(pdf.read_bytes(), "bad.pdf")
    finally:
        pdf.unlink(missing_ok=True)

    assert out["verdict"] == "needs_review"
    # Not just "something is wrong" - the exact line.
    assert "item.3.amount" in out["flagged"], out["flagged"]
    assert any(c["name"] == "line_math" and c["status"] == "fail"
               for c in out["checks"])


def test_a_temp_file_never_outlives_the_request():
    """A stranger's receipt must not be left lying in the temp folder.

    check_bytes has to write the bytes down for a moment, because pymupdf and
    the OCR engine both open paths rather than buffers. The deletion is in a
    finally, and this is what proves the finally runs when the read explodes.
    """
    import tempfile

    before = set(Path(tempfile.gettempdir()).glob("tab-demo-*"))
    try:
        demo.check_bytes(b"this is not a pdf at all", "broken.pdf")
    except Exception:
        pass
    after = set(Path(tempfile.gettempdir()).glob("tab-demo-*"))
    assert after == before, f"left behind: {after - before}"


def test_a_scanned_pdf_leaves_no_picture_of_the_receipt_behind():
    """A PDF with no text layer gets rendered to an image so it can be read.

    That image is a picture of somebody's receipt. It used to be written to the
    temp folder under a predictable name and left there permanently — for every
    scanned receipt anyone ever ingested, not just through this demo.
    """
    import tempfile

    from tab import pipeline

    scan = ROOT / "build" / "test-scanned.pdf"
    scan.parent.mkdir(parents=True, exist_ok=True)
    fixtures.write_image_only_pdf(scan)
    before = set(Path(tempfile.gettempdir()).glob("tab-render-*"))
    try:
        pipeline.read(scan, reader="ocr")
    except Exception:
        pass          # unreadable is fine; the file on disk is what is on trial
    finally:
        scan.unlink(missing_ok=True)
    after = set(Path(tempfile.gettempdir()).glob("tab-render-*"))
    assert after == before, f"rendered receipt left behind: {after - before}"


def test_only_receipt_shaped_files_are_accepted():
    for name in ("notes.txt", "payload.exe", "archive.zip", "noextension"):
        try:
            demo.check_bytes(b"x", name)
        except ValueError as exc:
            assert "not a receipt file" in str(exc)
        else:
            raise AssertionError(f"{name} should have been refused")


def test_the_rate_limiter_lets_a_burst_through_then_stops_it():
    """Counted per address over a rolling minute, so a shared office IP is not
    locked out for an hour by one enthusiastic script."""
    demo._hits.clear()
    now = 1000.0
    allowed = sum(not demo.rate_limited("1.2.3.4", now) for _ in range(demo.RATE_LIMIT + 5))
    assert allowed == demo.RATE_LIMIT

    # A different caller is unaffected by the first one's burst.
    assert not demo.rate_limited("5.6.7.8", now)

    # And the window rolls: a minute later the first caller is served again.
    assert not demo.rate_limited("1.2.3.4", now + 61)
    demo._hits.clear()


def test_a_sample_name_cannot_walk_out_of_the_samples_folder():
    handler = demo.Handler.__new__(demo.Handler)
    for attack in ("../../pyproject.toml", "..\\..\\pyproject.toml",
                   "/etc/passwd", "....//pyproject.toml"):
        try:
            handler._from_sample(json.dumps({"sample": attack}).encode())
        except ValueError:
            pass
        else:
            raise AssertionError(f"{attack!r} was served")


def test_the_browser_file_input_is_parsed():
    """cgi.FieldStorage did this until Python 3.13 removed it, so the multipart
    reader here is hand-written and therefore worth a test."""
    handler = demo.Handler.__new__(demo.Handler)
    boundary = "----abc123"
    payload = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="notes"\r\n\r\nignored\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="receipt.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG-bytes-here" + f"\r\n--{boundary}--\r\n".encode()

    data, name = handler._from_multipart(payload, f"multipart/form-data; boundary={boundary}")
    assert name == "receipt.png"
    assert data == b"\x89PNG-bytes-here", data


def test_the_server_answers_over_a_real_socket():
    """Everything above calls functions directly. This one uses HTTP, because a
    handler that works when called and 500s when served is a real possibility."""
    demo._hits.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), demo.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                    health = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("the demo server never answered")

        assert health["ok"] is True
        assert health["stores_nothing"] is True

        with urllib.request.urlopen(base + "/", timeout=5) as r:
            page = r.read()
        assert b"<title>" in page and b"api/check" in page

        # An empty POST is a bad request, not a traceback.
        req = urllib.request.Request(base + "/api/check", data=b"", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, exc.code
        else:
            raise AssertionError("an empty body should be refused")
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
