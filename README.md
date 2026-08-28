# TAB — Tally All Bills

Point it at a pile of receipts. It reads each one, **checks that the numbers
actually add up**, and appends a row to your ledger. When the arithmetic
disagrees with itself, it does not guess — the receipt goes to a review queue
with the doubtful field highlighted.

Everything runs on your machine. No receipt is uploaded anywhere.

> **Status: it runs end to end, with a review screen.** Point it at a folder,
> fix what it flags, get a CSV. The folder watcher is not built yet, so nothing
> runs unattended.

---

## Why the arithmetic check is the whole idea

A model that reads a receipt will tell you the total is ₱1,240.00 with complete
confidence, and be wrong. Asking it how sure it is does not help — it is just as
confident either way.

So TAB never asks. It checks:

```
Σ(quantity × unit price)  ≈  subtotal
subtotal + service + VAT − discounts ≈  total   (or VAT already inside)
VAT                        ≈  VATable sales × 0.12
```

If a receipt fails its own arithmetic, something was misread, and you know it
without any model being involved. That one guard costs nothing to run and is
what separates this from a wrapper around an OCR call.

## What it does so far, measured

On **100 photographed Indonesian receipts** (CORD test split), with the free
local `qwen2.5vl:3b` model, on one laptop GPU:

| | |
|---|---|
| totals read correctly | **89 / 100** |
| wrong totals caught by the arithmetic alone | **10 of 11** |
| straight-through (no human needed) | **30%** |
| silent error rate (committed and wrong) | **1%** |
| median time per receipt | 21.7s |

The guard works. It catches nine in ten wrong totals without any model being
asked how sure it feels. It is also over-cautious right now — 25 correct
receipts in 100 were escalated for no good reason — and that is the next thing
to improve.

**These are Indonesian receipts.** They say nothing about Philippine VAT, TIN or
OR numbers, and no such figure is claimed until a local labelled set exists.
Full working and the four bugs this shook out: [docs/PHASE0.md](docs/PHASE0.md).

## What it reports

Four numbers, always together, never one alone:

| metric | what it catches |
|---|---|
| field-level accuracy | per field, on a hand-labelled set — not one blended score |
| **straight-through rate** | share of receipts that needed no human at all |
| escalation precision | when it asked for help, was it genuinely unsure? |
| **silent error rate** | confident, unchecked, and **wrong** |

The last one is the one that matters. A tool that escalates everything is
useless but harmless. A tool that writes a wrong total into your tax records is
worse than doing nothing at all.

## Running it

```bash
pip install -e .
ollama pull qwen2.5vl:3b          # only needed for photographs

python -m tab watch ./receipts     # read them as they land, and say nothing else
python -m tab ingest ./receipts   # or one batch now; a file or a folder, safe to re-run
python -m tab review              # the review screen, in your browser
python -m tab queue               # or the same thing in the terminal
python -m tab export --csv ledger.csv
```

`watch` is the one to leave running. Drop receipts in the folder and the only
thing that ever appears on screen is the handful that need you:

```
watching ./receipts
ledger: data/tab.db
only receipts that need you will appear here. Ctrl-C to stop.
  needs you  receipt-05.pdf: the parts add up to ₱1,190.00 but the receipt says ₱1,190.50. Difference: ₱0.50
  needs you  receipt-12.pdf: the parts add up to ₱1,190.00 but the receipt says ₱1,190.50. Difference: ₱0.50
  needs you  receipt-18.pdf: the parts add up to ₱1,190.00 but the receipt says ₱1,190.50. Difference: ₱0.50
```

That is the whole output of a run where twenty receipts were dropped into the
folder. The other seventeen went into the ledger without a word, which is the
point.

`pip` also installs a `tab` command, but it may land in a scripts folder that is
not on your PATH — it did here. `python -m tab` always works, so that is what
these instructions use.

Try it on the sample receipts, no model required:

```bash
python tests/fixtures.py                                  # build sample PDFs
python -m tab ingest tests/fixtures --no-model
python -m tab review
```

You should see three receipts committed, one held back because its total is
fifty centavos off, and one PDF that has no text layer and therefore needs the
model. `itemised.pdf` is the one worth opening in `tab review` — its basket is
read line by line, and the strongest check TAB has is the one asking whether
those lines add up to the printed subtotal.

The public page — the scoreboard and a replay of a real run — is generated,
never edited:

```bash
python tools/build_site.py     # writes docs/index.html
python tools/screenshot.py     # writes build/shots/*.png
```

Both read from `results/`, so a figure on that page cannot drift from the run
that produced it. There is a test that fails if anyone types a percentage into
the template.

To reproduce the measured numbers:

```bash
python data/fetch_cord.py --split test
python -m tab.eval --corpus cord --split test --gold-ceiling
python -m tab.eval --corpus cord --split test --rescore --markdown
```

Runs are resumable: a killed batch picks up where it stopped, and
`--retry-failed` re-attempts only what failed.

The review screen serves on `127.0.0.1` only — receipts are personal data and
there is no server for them to go to.

If Ollama stops while `watch` is running, it says so once and waits. The
receipts stay on disk and get read when it comes back — they are **not** marked
as seen, because a receipt nobody read is not a receipt that failed. See
[ADR 0009](docs/adr/0009-a-stopped-model-is-not-a-bad-receipt.md).

Still to build: the learning loop that feeds corrections back, and the ~50
hand-labelled Philippine receipts that any PH or VAT accuracy claim has to
wait for.

## Documents

Written before the code, in this order:

- [PRD](docs/PRD.md) — the problem, who it is for, and what it deliberately will not do
- [TDD](docs/TDD.md) — how it works, and the approaches rejected
- [App flow](docs/APP_FLOW.md) — every step and every branch, including the ugly ones
- [Design brief](docs/DESIGN_BRIEF.md) — how the review screen looks and behaves
- [Schema](docs/SCHEMA.md) — the tables, the indexes, and why each exists
- [Decisions](docs/adr/) — one file per decision, never rewritten

## Scope, stated plainly

**In:** merchant, date, totals, the Philippine VAT breakdown (VATable,
VAT-exempt, zero-rated), TIN and OR number, and itemised lines.

**Out for now:** senior citizen and PWD discount decomposition, handwritten
sari-sari store slips, currency conversion, and any hosted service that would
take your receipts off your own machine.

## Licence

MIT.
