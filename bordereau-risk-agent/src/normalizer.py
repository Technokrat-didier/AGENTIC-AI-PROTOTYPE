"""Normalization layer.

Maps heterogeneous cedant bordereaux and parsed slips into one canonical
model: dates parsed to ISO, money converted to a base currency (USD),
shared field names. Raw values are preserved so the data-quality layer can
still see what the source actually contained.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Optional

from .util import parse_date, parse_number, to_base_currency


@dataclass
class RiskRecord:
    cedant: str
    policy_id: str
    insured_name: Optional[str]
    line_of_business: Optional[str]
    peril: Optional[str]
    inception_date: Optional[object]
    expiry_date: Optional[object]
    sum_insured: Optional[float]
    currency: Optional[str]
    gross_premium: Optional[float]
    ceded_share: Optional[float]
    sum_insured_usd: Optional[float] = None
    gross_premium_usd: Optional[float] = None
    currency_known: bool = True
    raw: dict = field(default_factory=dict)
    source: str = "bordereau_policies.csv"


@dataclass
class ClaimRecord:
    cedant: str
    claim_id: str
    policy_id: Optional[str]
    insured_name: Optional[str]
    date_of_loss: Optional[object]
    reported_date: Optional[object]
    paid_amount: Optional[float]
    outstanding_amount: Optional[float]
    currency: Optional[str]
    cause_of_loss: Optional[str]
    incurred: Optional[float] = None
    incurred_usd: Optional[float] = None
    currency_known: bool = True
    raw: dict = field(default_factory=dict)
    source: str = "bordereau_claims.csv"


def load_policies(path: str) -> list[RiskRecord]:
    out: list[RiskRecord] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            si = parse_number(row.get("sum_insured"))
            prem = parse_number(row.get("gross_premium"))
            cur = (row.get("currency") or "").strip() or None
            si_usd, _, si_known = to_base_currency(si, cur)
            prem_usd, _, _ = to_base_currency(prem, cur)
            out.append(
                RiskRecord(
                    cedant=(row.get("cedant") or "").strip(),
                    policy_id=(row.get("policy_id") or "").strip(),
                    insured_name=(row.get("insured_name") or "").strip() or None,
                    line_of_business=(row.get("line_of_business") or "").strip() or None,
                    peril=(row.get("peril") or "").strip() or None,
                    inception_date=parse_date(row.get("inception_date")),
                    expiry_date=parse_date(row.get("expiry_date")),
                    sum_insured=si,
                    currency=cur,
                    gross_premium=prem,
                    ceded_share=parse_number(row.get("ceded_share")),
                    sum_insured_usd=si_usd,
                    gross_premium_usd=prem_usd,
                    currency_known=si_known,
                    raw=dict(row),
                )
            )
    return out


def load_claims(path: str) -> list[ClaimRecord]:
    out: list[ClaimRecord] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            paid = parse_number(row.get("paid_amount"))
            outs = parse_number(row.get("outstanding_amount")) or 0.0
            cur = (row.get("currency") or "").strip() or None
            incurred = None if paid is None else paid + outs
            incurred_usd, _, known = to_base_currency(incurred, cur)
            out.append(
                ClaimRecord(
                    cedant=(row.get("cedant") or "").strip(),
                    claim_id=(row.get("claim_id") or "").strip(),
                    policy_id=(row.get("policy_id") or "").strip() or None,
                    insured_name=(row.get("insured_name") or "").strip() or None,
                    date_of_loss=parse_date(row.get("date_of_loss")),
                    reported_date=parse_date(row.get("reported_date")),
                    paid_amount=paid,
                    outstanding_amount=outs,
                    currency=cur,
                    cause_of_loss=(row.get("cause_of_loss") or "").strip() or None,
                    incurred=incurred,
                    incurred_usd=incurred_usd,
                    currency_known=known,
                    raw=dict(row),
                )
            )
    return out


def slip_to_risk_record(parsed: dict) -> RiskRecord:
    """Fold a parsed slip into the canonical risk model (single contract row)."""
    cur = parsed.get("currency")
    si = parsed.get("layer_limit")
    prem = parsed.get("reinsurance_premium")
    si_usd, _, si_known = to_base_currency(si, cur)
    prem_usd, _, _ = to_base_currency(prem, cur)
    return RiskRecord(
        cedant=parsed.get("reinsured") or "UNKNOWN",
        policy_id=parsed.get("slip_reference") or parsed.get("cedant_reference") or "SLIP",
        insured_name=parsed.get("reinsured"),
        line_of_business=parsed.get("line_of_business"),
        peril=parsed.get("basis"),
        inception_date=parsed.get("inception_date"),
        expiry_date=parsed.get("expiry_date"),
        sum_insured=si,
        currency=cur,
        gross_premium=prem,
        ceded_share=parsed.get("cession_pct"),
        sum_insured_usd=si_usd,
        gross_premium_usd=prem_usd,
        currency_known=si_known,
        raw=parsed.get("_extraction", {}).get("raw_labels", {}),
        source="slip_reinsurance.txt",
    )
