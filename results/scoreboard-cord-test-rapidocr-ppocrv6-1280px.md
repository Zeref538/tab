Measured on **cord**, n=100, model `rapidocr-ppocrv6@1280px`, tolerance 5 centavos.

Two columns because "wrong" has two honest meanings: the total alone is
the number that lands in the ledger, but an invented VAT line is a bad row
too. Naming which one a figure uses is not a formality.

| metric | wrong = total | wrong = any scored field |
|---|---|---|
| straight-through rate | 15.0% | 15.0% |
| **silent error rate** | 1.0% | 2.0% |
| escalation precision | 31.8% | 67.1% |

Under the product rules, which also require a merchant name and a date, straight-through is 0.0% — CORD labels neither field, so that column measures the corpus, not the system.

| field | accuracy | correct |
|---|---|---|
| `subtotal` | 76.0% | 76/100 |
| `vat_amount` | 71.0% | 71/100 |
| `service_charge` | 94.0% | 94/100 |
| `discount_total` | 94.0% | 94/100 |
| `total` | 72.0% | 72/100 |

Not scored on this corpus, because it does not label them: `merchant`, `date`, `tin`, `or_number`, `vatable_sales`, `vat_exempt_sales`, `zero_rated_sales`.

Extraction failures: 0. Median 0.7s per receipt.

**Ceiling:** 91/100 (91.0%) of the gold labels pass their own arithmetic at this tolerance. A perfect extractor is still escalated on the rest, so no straight-through rate here can honestly beat that.