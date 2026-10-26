"""Deterministic reconciliation of observed sales, processor entries, and deposits."""

from collections import defaultdict

from .models import Deposit, Entry, InputError, Sale


def _evidence(source: str, record: Sale | Entry | Deposit) -> dict:
    if isinstance(record, Sale):
        identifier = record.sale_id
    elif isinstance(record, Entry):
        identifier = record.transaction_id
    else:
        identifier = record.bank_ref
    return {"source": source, "row": record.row, "id": identifier}


def _evidence_key(item: dict) -> tuple:
    return item["source"], item["row"], item["id"]


def _unique(records: list, record_type: type, attribute: str, source: str) -> dict:
    indexed = {}
    for record in records:
        if not isinstance(record, record_type):
            raise InputError(f"{source} must contain {record_type.__name__} records")
        key = getattr(record, attribute)
        if key in indexed:
            raise InputError(f"duplicate {source} {attribute}: {key!r}")
        indexed[key] = record
    return indexed


def reconcile(sales: list[Sale], entries: list[Entry], deposits: list[Deposit]) -> dict:
    """Compare explicit references without inferring missing history or exchange rates.

    Duplicate identifiers are input errors. Findings concern only the supplied
    observation window: an absent record is a review item, not proof of lost cash.
    """
    if not sales and not entries and not deposits:
        raise InputError("no observed records: supply at least one sale, processor entry, or bank deposit")
    _unique(sales, Sale, "sale_id", "sales")
    sales_by_ref = _unique(sales, Sale, "payment_ref", "sales")
    _unique(entries, Entry, "transaction_id", "processor")
    _unique(deposits, Deposit, "bank_ref", "bank")
    deposits_by_payout = _unique(deposits, Deposit, "payout_id", "bank")
    charges_by_ref = defaultdict(list)
    entries_by_payout = defaultdict(list)
    findings = []
    matched_sales = 0
    matched_payouts = 0
    payouts = []

    def finding(code: str, severity: str, reference: str, message: str, evidence: list[dict],
                details: dict | None = None) -> None:
        item = {"code": code, "severity": severity, "reference": reference,
                "message": message, "evidence": sorted(evidence, key=_evidence_key)}
        if details is not None:
            item["details"] = details
        findings.append(item)

    for entry in entries:
        if entry.kind == "charge":
            charges_by_ref[entry.payment_ref].append(entry)
        if entry.payout_id:
            entries_by_payout[entry.payout_id].append(entry)
        else:
            finding("PAYOUT_NOT_ATTRIBUTED", "review", entry.transaction_id,
                    "Processor entry has no payout attribution in the supplied data.",
                    [_evidence("processor", entry)])

    for payment_ref in sorted(set(sales_by_ref) | set(charges_by_ref)):
        sale = sales_by_ref.get(payment_ref)
        charges = charges_by_ref.get(payment_ref, [])
        charge_evidence = [_evidence("processor", charge) for charge in charges]
        if sale is None:
            finding("SALE_NOT_OBSERVED", "review", payment_ref,
                    "A charge was observed without a sale in the supplied data.", charge_evidence)
        if not charges:
            finding("CHARGE_NOT_OBSERVED", "review", payment_ref,
                    "No charge was observed for this sale in the supplied data.", [_evidence("sales", sale)])
        elif len(charges) > 1:
            evidence = charge_evidence + ([_evidence("sales", sale)] if sale is not None else [])
            finding("MULTIPLE_CHARGES", "error", payment_ref,
                    "Multiple charges share this payment reference; no single sale match was selected.", evidence)
        elif sale is not None:
            charge = charges[0]
            evidence = [_evidence("sales", sale), _evidence("processor", charge)]
            if sale.currency != charge.currency:
                finding("CURRENCY_MISMATCH", "error", payment_ref,
                        "Sale and charge currencies differ; their amounts were not compared.", evidence)
            elif sale.gross_minor != charge.gross_minor:
                finding("CHARGE_AMOUNT_MISMATCH", "error", payment_ref,
                        "Sale gross amount differs from the observed charge gross amount.", evidence,
                        {"currency": sale.currency, "expected_minor": sale.gross_minor,
                         "observed_minor": charge.gross_minor,
                         "delta_minor": charge.gross_minor - sale.gross_minor})
            else:
                matched_sales += 1

    for entry in entries:
        if entry.kind not in {"refund", "dispute"}:
            continue
        charges = charges_by_ref.get(entry.payment_ref, [])
        if not charges:
            finding("ORIGINAL_CHARGE_NOT_OBSERVED", "review", entry.payment_ref,
                    "The original charge for this refund or dispute was not observed; it may be from a prior period.",
                    [_evidence("processor", entry)])
        elif entry.currency not in {charge.currency for charge in charges}:
            finding("CURRENCY_MISMATCH", "error", entry.payment_ref,
                    "Refund or dispute currency differs from the observed original charge currency.",
                    [_evidence("processor", entry)] + [_evidence("processor", charge) for charge in charges])

    for payout_id in sorted(set(entries_by_payout) | set(deposits_by_payout)):
        payout_entries = entries_by_payout.get(payout_id, [])
        deposit = deposits_by_payout.get(payout_id)
        evidence = [_evidence("processor", entry) for entry in payout_entries]
        if deposit is not None:
            evidence.append(_evidence("bank", deposit))
        currencies = {entry.currency for entry in payout_entries}
        currency_error = len(currencies) > 1 or (
            bool(currencies) and deposit is not None and deposit.currency not in currencies)
        net_by_currency = {currency: sum(entry.net_minor for entry in payout_entries if entry.currency == currency)
                           for currency in sorted(currencies)}
        delta = (deposit.amount_minor - net_by_currency[deposit.currency]
                 if deposit is not None and len(currencies) == 1 and not currency_error else None)
        if len(currencies) > 1:
            status = "mixed_currency"
        elif not payout_entries:
            status = "processor_not_observed"
        elif deposit is None:
            status = "bank_not_observed"
        elif currency_error:
            status = "currency_mismatch"
        else:
            status = "matched" if delta == 0 else "amount_mismatch"
        payouts.append({"payout_id": payout_id, "processor_net_by_currency": net_by_currency,
                        "bank": ({"currency": deposit.currency, "amount_minor": deposit.amount_minor,
                                  "evidence": _evidence("bank", deposit)} if deposit is not None else None),
                        "entry_count": len(payout_entries), "status": status, "delta_minor": delta,
                        "evidence": sorted(evidence, key=_evidence_key)})
        if currency_error:
            finding("PAYOUT_CURRENCY_MISMATCH", "error", payout_id,
                    "Payout records contain different currencies; payout amounts were not combined or compared.", evidence)
        if not payout_entries:
            finding("PROCESSOR_PAYOUT_NOT_OBSERVED", "review", payout_id,
                    "No processor payout entries were observed for this bank deposit.", evidence)
        elif deposit is None:
            finding("BANK_DEPOSIT_NOT_OBSERVED", "review", payout_id,
                    "No bank deposit was observed for this processor payout in the supplied data.", evidence)
        elif not currency_error:
            expected_net = sum(entry.net_minor for entry in payout_entries)
            if deposit.amount_minor != expected_net:
                finding("PAYOUT_AMOUNT_MISMATCH", "error", payout_id,
                        "Bank deposit amount differs from the sum of processor net amounts.", evidence,
                        {"currency": deposit.currency, "expected_minor": expected_net,
                         "observed_minor": deposit.amount_minor,
                         "delta_minor": deposit.amount_minor - expected_net})
            else:
                matched_payouts += 1

    totals = {}
    for currency in sorted({entry.currency for entry in entries} | {deposit.currency for deposit in deposits}):
        currency_entries = [entry for entry in entries if entry.currency == currency]
        totals[currency] = {
            "gross_minor": sum(entry.gross_minor for entry in currency_entries),
            "fee_minor": sum(entry.fee_minor for entry in currency_entries),
            "net_minor": sum(entry.net_minor for entry in currency_entries),
            "bank_minor": sum(deposit.amount_minor for deposit in deposits if deposit.currency == currency),
        }
    findings.sort(key=lambda item: (item["code"], item["reference"],
                                   tuple(_evidence_key(e) for e in item["evidence"])))
    return {
        "schema_version": "1",
        "summary": {"sales": len(sales), "processor_entries": len(entries), "bank_deposits": len(deposits),
                    "findings": len(findings), "matched_sales": matched_sales, "matched_payouts": matched_payouts,
                    "reconciled": not findings},
        "totals_by_currency": totals,
        "payouts": payouts,
        "findings": findings,
    }
