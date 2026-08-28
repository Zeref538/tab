# Phase 0 — the gate

What was measured before any product code was written, and what it decided.

Every number here came from a command in this repo, on this machine. Nothing is
estimated or carried over from another project. Reproduce with:

```bash
python data/fetch_cord.py --split test
python -m tab.eval --corpus cord --split test --gold-ceiling
python -m tab.eval --corpus cord --split test --markdown
```

Corpus: **CORD** (`naver-clova-ix/cord-v2`, CC BY 4.0), 100 photographed
Indonesian receipts, test split. Model: **`qwen2.5vl:3b`**, free, local, through
Ollama. Nothing left the machine.

---

## The verdict, first

**Build it.** A free 3B vision model reads real receipt photographs well enough
to be useful, and the arithmetic guard catches almost everything it gets wrong.

The kill rule did not fire. Scope does not need to shrink to clean PDFs.

## Gate A — can a free local model read a photograph at all?

**Yes.** 89 of 100 totals read correctly, zero extraction failures, median 21.7
seconds per receipt on this laptop GPU.

| field | accuracy |
|---|---|
| `total` | 89% |
| `service_charge` | 94% |
| `discount_total` | 93% |
| `vat_amount` | 83% |
| `subtotal` | 66% |

Not scored, because CORD does not label them: merchant, date, TIN, OR number,
and the whole VAT split. An accuracy figure for a field the gold set does not
contain would be invented.

`subtotal` at 66% is the weak one and it is worth watching — it is the anchor the
item sum is checked against, so a wrong subtotal escalates a receipt that was
otherwise read perfectly.

## Gate B — the baseline

One extraction pass plus the checks, no routing, no agent logic. **30%
straight-through**: thirty receipts in a hundred were committed with no human
involved.

That is the bar every clever addition has to beat. It is not a good number yet,
and §"what it costs" below says why.

## Gate C — does the arithmetic guard actually fire?

**Yes, and this is the finding the project rests on.**

|  | total right | total wrong |
|---|---|---|
| guard committed | 29 | **1** |
| guard escalated | 60 | 10 |

**Ten of the eleven wrong totals were caught — 90.9% — with no model confidence
consulted anywhere.** One slipped through. That single receipt is the silent
error rate: **1%**.

The blind spot behaves exactly as [ADR 0003](adr/0003-confidence-from-checks-not-the-model.md)
predicted it would. A receipt can be misread *consistently* and still balance,
and arithmetic cannot see that. One in a hundred did precisely this.

### What it costs

Sixty receipts with a correct total were escalated. That sounds terrible, and
half of it is not:

- **35** of them had a *different* scored field wrong — usually a VAT line the
  model invented on a receipt that has none. Those are bad rows. Escalating them
  is correct.
- **25** were genuinely clean and escalated anyway. That is the real
  over-escalation: 25 of 89 correct receipts, 28%.

Which is why escalation precision is reported twice, and why the definition
matters more than the number:

| wrong means | silent error rate | escalation precision |
|---|---|---|
| the total is wrong | 1.0% | 14.3% |
| any scored field is wrong | 8.0% | 64.3% |

Quoting 64.3% alone would be flattering. Quoting 14.3% alone would be
pessimistic. Both are true and they answer different questions.

## Gate D — the Philippine claim

**Not met, and nothing is published.** CORD is Indonesian. It has no VATable
sales, no VAT-exempt or zero-rated split, no TIN and no OR number, so it cannot
support a single Philippine or VAT figure. Roughly fifty hand-labelled local
receipts are still required before any such number is stated anywhere.

One consequence showed up in the measurement itself: the 12% VAT check passed
zero times and failed sixteen, purely because Indonesian receipts do not use a
12% rate. That was a broken check, not a misread receipt, and it is now skipped
on any non-Philippine receipt.

## The ceiling

**91 of 100 CORD gold labels pass their own arithmetic.** A perfect extractor is
still escalated on the other nine, so no straight-through rate measured here can
honestly exceed 91%.

The tolerance knob barely moves it — 91% at ₱0.05, 93% at a rupiah, then flat
until absurd slack. So the remaining failures are genuine label errors in CORD,
not rounding, and loosening the tolerance buys almost nothing while weakening the
guard. **The default stays at ₱0.05.**

## Four bugs the measurement found

None of these would have been visible from reading the code.

1. **The receipt model had fewer parts than a real receipt.** Service charges,
   nested add-on lines and per-line discounts were all dropped, escalating 14
   correct receipts. Fixing it took gold self-consistency from 86 to 91 of 100.
2. **`normalise` crashed on `line_no: "0571-1854"`** — an item code in a field
   meant for a small integer — killing a 30-minute batch twelve receipts in.
3. **Tall receipts blew the context window**, `4105 tokens exceeds 4096`.
4. **Huge photographs killed the model runner outright.** A vision model makes
   tokens roughly in proportion to image *area*, and the corpus holds photos up
   to 3024×4096 against a median of 864×1296. No context setting fixes that;
   capping the long edge at 1600px does, and took the run from 17 failures to 0.

Bug 4 is the one worth remembering. It first looked like bug 3 and the obvious
fix made it worse — widening the window turned clean 400 refusals into 500
crashes. The error message that named the real cause was the *absence* of one.

## What Phase 0 does not tell us

- Nothing about Philippine receipts, VAT, TIN or OR numbers.
- Nothing about handwritten sari-sari slips — CORD has none.
- Nothing about PDFs with a real text layer; that path is not built yet and it
  should be far more accurate than any of this.
- Nothing about the correction loop, which has no corrections to learn from.
- n=100. Small. Treated as small.
