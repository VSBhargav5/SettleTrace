# Observation declarations and explicit bank mapping

v0.3 records why a supplied set of files was chosen. It does not establish that
the records are complete, that their dates fall within an interval, or that an
operator's payout attribution is correct. No bank-provider adapter is claimed.

## Bank mapping contract

Prepare UTF-8 CSVs (BOM accepted), with exact headers in any order:

```csv
bank_ref,currency,amount_minor
wire_demo,USD,7650
```

```csv
bank_ref,payout_id
wire_demo,po_demo
```

The first file is a prepared extract with integer minor units, not an arbitrary
bank export. Supported currencies and 128-digit amount limits are the same as
canonical reconciliation. Signed negative and zero amounts are preserved. Each
bank reference and payout is unique. Every observed bank row must be mapped
exactly once; unknown mapping references also fail. Equal amounts or dates never
select a payout. One bank row per payout is the supported boundary; splits,
aggregates, bank fees, currency conversion, and guessed attribution need a
different contract. The mapping must be chosen using external business evidence.

`map-bank` captures bounded immutable bytes for each input, joins them, and emits
canonical `bank.csv` plus a completion-marked `audit.json`. The audit includes
input sizes/hashes, the canonical output hash, bank and mapping physical ending
lines, and actual canonical ending lines. Multiline quoted identifiers are
preserved. This machine CSV is not spreadsheet-neutralized.

`verify-bank-map --bundle DIR --bank EXTRACT --mapping MAP` checks fixed artifact
names, both supplied input fingerprints, exact regenerated canonical bytes, and
the replayed row audit. It opens no paths supplied by the audit. It verifies the
stated join, not the truth of the operator's attribution. Renaming a source file
without changing its bytes is allowed. Stable copies are required; there is no
concurrent-writer lock, authenticity guarantee, or power-loss durability claim.

The reconciliation report refers to the canonical bank CSV's rows. Retain its
mapping pack and original sources to follow those rows back to both originals;
the report does not automatically ingest the mapping audit.

## UTC declaration contract

`reconcile` and `validate` accept optional `--window PATH`. See the complete
[synthetic declaration](../examples/windowed/window.json). Its exact root fields
are `schema_version` (`"1"`), `account_scope` (a nonblank unpadded UTF-8 operator
label), and `sources` (exactly sales, processor, bank). Each source has exactly:

| Field | Meaning |
| --- | --- |
| `start_utc` | Inclusive declared beginning, `YYYY-MM-DDTHH:MM:SSZ` |
| `end_utc` | Exclusive declared end, strictly after beginning |
| `time_basis` | Sales: `captured_at_utc`; processor: `automatic_payout_effective_at_utc`; bank: `bank_posted_at_utc` |
| `sha256` | Lowercase SHA-256 of the actual input bytes |
| `size_bytes` | Nonnegative integer byte count, not a boolean |

Dates must be valid UTC whole seconds. Offsets, naive dates, fractional seconds,
duplicate JSON keys, unsupported fields/versions, non-integer JSON numbers, and
declarations over 1 MiB are rejected. Source capture also retains the existing
per-input byte limit. BOMs are accepted. These declarations currently describe
the Stripe automatic-payout workflow, including canonical data prepared from it;
they are not a general time model for arbitrary providers.

The source hashes must match all three captured input snapshots before a report
is written. For a mapped bank input, hash the generated canonical `bank.csv`, not
the unmapped extract. To inspect a fingerprint without changing a file:

```sh
python -c "import hashlib; from pathlib import Path; b=Path('output/mapped-bank/bank.csv').read_bytes(); print(len(b), hashlib.sha256(b).hexdigest())"
```

The report includes the declaration, `source_bytes_match: true`,
`row_timestamps_checked: false`, `completeness: "not_established"`, and whether
intervals have identical boundaries. Identical boundaries describe dates, not
equivalent economic events or complete coverage. `summary.reconciled` retains
its earlier meaning: no exceptions were observed in the supplied records.
No finding is suppressed by the declaration. No record is filtered by date.
The operator label does not verify account ownership or scope.

The window file has its own manifest fingerprint and is included in source
verification. `verify --bundle DIR` checks bundle consistency; supplying all
three sources **and** `--window` also hashes the supplied original declaration
and compares its parsed content with the report. Hashes do not authenticate a
bundle whose manifest and outputs have all been replaced. Old three-input
bundles remain supported. `compare` reports a window added, removed, or changed,
even when financial findings are identical; absence still does not prove resolution.

## Provider evidence checked 26 October 2026

- Stripe's [Reports API](https://docs.stripe.com/reports/api) uses inclusive start
  and exclusive end intervals, expressed as Unix seconds; report timezone
  defaults to UTC. SettleTrace's declaration requires explicit UTC.
- [Payout reconciliation](https://docs.stripe.com/reports/payout-reconciliation)
  selects the date range using estimated payout arrival, which can differ from
  actual bank posting. Dashboard reports cover whole days; API ranges can cover
  partial days. A bank's later posting window is therefore not rejected here.
- The [versioned itemized schema](https://docs.stripe.com/reports/report-types/payout-reconciliation)
  distinguishes `automatic_payout_effective_at_utc`, `created_utc`,
  `charge_created_utc`, and `available_on_utc`. These are not interchangeable.
  A prior-period charge can contribute to a later payout. Existing SettleTrace
  records do not model these timestamps, so row membership remains unchecked.

The next evidence gate is a permitted real-account export and operator review.
Before any completeness claim, the project would also need verified account
scope, event timestamps, boundary membership, available-report horizons, and
evidence of omitted or late records. No demand, revenue, or time savings is established.
