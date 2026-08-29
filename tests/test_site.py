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
    allowed = {
        "100%", "0%", "50%",   # CSS lengths and keyframe stops, not measurements
        "12%",                 # the statutory Philippine VAT rate: a fact of
                               # law, printed on the receipt itself, and the
                               # same constant as tab.receipt.VAT_RATE_PERCENT.
                               # This rule is about measured RESULTS.
    }
    found = [f for f in found if f.strip() not in allowed]
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


def test_each_reader_row_matches_the_scoreboard_it_came_from():
    """The comparison table is the easiest thing on the page to fake.

    Three arms measured hours apart, one of them resumed twice — it would be very
    easy for a row to end up labelled 7b while carrying the 3b numbers. That
    already happened once: the eval wrote every model to the same predictions
    file, so `--model qwen2.5vl:7b` resumed from the 3b run and printed a
    scoreboard headed 7b. So every cell is checked back against its own file.
    """
    readers = page_data(PAGE.read_text(encoding="utf-8"))["readers"]
    assert len(readers) >= 2, "a comparison of one is not a comparison"
    assert sum(bool(r["shipped"]) for r in readers) == 1, "exactly one default"

    by_model = {r["model"]: r for r in readers}
    for _, name, _ in build_site.READERS:
        path = ROOT / "results" / name
        if not path.exists():
            continue
        board = json.loads(path.read_text(encoding="utf-8"))["scoreboard"]
        row = by_model[board["model"]]
        assert row["n"] == board["n"]
        assert row["totals_correct"] == board["totals_correct"]
        assert row["committed"] == board["arithmetic_only"]["committed"]
        assert row["median_seconds"] == board["median_seconds"]
        assert (row["silent_any"]
                == board["arithmetic_only_any_field"]["silent_error_rate"])

    # Every arm has to be the same size, or the columns are not comparable.
    assert len({r["n"] for r in readers}) == 1, "arms measured on different n"


def test_the_numbers_cannot_be_lost_to_a_network_error():
    """Every figure is baked into the file, not fetched.

    The page loads a font stylesheet, which is a deliberate exception: type
    carries the personality of a product page, and a font that fails to load
    falls back to the declared stack and costs nothing but the look. A *script*
    or a *fetch* from elsewhere is different - it can leave the scoreboard blank
    on someone's machine and make the page quietly claim nothing at all.
    """
    text = PAGE.read_text(encoding="utf-8")
    assert "http://" not in text.replace("http://www.w3.org", "")
    for forbidden in ("fetch(", "<script src"):
        assert forbidden not in text, forbidden
    assert "const DATA = {" in text, "the figures must be in the file"

    # Any stylesheet that is loaded has to be the font one and nothing else.
    for href in re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', text):
        assert href.startswith("https://fonts.googleapis.com/"), href

    # And the faces must have a real fallback, or a blocked font host means a
    # page set in whatever the browser picks.
    assert "ui-monospace" in text and "system-ui" in text


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
