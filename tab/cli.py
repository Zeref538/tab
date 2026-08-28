"""The command line: ingest receipts, see what needs you, export the ledger.

argparse, from the standard library. A CLI framework would be a dependency
bought for three subcommands.

    tab ingest ./receipts
    tab queue
    tab export --csv ledger.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from tab import pipeline, store
from tab.receipt import AMOUNT_FIELDS

DEFAULT_DB = os.environ.get("TAB_DB_PATH", "data/tab.db")

CSV_COLUMNS = ["date", "merchant", "tin", "or_number", "currency", *AMOUNT_FIELDS,
               "source"]


def plural(count: int, one: str, many: str | None = None) -> str:
    return one if count == 1 else (many or one + "s")


def _out(text: str = "") -> None:
    """Print without dying on a Windows console that cannot encode ₱."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode())


def cmd_ingest(args) -> int:
    files = pipeline.gather(args.paths)
    if not files:
        _out("nothing to do: no receipts found in " + ", ".join(args.paths))
        return 0

    conn = store.connect(args.db)
    tally = {"commit": 0, "needs_review": 0, "duplicate": 0, "unreadable": 0}
    for path in files:
        result = pipeline.ingest_one(conn, path, use_model=not args.no_model)
        tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
        _out("  " + result.line())
    conn.close()

    _out()
    _out(f"{tally['commit']} committed, "
         f"{tally['needs_review']} {plural(tally['needs_review'], 'needs', 'need')} review, "
         f"{tally['duplicate']} already imported, {tally['unreadable']} unreadable")
    if tally["needs_review"]:
        _out("Run `tab queue` to see what needs you.")
    # A receipt nobody looked at is not an error, so this still exits 0.
    return 0


def cmd_queue(args) -> int:
    conn = store.connect(args.db)
    rows = store.queue(conn)
    if not rows:
        committed = len(store.ledger(conn))
        _out("Nothing needs you.")
        _out(f"{committed} {plural(committed, 'receipt')} in the ledger.")
        conn.close()
        return 0

    for row in rows:
        failures = conn.execute(
            "SELECT name, detail FROM checks WHERE receipt_id = ? AND status = 'fail'",
            (row["id"],)).fetchall()
        _out(f"#{row['id']}  {row['merchant'] or '(no merchant read)'}"
             f"  {row['date'] or '(no date)'}")
        _out(f"     {Path(row['path']).name}")
        for f in failures:
            _out(f"     ! {f['detail']}")
        _out()
    _out(f"{len(rows)} {plural(len(rows), 'receipt')} waiting.")
    conn.close()
    return 0


def cmd_export(args) -> int:
    conn = store.connect(args.db)
    rows = store.ledger(conn)
    sources = dict(conn.execute("SELECT id, path FROM documents").fetchall())

    handle = sys.stdout if args.csv == "-" else open(args.csv, "w", encoding="utf-8",
                                                     newline="")
    try:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            record = {c: row[c] for c in CSV_COLUMNS if c in row.keys()}
            # Divide by 100 here and nowhere else. Everything upstream is an
            # integer number of centavos precisely so the checks cannot be
            # defeated by float rounding.
            for field in AMOUNT_FIELDS:
                value = row[field]
                record[field] = "" if value is None else f"{value / 100:.2f}"
            record["source"] = Path(sources.get(row["document_id"], "")).name
            writer.writerow(record)
    finally:
        if handle is not sys.stdout:
            handle.close()
            _out(f"{len(rows)} rows -> {args.csv}")
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tab", description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help=f"ledger file ({DEFAULT_DB})")
    subs = parser.add_subparsers(dest="command", required=True)

    ingest = subs.add_parser("ingest", help="read receipts into the ledger")
    ingest.add_argument("paths", nargs="+", help="files or folders")
    ingest.add_argument("--no-model", action="store_true",
                        help="text-layer PDFs only; never call the vision model")
    ingest.set_defaults(func=cmd_ingest)

    queue = subs.add_parser("queue", help="show receipts that need a human")
    queue.set_defaults(func=cmd_queue)

    export = subs.add_parser("export", help="write committed rows out")
    export.add_argument("--csv", default="-", help="file, or - for stdout")
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
