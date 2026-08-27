# 0003 — Confidence comes from arithmetic, never from the model

Date: 2026-08-28
Status: accepted

## Context

TAB has to decide, per receipt, whether to write a row or ask a human. Getting
that wrong in one direction wastes the user time; getting it wrong in the other
direction puts a number they cannot defend into a tax filing.

The obvious source of that decision is the model itself. Ask it for a confidence
score, or read the token probabilities, and threshold on the result.

This does not work, and it fails in the specific way that matters. A model that
misreads ₱1,240.00 as ₱1,740.00 does not hedge. It reports the wrong number in
exactly the tone it reports a right one, and its self-reported certainty is
roughly as high either way. Model confidence measures fluency, not correctness.
Thresholding on it produces a system that is most confident precisely when it is
cleanly and completely wrong.

There is a better source sitting in the document already: **a receipt is a
document that checks itself.** It carries the parts and the sum, printed side by
side by the merchant.

## Options

- **Model self-reported confidence.** Free, one field in the response, and
  meaningless.
- **Token log-probabilities.** More principled, still measuring the wrong thing,
  and not exposed uniformly across local models.
- **A second model grading the first.** Two confident guessers do not make a
  check, and it doubles the cost.
- **Arithmetic that the document itself supplies.**

## Decision

**Every escalation decision comes from checks that need no model to evaluate.**

```
Σ(qty × unit_price)          ≈ subtotal
subtotal + VAT − discounts   ≈ total
VAT                          ≈ VATable sales × 0.12
vatable + exempt + zero_rated ≈ subtotal
```

plus format checks — the date parses and is not in the future, the total is
positive, the merchant is non-empty — and cross-method agreement when two routes
have both run.

No model confidence score is stored, read, or thresholded anywhere. If a model
returns one, it is ignored.

## Consequences

- **This is the cheapest guard in the project and probably the strongest.** It
  costs a few additions. Phase 0 measures exactly how much of the known-bad set
  it catches on its own, and if that share is high, the design gets simpler
  everywhere else.
- Money is stored in integer centavos, not floats, because the guard is an
  equality test on money and floating point would make it fail on rounding noise
  it invented itself. See [SCHEMA.md](../SCHEMA.md).
- `≈` needs a tolerance, and the tolerance is a real calibration knob, not a
  magic number. Real receipts round in ways a clean model does not predict. Too
  loose lets wrong receipts through; too tight escalates everything. Both
  directions are measured, which is what silent error rate and escalation
  precision are for.
- **The guard has a blind spot and it must be stated:** a receipt can be misread
  *consistently* and still balance — for example if the same digit is misread in
  both the subtotal and the total. Arithmetic cannot catch that. Cross-method
  agreement is the partial answer, and the residue is exactly what silent error
  rate measures on the labelled set. This is why that metric exists and why it is
  published.
- The failing check produces the sentence the review screen shows. One source,
  so the interface cannot drift away from the logic.
- Line items earn their cost here: `item_sum` is the strongest of these checks,
  and it only exists if items were extracted.
