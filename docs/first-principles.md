# First session: explain a payout from the records

Allow 60–90 minutes. This is an exercise to complete, not a record that you have
already completed it. Use the synthetic files in `examples/clean` and
`examples/exceptions`; they contain no real customer data.

## 1. Predict the money movement — 10 minutes

A captured sale and a bank deposit represent different stages of a payment.
Suppose a customer was charged USD 100.00, USD 20.00 was refunded, and the
processor activity contains USD 3.50 of fees in total.

Write the expected deposit before running the program:

```text
gross movement = 10000 + (-2000) = 8000 minor units
fees          = 350 minor units
net movement  = gross - fees = 7650 minor units
bank deposit  = USD 76.50
```

All four supported currencies have two decimal places in this canonical format.
USD 100.00 is stored as `10000`, not a binary floating-point `100.00`. The program
can therefore compare one-cent differences exactly. This does not mean every
currency has two decimal places; unsupported currencies must be rejected rather
than converted by guesswork. [Stripe's currency
documentation](https://docs.stripe.com/currencies) explains why the unit matters.

For every processor entry, the invariant is:

```text
net_minor = gross_minor - fee_minor
```

A charge has positive gross. A refund has negative gross. A standalone fee has
zero gross and records its signed fee in `fee_minor`. A negative fee is a credit.
Never subtract a fee twice. The payout's expected amount is the sum of its
entries' net amounts, compared only within the same currency.

## 2. Run the clean case — 15 minutes

From the repository root with Python 3.11 or later:

```powershell
python -m settletrace reconcile --sales examples/clean/sales.csv --processor examples/clean/processor.csv --bank examples/clean/bank.csv --output output/lesson-clean
$LASTEXITCODE
```

Use a new output directory if you have run it before. The CLI preserves existing
directories. Open `output/lesson-clean/report.html` and inspect `report.json`.

Expect no findings, exit code `0`, processor gross `8000`, fees `350`, processor
net `7650`, and bank amount `7650`. The original USD 100.00 sale matches the
original charge's gross amount; the refund changes the payout, not the historical
captured-sale amount.

Explain aloud why comparing the sale's `10000` directly with the bank's `7650`
would report a misleading difference.

## 3. Trace a real exception — 15 minutes

Before running the exception files, find the sale with gross `5000` and its
observed charge with gross `4900`. Predict:

```text
observed - expected = 4900 - 5000 = -100 minor units
```

```powershell
python -m settletrace reconcile --sales examples/exceptions/sales.csv --processor examples/exceptions/processor.csv --bank examples/exceptions/bank.csv --output output/lesson-exceptions
$LASTEXITCODE
```

Expect exit code `1`: valid inputs produced findings for review. Find
`CHARGE_AMOUNT_MISMATCH`; its expected amount is `5000`, observed amount `4900`,
and difference `-100`. Follow the evidence back to both CSV lines and payment
references. The fixture has four findings. Explain the other three:

- `CHARGE_NOT_OBSERVED`: no charge for `pay_2002` appears in the supplied data.
- `BANK_DEPOSIT_NOT_OBSERVED`: no deposit for `payout_003` appears in the bank file.
- `PAYOUT_AMOUNT_MISMATCH`: `payout_002` has processor net `4750`, bank amount
  `4700`, and difference `-50`.

A successful payout-total comparison does not make that sale discrepancy
disappear. It only shows that the supplied payout entries add up to the supplied
deposit.

## 4. Change one assumption — 15 minutes

Make a separate copy of the clean CSVs for experiments. Predict the result, make
one change, then rerun into a new output directory:

1. Change the clean bank deposit from `7650` to `7651`. Expect
   `PAYOUT_AMOUNT_MISMATCH`, with expected `7650`, observed `7651`, and difference
   `1`.
2. Restore the bank amount. Remove the clean charge from the processor copy,
   leaving the header intact. Expect `CHARGE_NOT_OBSERVED` for the sale. A refund
   whose original charge is no longer present also needs review. Do not conclude
   that the customer was never charged.
3. Restore the processor file. Change one entry's net without changing its gross
   or fee. Expect input-error exit code `2`, because `net = gross - fee` no longer
   holds. No completed report bundle should be created.

## 5. Separate evidence from assertion — 5–20 minutes

Answer these without looking at the implementation:

- Does a matching total prove that every transaction was exported? No: missing
  offsetting entries can leave the same total.
- Does a missing deposit prove lost money? No: the bank file may cover a different
  period, or the payout mapping may be incomplete.
- Does a SHA-256 fingerprint prove the bank supplied a file? No: it identifies
  the file's bytes; it does not establish their origin or truth.
- Can the program safely match a sale to a different currency by amount? No: it
  has no exchange-rate evidence and reports the currency difference.

Inspect the manifest, one finding's source lines, and the corresponding code in
`settletrace/engine.py`. Finish with a short explanation of one invariant, one
reproduced failure, and one limit. That explanation is the learning outcome; a
green report alone is not evidence that the underlying books are complete.
