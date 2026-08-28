"""The review page must use the colours the design brief specifies.

A design document that the code has quietly drifted away from is worse than no
design document, because it stops the next reader from checking. This is the
cheapest possible guard against that: every token defined in DESIGN_BRIEF.md
must appear in review.html with the same value.

It also re-computes the contrast ratios rather than trusting the numbers written
beside them, because those were wrong once already.

Run: pytest tests/test_design_tokens.py -q   (or: python tests/test_design_tokens.py)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BRIEF = ROOT / "docs" / "DESIGN_BRIEF.md"
PAGE = ROOT / "tab" / "static" / "review.html"

TOKEN = re.compile(r"(--[a-z-]+):\s*(#[0-9A-Fa-f]{6})")


def tokens_from(text: str, block: str) -> dict:
    """Pull `--name: #hex` pairs out of one CSS block."""
    start = text.find(block)
    assert start != -1, f"could not find {block!r}"
    end = text.find("}", start)
    return {m.group(1): m.group(2).upper()
            for m in TOKEN.finditer(text[start:end])}


def relative_luminance(hex_colour: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(foreground: str, background: str) -> float:
    a, b = relative_luminance(foreground), relative_luminance(background)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_light_tokens_match_the_brief():
    brief = tokens_from(BRIEF.read_text(encoding="utf-8"), ":root {")
    page = tokens_from(PAGE.read_text(encoding="utf-8"), ":root {")
    for name, value in brief.items():
        assert page.get(name) == value, (
            f"{name} is {page.get(name)} on the page but {value} in the brief")


def test_dark_tokens_match_the_brief():
    brief_text = BRIEF.read_text(encoding="utf-8")
    brief = tokens_from(brief_text, ':root[data-theme="dark"] {')
    page = tokens_from(PAGE.read_text(encoding="utf-8"),
                       "@media (prefers-color-scheme: dark)")
    for name, value in brief.items():
        assert page.get(name) == value, (
            f"dark {name} is {page.get(name)} on the page but {value} in the brief")


def test_text_colours_clear_four_and_a_half_to_one():
    """WCAG's floor for body text. Computed here, not copied from the brief."""
    page_text = PAGE.read_text(encoding="utf-8")
    for block, label in ((":root {", "light"),
                         ("@media (prefers-color-scheme: dark)", "dark")):
        t = tokens_from(page_text, block)
        background = t["--paper"]
        for name in ("--ink", "--ink-soft", "--flag", "--ok", "--stop", "--focus"):
            ratio = contrast(t[name], background)
            assert ratio >= 4.5, f"{label} {name} is only {ratio:.2f}:1 on --paper"


def test_control_borders_clear_three_to_one():
    """SC 1.4.11: the visible edge of something you can click. --rule is the one
    token below this, which is why it is only allowed on decorative hairlines."""
    page_text = PAGE.read_text(encoding="utf-8")
    for block, label in ((":root {", "light"),
                         ("@media (prefers-color-scheme: dark)", "dark")):
        t = tokens_from(page_text, block)
        ratio = contrast(t["--rule-strong"], t["--paper"])
        assert ratio >= 3.0, f"{label} --rule-strong is only {ratio:.2f}:1"


def test_the_page_promises_what_the_brief_promises():
    page = PAGE.read_text(encoding="utf-8")
    assert "tabular-nums" in page, "amounts must line up in a column"
    assert "prefers-reduced-motion" in page, "the brief requires an alternative"
    assert "focus-visible" in page, "a removed focus ring is a bug"
    assert 'aria-live="polite"' in page, "the failing-check sentence is announced"
    assert "min-height: 44px" in page, "44px minimum target size"
    assert "position: sticky" in page, (
        "the failing-check sentence must survive the scroll that autofocus causes")


def test_no_colour_is_hard_coded_outside_the_tokens():
    """Every colour in the page comes from a token, so the dark theme cannot
    have a hole in it that only shows up on someone else's machine."""
    page = PAGE.read_text(encoding="utf-8")
    css = page[page.find("<style>"):page.find("</style>")]
    declared = {m.group(2).upper() for m in TOKEN.finditer(css)}
    used = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}", css)}
    assert used <= declared, f"colours used outside the token blocks: {used - declared}"


def test_the_page_javascript_parses():
    """No browser is available here, so this is the closest thing to running it.

    It catches the whole class of "the page silently does nothing because line
    140 has a stray bracket", which no HTTP-level test would ever notice.
    Skipped rather than failed where node is not installed.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("     (skipped: node is not installed)")
        return

    page = PAGE.read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", page, re.S)
    assert script, "the page has no script block"

    with tempfile.TemporaryDirectory() as d:
        js = Path(d) / "review.mjs"
        js.write_text(script.group(1), encoding="utf-8")
        done = subprocess.run([node, "--check", str(js)],
                              capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            passed += 1
            print(f"  ok  {name}")
    print(f"\n{passed} checks passed")
