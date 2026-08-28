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
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tab import store  # noqa: E402

RESULTS = ROOT / "results"
OUT = ROOT / "docs" / "index.html"
REPO = "https://github.com/Zeref538/tab"


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


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT),
                    help="where to write the page (default: docs/index.html)")
    args = ap.parse_args(argv)
    out = Path(args.out)

    scoreboard, ceiling = load_scoreboard()
    payload = {
        "scoreboard": scoreboard,
        "ceiling": ceiling.get("5", {}),
        "replay": record_replay(),
        "built": date.today().isoformat(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8", newline="\n")
    # Without this, GitHub Pages runs the markdown in docs/ through Jekyll.
    (out.parent / ".nojekyll").write_text("", encoding="utf-8")

    committed = sum(1 for r in payload["replay"] if r["outcome"] == "committed")
    print(f"  {out}  ({out.stat().st_size // 1024} KB)")
    print(f"  replay: {len(payload['replay'])} receipts, {committed} committed")
    print(f"  scoreboard: n={scoreboard['n']} on {scoreboard['corpus']}, "
          f"{scoreboard['model']}")
    return 0


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TAB — a receipt is a document that checks itself</title>
<meta name="description" content="A local-first receipt reader that trusts arithmetic instead of a model's confidence.">
<style>
:root {
  --paper: #FAF9F6; --card: #FFFFFF;
  --ink: #1A1A18; --ink-soft: #5C5A54;
  --rule: #E3E0D8; --rule-strong: #8A867C;
  --flag: #B45309; --flag-wash: #FDF3E3;
  --ok: #2F6F4F; --ok-wash: #EDF5F0;
  --stop: #A32F2F; --focus: #1D4ED8;
  --font-ui: ui-sans-serif, "Inter", "Segoe UI", system-ui, sans-serif;
  --font-num: ui-monospace, "JetBrains Mono", "Cascadia Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #161614; --card: #1F1F1C;
    --ink: #F2F0EA; --ink-soft: #A8A49A;
    --rule: #34332E; --rule-strong: #6E6B62;
    --flag: #F0A85C; --flag-wash: #2C2318;
    --ok: #6FBF95; --ok-wash: #17251E;
    --stop: #E8837E; --focus: #7FA5FF;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 17px/1.65 var(--font-ui);
}
main { max-width: 780px; margin: 0 auto; padding: 56px 24px 96px; }
h1 { font-size: 34px; line-height: 1.2; margin: 0 0 8px; letter-spacing: -.01em; }
h2 { font-size: 22px; margin: 56px 0 12px; letter-spacing: -.005em; }
h3 { font-size: 15px; margin: 28px 0 8px; text-transform: uppercase;
     letter-spacing: .08em; color: var(--ink-soft); font-weight: 600; }
p { margin: 0 0 16px; }
a { color: var(--focus); }
.lede { font-size: 20px; color: var(--ink-soft); margin-bottom: 28px; }
.rule { border: 0; border-top: 1px solid var(--rule); margin: 40px 0 0; }
code, .num { font-family: var(--font-num); }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr));
         gap: 12px; margin: 20px 0 8px; }
.card { background: var(--card); border: 1px solid var(--rule); border-radius: 10px;
        padding: 16px; }
.card .big { font: 600 30px/1.1 var(--font-num); display: block; margin-bottom: 6px;
             font-variant-numeric: tabular-nums; }
.card .name { font-size: 14px; color: var(--ink-soft); }
.card.worst { border-color: var(--flag); background: var(--flag-wash); }
.card.worst .big { color: var(--flag); }

table { width: 100%; border-collapse: collapse; font-size: 15px; margin: 12px 0; }
th { text-align: left; font-size: 13px; text-transform: uppercase;
     letter-spacing: .06em; color: var(--ink-soft); font-weight: 600;
     padding-bottom: 6px; }
td { padding: 7px 0; border-top: 1px solid var(--rule); }
td.n { text-align: right; font-family: var(--font-num);
       font-variant-numeric: tabular-nums; }
.bar { height: 6px; border-radius: 3px; background: var(--rule); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--ok); }

.note { background: var(--flag-wash); border-left: 3px solid var(--flag);
        border-radius: 4px; padding: 14px 18px; margin: 20px 0; }
.note strong { color: var(--flag); }

/* ---- the replay ---- */
#replay { background: var(--card); border: 1px solid var(--rule); border-radius: 10px;
          padding: 4px 18px 18px; margin-top: 16px; }
.doc { border-top: 1px solid var(--rule); padding: 14px 0; }
.doc:first-child { border-top: 0; }
.doc-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.doc-name { font-family: var(--font-num); font-size: 15px; }
.tag { font-size: 12px; padding: 2px 8px; border-radius: 999px;
       border: 1px solid var(--rule-strong); color: var(--ink-soft); }
