"""Render the review page to PNGs so a person can look at it.

No browser automation library and no MCP server -- Chrome has taken
--screenshot on the command line for years, and that is the whole tool:

    python tools/screenshot.py                 # writes to build/shots/
    python tools/screenshot.py --db my.db      # against a real ledger

Without --db it builds a throwaway ledger from the test fixtures, so the
output is the same on any machine.

Why this exists: the design-token tests can prove the page uses the right
colours and that its javascript parses, and still miss the page being wrong.
A grid row stretched a warning banner into a 455px block of amber and every
test passed. Looking at it is the only check that catches that.
"""

import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tab import store, web  # noqa: E402

# Where Chrome tends to live on each platform. First hit wins.
CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

# preferredColorScheme: 1 is light, 0 is dark. Headless defaults to dark, which
# is not the default a person sees, so both are always taken.
#
# The heights are deliberately taller than the page. Headless Chrome captures a
# surface that does not match the viewport once the page has scrolled, and the
# page scrolls itself on load by focusing the flagged field - which produced a
# perfectly blank PNG of a page that was rendering correctly. Give it room and
# nothing scrolls, so nothing lies.
SHOTS = [
    ("review-light", "1440,1600", 1),
    ("review-dark", "1440,1600", 0),
    ("review-narrow", "760,2600", 1),
]

# A PNG of one flat colour compresses to almost nothing. Anything under this is
# a blank page, and a screenshot tool that hands back a blank page without
# saying so is worse than no screenshot tool.
MIN_PNG_BYTES = 20_000


def find_chrome() -> str:
    import shutil
    for path in CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("chromium")
    if not found:
        raise SystemExit("no Chrome or Edge found - install one, or pass --chrome")
    return found


def demo_ledger(folder: Path) -> str:
    """One receipt that adds up and one that does not, so the page has both."""
    from tab.cli import main as cli_main
    from tests.fixtures import BAD_LINE_MATH, CLEAN, write_receipt_pdf

    db = str(folder / "tab.db")
    receipts = folder / "receipts"
    write_receipt_pdf(receipts / "clean.pdf", CLEAN)
    # The itemised one, with a line that does not multiply out. It puts a
    # basket on the page as well as a flagged field, which is the harder
    # layout and therefore the one worth looking at.
    write_receipt_pdf(receipts / "bad-line-math.pdf", BAD_LINE_MATH)
    with contextlib.redirect_stdout(io.StringIO()):   # the CLI narrates; this should not
        cli_main(["--db", db, "ingest", str(receipts), "--no-model"])
    return db


def serve(db_path: str) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    httpd.conn = store.connect(Path(db_path), check_same_thread=False)
    httpd.lock = threading.Lock()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    for _ in range(50):                              # wait for the socket, do not sleep blind
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return httpd, url
        except OSError:
            time.sleep(0.1)
    raise SystemExit("the review server never answered")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="an existing ledger; default is a throwaway one")
    ap.add_argument("--out", default=str(ROOT / "build" / "shots"))
    ap.add_argument("--chrome", help="path to a Chrome or Edge binary")
    args = ap.parse_args(argv)

    chrome = args.chrome or find_chrome()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        db = args.db or demo_ledger(Path(scratch))
        httpd, url = serve(db)
        try:
            for name, size, scheme in SHOTS:
                png = out / f"{name}.png"
                done = subprocess.run(
                    [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                     "--virtual-time-budget=5000", f"--window-size={size}",
                     f"--blink-settings=preferredColorScheme={scheme}",
                     f"--screenshot={png}", url],
                    capture_output=True, text=True, timeout=180)
                if done.returncode != 0 or not png.exists():
                    print(f"  FAILED {name}: {done.stderr[-400:]}")
                    return 1
                size = png.stat().st_size
                if size < MIN_PNG_BYTES:
                    print(f"  FAILED {name}: {size} bytes is a blank page, not a "
                          f"screenshot. The window is probably shorter than the "
                          f"page, so Chrome captured past the end of it.")
                    return 1
                print(f"  {png}  ({size // 1024} KB)")
        finally:
            httpd.shutdown()
            httpd.conn.close()
            httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
