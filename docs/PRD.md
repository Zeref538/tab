# PRD — TAB

**T**ally **A**ll **B**ills.

*Picking up the tab* is what you do at the end of a meal. This picks up the pile
of receipts instead.

Status: **specification. No code exists and nothing has been measured.** Every
number in this document is a target. Results land in `results/` and are copied
outward only after the run that produced them, with the sample size and the
corpus named beside them.

---

## 1. Problem

Someone has a shoebox, a camera roll, or a downloads folder full of receipts,
and a spreadsheet that needs a row for each one. So at midnight before a
deadline they type them in by hand: merchant, date, total, tax. Fifty of them.
They make mistakes doing it, and they never notice which ones.

The existing options fail in two different directions.

**Manual entry is accurate but expensive**, and it is the only option most
freelancers and small shop owners actually have. It also degrades exactly when
it matters most, which is late at night at the end of a filing period.

**Automated extraction is cheap but silently wrong.** Hand a receipt to any
vision model and it will return a total. It will return a total whether or not
it read the number correctly, in the same confident tone either way. Nothing in
that loop tells you which rows to check, so you either check all of them — in
which case you have saved nothing — or you check none of them and file numbers
you cannot defend.

Philippine receipts add a third problem. VATable sales, VAT-exempt lines,
zero-rated sales, the TIN and the official receipt number are what a BIR-facing
ledger actually needs, and they are the fields general-purpose receipt tools
either drop or quietly mangle. A tool that mishandles VAT is worse than no tool
for the person it is meant to help.

## 2. Users

**Primary: a freelancer or small shop owner filing their own taxes.** Has
receipts in three places and a spreadsheet whose column layout they already
like. Not technical. Will abandon anything that needs more attention than doing
it by hand. Cares about being able to answer "where did this number come from"
six months later.

**Secondary: a student or anyone tracking spending.** Lower stakes, same job.
Wants the pile turned into rows without thinking about it.

**Tertiary: an engineer or hiring reader arriving from the portfolio.** Has
thirty seconds. Needs to see a receipt go in, a row come out, one field flagged
for review, and honest accuracy numbers next to the claim. Leaves either
believing the system or not; there is no middle.

## 3. Goals

Each measurable, each reported with the size of the set it was measured on.

| # | goal | how it is checked |
|---|---|---|
| G1 | Extract the header fields correctly | per-field accuracy on a hand-labelled set, reported per field, never blended |
| G2 | Know when it is wrong without asking a model | share of known-bad extractions caught by the arithmetic checks alone |
| G3 | Do most of the work unattended | straight-through rate — receipts committed with no human touch |
| G4 | Almost never be confidently wrong | silent error rate, reported next to G3 every single time |
| G5 | Ask for help only when genuinely unsure | escalation precision — of the receipts escalated, how many were actually wrong |
| G6 | Handle the Philippine VAT breakdown | VAT fields scored separately, on a Philippine set, never claimed from a foreign corpus |
| G7 | Be understandable in ten seconds | drag a receipt in, see the row appear, see one field flagged |

## 4. Non-goals

Written down deliberately, because these are the things that would quietly eat
the whole budget.

- **Not a hosted service.** Receipts contain card last-four digits, names,
  addresses, locations and medical purchases. Processing is local by default and
  the public page carries no uploader. See
  [ADR 0004](adr/0004-local-only-public-page-is-a-replay.md).
- **Not a senior-citizen and PWD discount calculator.** Discount totals are
  captured as a single amount. Decomposing them into their statutory parts is
  out of scope for v1 and stated as a limitation in the interface.
- **Not an OCR engine.** No model is trained here. Existing local models are used
  as they are.
- **Not a handwriting reader.** Handwritten sari-sari store slips are out. They
  are included in the evaluation set anyway and their failure rate published,
  because pretending they do not exist is how a tool lies about its coverage.
- **Not multi-currency.** A foreign-currency receipt is detected and escalated,
  never converted.
- **Not an accounting package.** It produces rows. It does not do bookkeeping,
  categorisation rules, or tax computation.
- **No metric scored by another model.** Every number here must be decidable by a
  script a reader could re-run against the committed labels.

## 5. User stories

**US1 — as a freelancer, I want the pile turned into rows, so I stop typing at
midnight.**
*Acceptance:* pointing TAB at a folder of twenty mixed receipts produces twenty
ledger rows, or an explicit escalation for each one that did not make it. No
receipt is silently dropped. `tab export --csv` opens in a spreadsheet without
editing.

**US2 — as a freelancer, I want to be told which rows to check, so I do not have
to check all of them.**
*Acceptance:* every committed row passed its arithmetic checks. Every row that
failed one appears in the review queue with the failing field marked and the
failing sum shown. A receipt whose items do not sum to its subtotal never
reaches the ledger unreviewed.

**US3 — as a freelancer filing in the Philippines, I want the VAT breakdown, not
just a tax number.**
*Acceptance:* VATable sales, VAT-exempt sales, zero-rated sales, TIN and OR
number appear as their own columns. Where the receipt states VATable sales, the
12% check runs against it, and disagreement escalates the receipt.

