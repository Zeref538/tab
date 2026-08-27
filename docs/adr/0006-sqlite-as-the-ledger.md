# 0006 — SQLite is the ledger; the spreadsheet is an export

Date: 2026-08-28
Status: accepted

## Context

TAB produces rows, and the people it is for keep those rows in a spreadsheet.
The obvious move is to write straight into the spreadsheet and skip the middle
layer.

That falls apart on the second requirement. TAB must be able to answer "where did
this number come from" six months later — which document, which extraction pass,
which checks ran, why it was committed instead of escalated. A spreadsheet row
holds a total. It cannot hold the reasoning trail, and it certainly cannot hold
the raw model response that a disputed number would be argued from.

There is also a duplicate problem. The exact-duplicate check is a lookup on a
file hash, run on every ingest before any model work happens. That is an index
query, and a spreadsheet is a poor place to run one.

## Options

- **Google Sheets as the store.** The user already lives there, and it is
  visible without installing anything. It also sends every receipt total to a
  server, needs OAuth on first run, breaks offline, and has no place to keep the
  audit trail. It fails the local-first constraint in
  [0004](0004-local-only-public-page-is-a-replay.md).
- **CSV as the store.** Simple and transparent. No indexes, no constraints, no
  transactions — a crash mid-write leaves a half-row, and there is nothing
  stopping two runs appending the same receipt twice.
- **Postgres.** Real constraints and real transactions, and a server to install
  and run for a single user on a single laptop.
- **SQLite, with CSV and Sheets as exports.**

## Decision

**One SQLite file is the source of truth. CSV export in v1. Google Sheets export
in v2, opt-in, off by default.**

`sqlite3` is in the Python standard library — no dependency, no server, no
install step. It gives transactions (so a crash cannot leave half a receipt),
`UNIQUE` and `CHECK` constraints enforced in the database rather than only in
application code, and indexes for the duplicate lookups. The whole schema fits on
one page.

No ORM. Nine tables and a handful of queries do not need one, and an ORM would be
a permanent dependency bought for a temporary convenience.

## Consequences

- The ledger is one file the user owns and can copy, back up, or delete. No
  account, no service, no export needed to walk away.
- Constraints live in the schema, so a second entry point — the web app, the CLI,
  a future importer — cannot bypass them by forgetting a validation.
- **Amounts are stored as integer centavos**, because the product is an equality
  check on money and floats would break it on rounding noise they invented
  themselves. Every reader of an amount divides by 100 at the display edge and
  nowhere else.
- Migrations back the file up before touching it, and write to a temp file then
  `os.replace` onto the target. The ledger is the artefact; there is no
  re-running a stack of receipts.
- The spreadsheet stops being the store and becomes a view, which means it can be
  regenerated at any time and a user editing it by hand does not corrupt
  anything.
- Sheets export is deferred to v2 specifically because it is the one path that
  sends data outward, and it needs the words in the interface that
  [0004](0004-local-only-public-page-is-a-replay.md) requires.
