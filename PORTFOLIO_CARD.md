# TAB — portfolio integration brief

*Paste this whole file into a session working in the `Portfolio` repo. It is
self-contained: what the project is, the verified numbers, and the exact edits.*

## Blocked until one thing changes

`Zeref538/tab` is **private**, so there is no GitHub Pages demo — the API refuses
it: *"Your current plan does not support GitHub Pages for this repository."*
The page itself is built and committed at `docs/index.html`.

Adding the card now would publish a link to a 404. Make the repo public first:

```bash
gh repo edit Zeref538/tab --visibility public --accept-visibility-change-consequences
gh api -X POST repos/Zeref538/tab/pages -f "source[branch]=main" -f "source[path]=/docs"
```

Then the demo URL below works. Receipts are personal data, but none are in the
repo — `.gitignore` keeps every image out and the sample PDFs are generated.

## What TAB is

A local-first agent that reads receipts and **proves the numbers add up before it
writes anything down**. Point it at a folder; it pulls out the merchant, date,
Philippine VAT breakdown and every line of the basket, then asks the receipt
about itself — do the items reach the subtotal, is the VAT 12% of the VATable
sales, do the parts reach the total. Receipts that answer yes go into a SQLite
ledger silently. The rest go to a review screen with the failing number
highlighted and the reason written out in words.

The thesis in one line: **a receipt is a document that checks itself**, so
confidence comes from arithmetic and never from the model's own say-so.

It is the **unattended** end of the owner's agent work — the other agents wait
for a person to talk to them; this one runs on a folder and only speaks when
something is wrong.

| fact | value |
|---|---|
| corpus | CORD v2 test split, n=100, Indonesian receipts |
| model | `qwen2.5vl:3b` via Ollama, local, free, 21.7s median per receipt |
| totals read correctly | 89/100, zero extraction failures |
| straight-through rate | 30% needed no human at all |
| **silent error rate** | **1%** committed with a wrong total (8% counting any wrong field) |
| escalation precision | 14.3% strict, 64.3% counting any wrong field |
| the finding | **10 of the 11 misread totals were caught by arithmetic alone** |
| ceiling | 91/100 gold-labelled receipts pass their own arithmetic, so ~9% can never go straight through |
| size | 2,635 lines in `tab/`, 3 dependencies, 89 automated checks, 10 ADRs |

The three things that make it portfolio-worthy, in order:

1. **Confidence is measured, not asked for.** No model confidence score is
   stored, read or thresholded anywhere. The number that justifies the design is
   the one above: of 11 receipts whose total the model got wrong, arithmetic
   caught 10 without knowing anything about receipts.
2. **The failure mode it is built to avoid is the one it reports.** Silent error
   rate is printed next to straight-through rate everywhere, with the sample
   size and the corpus named. A tool that escalates everything is useless but
   harmless; one that writes a wrong total into a tax return is worse than
   nothing.
3. **It says what it has not measured.** CORD is Indonesian and carries no
   BIR-style VAT breakdown, so no Philippine or VAT accuracy figure is published
   anywhere — and there is a test that fails if one appears on the public page.

**Links:** repo https://github.com/Zeref538/tab · live case study
https://zeref538.github.io/tab/ *(both need the repo made public first)*

---

## What to paste where

**This file is not what goes in the codebase.** The block below is a JavaScript
object; it goes into `Portfolio/src/data.js`, in the `projects` array.

## No App.jsx change needed

`Portfolio/src/App.jsx:235` hardcodes the filter tabs:

```js
const projGroups = ["Agentic AI", "RAG", "Building LLMs", "Fine-Tuning LLMs", "ML & Forecasting", "Web & Apps"];
```

`"Agentic AI"` and `"Web & Apps"` are both already there, so the card below
appears under both with no edit to `App.jsx`.

## Images are ready

Already converted, 1000px wide, q82, in `Portfolio/public/projects/`:

| file | what |
|---|---|
| `tab-1.jpg` | the review screen — a receipt whose third line does not multiply out, with that line flagged and focused |
| `tab-2.jpg` | the public page — generated scoreboard and the replay of a real run |
| `tab-3.jpg` | the review screen in dark mode |
| `tab-4.jpg` | the review screen at phone width |

Originals in `Portfolio/source-assets/TAB/`. All are regenerable:
`python tools/screenshot.py` and `python tools/build_site.py` in the TAB repo.

```js
  {
    title: "TAB — Receipts That Check Themselves",
    groups: ["Agentic AI", "Web & Apps"],
    description:
      "A local-first agent that reads receipts and refuses to write one down until the arithmetic proves it. Point it at a folder and it pulls out the merchant, the date, the Philippine VAT split and every line of the basket, then asks the receipt about itself — do the items reach the subtotal, is the VAT 12% of the VATable sales, do the parts reach the total. Receipts that add up land in a SQLite ledger without a word; the rest surface on a review screen with the failing number highlighted and the reason in plain English. No model confidence score is stored, read or thresholded anywhere in it, and the measurement is why: on 100 CORD receipts a free local qwen2.5vl:3b misread 11 totals, and arithmetic alone caught 10 of them, leaving a 1% silent error rate against a 30% straight-through rate. It runs unattended on a folder, on a laptop, for nothing, and no receipt ever leaves the machine.",
    tags: ["Python", "Ollama", "Vision LLM", "SQLite", "Evaluation", "Local-First"],
    metric: "1% silent error rate · 30% straight-through on 100 receipts",
    category: "Agentic · Document AI · Evaluation",
    date: "2026",
    image: "/projects/tab-1.jpg",
    images: [
      "/projects/tab-1.jpg",
      "/projects/tab-2.jpg",
      "/projects/tab-3.jpg",
      "/projects/tab-4.jpg",
    ],
    link: "https://github.com/Zeref538/tab",
    demo: "https://zeref538.github.io/tab/",
    demoLabel: "scoreboard & replay",
    highlights: [
      "Built the whole thing on the premise that a model saying \"95% sure\" means nothing, then measured whether that was true: of 11 receipts whose total qwen2.5vl:3b read wrong, plain arithmetic caught 10 without knowing anything about receipts — a 1% silent error rate, and the number the entire design rests on",
      "Reports straight-through rate and silent error rate together, always, with the sample size and corpus beside them — a tool that escalates everything is useless but harmless, one that writes a wrong total into a tax return is worse than doing nothing",
      "Publishes no Philippine or VAT accuracy figure at all, because CORD is Indonesian and has no BIR-style VAT breakdown, and there is an automated test that fails if such a claim ever appears on the public page",
      "Chased a 17-failure batch to the wrong cause first: the error said \"4105 tokens exceeds 4096\", raising the context window turned it into HTTP 500s, and the real culprit was image area — capping the long edge at 1600px took failures to zero and accuracy from 73% to 89%",
      "Found two bugs by driving the running software rather than reading it: correcting a total could silently file a duplicate ledger row, and a warning banner ballooned into a 455px block of colour that every test passed straight through",
    ],
  },
```

## If asked what is unfinished

Say it plainly — it is more convincing than the alternative:

- **Gate D is open.** ~50 hand-labelled Philippine receipts, thermal fade and
  phone photos included, before any PH or VAT number is published.
- **The learning loop is not built.** Corrections are recorded per field from
  the first review screen, but nothing consumes them yet. Feeding them back
  would need measuring before and after on a frozen eval set, and there are no
  real corrections to learn from until people use it.
- **Line quantities are only read when the receipt states them** with an `x` or
  an `@`. Inferring which unlabelled column is the quantity means picking the
  reading that makes the check pass, which would make the check prove nothing.
  Column geometry is the honest fix and it is written down, not done.