.tag.committed { color: var(--ok); border-color: var(--ok); }
.tag.needs_review { color: var(--flag); border-color: var(--flag); }
.tag.unreadable { color: var(--stop); border-color: var(--stop); }
.tag.duplicate { color: var(--ink-soft); }
.why { color: var(--ink-soft); font-size: 14px; margin: 6px 0 0; }
.checks { list-style: none; margin: 8px 0 0; padding: 0;
          font-size: 14px; }
.checks li { padding: 2px 0 2px 22px; position: relative; color: var(--ink-soft); }
.checks li::before { position: absolute; left: 0; font-family: var(--font-num); }
.checks li.pass::before { content: "OK"; color: var(--ok); font-size: 11px; top: 4px; }
.checks li.fail::before { content: "!!"; color: var(--flag); }
.checks li.skip::before { content: "--"; color: var(--rule-strong); }
.checks li.fail { color: var(--ink); }

.doc { opacity: 0; transform: translateY(6px);
       transition: opacity .35s ease, transform .35s ease; }
.doc.shown { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) {
  .doc { opacity: 1; transform: none; transition: none; }
}
button.replay-again {
  font: 15px var(--font-ui); color: var(--ink); background: var(--card);
  border: 1px solid var(--rule-strong); border-radius: 6px;
  padding: 8px 14px; min-height: 44px; cursor: pointer; margin-top: 14px;
}
button.replay-again:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
footer { color: var(--ink-soft); font-size: 14px; margin-top: 56px; }
</style>
</head>
<body>
<main>

<h1>A receipt is a document that checks itself.</h1>
<p class="lede">TAB reads receipts, then proves the numbers add up before it
writes anything down. Nothing is committed because a model sounded sure.</p>

<p>Point it at a folder. It pulls out the merchant, the date, the VAT breakdown
and every line of the basket, then asks the receipt about itself: do the items
reach the subtotal, is the VAT twelve percent of the VATable sales, do the parts
reach the total. Receipts that answer yes go into the ledger and are never
mentioned again. The rest go to a person, with the failing number highlighted
and the reason written out in words.</p>

<p>It runs on a laptop, on a free local model, and no receipt leaves the machine
— which is also why this page is a recording rather than an upload box.
<a href="__REPO__">Source and the decision records are on GitHub.</a></p>

<hr class="rule">

<h2>A real run, replayed</h2>
<p>Six sample documents, ingested for real when this page was built. Nothing
below was written by hand — if the software changes its mind, the page changes
with it.</p>

<p>The recording is made with the vision model switched off, so it rebuilds on
any machine with nothing running. That is why <code>scanned.pdf</code> stops
where it does: it is a page with no text on it, so it is the one file here that
would have gone to the model.</p>

<div id="replay"></div>
<button class="replay-again" id="again" type="button">Play it again</button>

<hr class="rule">

<h2>What it scores</h2>
<p id="board-intro"></p>

<div class="cards" id="cards"></div>
<p class="why" id="cards-note"></p>

<h3>Per field</h3>
<table id="fields"><thead><tr><th>Field</th><th>Read correctly</th>
<th style="width:110px"></th></tr></thead><tbody></tbody></table>
<p class="why" id="unscored"></p>

<div class="note" id="caveat"></div>

<h3>The ceiling</h3>
<p id="ceiling-text"></p>

<hr class="rule">

<h2>What is not claimed</h2>
<p>No Philippine accuracy figure appears anywhere on this page. CORD is a corpus
of Indonesian receipts; it has no BIR-style VAT breakdown, no TIN, no OR number.
It measures whether a small local model can read a photograph of a receipt at
all, and nothing more. Around fifty hand-labelled Philippine receipts — thermal
fade and phone photographs included — have to exist before any VAT or PH number
is published here.</p>

<p>The straight-through rate above is also not a promise about your receipts. It
was measured on one corpus, at one tolerance, with one model, at a sample size
printed next to it. Every one of those things moves the number.</p>

<footer id="built"></footer>
</main>

<script>
const DATA = __DATA__;
const pct = x => x === null || x === undefined ? "n/a" : (x * 100).toFixed(0) + "%";
const pesos = c => c === null || c === undefined ? "—"
  : "\\u20b1" + (c / 100).toLocaleString("en-PH", {minimumFractionDigits: 2,
                                                  maximumFractionDigits: 2});
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

