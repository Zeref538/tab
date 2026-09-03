"""The public demo, and the automation endpoint underneath it.

Two things share one small server, the way callback-ai does it: an HTML page for
a person, and a JSON endpoint for a machine. The machine is the point. n8n, Make,
Zapier, a cron job or a shell script can all POST a receipt here and get back a
verdict they can branch on, which is what turns TAB from a program somebody runs
into a step in somebody's pipeline.

    python -m tab.demo                 # http://127.0.0.1:8000
    python -m tab.demo --host 0.0.0.0 --port $PORT

Endpoints:

    GET  /                 the page
    GET  /api/health       for the host's health check
    GET  /api/samples      the receipts bundled with this build
    POST /api/check        a receipt in, a verdict out

**Nothing is written down.** No ledger, no temp file that outlives the request,
no log of what was read. The uploaded bytes live in memory for the length of one
request and are gone when it returns. That is a deliberate narrowing of ADR 0004
rather than a hole in it — see docs/adr/0013.

The reader is OCR, not the vision model, and that is what makes this hostable at
all: no GPU, no Ollama, ~0.9 seconds a receipt, and a peak of about 175 MB, which
fits the free tier of every host worth naming. ADR 0012 has what that costs in
accuracy.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import tempfile
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tab import pipeline
from tab.checks import accused, run as run_checks, verdict
from tab.receipt import normalise

STATIC = Path(__file__).resolve().parent / "static"
SAMPLES = Path(__file__).resolve().parent / "samples"

# Bigger than any receipt, small enough that a hostile upload cannot exhaust a
# 512 MB container. A phone photo of a receipt is comfortably under 8 MB.
MAX_UPLOAD = int(os.environ.get("TAB_MAX_UPLOAD", 8 * 1024 * 1024))

# Requests per minute per address. A free-tier box and a ~1 second CPU-bound
# read is a combination that a single enthusiastic script can flatten.
RATE_LIMIT = int(os.environ.get("TAB_RATE_LIMIT_PER_MIN", "20"))

# Longest edge an uploaded photo is allowed before the demo shrinks it.
#
# This lives here and NOT in tab.ocr on purpose. Capping inside the reader would
# silently change every published accuracy figure, because 64 of the 100 CORD
# test receipts are longer than 1280px. Size is a hosting problem; the library
# keeps reading what it is given.
#
# Measured on a 3024x4032 phone photo, peak resident memory for one read:
#   no cap  606 MB      1600px  437 MB      1280px  336 MB      1024px  301 MB
# against 512 MB on a free instance. Below about 1024 nothing more is saved.
#
# And what it costs, re-scored on the same 100 CORD receipts (64 of which are
# larger than this and therefore actually shrink):
#   totals    73/100 uncapped -> 72/100 capped
#   subtotal  77/100          -> 76/100
#   vat, service charge, discount, straight-through, silent error: unchanged
#   median    0.9s            -> 0.7s
# One total and one subtotal out of a hundred, for half the memory and a faster
# read. Reproduce with:
#   python -m tab.eval --corpus cord --split test --reader ocr --max-edge 1280
DEMO_MAX_EDGE = int(os.environ.get("TAB_DEMO_MAX_EDGE", "1280"))

# How many receipts may be read at the same moment.
#
# One, because concurrency here is all cost and no benefit. Measured against the
# running server: 1 request peaked at 387 MB, 2 at 675, 4 at 1113, 8 at 1894 -
# so two people at once already exceed a 512 MB instance. Meanwhile the wall
# clock for 1/2/4/8 concurrent reads was 1.0/1.7/3.4/6.5 seconds, which is dead
# linear: the work is already serialised by the interpreter lock, so running it
# in parallel never made anything faster. It only made the box die.
MAX_CONCURRENT = int(os.environ.get("TAB_MAX_CONCURRENT", "1"))

# How long a request waits its turn before giving up. Longer than a read (about
# a second) so a small queue still gets served, short enough that a caller gets
# a clear "busy" rather than a hung connection.
QUEUE_WAIT = float(os.environ.get("TAB_QUEUE_WAIT", "20"))

_reading = threading.Semaphore(MAX_CONCURRENT)

ALLOWED_SUFFIXES = pipeline.SUPPORTED

_hits: dict[str, deque] = {}
_hits_lock = threading.Lock()


class Busy(RuntimeError):
    """Too many receipts in flight. A 503, not a bad request — the caller did
    nothing wrong and should try the same thing again shortly."""


def rate_limited(who: str, now: float | None = None) -> bool:
    """True when this caller has had its share of the last minute.

    Kept in memory on purpose: a demo that needs Redis to say "slow down" is a
    demo with a second thing to deploy and a second thing to break.
    """
    now = time.time() if now is None else now
    with _hits_lock:
        seen = _hits.setdefault(who, deque())
        while seen and now - seen[0] > 60:
            seen.popleft()
        if len(seen) >= RATE_LIMIT:
            return True
        seen.append(now)
        # Addresses that stopped calling should not accumulate forever.
        if len(_hits) > 2048:
            for key in [k for k, v in _hits.items() if not v]:
                del _hits[key]
        return False


def samples() -> list[dict]:
    """The receipts shipped with this build, for the one-click demo."""
    if not SAMPLES.is_dir():
        return []
    out = []
    for path in sorted(SAMPLES.iterdir()):
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        note = path.with_suffix(".txt")
        out.append({
            "name": path.name,
            "size": path.stat().st_size,
            "about": note.read_text(encoding="utf-8").strip() if note.exists() else "",
        })
    return out


def _erase(path: str) -> bool:
    """Delete the temp copy, and mean it.

    Windows refuses to unlink a file while anything still has it open, and a
    reader that just raised may not have let go yet. So this collects — which
    drops the last reference to whatever was holding it — and tries again.

    The first version of this swallowed the error and moved on, which left a
    stranger's receipt sitting in the temp folder while the docstring above
    promised it had been deleted. A failure here is now loud, because the whole
    claim this demo makes is that it keeps nothing.
    """
    for attempt in range(4):
        try:
            os.unlink(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            gc.collect()
            time.sleep(0.05 * (attempt + 1))
    print(f"WARNING: could not delete {path} — a receipt is still on disk")
    return False


def check_bytes(data: bytes, filename: str, reader: str = "ocr") -> dict:
    """One receipt, read and checked, with nothing kept.

    The file has to exist on disk for a moment because every reader here takes a
    path — pymupdf and the OCR engine both open files, not buffers. It goes to a
    temp file that is deleted in a finally, so an exception cannot leave a
    stranger's receipt lying in /tmp.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"{suffix or 'that'} is not a receipt file — "
                         f"send {', '.join(sorted(ALLOWED_SUFFIXES))}")

    # One read at a time. See MAX_CONCURRENT: two at once is more memory than a
    # free instance has, and the reads never ran in parallel anyway.
    if not _reading.acquire(timeout=QUEUE_WAIT):
        raise Busy(f"still reading someone else's receipt after {QUEUE_WAIT:.0f}s")

    started = time.time()
    handle, tmp = tempfile.mkstemp(suffix=suffix, prefix="tab-demo-")
    failure = None
    raw = meta = None
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(data)
        raw, meta = pipeline.read(Path(tmp), reader=reader,
                                  max_edge=DEMO_MAX_EDGE)
    except Exception as exc:  # noqa: BLE001 — re-raised below, after the cleanup
        # The traceback is dropped on purpose. Its frames still reference the
        # reader that has this file open, and on Windows an open file cannot be
        # deleted - so keeping the traceback keeps a stranger's receipt on disk.
        # The message is what the caller turns into a 422 anyway.
        failure = RuntimeError(f"{type(exc).__name__}: {exc}")
    finally:
        _erase(tmp)
        _reading.release()
    if failure is not None:
        raise failure

    receipt = normalise(raw)
    checks = run_checks(receipt)
    action, why = verdict(checks)
    return {
        "verdict": action,
        "why": why,
        "route": meta.get("method"),
        "route_why": meta.get("why"),
        "seconds": round(time.time() - started, 2),
        "receipt": receipt,
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail}
                   for c in checks],
        "flagged": accused(checks, receipt),
        # Said out loud in every response, because the claim on the page is only
        # worth as much as the API is willing to repeat.
        "stored": False,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "tab-demo"

    def log_message(self, fmt, *args) -> None:
        # One line per request, no receipt names, nothing about the content.
        print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The endpoint is meant to be called from other people's automations.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:  # noqa: N802 — http.server names it this
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            page = STATIC / "demo.html"
            if not page.exists():
                return self._send(500, b"demo.html is missing from tab/static/",
                                  "text/plain; charset=utf-8")
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/health":
            return self._json({"ok": True, "reader": "ocr", "stores_nothing": True})
        if path == "/api/samples":
            return self._json({"samples": samples()})
        if path.startswith("/samples/"):
            name = Path(path).name
            found = SAMPLES / name
            # Resolve and confirm the result is still inside SAMPLES, so a
            # crafted "..%2f" cannot walk out of the folder and serve any file
            # on the box.
            if (not found.exists()
                    or SAMPLES.resolve() not in found.resolve().parents):
                return self._json({"error": "no such sample"}, 404)
            import mimetypes
            kind = mimetypes.guess_type(found.name)[0] or "application/octet-stream"
            return self._send(200, found.read_bytes(), kind)
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/api/check":
            return self._json({"error": "not found"}, 404)

        who = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0]
        if rate_limited(who.strip()):
            return self._json({"error": f"more than {RATE_LIMIT} requests a minute "
                                        f"from one address; wait a moment"}, 429)

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._json({"error": "send the receipt as the request body"}, 400)
        if length > MAX_UPLOAD:
            return self._json({"error": f"{length} bytes is over the "
                                        f"{MAX_UPLOAD} byte limit"}, 413)

        body = self.rfile.read(length)
        content_type = (self.headers.get("Content-Type") or "").lower()

        try:
            if content_type.startswith("application/json"):
                data, filename = self._from_sample(body)
            elif content_type.startswith("multipart/form-data"):
                data, filename = self._from_multipart(body, content_type)
            else:
                # Raw bytes with the name in a header. This is the shape n8n's
                # HTTP Request node sends binary in, and the easiest thing to
                # produce from curl, so it is the documented one.
                data = body
                filename = self.headers.get("X-Filename") or "upload.jpg"
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

        try:
            return self._json(check_bytes(data, filename))
        except Busy as exc:
            # 503 with Retry-After: this is the server being full, not the
            # request being wrong, and an automation should retry rather than
            # treat the receipt as unreadable.
            self.send_response(503)
            body = json.dumps({"error": str(exc), "retry": True}).encode()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", "5")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return self.wfile.write(body)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 — one bad upload must not stop the server
            # The document defeated the reader. That is a fact about the file,
            # not a crash, and it gets the same shape as any other answer.
            return self._json({"error": f"could not read that: "
                                        f"{type(exc).__name__}: {exc}"}, 422)

    def _from_sample(self, body: bytes) -> tuple[bytes, str]:
        try:
            wanted = (json.loads(body or b"{}") or {}).get("sample")
        except json.JSONDecodeError:
            raise ValueError("that is not JSON") from None
        if not wanted:
            raise ValueError('send {"sample": "<name>"} or the file itself')
        found = SAMPLES / Path(str(wanted)).name
        if not found.exists() or SAMPLES.resolve() not in found.resolve().parents:
            raise ValueError(f"no sample called {wanted!r}")
        return found.read_bytes(), found.name

    def _from_multipart(self, body: bytes, content_type: str) -> tuple[bytes, str]:
        """The browser's file input, parsed by hand.

        `cgi.FieldStorage` did this in one line and was removed in Python 3.13,
        so this is the smallest thing that reads one file part correctly.
        """
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise ValueError("multipart body with no boundary")
        sep = b"--" + match.group(1).encode()
        for part in body.split(sep):
            head, _, content = part.partition(b"\r\n\r\n")
            if b"filename=" not in head.lower():
                continue
            name = re.search(rb'filename="([^"]*)"', head)
            filename = (name.group(1).decode("utf-8", "replace") if name else "upload.jpg")
            if not filename:
                continue
            return content.rstrip(b"\r\n-"), filename
        raise ValueError("no file found in the form")


