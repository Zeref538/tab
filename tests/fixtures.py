"""Build receipt PDFs to test against.

Generated rather than committed, so the input to a test is visible as code
instead of an opaque binary nobody can diff. PyMuPDF is already a dependency for
reading PDFs, so writing one costs no extra package.

    python tests/fixtures.py            # writes tests/fixtures/clean.pdf
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

# A Philippine receipt as it is actually printed: prices INCLUDE VAT, so the
# total equals the subtotal and the VAT is carved out of it, not added on.
#   VATable 1,062.50 + VAT 127.50 = 1,190.00
CLEAN = """SM SUPERMARKET
SM City North EDSA, Quezon City
TIN: 000-123-456-000
OR No.: 0099123
Date: 2026-08-12

Rice 5kg                      700.00
Milk 1L                       490.00

SUBTOTAL                    1,190.00
VATable Sales               1,062.50
VAT-Exempt Sales                0.00
Zero-Rated Sales                0.00
VAT (12%)                     127.50
Discount                        0.00
TOTAL                       1,190.00

CASH                        2,000.00
CHANGE                        810.00

Thank you for shopping!
"""

# Same receipt, total typed wrong by fifty centavos. The guard must catch it.
WRONG_TOTAL = CLEAN.replace("TOTAL                       1,190.00",
                            "TOTAL                       1,190.50")

# A restaurant bill: subtotal, then service charge, then VAT on top.
#   1,000.00 + 100.00 service + 132.00 VAT = 1,232.00
RESTAURANT = """MANG INASAL
Ayala Center, Makati
TIN: 111-222-333-000
Invoice No. 5541
Date: 2026-07-30

SUBTOTAL                    1,000.00
Service Charge                100.00
VATable Sales               1,100.00
VAT (12%)                     132.00
TOTAL                       1,232.00
"""


def write_receipt_pdf(path: str | Path, text: str = CLEAN) -> Path:
    """Render text into a real PDF with a real text layer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=320, height=560)  # roughly receipt-shaped
    page.insert_text((20, 30), text, fontname="cour", fontsize=8)
    doc.save(path)
    doc.close()
    return path


def write_image_only_pdf(path: str | Path) -> Path:
    """A PDF with no text layer at all — what a scan or a photo produces.

    The router must send this to the vision model rather than parse nothing
    out of it and commit an empty row.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=320, height=560)
    page.draw_rect(pymupdf.Rect(20, 20, 300, 540), color=(0, 0, 0), width=1)
    doc.save(path)
    doc.close()
    return path


if __name__ == "__main__":
    here = Path(__file__).resolve().parent / "fixtures"
    for name, text in (("clean.pdf", CLEAN), ("wrong-total.pdf", WRONG_TOTAL),
                       ("restaurant.pdf", RESTAURANT)):
        print("wrote", write_receipt_pdf(here / name, text))
    print("wrote", write_image_only_pdf(here / "scanned.pdf"))
