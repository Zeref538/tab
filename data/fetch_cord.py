"""Download the CORD receipt corpus and convert it into TAB label shape.

CORD (Consolidated Receipt Dataset), naver-clova-ix/cord-v2 on Hugging Face,
CC BY 4.0. Photographs of real Indonesian receipts with labelled fields,
including line items. Verified to exist before this script was written:

    curl -s https://huggingface.co/api/datasets/naver-clova-ix/cord-v2   # 200

Why this corpus and not a Philippine one: getting to a first honest number in a
day beats stalling for a fortnight. What it CANNOT support is any Philippine or
VAT claim — CORD has no VATable/exempt/zero-rated split, no TIN, no OR number.
See docs/adr/0005. Every label written here carries corpus="cord" so a figure
can never be quoted as a Philippine result by accident.

Images are downloaded, never committed — .gitignore excludes data/.

    python data/fetch_cord.py --split test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tab.receipt import to_centavos  # noqa: E402

DATASET = "naver-clova-ix/cord-v2"
ROWS_API = "https://datasets-server.huggingface.co/rows"
PAGE = 100  # the API caps a page at 100 rows
OUT = Path(__file__).resolve().parent / "cord"


def _get(url: str, tries: int = 3) -> bytes:
    """Fetch, retrying on the transient failures a public API actually throws."""
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == tries:
                raise
            print(f"    retry {attempt}/{tries - 1} after {exc}")
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def _as_list(value):
    """CORD stores a single line item as a dict and several as a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _qty(raw):
    """Counts appear as "2", "2 x", "x2", "2.00". Pull the number out."""
    if raw is None:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit() or c == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def to_tab_shape(gt_parse: dict) -> dict:
    """CORD ground truth -> the one TAB receipt shape.

    Amounts here are Indonesian rupiah written as "60.000", where the dot is a
    THOUSANDS separator, not a decimal point. to_centavos already handles that
    (a separator is only decimal when exactly two digits follow it), and the
    same parser runs on the model output, so gold and prediction cannot drift
    apart on formatting.
    """
    sub = gt_parse.get("sub_total") or {}
    tot = gt_parse.get("total") or {}

    # CORD nests add-on lines under menu.sub (a drink upgrade, a side), and
    # puts per-line promos in menu.discountprice. Both are real printed lines,
    # and dropping either makes correct receipts fail their own item sum.
    items = []
    for m in _as_list(gt_parse.get("menu")):
        if not isinstance(m, dict):
            continue
        for entry in [m] + _as_list(m.get("sub")):
            if not isinstance(entry, dict):
                continue
            items.append({
                "line_no": len(items) + 1,
                "description": entry.get("nm"),
                "qty": _qty(entry.get("cnt")),
                "unit_price": to_centavos(entry.get("unitprice")),
                "amount": to_centavos(entry.get("price")),
                "discount": to_centavos(entry.get("discountprice")),
            })

    discount = to_centavos(sub.get("discount_price"))
    return {
        # Not labelled in CORD. Left None rather than invented — a gold value
        # that was guessed is worse than an absent one.
        "merchant": None,
        "tin": None,
        "or_number": None,
        "date": None,
        "currency": "IDR",
        "subtotal": to_centavos(sub.get("subtotal_price")),
        "vatable_sales": None,
        "vat_exempt_sales": None,
        "zero_rated_sales": None,
        "vat_amount": to_centavos(sub.get("tax_price")),
        "service_charge": to_centavos(sub.get("service_price")),
        "discount_total": abs(discount) if discount is not None else None,
        "total": to_centavos(tot.get("total_price")),
        "line_items": items,
    }


def fetch(split: str, limit: int | None) -> None:
    images = OUT / "images"
    images.mkdir(parents=True, exist_ok=True)
    labels_path = OUT / f"labels-{split}.jsonl"

    offset, written = 0, 0
    with labels_path.open("w", encoding="utf-8", newline="\n") as fh:
        while True:
            url = (f"{ROWS_API}?dataset={DATASET}&config=default&split={split}"
                   f"&offset={offset}&length={PAGE}")
            payload = json.loads(_get(url))
            if "rows" not in payload:
                raise SystemExit(f"datasets-server said: {payload}")
            total_rows = payload["num_rows_total"]
            rows = payload["rows"]
            if not rows:
                break

            for entry in rows:
                idx = entry["row_idx"]
                row = entry["row"]
                name = f"{split}-{idx:04d}.jpg"
                dest = images / name
                if not dest.exists():
                    dest.write_bytes(_get(row["image"]["src"]))

                gt = json.loads(row["ground_truth"])
                record = {
                    "document": name,
                    "corpus": "cord",
                    "split": split,
                    "labels": to_tab_shape(gt.get("gt_parse") or {}),
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                if written % 20 == 0:
                    print(f"    {written}/{limit or total_rows}")
                if limit and written >= limit:
                    break

            if limit and written >= limit:
                break
            offset += len(rows)
            if offset >= total_rows:
                break

    print(f"{written} receipts -> {labels_path}")
    print(f"images -> {images}")
    print("\nCORD, naver-clova-ix/cord-v2, CC BY 4.0. Indonesian receipts.")
    print("Not a Philippine corpus: no VAT split, no TIN, no OR number, no date.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="test", choices=["train", "validation", "test"])
    p.add_argument("--limit", type=int, default=None, help="stop after N receipts")
    a = p.parse_args()
    fetch(a.split, a.limit)
