# Session 3: a matching total is not completeness

Allow 60–90 minutes. Run from the repository root with Python 3.11+. This lesson
is offered for practice; reading it does not mark learning complete.

## Predict, then reproduce (20 minutes)

Start with `net = gross - fee`: `10000 - 2000 - 350 = 7650` minor units.
Predict the payout delta against a 7650 bank record. Inspect
`examples/windowed/mapping.csv`: the operator explicitly associates `wire_demo`
with `po_demo`. An equal amount alone cannot establish that association.

Run the four commands in the README's v0.3 example, using new output directories.
Expect a matched payout, zero findings, and a verified mapping replay. Open
`output/windowed/report.html` and compare the processor estimated arrival and
bank posting windows. Read `report.json`: completeness is still not established,
and no row timestamps were checked.

## Change one cent and keep the evidence (25 minutes)

Copy the prepared bank extract, change 7650 to 7651, and map into a new pack:

```sh
python -c "from pathlib import Path; p=Path('output/bank-one-cent.csv'); p.open('xb').write(Path('examples/windowed/bank-extract.csv').read_bytes().replace(b'7650',b'7651'))"
python -m settletrace map-bank --bank output/bank-one-cent.csv --mapping examples/windowed/mapping.csv --output output/mapped-bank-cent
python -m settletrace reconcile --sales examples/windowed/sales.csv --processor examples/windowed/processor.csv --processor-format stripe-payout-itemized-7 --bank output/mapped-bank-cent/bank.csv --window examples/windowed/window.json --output output/stale-window
```

The last command exits 2 before creating a report: the declaration refers to
different bank bytes. It must not quietly rebind itself to the changed file.
Make a new declaration, preserving the intended dates while binding the new
bank snapshot, then reconcile:

```sh
python -c "import json,hashlib; from pathlib import Path; d=json.loads(Path('examples/windowed/window.json').read_text()); b=Path('output/mapped-bank-cent/bank.csv').read_bytes(); d['sources']['bank'].update(sha256=hashlib.sha256(b).hexdigest(),size_bytes=len(b)); p=Path('output/window-cent.json'); p.open('x',encoding='utf-8').write(json.dumps(d,indent=2))"
python -m settletrace reconcile --sales examples/windowed/sales.csv --processor examples/windowed/processor.csv --processor-format stripe-payout-itemized-7 --bank output/mapped-bank-cent/bank.csv --window output/window-cent.json --output output/windowed-cent
python -m settletrace compare --baseline output/windowed --current output/windowed-cent
```

Expect exit 1 and `PAYOUT_AMOUNT_MISMATCH`: expected 7650, observed 7651, delta
`+1`. The comparison discloses changed bank and window inputs. Find the canonical
bank row in the report and follow `output/mapped-bank-cent/audit.json` back to
the extract and mapping lines. The audit shows what joined; it does not prove
that the chosen payout was correct.

## Inspect the boundary (15–30 minutes)

Read `map_bank` in `settletrace/bank.py`, `assess_window` in
`settletrace/window.py`, and the absent-bank regression in
`tests/test_cli_window.py`. Then run:

```sh
python -m unittest tests.test_bank tests.test_window tests.test_cli_window -v
```

There is no date membership check in these records. Extending the declared bank
end date cannot turn an absent deposit into observed cash. Offsetting omitted
entries could also leave the same net total. Matching arithmetic and complete
coverage are separate claims.

Tradeoff: strict one-to-one mappings refuse splits and aggregates, increasing
manual preparation but preventing a guessed allocation. Declared windows expose
selection context with little input complexity; they leave timestamp membership
and completeness unproven. A future stronger claim requires more source evidence.

Explain this one question in your own words: **Why can a 7650 matching deposit,
correct file hashes, and a later bank end date still fail to prove completeness?**
