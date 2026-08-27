# 0005 — CORD is the baseline corpus; a Philippine set is required before any PH claim

Date: 2026-08-28
Status: accepted

## Context

Phase 0 needs a labelled set of receipts before any extraction code is written,
because a system with no measured baseline has no way to tell whether its clever
parts helped.

Collecting and hand-labelling 100–200 real receipts is the honest starting point
and also the step most likely to stall the project for a fortnight. A public
dataset gets to a number in a day.

Verified on 2026-08-28, not assumed:

```
curl -s https://huggingface.co/api/datasets/naver-clova-ix/cord-v2
# 200 — exists. license: cc-by-4.0. size: 1K–10K rows.
```

CORD is the Consolidated Receipt Dataset: photographed Indonesian receipts with
labelled fields including line items. It is real photographs, not synthetic
renders, which is the property that matters — accuracy on clean generated images
says nothing about accuracy on paper.

**What it is not: Philippine.** CORD has no VATable / VAT-exempt / zero-rated
split, no TIN, no official receipt number, and no senior or PWD discount lines.
Those are precisely the fields [PRD §3 G6](../PRD.md) commits to handling.

## Options

- **Hand-label 100–200 Philippine receipts first.** The right corpus, and the
  project produces no number for two weeks. High chance of stalling entirely.
- **CORD only.** Fast, and every published figure would then be a claim about
  Indonesian receipts wearing a Philippine label. That is the exact dishonesty
  this project exists to avoid.
- **CORD as the baseline, with a Philippine set as a hard gate on Philippine
  claims.**

## Decision

**Build and measure on CORD. Publish no Philippine or VAT figure until roughly
fifty hand-labelled local receipts exist.**

CORD answers "does the extraction and checking machinery work at all" — routing,
JSON validity, the arithmetic guard firing rate, straight-through rate on real
photographs. That is a genuine result about the machinery.

The Philippine set answers "does it handle the fields a BIR-facing ledger needs",
and nothing else can answer it. It must include thermal fade, phone photos taken
at an angle, and at least a few handwritten sari-sari slips, because a corpus of
clean scans produces a number that is fiction.

**Every published figure names its corpus.** The `labels` table carries a
`corpus` column for exactly this reason — it makes mislabelling a figure a
schema-level mistake rather than a wording one.

## Consequences

- Images are downloaded by a script and **never committed**. CC BY 4.0 permits
  redistribution with attribution, but receipts do not belong in this repo and
  the licence file is not the reason.
- The attribution for CORD goes in the README and in `data/fetch.py`, because
  CC BY requires it and because the next reader should know where the number
  came from.
- Two scoreboards, not one blended number. A CORD figure and a PH figure are
  different claims and are never averaged together.
- **The VAT checks cannot be validated on CORD at all.** They will be exercised
  against hand-constructed fixtures until the PH set exists — a receipt whose VAT
  is correct must pass, one off by ₱0.50 must fail. Fixtures prove the logic;
  only real receipts prove the accuracy.
- If the Philippine set never materialises, the honest outcome is to ship without
  the VAT claim and say so, rather than to quote a CORD number next to the word
  VAT.
