# TDD — TAB

How it works, and what was rejected. Read [PRD.md](PRD.md) first for what and
why.

---

## 1. Approach

One sentence: **a model proposes the numbers, deterministic Python decides
whether they are allowed into the ledger.**

A receipt arrives. TAB picks how to read it — a PDF with a real text layer needs
no model at all, a phone photo of thermal paper needs the vision model. Whatever
comes back is a JSON object validated against a schema, then run through
arithmetic checks that need no model to evaluate: the items must sum to the
subtotal, the parts must rebuild the total in one of the two legal VAT
conventions, and the VAT must be twelve percent of the VATable sales. If the
receipt fails its own arithmetic, something
was misread, and TAB knows it without anyone being asked how confident they are.

Failing that check buys one retry, done differently — higher resolution, a
second prompt shape, or the other route entirely. If two independent methods
produce the same total, that agreement is worth more than either method claiming
certainty. Still failing means the receipt goes to a review queue with the
offending field marked. Passing means the row is written.

This is the architecture already proven in `YODA/`, where a local model proposes
a data-cleaning plan and deterministic pandas executes it. The pieces transfer
almost directly, listed in §3.

## 2. Alternatives considered, and why rejected

**A cloud document-AI API (Google Document AI, AWS Textract, Azure Form
Recognizer).** Better accuracy today, and no local model to manage. Rejected on
the privacy constraint: every receipt would leave the machine, and receipts carry
card digits, addresses, locations and medical purchases. It also carries a
per-page cost, which kills the story that this runs for nothing. Rejected, not
dismissed — if a user ever wants it, it becomes an opt-in route behind the same
check layer, and the interface says plainly that documents are leaving.

**One fixed pipeline: OCR everything, parse with regex.** Cheapest to build,
fully deterministic, and it would work on the clean half of the corpus. Rejected
because it collapses on the messy half, which is the half that matters — and
because deciding *how* to read each document is the part of this that is
actually interesting. A single pipeline is a batch job, not an agent.

**Fine-tune a document model (Donut, LayoutLM).** Strong on a fixed layout,
which Philippine receipts are not, and it would need thousands of labelled
examples this project does not have. It also puts the accuracy back inside model
weights, where it cannot be checked. Rejected as a v1; revisit only if extraction
accuracy is the measured bottleneck and the checks are already good.

**Trust the model self-reported confidence and skip the arithmetic.** Half the
code, and it is what most receipt demos do. Rejected because it does not work: a
model states a wrong total in exactly the tone it states a right one. This is
[ADR 0003](adr/0003-confidence-from-checks-not-the-model.md) and it is the
whole point of the project.

**Postgres or an ORM for the ledger.** Rejected — one user, one machine, one
file. `sqlite3` is in the standard library and the schema fits on a page. See
[ADR 0006](adr/0006-sqlite-as-the-ledger.md).

**A hosted web app with an uploader.** Rejected. The product is local; the
public page is a replay. [ADR 0004](adr/0004-local-only-public-page-is-a-replay.md).

## 3. Components

| component | responsibility | reuse |
|---|---|---|
Built, and what each turned out to be:

| component | responsibility | status |
|---|---|---|
| `tab/receipt.py` | the one receipt shape, and money parsing into integer centavos | built |
| `tab/checks.py` | the arithmetic, VAT and format checks; a verdict per check | built |
| `tab/pdftext.py` | header fields **and the basket** from a PDF text layer, no model involved | built — see [ADR 0010](adr/0010-a-quantity-is-only-believed-when-the-receipt-states-one.md) |
| `tab/vision.py` | prepare the image, call Ollama, validate the JSON, retry differently | built |
| `tab/store.py` | SQLite schema, transactional writes, the append-only decision log | built |
| `tab/pipeline.py` | hash, dedupe, route per document, check, save, log why | built |
| `tab/cli.py` | `ingest`, `watch`, `queue`, `review`, `export`; CSV written here | built |
| `tab/eval.py` | score a run against gold labels, emit the four metrics | built |
| `tab/web.py` + `tab/static/review.html` | the local review page, standard library only | built — see [ADR 0007](adr/0007-stdlib-http-server-for-the-review-page.md) |
| `tab/watch.py` | folder polling, one watcher per ledger, only exceptions printed | built — see [ADR 0008](adr/0008-poll-the-folder-instead-of-watching-it.md) |
| `tab/errors.py` | the two ways reading can fail, kept apart | built — see [ADR 0009](adr/0009-a-stopped-model-is-not-a-bad-receipt.md) |

