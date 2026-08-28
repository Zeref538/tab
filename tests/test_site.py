"""The public page must not contain a number anybody typed.

A figure retyped from a terminal onto a portfolio page will be wrong within a
month, and wrong in the flattering direction. So the page is generated, and
these checks are what stop it quietly becoming hand-maintained again.

Run: pytest tests/test_site.py -q      (or: python tests/test_site.py)
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_site  # noqa: E402

PAGE = ROOT / "docs" / "index.html"
BOARD = ROOT / "results" / "scoreboard-cord-test.json"

# Digits followed by a percent sign, or a fraction like 89/100. Either one in
# the template means somebody typed a measurement into the page.
TYPED_FIGURE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d+\s*/\s*\d{2,}\b")


def page_data(text: str) -> dict:
    match = re.search(r"const DATA = (\{.*?\});\n", text, re.S)
    assert match, "the page has no data blob"
    return json.loads(match.group(1))


def test_no_figure_is_typed_into_the_template():
    """The check that keeps the rest honest. Every number on the page has to
    arrive through the data blob, so the template itself must contain none."""
    template = build_site.TEMPLATE
    body = template[template.find("<body>"):]
    found = TYPED_FIGURE.findall(body)
    # 100% and 0% appear as CSS lengths and keyframe stops, not as measurements.
    found = [f for f in found if f.strip() not in {"100%", "0%", "50%"}]
    assert not found, f"typed figures in the page template: {found}"


def test_the_page_matches_the_scoreboard_it_was_built_from():
    text = PAGE.read_text(encoding="utf-8")
    board = json.loads(BOARD.read_text(encoding="utf-8"))["scoreboard"]
    shown = page_data(text)["scoreboard"]
    for key in ("n", "corpus", "model", "tolerance", "totals_correct"):
        assert shown[key] == board[key], key
    assert shown["arithmetic_only"] == board["arithmetic_only"]
    assert shown["field_accuracy"] == board["field_accuracy"]


def test_the_replay_is_a_real_run_with_every_outcome_in_it():
    """If it only ever showed the receipts that worked it would be an advert,
    not a demonstration."""
    replay = page_data(PAGE.read_text(encoding="utf-8"))["replay"]
    outcomes = {r["outcome"] for r in replay}
    assert {"committed", "needs_review", "duplicate", "unreadable"} <= outcomes, outcomes
    flagged = [r for r in replay if r["outcome"] == "needs_review"]
    assert any(c["status"] == "fail" for r in flagged for c in r["checks"]), (
        "a held receipt has to show which check failed")


def test_no_philippine_accuracy_claim_is_made():
    """Gate D of Phase 0 is still open: CORD is Indonesian. Until ~50 real
    Philippine receipts are hand-labelled, no PH or VAT figure may appear."""
    text = PAGE.read_text(encoding="utf-8")
    body = text[text.find("<body>"):text.find("<script>")]
    flat = " ".join(body.split())      # the prose is wrapped; the claim is not
    assert "CORD is a corpus of Indonesian receipts" in flat
    assert "No Philippine accuracy figure appears anywhere on this page" in flat


def test_the_page_carries_its_sample_size_wherever_it_carries_a_rate():
    """A rate without an n beside it is a claim, not a measurement."""
    text = PAGE.read_text(encoding="utf-8")
    assert page_data(text)["scoreboard"]["n"] > 0
    assert "${s.n} receipts from the" in text, (
        "the sentence introducing the rates must interpolate the sample size")
    assert "${r.correct}/${r.n}" in text, (
        "every per-field figure must carry the count it was measured over")


def test_it_is_one_self_contained_file():
    """No CDN and no fetch, so the page works from file:// and cannot silently
    lose its numbers to a network error."""
    text = PAGE.read_text(encoding="utf-8")
    assert "http://" not in text.replace("http://www.w3.org", "")
    for forbidden in ("fetch(", "<script src", "<link rel=\"stylesheet\""):
        assert forbidden not in text, forbidden


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
