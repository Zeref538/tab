# 0010 — A quantity is only believed when the receipt states one

Date: 2026-08-28
Status: accepted

Follows [ADR 0003](0003-confidence-from-checks-not-the-model.md), which says
confidence comes from arithmetic. This is about not cheating at that arithmetic.

## Context

`item_sum` — do the line amounts add up to the printed subtotal — is the
strongest guard TAB has. It cannot run without line items, and until now the
text-layer route returned none, so it skipped on every PDF. Reading the basket
was the last real gap.

Most of it is easy. A line has a description and an amount, and the amount is
money-shaped. The hard part is the columns in between:

```
Milk 1L            2      245.00      490.00
```

Is that a quantity of 2 at 245.00 each? Almost certainly. But nothing in the
text says so. The columns are only columns because of where they sit on the
page, and a text layer gives characters in reading order, not a grid.

## The trap

The tempting rule is: take the last three numbers as quantity, unit price and
amount, and accept them if `qty × unit ≈ amount`.

That rule cannot fail. It selects the reading of the line that satisfies the
check, and then reports that the check passed. `line_math` would be verifying a
parse that was chosen to make `line_math` pass — a measurement of nothing,
dressed as a green tick. Worse, it would look like the most reliable check in
the system, because it would never fail.

This is the same error as trusting a model's confidence score, arrived at from
a different direction: the thing doing the checking and the thing being checked
would be the same decision.

## Decision

A quantity and a unit price are read only when the receipt states them with an
explicit operator — `2 x Milk`, `2 @ 245.00`. No operator, no quantity.

The amount is still taken (it is the last money-shaped number on the line), so
`item_sum` runs on every basket. `line_math` skips the lines whose columns were
never labelled, which is the honest answer: a check that could not run has not
passed.

## Consequences

`line_math` covers fewer lines than a clever parser would claim to cover. The
lines it does cover, it genuinely checked.

On receipts that print `2 @ 82.00`, both checks run and `line_math` names the
exact line that disagrees — which is what the review screen highlights, so a
person is sent to the number that is actually wrong rather than to the subtotal,
which in that situation is right. See `tab.checks.accused`.

The way to cover the unlabelled layouts is to read the column geometry —
`page.get_text("words")` in pymupdf gives an x position for every word, and a
column is then a real observation rather than a guess. That is worth doing when
there is a corpus to measure it against. Guessing is not worth doing at all.

A misread basket is not silent either way: if the amounts do not reach the
subtotal, `item_sum` fails and the receipt goes to a person. That is what lets
this parser be simple.
