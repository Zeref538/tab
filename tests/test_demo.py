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


def test_only_one_receipt_is_read_at_a_time():
    """Concurrency here is all cost and no benefit.

    Measured against the running server, peak resident memory by concurrent
    requests: 1 -> 387 MB, 2 -> 675, 4 -> 1113, 8 -> 1894, against 512 MB on a
    free instance. Two people at once killed the box. Meanwhile the wall clock
    for 1/2/4/8 was 1.0/1.7/3.4/6.5 seconds — dead linear, because the work is
    already serialised by the interpreter lock. Parallelism never bought a
    thing; it only spent memory.
    """
    assert demo.MAX_CONCURRENT == 1, demo.MAX_CONCURRENT

    seen_together = []
    inside = threading.Semaphore(0)
    live = []
    lock = threading.Lock()

    def slow_read(*args, **kwargs):
        with lock:
            live.append(1)
            seen_together.append(len(live))
        time.sleep(0.2)
        with lock:
            live.pop()
        return {"total": None, "line_items": []}, {"method": "ocr", "why": ""}

    from tab import pipeline

    real = pipeline.read
    pipeline.read = slow_read
    try:
        threads = [threading.Thread(target=demo.check_bytes, args=(b"x", "a.pdf"))
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        pipeline.read = real
        inside.release()

    assert seen_together, "no read ever ran"
    assert max(seen_together) == 1, (
        f"{max(seen_together)} reads ran at once; the semaphore is not holding")


def test_a_busy_server_says_so_instead_of_hanging():
    """When the queue is full the answer is a 503 the caller can retry, not a
    connection that sits there until something times out."""
    original = demo.QUEUE_WAIT
    demo.QUEUE_WAIT = 0.05
    demo._reading.acquire()          # pretend a read is already in flight
    try:
        demo.check_bytes(b"x", "a.pdf")
    except demo.Busy as exc:
        assert "still reading" in str(exc)
    else:
        raise AssertionError("a full queue should raise Busy")
    finally:
        demo._reading.release()
        demo.QUEUE_WAIT = original


def test_the_demo_caps_image_size_but_the_reader_does_not():
    """The cap belongs to the host, not to the library.

    64 of the 100 CORD test receipts are longer than 1280px. Capping inside
    tab.ocr.read would change what every published accuracy figure means while
    leaving the number printed next to it alone.
    """
    import inspect

    from tab import ocr

    assert demo.DEMO_MAX_EDGE > 0
    signature = inspect.signature(ocr.read)
    assert signature.parameters["max_edge"].default is None, (
        "tab.ocr.read must not resize unless a caller asks")
    assert inspect.signature(pipeline_read()).parameters["max_edge"].default is None


def pipeline_read():
    from tab import pipeline
    return pipeline.read


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
