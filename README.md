# TAB — Tally All Bills

Point it at a pile of receipts. It reads each one, **checks that the numbers
actually add up**, and appends a row to your ledger. When the arithmetic
disagrees with itself, it does not guess — the receipt goes to a review queue
with the doubtful field highlighted.

Everything runs on your machine. No receipt is uploaded anywhere.

> **Status: Phase 0 complete.** The extractor, the arithmetic guard and the
> evaluation harness exist and have been measured. The ledger, the review screen
> and the folder watcher have not been built yet.

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

What works today is the extractor and the evaluation harness:

```bash
pip install -e .
ollama pull qwen2.5vl:3b

python data/fetch_cord.py --split test              # get the corpus
python -m tab.eval --corpus cord --split test       # measure it
python -m tab.eval --corpus cord --split test --gold-ceiling
python -m tab.vision path/to/receipt.jpg            # read one receipt
```

Runs are resumable: a killed batch picks up where it stopped, and
`--retry-failed` re-attempts only what failed.

Still to build: the SQLite ledger, the review screen, the folder watcher, the
text-layer PDF path, and CSV export.

Requires [Ollama](https://ollama.com) running locally. PDFs with a real text
layer will be read directly and need no model at all.

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
