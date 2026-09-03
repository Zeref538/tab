"""Confirm or correct what TAB read, one Philippine receipt at a time.

    python tools/label_ph.py            # next 10 unlabelled
    python tools/label_ph.py --n 50

TAB reads the receipt, shows you what it got, and you press enter if it is right
or type the correct value if it is not. Correcting is roughly ten times faster
than typing eleven fields blind, and the receipt is open in front of you either
way. Fifty of these is an evening, not a fortnight.

The image opens in whatever your machine uses for pictures. Type the value as it
is printed - "1,190.50" is fine, TAB parses it the same way it parses a receipt.
Enter accepts, "-" means the receipt does not print that field at all, and "q"
stops and saves.

Writes back into data/ph/labels.jsonl after every receipt, so a crash or a "q"
never costs more than the one in front of you.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab import pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "data" / "ph"
LABELS = ROOT / "labels.jsonl"

# The fields TAB is scored on. VAT ones are the whole reason this corpus exists:
# CORD has none of them, so this parser has never met a real printed VAT block.
FIELDS = [
    "merchant", "date", "total", "subtotal",
    "vat_amount", "vatable_sales", "vat_exempt_sales", "zero_rated_sales",
    "tin", "or_number",
]


def show(path: Path) -> None:
    """Open the image the way the operating system would on a double click."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - a local file we just wrote
        else:
            subprocess.run(["xdg-open" if sys.platform != "darwin" else "open",
                            str(path)], check=False)
    except OSError as exc:
        print(f"  (could not open the image: {exc} - open it yourself: {path})")


def label(limit: int) -> None:
    if not LABELS.exists():
        sys.exit(f"no corpus yet: {LABELS}\nrun  python data/fetch_ph.py  first")

    records = [json.loads(line) for line in
               LABELS.read_text(encoding="utf-8").splitlines() if line.strip()]
    todo = [r for r in records if not r.get("labelled")]
    print(f"{len(records) - len(todo)} of {len(records)} done, "
          f"{len(todo)} to go. Enter accepts, '-' means not printed, 'q' quits.\n")

    done = 0
    for record in todo[:limit]:
        image = ROOT / record["image"]
        print(f"--- {record['id']} ---")
        show(image)
        try:
            read, meta = pipeline.read(image, reader="ocr")
            print(f"    read in {meta['seconds']}s via {meta['method']}")
        except Exception as exc:  # noqa: BLE001 - one bad photo must not end the run
            print(f"    TAB could not read it ({type(exc).__name__}: {exc})")
            read = {}

        fields = {}
        for field in FIELDS:
            guess = read.get(field)
            shown = "" if guess in (None, "") else str(guess)
            answer = input(f"  {field:18} [{shown}] ").strip()
            if answer.lower() == "q":
                _save(records)
                print(f"\nstopped. {done} labelled this run.")
                return
            if answer == "-":
                fields[field] = None
            elif answer:
                fields[field] = answer
            elif shown:
                fields[field] = shown
            # blank answer with no guess: leave the field out entirely, which is
            # "nobody has said", not "the receipt does not print it".

        record["fields"] = fields
        record["labelled"] = True
        _save(records)          # after every receipt, not at the end
        done += 1
        print()

    print(f"{done} labelled. {len([r for r in records if r.get('labelled')])} "
          f"of {len(records)} total.")
    print("Gate D wants about 50 before any Philippine figure gets published.")


def _save(records: list[dict]) -> None:
    tmp = LABELS.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                           for r in records), encoding="utf-8")
    os.replace(tmp, LABELS)     # atomic: the old file survives a crash mid-write


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=10, help="how many this sitting")
    label(p.parse_args().n)