Routing and ingest live together in `tab/pipeline.py` rather than in separate
`ingest.py` and `route.py` files: they are one decision followed by its
consequence, and splitting them would have meant passing the same document
state across a seam for no gain. CSV export is a dozen lines inside `cli.py`
for the same reason. `typer` and `rich` were not needed — `argparse` covers
three subcommands.

Dependencies, as shipped — three, all verified on PyPI before install per
playbook §4:

| package | why |
|---|---|
| `pymupdf` | one package doing PDF text extraction *and* page rasterising, instead of `pdfplumber` + `pdf2image` + a `poppler` binary |
| `jsonschema` | validates what the vision model returns before anything reads it |
| `pillow` | caps an oversized photo before it reaches the model |

`sqlite3`, `hashlib`, `urllib`, `csv`, `argparse` and `http.server` are standard
library. Ollama is an external program, not a pip package.

This list is shorter than the one first written here, which included `fastapi`,
`uvicorn`, `python-multipart`, `typer` and `rich`. None survived contact with
counting what they cost: see [ADR 0007](adr/0007-stdlib-http-server-for-the-review-page.md)
for the web framework, and `argparse` covers five subcommands without `typer`.

`pymupdf` was missing from `pyproject.toml` until it was caught by installing
the package into a clean virtual environment — every test passes without it
declared, because the test machine already had it.

## 4. Data flow

```
file ──▶ sha256 ──▶ documents row
                        │
                        ▼
                  route decision ─────────────┐
                        │                     │
          text layer ◀──┘                     └──▶ render PNG ──▶ Ollama
                │                                                   │
                └──────────────▶ extraction JSON ◀──────────────────┘
                                       │
                                       ▼
                                 checks.run()
                                       │
                    ┌──────────────────┴──────────────────┐
                 all pass                            any fail
                    │                                     │
                    ▼                              retry differently
              receipts row                               │
              status=committed              ┌────────────┴──────────┐
                    │                    passes now             still fails
                    ▼                       │                       │
                 CSV / Sheets                ▼                      ▼
                                        committed          status=needs_review
                                                                    │
                                                                    ▼
                                                            review queue
                                                        (field flagged, edit,
                                                         approve → corrections)
```

Every arrow that represents a decision writes a row to `decisions` with the
reason in plain words. That log is what makes the demo convincing: you can show
*why* a receipt was escalated, not merely that it was.

The extraction JSON has exactly one shape, and it is the same shape as the gold
labels and the same shape the scorer reads. Three formats would be three bugs.

## 5. The checks, precisely

| check | rule | fires when |
|---|---|---|
| `line_math` | `qty × unit_price ≈ amount`, per line | a line has all three |
| `item_sum` | `Σ(amount − line discount) ≈ subtotal` | line amounts and a subtotal exist |
| `total_math` | `subtotal + service charge + vat − discount ≈ total`, in either VAT convention | enough parts exist |
| `vat_rate` | `vat_amount ≈ vatable_sales × 0.12` | the receipt states VATable sales |
| `vat_split` | `vatable + exempt + zero_rated ≈ subtotal`, either convention | any VAT split was extracted |
| `date_sane` | parses, and is not in the future | always |
| `total_sane` | `total > 0` and merchant is non-empty | always |
| `agreement` | two independent methods produced the same total | both routes ran |
| `not_duplicate` | sha256 unseen, and `(merchant, date, total)` unseen | always |

`≈` means "within `TAB_AMOUNT_TOLERANCE`", which defaults to ₱0.05 and lives in
one named constant. It is a knob, not a magic number: real receipts round in ways
a clean model does not predict, and the right value is discovered against real
paper. Too loose and wrong receipts slip through; too tight and everything
escalates. Both directions are measured — that is what escalation precision and
silent error rate are for.