def warm_up() -> None:
    """Load the OCR models before the first visitor arrives.

    Building the engine costs about 4 seconds and reading a receipt costs about
    one. Left alone, the very first person to try the demo waits for both and
    concludes it is slow. On a host that sleeps an idle free instance this is the
    difference between a five second first impression and a one second one.
    """
    try:
        from tab.ocr import engine
        started = time.time()
        engine()
        print(f"  OCR models loaded in {time.time() - started:.1f}s")
    except (SystemExit, Exception) as exc:  # noqa: BLE001 — see below
        # Anything at all here means photographs cannot be read, and none of it
        # is a reason to refuse to start: the text-layer route needs nothing and
        # still works. This caught SystemExit only at first, which missed the
        # actual failure - rapidocr raising ImportError for a missing inference
        # engine - and killed the server on boot instead of degrading.
        print(f"  OCR is NOT available ({type(exc).__name__}: {exc}).")
        print("  PDFs carrying text still work; photographs will not.")
        print('  Fix with:  pip install "tab-agent[ocr]"')


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    warm_up()
    httpd = ThreadingHTTPServer((host, port), Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"TAB demo on http://{shown}:{port}")
    print(f"  reader: OCR (no model, no GPU)   rate limit: {RATE_LIMIT}/min   "
          f"max upload: {MAX_UPLOAD // 1024 // 1024} MB")
    print("  nothing uploaded here is written to disk")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    # Render, Railway and Fly all hand the port over in $PORT.
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = ap.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
