"""Build the public page: docs/index.html.

    python tools/build_site.py

Two things go on that page and neither is typed by hand.

The **scoreboard** is read from `results/scoreboard-cord-test.json`, which
`python -m tab.eval` writes. A number on a portfolio page that was retyped from
a terminal is a number that will be wrong within a month, and wrong in the
flattering direction.

The **replay** is recorded here and now, by actually ingesting the sample
receipts and reading back what the ledger decided. Nobody writes the script for
it: if the software changes its mind about a receipt, the page changes with it.
That is the point of ADR 0004 — receipts never leave the machine, so the public
page shows a recording of a real run rather than offering an upload box.

Output is one self-contained file. No fetch, no CDN, so it works over file://
as well as over GitHub Pages.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tab import store  # noqa: E402

LF = chr(10)        # spelled out: a literal backslash-n keeps getting mangled
                    # on the way through a shell heredoc into this file
ARTIFACT_TITLE = "Receipts That Check Themselves"
RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "index.html"
REPO = "https://github.com/Zeref538/tab"

# Where the live demo is, once it has been deployed. Empty until then, and the
# page renders no "try it" button while it is empty — a button promising a live
# demo that answers 404 is worse than no button, and a URL typed in hopefully
# before the deploy is exactly how that happens.
#
#   TAB_DEMO_URL=https://tab-demo.onrender.com python tools/build_site.py
DEMO_URL = os.environ.get("TAB_DEMO_URL", "").rstrip("/")


def record_replay() -> list[dict]:
    """Ingest the sample receipts for real and write down what happened.

    Recorded through pipeline.ingest_one, one file at a time, so what the page
    shows is literally what the command line narrates - including the ones it
    skips. Reconstructing it from the tables afterwards would miss a duplicate
    entirely, because a duplicate never becomes a row.

    The vision model is switched off, so this rebuilds on any machine with no
    Ollama running. scanned.pdf is the file that would have gone to it, and it
    says so rather than pretending otherwise.
    """
    from tab import pipeline
    from tests import fixtures

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        folder = tmp / "receipts"
        # Chosen to show one of each outcome.
        written = [
            ("clean.pdf", fixtures.CLEAN),
            ("restaurant.pdf", fixtures.RESTAURANT),
            ("bad-line-math.pdf", fixtures.BAD_LINE_MATH),
            ("wrong-total.pdf", fixtures.WRONG_TOTAL),
        ]
        for name, text in written:
            fixtures.write_receipt_pdf(folder / name, text)
        fixtures.write_image_only_pdf(folder / "scanned.pdf")
        # Copied, not written again: pymupdf stamps a creation time into every
        # PDF it makes, so re-writing the same text gives different bytes and a
        # different hash. A copy is what re-importing a folder actually looks
        # like, and it is the hash guard that catches it.
        shutil.copy2(folder / "clean.pdf", folder / "clean-again.pdf")

        order = [n for n, _ in written] + ["scanned.pdf", "clean-again.pdf"]
        conn = store.connect(tmp / "tab.db")
        try:
            return [_as_step(conn, name,
                             pipeline.ingest_one(conn, folder / name, use_model=False))
                    for name in order]
        finally:
            conn.close()


def _as_step(conn, name: str, result) -> dict:
    """One file, as the command line would have narrated it."""
    step = {
        "name": name,
        "outcome": "committed" if result["outcome"] == "commit" else result["outcome"],
        "why": result.get("why"),
        "route": result.get("route"),
        "total": result.get("total"),
        "checks": [], "items": 0, "merchant": None,
    }
    if result["outcome"] == "duplicate":
        step["why"] = "these exact bytes have been imported before"
        return step

    receipt = conn.execute("SELECT * FROM receipts WHERE document_id = ?",
                           (result["document_id"],)).fetchone()
    if receipt is None:
        return step
    step["merchant"] = receipt["merchant"]
    step["items"] = conn.execute(
        "SELECT COUNT(*) c FROM line_items WHERE receipt_id = ?",
        (receipt["id"],)).fetchone()["c"]
    step["checks"] = [dict(r) for r in conn.execute(
        "SELECT name, status, detail FROM checks WHERE receipt_id = ? ORDER BY id",
        (receipt["id"],))]
    step["route"] = next(
        (r["why"] for r in conn.execute(
            "SELECT why FROM decisions WHERE document_id = ? AND step = 'route'",
            (result["document_id"],))), step["route"])
    return step


def load_scoreboard() -> tuple[dict, dict]:
    board = RESULTS / "scoreboard-cord-test.json"
    if not board.exists():
        raise SystemExit(
            f"{board} is missing. The page refuses to invent numbers.\n"
            f"Generate it first:\n"
            f"  python -m tab.eval --corpus cord --split test --rescore")
    data = json.loads(board.read_text(encoding="utf-8"))
    ceiling_path = RESULTS / "ceiling-cord-test.json"
    ceiling = (json.loads(ceiling_path.read_text(encoding="utf-8"))
               if ceiling_path.exists() else {})
    # `rows` is 100 per-receipt records. The page does not use them and they
    # would triple the file, so they stay in results/ where they belong.
    return data["scoreboard"], ceiling


# The readers measured on the same split, in the order the page lists them.
# `shipped` marks the one TAB actually runs unless told otherwise.
READERS = [
    ("vision 3b", "scoreboard-cord-test.json", True),
    ("vision 7b", "scoreboard-cord-test-qwen2.5vl-7b.json", False),
    ("OCR", "scoreboard-cord-test-rapidocr-ppocrv6.json", False),
]


def load_readers() -> list[dict]:
    """Every reader that has a scoreboard on disk, for the comparison table.

    A missing arm is skipped rather than fatal. The default board is already
    required by load_scoreboard(), and a machine that has only run one arm
    should still be able to build the page - it just shows one row.

    Only the arithmetic-only block is taken. The headline straight-through rate
    on this corpus is zero for every reader, because CORD labels no merchant and
    no date and those format rules therefore fail on all 100 documents. Putting
    three zeroes side by side would say nothing about the readers and a great
    deal about the corpus.
    """
    out = []
    for label, name, shipped in READERS:
        path = RESULTS / name
        if not path.exists():
            continue
        s = json.loads(path.read_text(encoding="utf-8"))["scoreboard"]
        arith = s["arithmetic_only"]
        out.append({
            "label": label,
            "model": s["model"],
            "shipped": shipped,
            "n": s["n"],
            "committed": arith["committed"],
            "straight_through": arith["straight_through_rate"],
            "silent_strict": arith["silent_error_rate"],
            # Silent error counting ANY wrong field, not just the total. Both
            # denominators are n, so 0.15 is 15 documents out of 100 filed with
            # something wrong in them - not 15% of the ones it chose to file.
            "silent_any": s["arithmetic_only_any_field"]["silent_error_rate"],
            "totals_correct": s["totals_correct"],
            "median_seconds": s["median_seconds"],
        })
    return out


def as_artifact(page: str) -> str:
    """The same page, shaped for a Claude artifact.

    An artifact is wrapped in its own <!doctype>/<head>/<body> at publish time,
    so those tags have to come off or the page ends up nested inside itself.
    Everything else - the tokens, the type, the markup - is untouched: this repo
    already has a design system in docs/DESIGN_BRIEF.md with a test that fails
    when the page drifts from it, and a second look-and-feel would be a second
    thing to keep in sync.
    """
    style = re.search(r"<style>(.*?)</style>", page, re.S)
    body = re.search(r"<body>(.*?)</body>", page, re.S)
    if not (style and body):
        raise SystemExit("the page is not shaped the way this expects")
    # The site's own <title> carries the thesis after a dash, which reads fine
    # in a browser tab and badly in a gallery, where a title has to work as a
    # name. Same page, named rather than described.
    return LF.join([f"<title>{ARTIFACT_TITLE}</title>",
                    f"<style>{style.group(1)}</style>",
                    body.group(1)])


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT),
                    help="where to write the page (default: docs/index.html)")
    ap.add_argument("--artifact", metavar="PATH",
                    help="also write an artifact-shaped copy, for publishing")
    args = ap.parse_args(argv)
    out = Path(args.out)

    scoreboard, ceiling = load_scoreboard()
    payload = {
        "scoreboard": scoreboard,
        "ceiling": ceiling.get("5", {}),
        "readers": load_readers(),
        "demo_url": DEMO_URL,
        "replay": record_replay(),
        "built": date.today().isoformat(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8", newline="\n")
    # Without this, GitHub Pages runs the markdown in docs/ through Jekyll.
    (out.parent / ".nojekyll").write_text("", encoding="utf-8")

    missing = copy_shots(out.parent / "img")
    if missing:
        print("  the page shows a screenshot and these are not there yet: "
              + ", ".join(missing))
        print("  make them with:  python tools/screenshot.py")

    if args.artifact:
        shaped = Path(args.artifact)
        shaped.parent.mkdir(parents=True, exist_ok=True)
        shaped.write_text(as_artifact(out.read_text(encoding="utf-8")),
                          encoding="utf-8", newline=LF)
        print(f"  {shaped}  (artifact-shaped copy)")

    committed = sum(1 for r in payload["replay"] if r["outcome"] == "committed")
    print(f"  {out}  ({out.stat().st_size // 1024} KB)")
    print(f"  replay: {len(payload['replay'])} receipts, {committed} committed")
    print(f"  scoreboard: n={scoreboard['n']} on {scoreboard['corpus']}, "
          f"{scoreboard['model']}")
    print(f"  readers compared: "
          + ", ".join(r["model"] for r in payload["readers"]))
    if DEMO_URL:
        print(f"  live demo linked: {DEMO_URL}")
    else:
        print("  live demo: not linked (set TAB_DEMO_URL once it is deployed)")
    return 0


# The page itself lives beside this file rather than inside it. A 400-line HTML
# string buried in a Python module is a page nobody edits with any confidence,
# and every escape in it is one more thing a shell can mangle on the way in.
TEMPLATE = (Path(__file__).resolve().parent / "site_template.html").read_text(
    encoding="utf-8").replace("__REPO__", REPO)

# Screenshots the page shows. Copied rather than referenced out of build/ so the
# published folder is self-contained; regenerate them with tools/screenshot.py.
SHOTS = ["review-light.png", "review-dark.png"]


def copy_shots(into: Path) -> list[str]:
    """Put the product screenshots next to the page. Returns what is missing."""
    source = ROOT / "build" / "shots"
    into.mkdir(parents=True, exist_ok=True)
    missing = []
    for name in SHOTS:
        found = source / name
        if found.exists():
            shutil.copy2(found, into / name)
        elif not (into / name).exists():
            missing.append(name)
    return missing


if __name__ == "__main__":
    raise SystemExit(main())
