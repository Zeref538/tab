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

---

# What got fixed, and what did not

## The diagnosis

The receipts *do* print a subtotal. OCR mangles the word:

    7 Iten(s)   Sabtotal 227.00        SUBTOTAL
    UAI Amount   24.32                 VAT AMOUNT
    IOTAL. DUE   227.00                TOTAL DUE
    CHWHGE   182.10                    CHANGE

Every label in the parser was an exact regex, and exact means one wrong letter
misses. You cannot enumerate the ways OCR breaks a word, so the fix is to stop
matching exactly: `difflib.SequenceMatcher`, standard library, scores two
strings for likeness. "SABTOTAL" against "SUBTOTAL" comes back 0.875. The
threshold is 0.8 - one letter in five may be wrong. 0.7 started matching TOTAL
as SUBTOTAL, which would have written the wrong number into a ledger.

The exact regexes still run first. Fuzzy is a fallback, never the first answer.

## The second bug, which the first one was hiding

The basket parser already knew to stop at the totals block - with exact regexes.
So `IOTAL. DUE`, `CHWHGE` and `Vetable Sales` walked straight past the guard and
were counted as things somebody bought. One receipt's six "items" included the
total, the cash tendered and the VAT-exempt line.

`item_sum` had been skipping for want of a subtotal, so nothing ever complained.
Fixing the labels switched the light on and showed the older bug underneath.

## Measured, 100 receipts

| | before | after |
|---|---|---|
| no subtotal found | 79 | **65** |
| item_sum passes | ~6 | **22** |
| item_sum fails | 65 | 44 |
| item_sum skips | 29 | 34 |

The remaining 65 genuinely print no subtotal - a fast-food till lists the items
and jumps to the total. For those, `item_sum` now compares against the total
instead, which only holds because nothing sits in between: no service charge, no
receipt-level discount, and Philippine VAT is inside the printed prices rather
than added on top. The check says which basis it used, so a passing receipt
never hides that it was measured against the total.

## Still broken, named honestly

- **`line_math` skips all 100.** It needs a quantity the receipt says out loud
  ("2 x 245.00"). These tills print unlabelled columns, so the quantity is a
  guess, and guessing the reading that makes the arithmetic work would make the
  check prove nothing.
- **The median receipt yields one line item.** The basket parser stops too early
  on some layouts, and an item-count line like "8 Iten(s) 388.10" still slips in
  as an item.
- **44 item_sum failures.** Some are real reading errors, some are the basket
  parser. Which is which cannot be said without labels.

None of the above is an accuracy figure. Every count here is about what TAB
found or reconciled, not what it got right. Gate D stays shut.
