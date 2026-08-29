Measured on **cord**, n=100, model `qwen2.5vl:7b`, tolerance 5 centavos.

Two columns because "wrong" has two honest meanings: the total alone is
the number that lands in the ledger, but an invented VAT line is a bad row
too. Naming which one a figure uses is not a formality.

| metric | wrong = total | wrong = any scored field |
|---|---|---|
| straight-through rate | 52.0% | 52.0% |
| **silent error rate** | 2.0% | 15.0% |
| escalation precision | 12.5% | 70.8% |

Under the product rules, which also require a merchant name and a date, straight-through is 0.0% — CORD labels neither field, so that column measures the corpus, not the system.

| field | accuracy | correct |
|---|---|---|
| `subtotal` | 69.0% | 69/100 |
| `vat_amount` | 92.0% | 92/100 |
| `service_charge` | 94.0% | 94/100 |
| `discount_total` | 91.0% | 91/100 |
| `total` | 92.0% | 92/100 |

Not scored on this corpus, because it does not label them: `merchant`, `date`, `tin`, `or_number`, `vatable_sales`, `vat_exempt_sales`, `zero_rated_sales`.

Extraction failures: 0. Median 38.5s per receipt.

**Ceiling:** 91/100 (91.0%) of the gold labels pass their own arithmetic at this tolerance. A perfect extractor is still escalated on the rest, so no straight-through rate here can honestly beat that.