# TAB — session handoff

**TAB** — **T**ally **A**ll **B**ills.

*Picking up the tab* is what you do at the end of a meal. This picks up the pile
of receipts instead.

Alternate expansions if the plain one feels thin later: **T**ranscribe **A**nd
**B**alance (names the checking step, which is the part that makes this
different), or **T**otals **A**utomatically **B**ooked. Rejected names from
earlier rounds, do not reuse: Bantay, Ayos, Ulat, Tally, Sundo, Kasama, Tindera,
Repaso.

> Context-only handoff, same pattern as `FORGE/` and `ABIDE/`. The owner writes
> the PRD, TDD, app flow, design brief and schema himself in this folder,
> following `~/.claude/ENGINEERING.md` — this is a **Project** tier build, so it
> gets the full document set before any code.

---

## What it is

Point it at a photo, a PDF, or a folder of them. It reads each receipt, pulls out
the merchant, date, total, tax and line items, **checks that the numbers actually
add up**, and appends a clean row to a spreadsheet. When it isn't sure, it does
not guess — the document lands in an approval queue with the doubtful field
highlighted, and the correction you make is remembered for next time.

The user is a freelancer, a small shop owner, or a student who currently types
these rows by hand at midnight before a deadline.

## Why this one is worth building

Three of your projects are agents that wait for a human to talk to them. This one
runs when nobody is watching, which is the part of agent work that employers are
actually hiring for right now — a repetitive job done end to end, with a human
approval step, and evidence it doesn't quietly get things wrong.

It is also the rare portfolio project where the headline number means something
to a non-technical reader. **Straight-through rate** — the share of documents
that needed no human at all — has an obvious dollar value behind it. "87%
straight-through on 400 real receipts" is a sentence a hiring manager
understands immediately, and it is the kind of claim almost every agent demo
avoids making.

## What makes it agentic, not a script

If it were one fixed pipeline it would be a batch job. The agent part is that it
**decides**:

- which method to use per document — a PDF with a real text layer needs no OCR at
  all, a crumpled thermal photo needs the vision model, and picking wrong wastes
  time or accuracy;
- when a first pass looks wrong and is worth retrying differently;
- when it is unsure enough to stop and ask a human, versus commit the row;
- what to do with a duplicate, a foreign currency, or a document that is not a
  receipt at all.

Those are the decisions worth writing an ADR about, because each one is a place
where a confident wrong choice costs the user real money.

## The honest hard parts — read before planning

**Line items are much harder than the header.** Merchant, date and total are
comparatively easy. The itemised list — with quantities, unit prices, discounts,
and a layout that changes per store — is where accuracy falls apart. Decide early
whether line items are in scope for version one, and say so in the PRD's
non-goals rather than discovering it halfway.

**Model confidence is not confidence.** A model saying it is 95% sure means very
little; it will state a wrong total with total conviction. Build your uncertainty
from things that are checkable instead:

- **The arithmetic check is the cheap superpower.** Line items plus tax should
  equal the stated total. When they don't, something was misread, and you know it
  without any model being involved. This is the single highest-value guard in the
  project and it costs nothing to run.
- Field format validation — does the date parse, is the total a number, is the
  merchant non-empty.
- Agreement between two methods — if OCR and the vision model produce the same
  total, trust it far more than either alone.

**Thermal receipts fade, curl and blur.** Real inputs are photographed at an
angle, in bad light, half-crumpled. Accuracy on clean PDFs tells you nothing
about accuracy on a phone photo of a jeepney-ride-old receipt from a bag.
Evaluate on the messy ones or the number is fiction.

**Philippine receipts have their own shape.** VATable sales, VAT-exempt lines,
zero-rated, senior citizen and PWD discounts, official receipt numbers, and
handwritten sari-sari store slips that no OCR will ever love. Decide which of
these are in scope. A tool that mishandles VAT is worse than no tool for the
freelancer filing taxes.

