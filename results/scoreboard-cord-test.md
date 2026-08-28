Measured on **cord**, n=100, model `qwen2.5vl:3b`, tolerance 5 centavos.

Two columns because "wrong" has two honest meanings: the total alone is
the number that lands in the ledger, but an invented VAT line is a bad row
too. Naming which one a figure uses is not a formality.

| metric | wrong = total | wrong = any scored field |
|---|---|---|
| straight-through rate | 30.0% | 30.0% |
| **silent error rate** | 1.0% | 8.0% |
| escalation precision | 14.3% | 64.3% |

Under the product rules, which also require a merchant name and a date, straight-through is 0.0% — CORD labels neither field, so that column measures the corpus, not the system.

| field | accuracy | correct |
|---|---|---|
| `subtotal` | 66.0% | 66/100 |
| `vat_amount` | 83.0% | 83/100 |
| `service_charge` | 94.0% | 94/100 |
| `discount_total` | 93.0% | 93/100 |
| `total` | 89.0% | 89/100 |

Not scored on this corpus, because it does not label them: `merchant`, `date`, `tin`, `or_number`, `vatable_sales`, `vat_exempt_sales`, `zero_rated_sales`.

Extraction failures: 0. Median 21.7s per receipt.

**Ceiling:** 91/100 (91.0%) of the gold labels pass their own arithmetic at this tolerance. A perfect extractor is still escalated on the rest, so no straight-through rate here can honestly beat that.