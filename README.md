# TAB — Tally All Bills

Point it at a pile of receipts. It reads each one, **checks that the numbers
actually add up**, and appends a row to your ledger. When the arithmetic
disagrees with itself, it does not guess — the receipt goes to a review queue
with the doubtful field highlighted.

Everything runs on your machine. No receipt is uploaded anywhere.

> **Status: specification.** The document set is written; no code exists yet.
> Every number in these documents is a target, not a result. Measured numbers
> land in `results/` and are copied into this README only after the run that
> produced them, with the sample size and the corpus named.

---

## Why the arithmetic check is the whole idea

A model that reads a receipt will tell you the total is ₱1,240.00 with complete
confidence, and be wrong. Asking it how sure it is does not help — it is just as
confident either way.

So TAB never asks. It checks:

```
Σ(quantity × unit price)  ≈  subtotal
subtotal + VAT − discounts ≈  total
VAT                        ≈  VATable sales × 0.12
```

If a receipt fails its own arithmetic, something was misread, and you know it
without any model being involved. That one guard costs nothing to run and is
what separates this from a wrapper around an OCR call.

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

Nothing to run yet. When there is:

```bash
pip install -e .
tab ingest ./receipts          # one file, or a folder
tab review                     # opens the local review page
tab export --csv ledger.csv
```

Requires [Ollama](https://ollama.com) running locally for the vision path. PDFs
with a real text layer are read directly and need no model at all.

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