**Receipts are personal data.** Card last-four digits, names, addresses,
locations, medical purchases. Process locally by default, and if anything ever
leaves the device, say so plainly in the interface. This is a design constraint,
not a footnote.

**Duplicates will happen.** The same receipt gets photographed twice, or a folder
gets re-imported. Deduplicate on file hash for the exact case, and on
merchant plus date plus total for the "photographed it again" case.

## How to measure it

Four numbers, always reported together — the same discipline as your other
studies, because a receipt tool has the identical two-sided failure:

| metric | what it catches |
|---|---|
| field-level accuracy | per field, on a hand-labelled set — not one blended score |
| **straight-through rate** | share of documents that needed no human at all |
| escalation precision | when it asked for help, was it genuinely unsure, or is it just noisy? |
| **silent error rate** | confident, unchecked, and **wrong** — the one that actually hurts |

The last one is the whole game. A tool that escalates everything is useless but
harmless; a tool that confidently writes a wrong total into your tax records is
worse than doing nothing. Report both, always, and never report straight-through
rate on its own.

**The learning loop must be measured, not assumed.** Corrections feeding back as
examples or per-merchant rules sounds obviously good. Prove it: freeze an
evaluation set, measure before and after the loop has run on real corrections,
and report the difference. If it doesn't help, say so — that is a finding, and
it's more interesting than the feature working.

## Phase 0 — the gate, before building anything

1. **Collect and hand-label 100–200 real receipts**, deliberately including bad
   photos, thermal fade, and handwritten slips. This is the boring step that
   decides whether the project is real.
2. **Measure the baseline** with the simplest thing that could work, before any
   agent logic. If a plain extraction pass plus the arithmetic check already
   reaches a decent number, that is the bar every clever addition has to beat.
3. **Check the arithmetic guard actually fires** — how many of the known-wrong
   extractions does it catch by itself? If it catches most of them, the
   uncertainty problem is largely solved for free and the design gets simpler.
4. **Confirm a free model can read a phone photo of a Philippine receipt at all.**
   If it can't, scope shrinks to PDFs and clean scans, and better to know now.

Kill rule: if labelled accuracy on messy real receipts is hopeless with free
models, ship the PDF-and-clean-scan version and state the limit on the page.
A narrower tool that works beats a broad one that lies.

## Shape of the build

**Local first.** A small vision-capable model through Ollama, with a text-layer
shortcut for real PDFs and a plain OCR path as fallback. No document leaves the
machine unless the user opts in. That is both the privacy story and the ₱0 story.

**Storage** is a local database — receipts, extracted fields, confidence signals,
corrections, and an append-only log of what the agent decided and why. That log
is what makes the demo convincing, because you can show the reasoning behind an
escalation.

**Automation surface.** Watch a folder, take a batch on a schedule, and only
surface the exceptions. The measure of success is that the user opens it rarely.

**Export** to CSV and Google Sheets, since that's where this data actually lives
for the people who need it.

**The demo has to be ten seconds.** Drag a receipt in, see the row appear, see one
field flagged for review. Anything longer and a recruiter closes the tab.

## Portfolio integration (later)

Card belongs under `Agentic AI`, and `Web & Apps` if it ships with an interface.
Write `PORTFOLIO_CARD.md` and `README.md` in this folder — `build-index.mjs`
indexes `README.md` only. Screenshots to `Portfolio/source-assets/TAB/`,
converted to `public/projects/*.jpg` at ~1000px q82. Save with LF line endings.

Consider a public accuracy scoreboard on the demo page, the way APAW publishes
its per-horizon table including the horizons it can't yet defend. Same move here:
show the straight-through rate *and* the silent error rate, with the sample size
next to both.

## Open decisions for the owner

1. Are line items in scope for v1, or headers only?
2. Philippine VAT and discount handling — first-class, or explicitly out of scope?
3. Web app, desktop app, or a folder-watching background job with a review screen?
4. Does the correction loop ship in v1, or arrive as v2 once there are real
   corrections to learn from?
5. Where does the ledger live — local file, Google Sheets, or both?
