# SettleTrace product brief

## The user and the job

The first proposed user is a small merchant's bookkeeper who has a custom
captured-payment ledger, one processor account, and bank records. At close, they
need to explain which supplied records agree and which need investigation.

The initial hypothesis is that a local exception pack with explicit source
references can make this investigation easier than maintaining custom spreadsheet
joins. This is a product experiment. No customer demand, time saving, revenue, or
production use has been established.

## Existing workflow

Stripe already offers itemized payout reconciliation reports containing payments,
refunds, disputes, fees, and other balance transactions. Custom metadata can help
match those transactions to internal records. Its payout reconciliation report
primarily serves automatic payouts. Rebuilding that report alone would provide
little differentiation. See [Stripe's payout reconciliation
documentation](https://docs.stripe.com/reports/payout-reconciliation) and
[custom report columns](https://docs.stripe.com/reports/metadata).

SettleTrace's proposed wedge is a merchant's custom internal ledger and a
repeatable offline exception review. Whether that wedge is useful enough to pay
for remains unvalidated. Existing accounting integrations are also alternatives;
the [Synder listing in Stripe's marketplace](https://marketplace.stripe.com/apps/synder)
describes syncing sales, fees, refunds, taxes, and payouts into accounting systems.

## What the tool actually does

The CLI reads canonical sales/bank CSVs and either canonical processor activity
or the explicitly selected [Stripe itemized.7 subset](stripe-import.md):

- Captured sales with unique sale and payment references.
- Processor activity with explicit payment and payout references, signed gross
  and fee amounts, and a checked net amount.
- Bank deposits explicitly mapped to payout IDs.

It checks a sale against one observed charge, and a deposit against the sum of
observed processor net amounts for that payout. It flags amount and currency
differences, ambiguous multiple charges, unattributed activity, and records not
observed on the other side. Duplicate identifiers and invalid input stop the run
instead of being silently combined.

Amounts are integer minor units in USD, EUR, GBP, or INR. Each comparison keeps
currencies separate. The output directory contains an HTML report, JSON report,
findings CSV, and a manifest with input and output fingerprints. Findings retain
source names, record IDs, and physical CSV line references. No network call or
model inference is needed.

## Boundaries that matter

The inputs must already contain reliable payment and payout references. The tool
does not infer a bank-to-payout mapping from a date or amount. It supports one
deposit record per payout and one captured sale per payment reference; split
captures, split deposits, FX, and automatic fuzzy matching remain outside scope.

There is no transaction-date model or completeness proof. An absent charge or
deposit means it was not observed in the supplied files. It may be outside the
observation window or incorrectly mapped; it is not proof of missing cash.
Matching totals can also conceal omitted offsetting entries. Each input's
fingerprint and parser refer to the same captured bytes. This is not a lock or a
common atomic snapshot across all three files. Fingerprints identify bytes, not
their authenticity or completeness.

Stripe's reports group payouts using estimated arrival dates, which can differ
from bank posting dates. Different report types also use different date bases.
See [payout timing](https://docs.stripe.com/reports/payout-reconciliation#payout-timing-and-report-availability)
and [report selection](https://docs.stripe.com/reports/select-a-report).

## Smallest next milestone

The itemized.7 subset is implemented against documented columns and synthetic
fixtures, with exact conversion, explicit identities, unsupported-category
rejection, and source-row evidence. It has not been tested with a real account
export. v0.3 adds a hash-bound operator declaration of observation intervals and
an explicit one-to-one bank mapping with replay verification. It does not check
row timestamps, account identity, or completeness. Next, validate the actual
import/mapping workflow against a permitted real-account export and operator
process. A stronger completeness claim needs event-time and coverage evidence;
it is not implied by matching a net total. Use suitable data and authorization.

## Validate before monetizing

With the user's explicit authorization for outreach, observe a bookkeeper's
current workflow using sanitized or synthetic examples. Establish a baseline,
then ask them to run the same investigation with the exception pack. Record
setup time, incorrect or missed findings, investigation time, and whether they
return for another period. Keep contrary feedback.

A possible first offer is a paid custom mapping and reconciliation setup. A
recurring product only becomes plausible if repeated use and willingness to pay
are observed. Hosting, AI summaries, and additional integrations should follow a
demonstrated need. No outreach has been authorized or performed by this brief.
