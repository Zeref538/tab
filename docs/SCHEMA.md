# Schema — TAB

One SQLite file. No ORM — `sqlite3` is standard library and the whole schema fits
on this page. See [ADR 0006](adr/0006-sqlite-as-the-ledger.md) for why.

Constraints live in the database, not only in Python. A rule enforced in
application code is a rule that a second entry point forgets.

---

## 1. Tables

### `documents` — one row per file that arrived

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `sha256` | TEXT | no | **UNIQUE.** Hash of the file bytes |
| `path` | TEXT | no | where it was read from |
| `mime` | TEXT | no | `application/pdf`, `image/jpeg`, … |
| `pages` | INTEGER | no | 1 for images |
| `route` | TEXT | yes | `text_layer` or `vision`; null until routing decides |
| `status` | TEXT | no | `pending` / `committed` / `needs_review` / `quarantined` / `discarded` |
| `ingested_at` | TEXT | no | ISO 8601, UTC |

`CHECK (status IN (...))`. A typo in a status string is otherwise a row that
never appears in any queue and is never noticed.

### `extractions` — one row per attempt to read a document

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `document_id` | INTEGER FK → documents | no | `ON DELETE CASCADE` |
| `method` | TEXT | no | `text_layer` / `vision` |
| `model` | TEXT | yes | model name and tag, null for the text path |
| `pass_no` | INTEGER | no | 1 for the first attempt, 2 for the retry |
| `raw_json` | TEXT | no | exactly what came back, before any cleaning |
| `created_at` | TEXT | no | |

Kept even when superseded. When a number is disputed six months later, the raw
response is the evidence, and cleaning it in place destroys that.

### `receipts` — the ledger row

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `document_id` | INTEGER FK → documents | no | **UNIQUE** — one receipt per document |
| `merchant` | TEXT | yes | null only while in review |
| `tin` | TEXT | yes | Philippine taxpayer identification number |
| `or_number` | TEXT | yes | official receipt number |
| `date` | TEXT | yes | ISO 8601 date, no time |
| `currency` | TEXT | no | ISO 4217, default `PHP` |
| `subtotal` | INTEGER | yes | **centavos** |
| `vatable_sales` | INTEGER | yes | centavos |
| `vat_exempt_sales` | INTEGER | yes | centavos |
| `zero_rated_sales` | INTEGER | yes | centavos |
| `vat_amount` | INTEGER | yes | centavos |
| `discount_total` | INTEGER | yes | centavos, not decomposed — see PRD non-goals |
| `total` | INTEGER | yes | centavos |
| `status` | TEXT | no | `committed` / `needs_review` / `discarded` |
| `committed_at` | TEXT | yes | null until it passes |

**Every amount is an integer number of centavos.** Floats do not represent
₱0.10 exactly, and the entire product is an arithmetic check on money. Storing
pesos as REAL would mean the guard fails on rounding noise it invented itself.
Display divides by 100 at the edge; nothing else ever does.

### `line_items`

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `receipt_id` | INTEGER FK → receipts | no | `ON DELETE CASCADE` |
| `line_no` | INTEGER | no | order as printed |
| `description` | TEXT | yes | |
| `qty` | REAL | yes | REAL because 0.5 kg is a real quantity |
| `unit_price` | INTEGER | yes | centavos |
| `amount` | INTEGER | yes | centavos, as printed on the receipt |

`UNIQUE (receipt_id, line_no)` — a retry that re-inserts items must replace them,
not silently double the subtotal. That specific bug would make `item_sum` fail on
a correct receipt, which is the worst kind: the guard blaming good data.

### `checks` — what ran, and what it said

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `receipt_id` | INTEGER FK → receipts | no | `ON DELETE CASCADE` |
| `name` | TEXT | no | `item_sum`, `total`, `vat_rate`, `vat_parts`, `date_sane`, `total_sane`, `agreement`, `not_duplicate` |
| `passed` | INTEGER | no | 0 or 1 |
| `detail` | TEXT | yes | the human sentence, e.g. "items add up to ₱1,190.00, receipt says ₱1,240.00" |

`detail` is generated from the check itself, which is why the review screen
cannot drift away from the logic.

### `corrections` — what a human changed

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `receipt_id` | INTEGER FK → receipts | no | |
| `field` | TEXT | no | which column was wrong |
| `old_value` | TEXT | yes | as extracted |
| `new_value` | TEXT | yes | as corrected |
| `corrected_at` | TEXT | no | |

Collected from the first review screen; the learning loop that consumes them is
v2, and it must be measured rather than assumed to help.

### `decisions` — append-only

| field | type | null | notes |
|---|---|---|---|
| `id` | INTEGER PK | no | |
| `document_id` | INTEGER FK → documents | no | |
| `step` | TEXT | no | `route`, `extract`, `check`, `retry`, `commit`, `escalate` |
| `action` | TEXT | no | what it did |
| `why` | TEXT | no | in plain words |
| `created_at` | TEXT | no | |

Never updated, never deleted. This is what the demo shows and what an audit
reads.

### `labels` — the gold set, evaluation only

| field | type | null | notes |
|---|---|---|---|
| `document_id` | INTEGER FK → documents | no | |
| `field` | TEXT | no | |
| `value` | TEXT | yes | the hand-checked truth |
| `corpus` | TEXT | no | `cord`, `ph_v1`, … — every number must name its corpus |

`PRIMARY KEY (document_id, field)`. `corpus` exists because a figure measured on
Indonesian receipts must never be quoted as a Philippine result.

## 2. Indexes, each with the query behind it

| index | query it serves |
|---|---|
| `documents.sha256` UNIQUE | "have I already imported this exact file?" — runs on every ingest, before any model |
| `receipts (merchant, date, total)` | the soft-duplicate check: same receipt, photographed twice |
| `receipts.status` | the review queue and the ledger view, the two most frequent reads |
| `line_items.receipt_id` | summing items per receipt for `item_sum` |
| `checks.receipt_id` | rendering which check failed on the review screen |
| `decisions.document_id` | the reasoning trail for one document |

No other indexes. An index with no query behind it is cargo cult, and on a
single-user file it costs write speed for nothing.

## 3. Deletes

- Delete a `document` → cascade to `extractions`, `receipts`, `line_items`,
  `checks`. The user asked for the receipt to be gone.
- **`decisions` and `corrections` do not cascade.** They are the record of what
  happened, and they survive the row they describe. Both carry the document id as
  a plain integer for that reason.
- Nothing is deleted from disk. The source file stays where the user put it.

## 4. Migrations

`PRAGMA user_version` holds the schema number. On open, TAB compares it and
applies forward migrations in order. Two rules, both learned the hard way
elsewhere:

1. **Back up the file before migrating**, `tab.db` → `tab.db.bak-<version>`. The
   ledger is the artefact; there is no re-running the receipts.
2. **Write to a temp file and `os.replace` onto the target.** Never write in
   place over the only copy.

Additive changes only — new nullable columns, new tables. Renaming a column that
an export or a check reads means grepping every reader first, because a field can
mean two things to two callers.