`item_sum` is the strongest of these and is the reason line items earn their
cost: a receipt whose items sum correctly to a stated subtotal is very unlikely
to have been misread.

## 6. Failure modes

| what breaks | what happens | what the user sees |
|---|---|---|
| Ollama is not running | ingest stops before doing any work | a plain message naming the command to start it — not a stack trace |
| Vision model returns malformed JSON | up to 3 retries, then the document is escalated | the receipt in the queue, marked "could not read" |
| Document is not a receipt | detected by the format checks, never committed | queued as "not a receipt", one click to discard |
| Foreign currency | detected, never converted | queued with the currency shown |
| Exact duplicate file | skipped at the hash step before any model runs | "already imported, skipped" |
| Same receipt, second photo | soft-duplicate check escalates it | queued, naming the twin: "looks like receipt #12: same merchant, date and total" |
| Corrupt or unreadable file | marked quarantined in the ledger with the reason; **the file is never moved** | listed by `tab queue` under "could not be read at all", and counted on the review screen. It has no receipt row, so there is nothing to correct - naming it is the whole job |
| Process dies mid-batch | already-committed rows stand; the rest re-ingest and skip by hash | re-running the same command is safe |
| Disk full mid-write | SQLite transaction rolls back; no half-row | the error, and no ledger damage |

Crash safety is not optional here: the ledger is the artefact. Writes are one
transaction per receipt, and re-running any command must be safe, because it
will happen.

## 7. Phase 0 — before any of this gets built

Nothing above is written until these numbers exist.

1. **Verify the corpus exists before writing a loader.** Invented dataset names
   are the same trap as invented package names:
   `curl -s https://huggingface.co/api/datasets/naver-clova-ix/cord-v2`.
   Check the licence in the same breath. Images are downloaded by a script and
   never committed.
2. **Define the label JSON once.** Same shape for gold labels, model output and
   scorer input.
3. **Baseline.** One plain extraction pass plus the checks. No routing, no
   retries, no agent. That number is the bar everything clever must beat.
4. **Does the arithmetic guard fire?** Of the extractions known to be wrong, what
   share do the checks catch alone? The most important number in Phase 0.
5. **Can a free local model read a phone photo of a Philippine receipt?**
   `ollama list` first — do not assume a model name exists. Pull candidates, look
   at the actual output, record the choice and the reason in an ADR.

**Kill rule:** if messy real photos are hopeless with free models, ship the
PDF-and-clean-scan version and state the limit on the page.

**Philippine gate:** CORD is Indonesian, SROIE is mixed scanned invoices. Neither
contains a Philippine VAT breakdown, so neither can support a VAT claim. Roughly
fifty hand-labelled local receipts must exist before any PH number is published.
[ADR 0005](adr/0005-cord-baseline-ph-set-required.md).

## 8. Testing strategy

**Tested hardest:** `checks.py`. It touches money and it is the guard everything
else depends on. It gets a real test file from the first slice — a receipt whose
items sum correctly must pass, and one off by ₱0.50 must fail and escalate. If
that test ever goes green while the logic is broken, the project has no floor.

**Tested:** the routing decision (a text-layer PDF must not call the model at
all — assert the model was never invoked), deduplication on both keys, the CSV
export round-trip, and schema validation of extraction JSON.

**Not tested by unit tests:** model output quality. That is what the evaluation
harness is for, and it is measured against labels rather than asserted.

**Not tested at all:** the visual appearance of the review page. Exercised by
hand, per slice.

Guards go where the expensive work starts: assert Ollama is reachable and the
model is present *before* a batch begins, not on the fortieth document.

## 9. Rollout and rollback

Built in vertical slices, each one committed working: text-layer end to end, then
the vision path, then the review page, then VAT, then line items, then unattended
mode, then the evaluation harness and the public page. No slice starts before the
one under it runs.

There is nothing to roll back — it is a local tool, installed with `pip install
-e .`, and the ledger is a file the user owns. The one irreversible action is
writing to an external sheet, which is why that path is opt-in, v2, and announced
in words at the moment it is enabled.
