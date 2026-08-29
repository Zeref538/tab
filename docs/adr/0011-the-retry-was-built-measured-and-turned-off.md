# 0011 — The retry was built, measured, and turned off

Date: 2026-08-29
Status: accepted

Supersedes the retry step drawn in [APP_FLOW §1](../APP_FLOW.md) and named in the
build plan: *"Any check failing → retry the document a different way (higher DPI,
second prompt, alternate route). Still failing → escalate."*

## Context

The design said a receipt whose arithmetic disagrees should be read again a
different way before a person is bothered with it. It is an obvious idea, it was
in the plan from the start, and it is the sort of thing that gets shipped on the
strength of sounding right.

It was built properly. A second reading of a photograph goes back to the model
with the prompt told which lines disagreed — naming the fields and never the
values, because handing a model the number you expect is asking it to type that
number back. A PDF that parsed but did not add up gets rendered and shown to the
vision model instead, which is a genuinely different reader.

Whether to believe the second reading is `checks.better`, and the bar is high on
purpose: every arithmetic check it still fails must already have been failing,
at least one must now be fixed, and nothing that reached a verdict may retreat
to a skip. A second reading that misreads different digits but happens to agree
with itself would otherwise be committed where the first was escalated — a
silent error bought with a prettier straight-through rate.

## The measurement

CORD test split, n=100, `qwen2.5vl:3b`, tolerance ₱0.05. 67 receipts failed an
arithmetic check on the first pass and were read again.

|                            | first pass | + retry |
|---|---:|---:|
| totals read correctly      | 89/100 | 89/100 |
| straight-through           | 30% | 31% |
| silent error rate (total)  | 1% | 1% |
| silent error rate (any field) | 8% | 8% |
| median seconds per receipt | 21.7 | 40.3 |

Of 67 second readings, `better` accepted **2**. One of those changed the verdict.

## Decision

The retry is out of the product path. `tab ingest` and `tab watch` read each
document once.

It buys one receipt in a hundred and costs 86% more time on every receipt that
needed checking. On a folder of two hundred photographs that is roughly an extra
hour of the machine being busy, for two more rows in the ledger. The person
clearing the queue would rather have the hour.

## What is kept, and why

`python -m tab.eval --second-look` stays, along with `checks.better`,
`checks.needs_a_second_look` and `vision.hint_for`. The experiment must stay
repeatable, because **this result is about one model, not about retries.** A
model that reads more of the receipt correctly may well produce second readings
worth having, and the next time the model changes this is the command that
answers it rather than a re-argument.

The result also says something quietly useful about the failures. If reading the
same receipt again with a targeted hint fixes almost nothing, the misreads are
not attention slips — the model is not seeing those digits at all. That points
at the image and the reader, not at the prompt, which is what the next
experiment goes after.

## What this cost

About forty minutes of GPU time and an afternoon of work, to delete the feature.
That is the cheap version of finding out. The expensive version is shipping it,
watching every batch take twice as long, and assuming the extra hour is the
price of accuracy.
