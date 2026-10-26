# Stripe itemized payout import

The explicit format `stripe-payout-itemized-7` targets the documented column
contract for **`payout_reconciliation.itemized.7`**. These examples are invented
test data shaped like that report, not exports downloaded from a Stripe account.
No live account or bank connection has been tested.

## Export and identity

Select an **itemized payout reconciliation CSV** for automatic payouts. Select
these eight columns, including the nondefault `charge_id` column:

```text
balance_transaction_id,charge_id,automatic_payout_id,reporting_category,currency,gross,fee,net
```

Order may vary. Additional columns are allowed and ignored, except documented
guard columns described below. Each row must have exactly as many cells as the
header. Headers and transaction IDs must be unique; missing identifiers are
errors. UTF-8, an optional BOM, and standard quoted CSV cells are supported.

`balance_transaction_id` identifies an activity record. `charge_id` identifies
the **original charge** on charges, refunds, and disputes; it becomes the
canonical `payment_ref`. `source_id` may identify a refund or another related
object, so it is never a fallback. Your merchant ledger must use the same
original charge IDs. PaymentIntent IDs, order IDs, and arbitrary metadata IDs
are not interchangeable.

`automatic_payout_id` supplies the payout grouping. It is mandatory in this
format. Manual/instant payouts are unsupported; bank references remain an
explicit mapping supplied in the canonical bank CSV.

## Amounts and supported activity

Stripe financial CSV `gross`, `fee`, and `net` columns use **major units**, unlike
the API's integer minor units. The importer accepts ASCII signed decimal strings
with up to two fractional digits for USD, EUR, GBP, and INR only. It converts by
integer arithmetic, never a float or a rounding rule. `19.99` becomes `1999`.
Exponents, grouping separators, whitespace, mixed separators, and excess
precision are rejected. Choose `--decimal-separator ,` explicitly for quoted
comma-decimal cells; the CSV column delimiter remains a comma.

Only `charge`, `refund`, and debit `dispute` reporting categories are supported.
Charges require positive gross; refunds and disputes require negative gross.
Fees on those rows retain their signs, including negative fee credits. Every
row must satisfy `net = gross - fee` exactly. Unknown categories abort the entire
import with source-line evidence. Standalone fee rows, partial-capture reversals,
dispute reversals, refund failures, reserves, transfers, and adjustments are
unsupported. **Do not remove unsupported rows to force a successful run**: doing
so can change payout totals and make the observation incomplete.

When supplied, `customer_facing_currency` must agree with the settlement
`currency`; a different currency is rejected because this version has no FX
model. A nonblank `connected_account_id` is rejected because this adapter does
not establish which Connect account's ledger is being reconciled. Omitting
those optional columns does not prove that the data has no FX or account-scope
issues. The operator remains responsible for a consistent single-account export.

The CSV does not carry a report-version authenticity proof. Selecting the format
is the operator's assertion that the input uses this documented schema. Date
columns are not used to filter or prove completeness. Stripe's payout report
uses estimated arrival dates, which can differ from bank posting dates.

## Repeatable workflow

From the repository root, use a new output directory each run:

```sh
python -m settletrace validate --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv --processor-format stripe-payout-itemized-7
python -m settletrace reconcile --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv --processor-format stripe-payout-itemized-7 --output output/stripe
python -m settletrace verify --bundle output/stripe --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv
python -m settletrace normalize-stripe --input examples/stripe/processor.csv --output output/normalized
```

Expect one matched sale and payout, no findings, and USD 76.50 after the USD
20.00 refund and USD 3.50 fee. The refund's source ID differs from the original
charge; its shared `charge_id` is the reason both belong to the same payment.

`normalize-stripe` produces canonical `processor.csv` plus `audit.json`, with the
raw input hash and the mapping from exported records back to their original CSV
lines. A later reconciliation of that canonical export refers to its canonical
line numbers; keep the audit alongside it to trace back to the raw export.
Reconciliation directly from the Stripe input retains raw source line numbers.

`validate` checks parsing and reconciliation input contracts without writing a
report; it does not certify a matching payout. `verify` checks recorded hashes
and supplied sources, not their authenticity or accounting completeness. The
normalization directory is not a reconciliation report bundle.

## Primary references

- [Versioned report schema](https://docs.stripe.com/reports/report-types/payout-reconciliation)
- [Payout report scope and timing](https://docs.stripe.com/reports/payout-reconciliation)
- [Financial CSV monetary formats](https://docs.stripe.com/reports/api)
- [Reporting categories](https://docs.stripe.com/reports/reporting-categories)
- [Balance transaction arithmetic](https://docs.stripe.com/api/balance_transactions/object)

Checked 24 October 2026. The supported subset and rejection rules above are
SettleTrace's contract, not a claim that Stripe exports are limited to that subset.
