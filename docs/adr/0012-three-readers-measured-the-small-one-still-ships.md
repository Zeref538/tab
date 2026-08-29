# 0012 — Three readers measured; the small one still ships

Date: 2026-08-30
Status: accepted

## The question

TAB has three ways to turn a receipt photograph into numbers. Which one should
it run when nobody has said otherwise?

- `qwen2.5vl:3b` — the small local vision model, the current default
- `qwen2.5vl:7b` — the same family, roughly twice the size
- `rapidocr-ppocrv6` — PP-OCRv6 through ONNX, no vision model at all, added in
  the same week and reachable with `--reader ocr`

## What was measured

All three on the same 100 receipts, CORD test split, tolerance 5 centavos,
scored by the same code. The arithmetic-only view, because CORD labels neither
merchant nor date, so the format rules fail on all 100 documents for every
reader and the headline straight-through rate is zero three times over — a fact
about the corpus, not about the readers.

| | vision 3b | vision 7b | OCR |
|---|---:|---:|---:|
| filed with no human | 30/100 | 52/100 | 15/100 |
| filed with a wrong field | 8/100 | 15/100 | 2/100 |
| filed with a wrong **total** | 1/100 | 2/100 | 1/100 |
| totals read correctly | 89/100 | 92/100 | 73/100 |
| subtotal | 66/100 | 69/100 | 77/100 |
| VAT amount | 83/100 | 92/100 | 71/100 |
| service charge | 94/100 | 94/100 | 94/100 |
| discount | 93/100 | 91/100 | 94/100 |
| median seconds | 21.7 | 38.5 | 0.9 |
| failed to read at all | 0 | 0 | 0 |

Both silent-error rows are out of 100 documents, not out of the ones each reader
chose to file. Per row actually filed: 3b is wrong 27% of the time, 7b 29%,
OCR 13%.

Reproduce any column with:

    python -m tab.eval --corpus cord --split test --model qwen2.5vl:7b
    python -m tab.eval --corpus cord --split test --reader ocr

## The decision

**The default stays `qwen2.5vl:3b`.** OCR remains available as `--reader ocr`.
Neither of the other two is promoted.

## Why

The 7b is genuinely the better reader — three more totals, nine more VAT lines.
It is not the better *filer*. It nearly doubles what goes through unattended, and
nearly doubles what goes through unattended and wrong: 15 bad rows against 8. The
share of filed rows carrying a bad field barely moves, 27% to 29%, so the extra
throughput is bought at an unchanged error rate on twice the volume. Against
ADR 0003 — confidence comes from the arithmetic, never from the model — a reader
that puts more unchecked rows in the ledger for the same per-row reliability is
not an improvement, it is the same tool turned up louder. And it costs 38.5
seconds a receipt against 21.7.

OCR is the interesting one and still not the default. It is wrong far less often
because it can only report characters it actually saw; it has no way to invent a
plausible VAT line, which is exactly the failure mode a vision model has. That
buys 2 bad rows instead of 8. But it reads only 73 totals against 89, because
finding *which* number on a thermal receipt is the total is a layout judgement
and an OCR engine makes none. It leaves 85 receipts on the screen. A tool that
escalates almost everything is useless but harmless — the phrasing in `eval.py`
is deliberate, and it applies here.

The 3b sits between them and costs half the 7b's time.

## What would change this

- **A Philippine corpus.** CORD is Indonesian, has no BIR VAT breakdown, no TIN,
  no OR number (ADR 0005, Gate D). Every row above may reorder on real PH paper,
  and the OCR arm most of all — the fields it is worst at are the ones a PH
  receipt prints most explicitly.
- **Routing rather than choosing.** OCR is 24 times faster and safer per row;
  the vision model is better at layout. Running OCR first and falling back to
  vision only when the arithmetic fails would plausibly beat all three rows here.
  It is not built, it is not measured, and it is not claimed. Written down so the
  next person does not have to notice it again.

## Related

Supersedes nothing. Extends [0003](0003-confidence-from-checks-not-the-model.md)
and [0005](0005-cord-baseline-ph-set-required.md). Sits beside
[0011](0011-the-retry-was-built-measured-and-turned-off.md), which is the same
shape of finding: built, measured, and not shipped.