**US4 — as anyone, I want to know where a number came from, six months later.**
*Acceptance:* every ledger row links to its source document, the extraction that
produced it, every check that ran, and the decision-log entry explaining why it
was committed or escalated. Nothing is stored as a bare number.

**US5 — as anyone, I do not want my receipts leaving my machine.**
*Acceptance:* with the network disconnected, ingest, checks, review and CSV
export all work. The only path that touches the network is an export the user
turns on explicitly, and the interface says so in words at the moment it is
turned on.

**US6 — as a reader with thirty seconds, I want to see it work and see whether
to believe it.**
*Acceptance:* the public page replays a real run from committed logs and shows
the straight-through rate and the silent error rate together, each with its
sample size and the corpus it came from. The page contains no model and cannot
disagree with the study.

**US7 — as the same reader, I want to be told what it cannot do.**
*Acceptance:* the README and the page both name the failure cases — handwriting,
foreign currency, discount decomposition — with the measured failure rate where
one exists.

## 6. Success metrics

**Four numbers, always reported together, never one alone:**

| metric | what it catches | direction |
|---|---|---|
| field-level accuracy | did it read this specific field right | up |
| **straight-through rate** | share needing no human at all — **the headline** | up |
| escalation precision | when it asked, was it genuinely unsure | up |
| **silent error rate** | committed, unchecked, and wrong | **down** |

Straight-through rate on its own is not a result, it is a boast. A system that
commits everything scores 100% and is worthless. A system that escalates
everything scores 0% and is merely useless. Only the pair says anything.

This is the same two-sided failure as Refusal Calibration, where a checkpoint cut
hallucination by 92.5 points while paying 61.5 points of over-refusal from one
set of weights. One number would have made that look like a triumph.

**The project is a success if:**

- The arithmetic checks catch most known-bad extractions on their own (G2). If
  they do, uncertainty is largely solved for free and the design gets simpler —
  a finding worth publishing on its own.
- Straight-through rate is high enough to be worth using, with a silent error
  rate low enough to be worth trusting, both stated with their sample size.
- The Philippine VAT fields are scored on Philippine receipts, or not claimed.

**The project is also a success if the kill rule fires** and it ships as a
PDF-and-clean-scan tool with the limit stated. A narrower tool that works beats
a broad one that lies.

## 7. Gates and kill rules

Decided in writing before any number arrives, so the decision is not made by
whoever is most tired. Full procedure in [TDD §7](TDD.md).

**Gate A — can a free local model read a receipt photo at all?** If not, scope
shrinks to PDFs and clean scans immediately, and better to know that before
writing an extractor.

**Gate B — what is the baseline?** One plain extraction pass plus the arithmetic
check, no agent logic. That number is the bar every clever addition has to beat.

**Gate C — does the arithmetic guard actually fire?** Of the extractions known to
be wrong, what share do the checks catch alone? The single most important number
in Phase 0.

**Gate D — the Philippine claim.** No VAT or Philippine accuracy figure is
published until roughly fifty hand-labelled local receipts exist, including
thermal fade and phone photos. Until then every published number carries the
corpus it came from.

**Kill rule.** If accuracy on messy real photos is hopeless with free models,
ship the narrow version and say so on the page.

## 8. Risks

| risk | what it costs | response |
|---|---|---|
| Line items are much harder than headers | accuracy collapses and drags the headline down with it | headers are measured and shipped as their own slice first, so a bad number has one suspect |
| The evaluation set is all clean scans | the accuracy number is fiction | messy photos, thermal fade and handwriting deliberately included, and scored separately |
| The public corpus is not Philippine | a VAT claim with nothing behind it | Gate D; every figure names its corpus |
| A model states a wrong total confidently | a wrong number in a real tax filing | no model confidence is ever used; every committed row passed arithmetic |
| Tolerance set too loose | wrong receipts pass the check silently | tolerance is one named constant, tuned against real receipts and reported |
| Tolerance set too tight | everything escalates and the tool is abandoned | escalation precision is measured, not assumed |
| The same receipt photographed twice | duplicate rows in a tax filing | deduplication on file hash and on merchant-date-total, from the first slice |
| A receipt image ends up in git history | personal data published permanently | `.gitignore` excludes image types by default; fixtures are opted in one at a time |
| The demo page and the measured results disagree | the most embarrassing possible failure | the page renders committed logs and generated scoreboard JSON only |
| Straight-through rate gets quoted alone | exactly the dishonest headline this project exists to avoid | every table template carries all four columns; a table with fewer is a bug |

## 9. Open questions

None blocking. The decisions taken so far are recorded as ADRs: the name
([0001](adr/0001-name-tab.md)), extraction routing
([0002](adr/0002-text-layer-before-vision.md)), confidence from arithmetic
([0003](adr/0003-confidence-from-checks-not-the-model.md)), local-only
processing ([0004](adr/0004-local-only-public-page-is-a-replay.md)), the
evaluation corpus ([0005](adr/0005-cord-baseline-ph-set-required.md)) and the
ledger store ([0006](adr/0006-sqlite-as-the-ledger.md)).