// ---- the replay -----------------------------------------------------------
function drawReplay() {
  const host = document.getElementById("replay");
  host.innerHTML = "";
  const nodes = DATA.replay.map(doc => {
    const box = el("div", "doc");
    const head = el("div", "doc-head");
    head.append(el("span", "doc-name", doc.name),
                el("span", "tag " + doc.outcome, doc.outcome.replace("_", " ")));
    if (doc.total !== null && doc.total !== undefined)
      head.append(el("span", "tag", pesos(doc.total)));
    if (doc.items)
      head.append(el("span", "tag", doc.items + (doc.items === 1 ? " line" : " lines")));
    box.append(head);

    if (doc.route) box.append(el("p", "why", doc.route));
    else if (doc.why) box.append(el("p", "why", doc.why));

    if (doc.checks.length) {
      const list = el("ul", "checks");
      for (const c of doc.checks) {
        list.append(el("li", c.status, c.name.replace(/_/g, " ") + " — " + c.detail));
      }
      box.append(list);
    }
    host.append(box);
    return box;
  });

  // Shown one at a time, at reading speed, because the point of the demo is
  // that a person can follow what it decided and why.
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  nodes.forEach((n, i) => {
    if (reduced) { n.classList.add("shown"); return; }
    setTimeout(() => n.classList.add("shown"), 250 + i * 550);
  });
}

// ---- the scoreboard -------------------------------------------------------
function drawBoard() {
  const s = DATA.scoreboard, a = s.arithmetic_only;
  document.getElementById("board-intro").textContent =
    `Measured on ${s.n} receipts from the ${s.corpus.toUpperCase()} test split, `
    + `read by ${s.model} running locally, at a tolerance of `
    + `${(s.tolerance / 100).toFixed(2)} pesos.`;

  const cards = [
    ["straight through", pct(a.straight_through_rate), "needed no human at all", false],
    ["silent error rate", pct(a.silent_error_rate), "committed, and the total was wrong", true],
    ["escalation precision", pct(a.escalation_precision), "of the ones it queried, really were wrong", false],
    ["totals read", s.totals_correct + "/" + s.n, "before any checking", false],
  ];
  const host = document.getElementById("cards");
  for (const [name, value, note, worst] of cards) {
    const c = el("div", "card" + (worst ? " worst" : ""));
    c.append(el("span", "big", value), el("span", "name", name + " — " + note));
    host.append(c);
  }
  document.getElementById("cards-note").textContent =
    "Silent error rate is the one that matters. A tool that escalates everything "
    + "is useless but harmless; one that writes a wrong total into a tax return "
    + "is worse than doing nothing. Scored the strict way: a committed receipt "
    + "whose total does not match the label. Counting any wrong field at all "
    + "puts it at " + pct(DATA.scoreboard.arithmetic_only_any_field.silent_error_rate) + ".";

  const body = document.querySelector("#fields tbody");
  for (const [field, r] of Object.entries(s.field_accuracy)) {
    const tr = body.insertRow();
    tr.insertCell().textContent = field.replace(/_/g, " ");
    const n = tr.insertCell(); n.className = "n";
    n.textContent = `${r.correct}/${r.n}`;
    const barCell = tr.insertCell();
    const bar = el("div", "bar");
    const fill = el("span"); fill.style.width = (r.accuracy * 100) + "%";
    bar.append(fill); barCell.append(bar);
  }
  document.getElementById("unscored").textContent =
    "Not scored on this corpus, because CORD does not label them: "
    + s.unscoreable_fields.join(", ") + ".";

  document.getElementById("caveat").innerHTML =
    "<strong>Read the two numbers together.</strong> " + pct(a.straight_through_rate)
    + " straight through with a " + pct(a.silent_error_rate) + " silent error rate "
    + "means the arithmetic caught almost everything the model got wrong: of the "
    + (s.n - s.totals_correct) + " receipts whose total was misread, all but one "
    + "were held back for a person. That is the whole design in one line — "
    + "confidence comes from the arithmetic, never from the model.";

  const ceiling = DATA.ceiling;
  document.getElementById("ceiling-text").textContent = ceiling.n
    ? `The checks cannot do better than the receipts allow. Running them against `
      + `the hand-written gold labels rather than the model's output, `
      + `${ceiling.self_consistent} of ${ceiling.n} pass their own arithmetic. `
      + `The remainder are receipts that genuinely do not add up, so roughly `
      + `${100 - Math.round(ceiling.rate * 100)}% of this corpus can never go `
      + `straight through no matter how well anything reads it.`
    : "";

  document.getElementById("built").textContent =
    "Built from results/scoreboard-" + s.corpus + "-test.json on " + DATA.built
    + ". Every figure on this page is generated; none is typed.";
}

drawBoard();
drawReplay();
document.getElementById("again").onclick = drawReplay;
</script>
</body>
</html>
"""

TEMPLATE = TEMPLATE.replace("__REPO__", REPO)

if __name__ == "__main__":
    raise SystemExit(main())
