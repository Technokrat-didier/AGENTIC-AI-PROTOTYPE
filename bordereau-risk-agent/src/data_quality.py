"""Data quality checks.

Run BEFORE anomaly detection. Gaps and inconsistencies are not silently
dropped: they are surfaced as findings because weak risk selection often
shows up as systematically incomplete bordereau data.
"""

from __future__ import annotations

from collections import Counter

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def _issue(category, severity, ref, field, message, fix=None):
    return {
        "category": category,
        "severity": severity,
        "ref": ref,
        "field": field,
        "message": message,
        "suggested_fix": fix,
    }


def _dominant_currency(records):
    counts = Counter(r.currency for r in records if r.currency)
    return counts.most_common(1)[0][0] if counts else None


def check_risks(risks):
    issues = []
    dom = _dominant_currency(risks)
    seen_ids = {}
    required = {
        "insured_name": "Insured name",
        "line_of_business": "Line of business",
        "sum_insured": "Sum insured",
        "gross_premium": "Gross premium",
        "inception_date": "Inception date",
        "expiry_date": "Expiry date",
    }
    for r in risks:
        ref = f"{r.cedant}/{r.policy_id}"
        if r.policy_id in seen_ids:
            issues.append(
                _issue("duplicate", "high", ref, "policy_id",
                       f"Duplicate policy_id '{r.policy_id}' also in {seen_ids[r.policy_id]} -- possible double cession.",
                       "Reconcile with cedant and de-duplicate before booking.")
            )
        else:
            seen_ids[r.policy_id] = ref

        for field_name, label in required.items():
            if getattr(r, field_name, None) in (None, ""):
                issues.append(
                    _issue("missing", "medium", ref, field_name,
                           f"{label} is missing.",
                           f"Request {label.lower()} from {r.cedant}.")
                )

        if r.inception_date and r.expiry_date and r.expiry_date < r.inception_date:
            issues.append(
                _issue("date_logic", "high", ref, "expiry_date",
                       f"Expiry {r.expiry_date} precedes inception {r.inception_date}.",
                       "Confirm period dates with the cedant; exposure may be mis-stated.")
            )

        if r.sum_insured is not None and r.sum_insured < 0:
            issues.append(_issue("range", "high", ref, "sum_insured",
                                 "Negative sum insured.", "Correct sign / re-key value."))
        if r.gross_premium is not None and r.gross_premium < 0:
            issues.append(_issue("range", "high", ref, "gross_premium",
                                 "Negative gross premium.", "Correct sign / re-key value."))

        if r.ceded_share is not None and not (0 <= r.ceded_share <= 1):
            issues.append(_issue("range", "medium", ref, "ceded_share",
                                 f"Ceded share {r.ceded_share} outside 0-1.",
                                 "Check whether value is a percentage or a fraction."))

        if r.currency and dom and r.currency != dom:
            issues.append(
                _issue("currency", "medium", ref, "currency",
                       f"Currency '{r.currency}' differs from bordereau base '{dom}'.",
                       "Confirm reporting currency; FX normalization applied for analytics.")
            )
        if r.currency is None:
            issues.append(_issue("currency", "low", ref, "currency",
                                 "No currency stated; assumed base currency.", "Add explicit currency."))
    return issues


def check_claims(claims, risk_ids):
    issues = []
    dom = _dominant_currency(claims)
    seen_ids = {}
    for c in claims:
        ref = f"{c.cedant}/{c.claim_id}"
        if c.claim_id in seen_ids:
            issues.append(_issue("duplicate", "high", ref, "claim_id",
                                 f"Duplicate claim_id '{c.claim_id}'.", "De-duplicate claim records."))
        else:
            seen_ids[c.claim_id] = ref

        for field_name, label in {
            "date_of_loss": "Date of loss",
            "reported_date": "Reported date",
            "paid_amount": "Paid amount",
            "policy_id": "Policy reference",
        }.items():
            if getattr(c, field_name, None) in (None, ""):
                issues.append(_issue("missing", "medium", ref, field_name,
                                     f"{label} is missing.", f"Request {label.lower()} from {c.cedant}."))

        if c.date_of_loss and c.reported_date and c.reported_date < c.date_of_loss:
            issues.append(_issue("date_logic", "high", ref, "reported_date",
                                 f"Reported date {c.reported_date} precedes loss date {c.date_of_loss}.",
                                 "Verify dates; possible keying error or back-dated report."))

        if c.policy_id and risk_ids and c.policy_id not in risk_ids:
            issues.append(_issue("referential", "medium", ref, "policy_id",
                                 f"Claim references unknown policy '{c.policy_id}'.",
                                 "Match claim to a ceded policy; unmatched claims may be out of scope."))

        if c.paid_amount is not None and c.paid_amount < 0:
            issues.append(_issue("range", "high", ref, "paid_amount",
                                 "Negative paid amount.", "Confirm sign / re-key."))

        if c.currency and dom and c.currency != dom:
            issues.append(_issue("currency", "low", ref, "currency",
                                 f"Currency '{c.currency}' differs from base '{dom}'.",
                                 "Confirm currency; FX normalization applied."))
    return issues


def check_slip(parsed):
    issues = []
    ex = parsed.get("_extraction", {})
    missing = ex.get("missing", [])
    conf = ex.get("confidence", 0)
    ref = parsed.get("slip_reference") or "slip"
    if conf < 1.0:
        issues.append(_issue("extraction", "medium", ref, ",".join(missing),
                             f"Slip extraction incomplete (confidence {conf:.0%}); missing: {', '.join(missing)}.",
                             "Manual review of un-extracted slip fields before binding."))
    if parsed.get("inception_date") and parsed.get("expiry_date") and parsed["expiry_date"] < parsed["inception_date"]:
        issues.append(_issue("date_logic", "high", ref, "period",
                             "Slip period end precedes start.", "Confirm contract period."))
    return issues


def summarize(issues):
    by_sev = Counter(i["severity"] for i in issues)
    by_cat = Counter(i["category"] for i in issues)
    score = sum(SEVERITY_WEIGHT.get(i["severity"], 1) for i in issues)
    return {
        "total": len(issues),
        "by_severity": dict(by_sev),
        "by_category": dict(by_cat),
        "quality_score": score,
    }
