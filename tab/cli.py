"""The command line: ingest receipts, see what needs you, export the ledger.

argparse, from the standard library. A CLI framework would be a dependency
bought for three subcommands.

    tab ingest ./receipts
    tab watch ./receipts
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
from tab.errors import ModelUnavailable
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
    read_so_far = 0
    for path in files:
        try:
            result = pipeline.ingest_one(conn, path, use_model=not args.no_model)
        except ModelUnavailable as exc:
            # Nothing was recorded about this file, so it can be read later.
            # Grinding through the rest the same broken way helps nobody.
            conn.close()
            _out("")
            _out(f"stopped: {exc}")
            _out(f"{read_so_far} read, {len(files) - read_so_far} untouched. "
                 f"Start Ollama and run this again - the ones already read "
                 f"will be skipped.")
            return 1
        read_so_far += 1
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


def _report_unreadable(conn) -> int:
    """Files that never became a receipt. Returns how many there were."""
    stuck = store.unreadable(conn)
    if not stuck:
        return 0
    _out(f"{len(stuck)} {plural(len(stuck), 'file')} could not be read at all:")
    for row in stuck:
        _out(f"     {Path(row['path']).name} — {row['why'] or 'no reason recorded'}")
    _out("     Nothing was extracted from these, so there is nothing to correct.")
    _out("     Re-photograph them, or start Ollama if they are images.")
    _out()
    return len(stuck)


def cmd_queue(args) -> int:
    conn = store.connect(args.db)
    rows = store.queue(conn)
    if not rows:
        committed = len(store.ledger(conn))
        stuck = _report_unreadable(conn)
        _out("Nothing needs reviewing." if stuck else "Nothing needs you.")
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
    _report_unreadable(conn)
    _out(f"{len(rows)} {plural(len(rows), 'receipt')} waiting.")
    conn.close()
    return 0


def cmd_review(args) -> int:
    from tab import web  # imported late so `tab export` never touches the server

    web.serve(args.db, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_watch(args) -> int:
    from tab import watch  # imported late; `tab export` has no business polling

    return watch.run(args.db, args.paths, use_model=not args.no_model,
                     interval=args.interval, report=_out)


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

    review = subs.add_parser("review", help="open the review screen in a browser")
    review.add_argument("--port", type=int, default=8000)
    review.add_argument("--no-browser", action="store_true",
                        help="serve, but do not open a browser")
    review.set_defaults(func=cmd_review)

    watch = subs.add_parser("watch", help="read receipts as they land in a folder")
    watch.add_argument("paths", nargs="+", help="folders to watch")
    watch.add_argument("--interval", type=float, default=5.0,
                       help="seconds between looks (5)")
    watch.add_argument("--no-model", action="store_true",
                       help="text-layer PDFs only; never call the vision model")
    watch.set_defaults(func=cmd_watch)

    export = subs.add_parser("export", help="write committed rows out")
    export.add_argument("--csv", default="-", help="file, or - for stdout")
    export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
