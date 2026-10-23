# SettleTrace

Trace exceptions between a merchant's captured-payment ledger, processor activity,
and explicitly mapped bank deposits. Runs offline with Python 3.11+, with no
runtime dependencies or API keys.

An operator can see **what differs, by how much, and which input rows explain it**.
The output is a portable HTML report, machine-readable JSON, findings CSV, and a
SHA-256 manifest. This is a small reconciliation engine and evidence pack;
customer demand and willingness to pay are still hypotheses.

## Run the synthetic demonstration

```sh
git clone https://github.com/VSBhargav5/SettleTrace.git
cd SettleTrace
python -m settletrace reconcile --sales examples/clean/sales.csv --processor examples/clean/processor.csv --bank examples/clean/bank.csv --output output/clean
python -m settletrace reconcile --sales examples/exceptions/sales.csv --processor examples/exceptions/processor.csv --bank examples/exceptions/bank.csv --output output/exceptions
```

Open `output/clean/report.html` or `output/exceptions/report.html` in a browser.
Choose a **new output directory** each run. Existing paths are refused. All sample
records are synthetic. The second command intentionally exits with code **1**.

| Example | Expected result |
| --- | --- |
| Clean | One matched sale and payout; charge 100.00 minus refund 20.00 minus total fees 3.50 = bank deposit **USD 76.50**; zero findings |
| Exceptions | Four findings: charge amount mismatch, charge not observed, bank deposit not observed, and payout amount mismatch. Sale expects USD 50.00 but charge is 49.00; payout expects 47.50 but bank shows 47.00 |

Optional installation exposes the same command as `settletrace`:

```sh
python -m pip install .
settletrace --version
python -m unittest discover -s tests -v
```

## Input contract, version 1

Use UTF-8 CSVs with these exact columns (column order can vary). The first record
is the header. UTF-8 BOM is accepted. Blank separator lines are ignored.

```csv
sale_id,payment_ref,currency,gross_minor
transaction_id,payment_ref,payout_id,kind,currency,gross_minor,fee_minor,net_minor
bank_ref,payout_id,currency,amount_minor
```

- **Money is a signed integer in minor units**: `10000` = USD 100.00. No floats,
  exponents, grouped numbers, or whitespace padding. Only USD, EUR, GBP, and INR
  are supported; each has two decimal places in this version. Currencies are
  never converted or added together.
- A sale is one captured payment, not an entire order with split captures.
  `sale_id` and `payment_ref` must each be unique in the sales file.
- Processor `transaction_id` is unique. `kind` is `charge`, `refund`, `dispute`,
  `adjustment`, or `fee`. Charge gross is positive; refund/dispute gross is
  negative; fee-only gross is zero. Fee is positive for a cost and negative for a
  credit. Every entry satisfies **net = gross - fee**.
- `payment_ref` is mandatory for charges, refunds, and disputes. `payout_id` can
  be empty, but this creates a review finding. Do not invent payout attribution.
- Bank `bank_ref` and `payout_id` are each unique. The user supplies the mapping
  between each payout and one bank record. Split or aggregated deposits need a
  separate mapping design and are not supported.
- Header-only sources are allowed so missing observations can be investigated.
  Three empty sources are rejected. Duplicate IDs and malformed inputs are input
  errors, rather than guessed matches.

**Raw Stripe exports are not accepted yet.** Stripe report CSV monetary values
use major units, while its API uses minor units. A raw-export adapter must define
and verify this conversion before use. See the
[Stripe reports guide](https://docs.stripe.com/reports/select-a-report) and
[balance transaction contract](https://docs.stripe.com/api/balance_transactions/object).

## Comparison and output

Sales match charges by `payment_ref`. Processor entries group by explicit
`payout_id`; their net sum is compared with the mapped bank record in the same
currency. A matched payout can coexist with an inconsistent sale: the report
shows both checks separately.

| Exit code | Meaning |
| --- | --- |
| 0 | No exceptions observed in the supplied records |
| 1 | Report produced; at least one review or error finding needs investigation |
| 2 | Invalid input or output problem; no successful report is claimed |

Each finding links to the source identifier and physical CSV line. Multiline
records use their ending line. Amount mismatches include expected, observed,
and signed delta (`observed - expected`) in minor units. Totals summarize the
observed processor/bank currencies, not an inferred complete sales ledger.

`manifest.json` records input basenames, byte sizes and SHA-256 hashes, plus
hashes of the three report files. It is written to a staging file, closed, then
renamed into place last as the completed-bundle marker. This is not a power-loss
durability guarantee. An output write failure can leave a partial new directory
without that marker. Each input is read into immutable bytes once: its fingerprint and parsed
records come from those same bytes. The three files are captured independently,
so use consistent, stable exports; this does not provide a transaction spanning
three files or lock the source files.

HTML escapes supplied text and has no network resources or JavaScript. CSV cells
that could be interpreted as spreadsheet formulas are prefixed with an
apostrophe; JSON preserves the original identifiers. The manifest uses source
basenames rather than absolute source paths. Treat reports as copies of the
supplied business records when sharing them.

## Boundaries and next steps

An absent record means **not observed in the supplied input**, not unpaid cash,
fraud, or a complete accounting conclusion. Inputs have no dates: choose a
consistent observation window and include the relevant payout entries. A refund
can relate to a charge in an earlier period. There is no automatic date matching,
FX, fee estimation, tax handling, refund entitlement check, processor connection,
or bank connection. The CLI loads the datasets into memory; large-file streaming
and performance have not been measured. It is not a replacement for accounting
review.

Stripe already offers [payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation).
The hypothesis here is a smaller offline investigation pack for a **custom
merchant ledger plus processor and bank evidence**. The first release establishes
correctness on synthetic fixtures; it does not prove differentiation or adoption.

Next: a verified raw-export mapping, then a real operator workflow comparison if
a suitable user is reachable. AI could later propose column mappings or explain
existing evidence; monetary reconciliation remains deterministic.

- [Product hypothesis and validation gates](docs/product-brief.md)
- [First-principles exercise, 60–90 minutes](docs/first-principles.md)
- Tests cover validation, duplicates, currencies, fees/refunds, incomplete input,
  deterministic output, HTML/CSV escaping, fingerprints, and output protection.

MIT licensed. No real customer or employer data is included.
