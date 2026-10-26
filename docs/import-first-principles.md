# Session 2: trust an import by checking its contract

Allow 60–90 minutes. These are practice steps, not a claim that you have already
learned the code. The broader operator commands can be studied in later sessions.

## Predict exact decimal conversion — 15 minutes

A financial report says `19.99` major units. For the supported two-decimal
currencies, split the text into whole and fractional digits:

```text
whole = 19
fraction = 99
minor units = 19 × 100 + 99 = 1999
```

Now predict `-0.01`, `10.1`, and `1.001`. The first two produce `-1` and `1010`.
The third must fail: rounding could hide a discrepancy. Read `settletrace/money.py`
and run `python -m unittest tests.test_money -v`. Explain why parsing a float
first changes the contract even if many examples happen to work.

## Identify a payment across two kinds of records — 15 minutes

Open `examples/stripe/processor.csv`. The original charge and its refund have
different balance transaction IDs and source IDs. Both have `charge_id=ch_demo`.
That original charge ID joins to the merchant's sale.

Predict the result if a mapper uses the refund's `source_id=re_demo` instead:
the refund loses its observed original-charge connection. A seemingly plausible
identifier is not necessarily the right identity for a join.

Run:

```sh
python -m settletrace validate --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv --processor-format stripe-payout-itemized-7
python -m settletrace reconcile --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv --processor-format stripe-payout-itemized-7 --output output/lesson-import
```

Choose a new output directory on repeated runs. Expect a USD 76.50 deposit:
`10000 - 350 - 2000 = 7650`. Open the report and inspect the payout ledger. Follow
its evidence to both original processor lines and the bank line.

## Reject an interpretation instead of silently losing data — 15 minutes

Copy the input files into an experiment directory. Change one reporting category
to `partial_capture_reversal`. Predict an input error, not a skipped row. Removing
that record would change what the report can claim about the payout.

Restore the category, then change the refund's net without changing gross or fee.
Predict another input error because `net = gross - fee` no longer holds. The
output directory must not contain a successful report from either invalid run.

Try the comma-decimal fixture with `--decimal-separator ,`. The correct result
is identical; the interpretation is explicit rather than detected by guessing.

## Bind the report to the bytes it used — 15 minutes

```sh
python -m settletrace verify --bundle output/lesson-import --sales examples/stripe/sales.csv --processor examples/stripe/processor.csv --bank examples/stripe/bank.csv
```

The command checks output bytes against the recorded hashes, and the supplied
input bytes against their recorded fingerprints. Alter a copy of `report.html`,
then verify the copied bundle. Expect failure. Alter a copy of an input, then
provide that changed file to verification. Expect failure even if the record
counts are unchanged.

Explain the boundary: a fingerprint binds content; it does not prove a file came
from Stripe, that all transactions were exported, or that the bank mapping is
correct. A valid bundle can still contain exceptions requiring investigation.

## Explain one tradeoff — optional 15–30 minutes

Read the rejection rules in [the import contract](stripe-import.md). Why is
rejecting an unsupported category safer than mapping every unfamiliar event to
an adjustment? What additional evidence would be needed to support it correctly?

End with your own explanation of exact units, payment identity, and one thing a
green report cannot establish. Keep user demand and time-saving claims separate
from this synthetic correctness demonstration.
