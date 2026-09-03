"""Download real Philippine receipt photographs to score TAB against.

Receipts Dataset Philippines, capstone-emk5p/receipts-dataset-philippines on
Roboflow Universe. 278 photographs of real Philippine receipts - thermal fade,
phone angles, creases - which is the exact material CORD's clean scans never
test.

    set ROBOFLOW_API_KEY   (roboflow.com -> Settings -> API Keys, free)
    python data/fetch_ph.py

WHAT THIS CORPUS DOES AND DOES NOT GIVE YOU. Its labels are bounding boxes for
Merchant, Date and Total - rectangles saying WHERE a value is printed, not what
it says. TAB outputs values, so a box cannot score it: "the total is in this
rectangle" cannot tell you whether TAB read 314.00 or 374.00.

So this writes labels with the values left EMPTY, on purpose. They are filled in
by looking at each receipt - see tools/label_ph.py, which shows you what TAB read
and asks you to confirm or correct it, because correcting is about ten times
faster than typing eleven fields from scratch.

Until those values exist, nothing here can be quoted as an accuracy figure.
tests/test_site.py enforces that, and docs/adr/0005 says why. Every record
carries corpus="ph-roboflow" so a CORD number and a PH number can never be
averaged together by accident.

Images are downloaded, never committed - .gitignore excludes data/.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

WORKSPACE = "capstone-emk5p"
PROJECT = "receipts-dataset-philippines"
API = "https://api.roboflow.com"
OUT = Path(__file__).resolve().parent / "ph"


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def newest_version(key: str) -> int:
    """Roboflow numbers dataset versions from 1. Ask rather than guess."""
    info = _json(f"{API}/{WORKSPACE}/{PROJECT}?api_key={urllib.parse.quote(key)}")
    versions = info.get("versions") or []
    if not versions:
        raise SystemExit("that project has no published versions - check the URL")
    # ids look like "capstone-emk5p/receipts-dataset-philippines/3"
    return max(int(str(v["id"]).rsplit("/", 1)[-1]) for v in versions)


def fetch(key: str, version: int | None = None) -> None:
    version = version or newest_version(key)
    print(f"version {version}")

    # Ask for the export, get back a signed link. `format=coco` is the one that
    # carries image filenames in a single json rather than one txt per image.
    meta = _json(f"{API}/{WORKSPACE}/{PROJECT}/{version}/coco"
                 f"?api_key={urllib.parse.quote(key)}")
    link = meta.get("export", {}).get("link")
    if not link:
        raise SystemExit(f"no download link in the reply: {meta}")

    print("downloading...")
    with urllib.request.urlopen(link, timeout=600) as r:
        blob = r.read()
    print(f"{len(blob) / 1e6:.1f} MB")

    images = OUT / "images"
    images.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for entry in z.namelist():
            if entry.lower().endswith((".jpg", ".jpeg", ".png")):
                name = Path(entry).name
                (images / name).write_bytes(z.read(entry))
                names.append(name)

    labels = OUT / "labels.jsonl"
    with labels.open("w", encoding="utf-8") as fh:
        for name in sorted(names):
            fh.write(json.dumps({
                "id": Path(name).stem,
                "image": f"images/{name}",
                "corpus": "ph-roboflow",
                # Empty until a person confirms them. Absent, not zero - a 0
                # here would score as "the total is nothing" and pass silently.
                "labelled": False,
                "fields": {},
            }, ensure_ascii=False) + "\n")

    print(f"{len(names)} images -> {images}")
    print(f"{len(names)} unlabelled records -> {labels}")
    print("\nReceipts Dataset Philippines, Roboflow Universe. Box labels only:")
    print("no values, no VAT split, no TIN. Nothing here is scoreable yet.")
    print("Next:  python tools/label_ph.py")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", type=int, default=None, help="default: newest")
    a = p.parse_args()
    api_key = os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        sys.exit("set ROBOFLOW_API_KEY first (roboflow.com -> Settings -> API Keys)")
    fetch(api_key, a.version)
