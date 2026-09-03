"""Build the receipts the public demo offers, into tab/samples/.

    python tools/make_samples.py

They are generated from the same fixtures the tests use, not photographed, for
two reasons. A real receipt is somebody's personal data and has no business in a
public repo (ADR 0004). And a generated one can be *known* to be wrong in a
specific way, so the demo can show the arithmetic catching something real rather
than hoping a photo happens to disagree with itself.

Three of them, chosen to show three different paths:

  clean.pdf          an e-receipt with a real text layer. No OCR at all - the
                     router sees text and reads it directly, in milliseconds.
  restaurant.pdf     service charge and VAT, so more than one check has to fire.
  bad-line-math.png  the itemised one, rendered to a picture so it has to go
                     through OCR, with line 3 printed at 80.00 where 3 x 30.00
                     is 90.00. This is the one that gets held back.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tab" / "samples"
RENDER_DPI = 200          # what pipeline renders a text-less PDF at


def main() -> int:
    import pymupdf

    from tests.fixtures import BAD_LINE_MATH, CLEAN, RESTAURANT, write_receipt_pdf

    OUT.mkdir(parents=True, exist_ok=True)

    notes = {
        "clean.pdf": "A supermarket e-receipt. Carries real text, so nothing "
                     "has to recognise anything - the router reads it directly "
                     "and every check passes.",
        "restaurant.pdf": "Service charge and VAT on top of the subtotal, so "
                          "the totals check has more than one part to reconcile.",
        "bad-line-math.png": "A photograph, so it has to go through OCR. Line 3 "
                             "reads 80.00 where 3 x 30.00 is 90.00. TAB should "
                             "refuse to file this one and point at that line.",
    }

    write_receipt_pdf(OUT / "clean.pdf", CLEAN)
    write_receipt_pdf(OUT / "restaurant.pdf", RESTAURANT)

    # Render to a picture so the demo exercises the OCR route rather than the
    # text layer. A PDF of this would be read perfectly and prove nothing about
    # reading a photograph.
    pdf = OUT / "_tmp-bad-line-math.pdf"
    write_receipt_pdf(pdf, BAD_LINE_MATH)
    with pymupdf.open(pdf) as doc:
        doc[0].get_pixmap(dpi=RENDER_DPI).save(OUT / "bad-line-math.png")
    pdf.unlink()

    for name, note in notes.items():
        (OUT / name).with_suffix(".txt").write_text(note + "\n", encoding="utf-8")

    for path in sorted(OUT.iterdir()):
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
