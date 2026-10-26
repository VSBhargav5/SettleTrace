"""Offline report formats. JSON preserves evidence; CSV is spreadsheet-safe."""

import csv
import html
import io
import json


def format_minor(amount: int, currency: str) -> str:
    """Display supported two-decimal currencies without floating-point arithmetic."""
    sign = "-" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), 100)
    return f"{currency} {sign}{whole:,}.{fraction:02d}"


def _csv_safe(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def findings_csv(result: dict) -> str:
    stream = io.StringIO(newline="")
    fields = ["code", "severity", "reference", "message", "details", "evidence"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for finding in result["findings"]:
        row = {key: str(finding.get(key, "")) for key in fields}
        row["details"] = json.dumps(finding.get("details", {}), sort_keys=True, ensure_ascii=False)
        row["evidence"] = json.dumps(finding["evidence"], sort_keys=True, ensure_ascii=False)
        writer.writerow({key: _csv_safe(value) for key, value in row.items()})
    return stream.getvalue()


def render_html(result: dict, manifest: dict) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    summary = result["summary"]
    status = "No exceptions observed" if summary["reconciled"] else "Needs review"
    totals = []
    for currency, values in result["totals_by_currency"].items():
        cells = "".join(f"<td>{esc(format_minor(values[key], currency))}</td>" for key in
                        ("gross_minor", "fee_minor", "net_minor", "bank_minor"))
        totals.append(f"<tr><th scope='row'>{esc(currency)}</th>{cells}</tr>")
    cards = []
    for finding in result["findings"]:
        evidence = []
        for item in finding["evidence"]:
            source = item["source"]
            filename = manifest["inputs"][source]["name"]
            evidence.append(f"<li>{esc(source)}: {esc(filename)} · line {esc(item['row'])} · <code>{esc(item['id'])}</code></li>")
        details = finding.get("details", {})
        amounts = ""
        if "expected_minor" in details:
            currency = details["currency"]
            amounts = "<dl class='amounts'>" + "".join(
                f"<div><dt>{label}</dt><dd>{esc(format_minor(details[key], currency))}</dd></div>"
                for label, key in (("Expected", "expected_minor"), ("Observed", "observed_minor"), ("Difference", "delta_minor"))
            ) + "</dl>"
        cards.append(f"""<article class="finding">
          <div class="finding-head"><span class="pill">{esc(finding['severity'])}</span>
          <code>{esc(finding['code'])}</code></div>
          <h3>{esc(finding['reference'])}</h3><p>{esc(finding['message'])}</p>{amounts}
          <details open><summary>Source evidence</summary><ul>{''.join(evidence)}</ul></details>
        </article>""")
    sources = "".join(f"<li><strong>{esc(label)}</strong>: {esc(info['name'])} "
                      f"<code>{esc(info['sha256'])}</code></li>" for label, info in manifest["inputs"].items())
    payout_rows = []
    for payout in result.get("payouts", []):
        nets = payout["processor_net_by_currency"]
        processor = "<br>".join(esc(format_minor(amount, currency)) for currency, amount in nets.items()) or "Not observed"
        bank = payout["bank"]
        observed = esc(format_minor(bank["amount_minor"], bank["currency"])) if bank else "Not observed"
        delta = (esc(format_minor(payout["delta_minor"], bank["currency"]))
                 if payout["delta_minor"] is not None else "Not compared")
        evidence = "".join(f"<li>{esc(item['source'])}: {esc(manifest['inputs'][item['source']]['name'])} "
                           f"· line {esc(item['row'])} · <code>{esc(item['id'])}</code></li>"
                           for item in payout["evidence"])
        payout_rows.append(f"<tr><th scope='row'><code>{esc(payout['payout_id'])}</code>"
                           f"<details><summary>Source evidence</summary><ul>{evidence}</ul></details></th>"
                           f"<td>{esc(payout['status'].replace('_', ' '))}</td><td>{payout['entry_count']}</td>"
                           f"<td>{processor}</td><td>{observed}</td><td>{delta}</td></tr>")
    payouts = ("<h2>Payout ledger</h2><p class='note'>Each explicit payout is checked separately. "
               "Matching totals do not establish complete records.</p><div class='table-wrap'><table>"
               "<thead><tr><th>Payout / evidence</th><th>Status</th><th>Entries</th><th>Processor net</th>"
               "<th>Bank amount</th><th>Bank − net</th></tr></thead><tbody>" + "".join(payout_rows)
               + "</tbody></table></div>") if payout_rows else ""
    empty = "<p class='empty'>The supplied records agree under the documented matching rules.</p>"
    configuration = manifest.get("configuration", {})
    contract = ("<h2>Import contract</h2><p class='note'>Processor format: <code>"
                + esc(configuration["processor_format"]) + "</code> · decimal separator: <code>"
                + esc(configuration["decimal_separator"]) + "</code> · exit policy: <code>"
                + esc(configuration.get("fail_on", "any")) + "</code></p>") if configuration else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>SettleTrace — reconciliation evidence</title>
<style>
:root{{color-scheme:light;--ink:#182d36;--muted:#52646b;--paper:#f5f3ec;--line:#d6ded8;--teal:#096b5c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,sans-serif}}
header{{background:var(--ink);color:white;padding:38px max(24px,calc((100vw - 1080px)/2))}}
.eyebrow{{text-transform:uppercase;letter-spacing:.16em;font-size:12px;font-weight:700;color:#b8dbcc}}
h1{{font-size:clamp(32px,5vw,52px);line-height:1.1;margin:12px 0}}header p{{color:#d2dedb;max-width:700px}}
main{{max-width:1128px;margin:auto;padding:28px 24px 56px}}h2{{font-size:24px;margin-top:32px}}h3{{margin:8px 0;overflow-wrap:anywhere}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px}}
.metric,.finding{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:20px}}
.metric strong{{display:block;font-size:30px;line-height:1.2}}.metric span{{font-size:13px;color:var(--muted)}}
.pill{{display:inline-block;border:1px solid #a8cabe;background:#e4f1e9;color:#164e40;border-radius:40px;padding:3px 12px;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
.finding{{margin:14px 0}}.finding-head{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
.finding-head code{{font-size:12px;color:var(--muted)}}.amounts{{display:flex;gap:30px;flex-wrap:wrap}}
dt{{font-size:12px;color:var(--muted)}}dd{{margin:0;font-weight:700;font-variant-numeric:tabular-nums}}
table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}th,td{{text-align:left;padding:14px;border-bottom:1px solid var(--line)}}
td{{white-space:nowrap;font-variant-numeric:tabular-nums}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px}}
details{{font-size:13px}}code{{overflow-wrap:anywhere}}.sources{{font-size:12px;padding-left:20px}}.sources code{{display:block;color:var(--muted)}}
.note,.empty{{color:var(--muted);font-size:14px}}footer{{border-top:1px solid var(--line);margin-top:28px;padding-top:18px;font-size:13px;color:var(--muted)}}
</style></head><body><header><div class="eyebrow">SettleTrace · offline evidence pack</div>
<h1>Follow the money.<br>Keep the evidence.</h1><p>Compare captured sales, processor activity, and explicitly mapped bank deposits. Every exception points back to the supplied records.</p>
<span class="pill">{status}</span></header><main>
<section class="metrics" aria-label="Reconciliation summary">
<div class="metric"><strong>{summary['sales']}</strong><span>Sales records</span></div>
<div class="metric"><strong>{summary['processor_entries']}</strong><span>Processor entries</span></div>
<div class="metric"><strong>{summary['matched_payouts']}</strong><span>Matching payout totals</span></div>
<div class="metric"><strong>{summary['findings']}</strong><span>Exceptions to review</span></div></section>
<h2>Observed totals by currency</h2><p class="note">Processor net = gross − fees. Currencies are kept separate; no exchange rates are inferred.</p>
<div class="table-wrap"><table><thead><tr><th>Currency</th><th>Processor gross</th><th>Fees / credits</th><th>Processor net</th><th>Bank records</th></tr></thead><tbody>{''.join(totals)}</tbody></table></div>
{payouts}<h2>Exceptions and evidence</h2>{''.join(cards) or empty}
{contract}<h2>Input fingerprints</h2><ul class="sources">{sources}</ul>
<footer>Observations apply only to the supplied files under the selected CSV contract. An absent record can reflect the observation window or incomplete mapping; it is not proof of missing cash. FX, split captures, split deposits, and accounting advice are outside the supported scope.</footer>
</main></body></html>"""
