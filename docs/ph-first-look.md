# First look at real Philippine receipts

100 of the 278 photographs from `data/fetch_ph.py`, read with the OCR route,
195 seconds. **No gold labels yet**, so nothing here is an accuracy figure — it
only counts what TAB failed to find at all, which needs no labels to be true.

| what | out of 100 |
|---|---|
| no subtotal found | **79** |
| no total found | 26 |
| merchant blank or junk | 8 |
| `vat_amount` parsed | 75 |
| "TIN" printed on the receipt | 92 |

## The one that matters

**79 receipts have no subtotal**, and the item-sum check — `Σ(qty × unit_price)
≈ subtotal`, the strongest guard in the project — cannot run without one. Under
the three-state rule a check that could not run is *skip*, not pass. So on real
Philippine receipts the best guard TAB has is silent four times out of five, and
the whole confidence story leans on the weaker checks instead.

CORD could never have shown this. Indonesian receipts print a subtotal; a lot of
Philippine ones go straight from the lines to the total, or print it under a
name the parser does not know.

## The merchant bug, diagnosed

Eight receipts came back with a merchant of `Your order number is`. OCR was not
at fault — it read `PATRICH QSR FOUD CEHTRE CORPORATION` and
`VAT REG TIN 736903725-000` correctly on the same page. The parser takes the
first line as the merchant. That is right on CORD, where the shop name is line
one, and wrong on a fast-food receipt that opens with an order-number banner.

## Caveat on the images

Roboflow re-encoded every photograph to 800px on the long edge. These are not
original phone photos, so they are a harder test of small text than the source
material and an easier test of file size. Any figure from this corpus carries
that, the way every CORD figure carries "Indonesian".

## Still blocked

Gate D is not open. These counts are about what TAB *found*, not what it got
right — a wrong total counts as found. Publishing an accuracy number needs
`tools/label_ph.py` run over about 50 of them first.
