"""AI Investigation Agent.

Takes flagged anomalies + data-quality issues, explains each in plain
language for an underwriter, forms a hypothesis, scores priority and
recommends next actions.

By default this runs a deterministic, offline reasoning engine so the
prototype works with no API keys or network. If BORDEREAU_LLM=1 and an
OPENAI_API_KEY is present, the narrative step is delegated to an LLM
(see _llm_narrative) -- the surrounding scoring/actions stay deterministic.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request

SEV_WEIGHT = {"high": 60, "medium": 35, "low": 15}
CONF_WEIGHT = 20
IMPACT_WEIGHT = 20

HYPOTHESIS = {
    "duplicate_claim": "Insurance fraud (duplicate / stacked claim)",
    "late_reporting": "Fraud or reserving manipulation (late notification)",
    "loss_ratio": "Weak risk selection / adverse selection driving poor technical result",
    "claim_frequency": "Weak risk selection (adverse frequency)",
    "exposure_outlier": "Under-rated exposure / possible under-pricing",
    "rate_adequacy": "Under-pricing / weak risk selection (rate inadequacy)",
    "claim_severity": "Large/severe claim - potential exaggeration or cat event",
    "slip_mismatch": "Contract-vs-reporting inconsistency (operational or selection risk)",
    "data_quality": "Poor bordereau data discipline (masks true risk selection)",
}

ACTIONS = {
    "duplicate_claim": [
        "Pull claim files for the flagged references and compare loss adjuster reports.",
        "Check whether the same loss was ceded under more than one contract/cedant.",
        "If confirmed, raise SIU referral and recover the duplicate payment.",
    ],
    "late_reporting": [
        "Request the cedant's notification log and explain the reporting lag.",
        "Re-test IBNR/reserves for the affected period.",
        "Add a bordereau timeliness clause/penalty at renewal.",
    ],
    "loss_ratio": [
        "Re-price or reduce the cession for this cedant at renewal.",
        "Request the underlying risk schedule to test for adverse selection.",
        "Review whether high-cession, high-loss risks were systematically ceded.",
    ],
    "claim_frequency": [
        "Analyse frequency by peril and insured segment for this cedant.",
        "Tighten underwriting criteria / attach experience-rating conditions.",
    ],
    "exposure_outlier": [
        "Verify sum insured and premium adequacy for the outlier risk.",
        "Confirm the risk falls within the contract's underwriting guidelines.",
        "Re-check rate-adequacy for the whole line given the outlier.",
    ],
    "rate_adequacy": [
        "Re-rate the risk to the line's technical price.",
        "Review the cedant's pricing/underwriting guidelines for this segment.",
        "Consider a rate-adequacy or minimum-rate condition at renewal.",
    ],
    "claim_severity": [
        "Review the claim file and loss adjuster report for the severe claim.",
        "Check for exaggerated or inflated loss components (fraud).",
        "Confirm whether the loss is a single event or systemic to the segment.",
    ],
    "slip_mismatch": [
        "Reconcile the signed slip terms against the reported bordereau cessions.",
        "Confirm the correct cession percentage with the broker.",
    ],
    "data_quality": [
        "Return the bordereau to the cedant for correction of the flagged fields.",
        "Add the missing fields to the bordereau template / EDI validation.",
        "Hold booking of affected records until reconciled.",
    ],
}


def _impact_factor(impact, max_impact):
    if not impact or impact <= 0 or not max_impact or max_impact <= 0:
        return 0.0
    return IMPACT_WEIGHT * (math.log10(1 + impact) / math.log10(1 + max_impact))


def _priority(anom, max_impact):
    base = SEV_WEIGHT.get(anom.get("severity"), 15)
    conf = CONF_WEIGHT * float(anom.get("confidence", 0.5))
    imp = _impact_factor(anom.get("financial_impact_usd"), max_impact)
    score = max(0, min(100, base + conf + imp))
    label = ("Critical" if score >= 78 else "High" if score >= 58
             else "Medium" if score >= 38 else "Low")
    return round(score, 1), label


def _local_narrative(anom):
    t = anom["type"]
    ev = anom.get("evidence", {})
    if t == "duplicate_claim":
        cross = " under two different cedants/bordereaux" if ev.get("cross_bordereau") else ""
        return (f"The same insured ({ev.get('insured_name')}), loss date ({ev.get('date_of_loss')}) "
                f"and paid amount ({ev.get('paid_amount'):,.0f}) appear {ev.get('occurrences')} times{cross}. "
                f"Identical loss details across separate cessions is a classic double-recovery / fraud pattern; "
                f"estimated duplicated exposure is {anom.get('financial_impact_usd') or 0:,.0f} USD.")
    if t == "late_reporting":
        return (f"Claim {anom['affected_refs'][0]} was reported {ev.get('lag_days')} days after the loss "
                f"(loss {ev.get('date_of_loss')}, reported {ev.get('reported_date')}), against a "
                f"{anom['expected']}-day expectation. Incurred {ev.get('incurred_usd'):,.0f} USD. "
                f"Extended notification delays distort reserves and can conceal late-manufactured claims.")
    if t == "loss_ratio":
        adv = " Average ceded share is high, so the cedant appears to be passing through a disproportionate share of poor risks (adverse selection)." if ev.get("adverse_selection") else ""
        return (f"{anom['affected_refs'][0]} runs a technical loss ratio of {ev.get('loss_ratio'):.2f} "
                f"versus a portfolio median of {ev.get('portfolio_median_lr'):.2f} "
                f"(robust z={ev.get('robust_z')}). On ceded premium of {ev.get('ceded_premium_usd'):,.0f} USD "
                f"this is roughly {anom.get('financial_impact_usd') or 0:,.0f} USD worse than the median book.{adv}")
    if t == "claim_frequency":
        return (f"{anom['affected_refs'][0]} shows {ev.get('claims')} claims over {ev.get('policies')} policies "
                f"({ev.get('claims') and round(ev.get('claims')/ev.get('policies'),2)} per policy) versus a "
                f"median of {anom['expected']}. Elevated frequency points to weak risk selection rather than a single large loss.")
    if t == "exposure_outlier":
        pid = anom["affected_refs"][0].split("/")[-1]
        rate = ev.get("rate_on_line")
        med_rate = ev.get("line_median_rate")
        if ev.get("under_priced"):
            return (f"{ev.get('cedant')}/{pid} carries a sum insured of {ev.get('sum_insured_usd'):,.0f} USD "
                    f"in {ev.get('line_of_business')} ({ev.get('robust_z')} robust-sigma above the line median) but is "
                    f"rated at {rate:.3%} against a line median of {med_rate:.3%}. The exposure is materially "
                    f"under-priced; estimated premium shortfall is {anom.get('financial_impact_usd') or 0:,.0f} USD.")
        return (f"{ev.get('cedant')}/{pid} carries a sum insured of {ev.get('sum_insured_usd'):,.0f} USD in "
                f"{ev.get('line_of_business')}, {ev.get('robust_z')} robust-sigma above the line median of "
                f"{anom['expected']:,.0f} USD. Rate-on-line ({rate:.3%}) is in line with the book, so this is an "
                f"accumulation / limit-adequacy question rather than under-pricing -- confirm it sits within the "
                f"contract's capacity and event limits.")
    if t == "claim_severity":
        return (f"{anom['affected_refs'][0]} ({ev.get('insured_name')}, {ev.get('cause_of_loss')}) incurred "
                f"{ev.get('incurred_usd'):,.0f} USD on {ev.get('date_of_loss')}, {ev.get('robust_z')} robust-sigma "
                f"above the book median of {ev.get('portfolio_median_incurred'):,.0f} USD. Severities this far above "
                f"the norm warrant a fraud/exaggeration review and a check on whether the loss is a single event or "
                f"systemic to the segment.")
    if t == "rate_adequacy":
        pid = anom["affected_refs"][0].split("/")[-1]
        return (f"{ev.get('cedant')}/{pid} ({ev.get('insured_name')}) is rated at {ev.get('rate_on_line'):.3%} in "
                f"{ev.get('line_of_business')} against a line median of {ev.get('line_median_rate'):.3%} -- an estimated "
                f"premium shortfall of {anom.get('financial_impact_usd') or 0:,.0f} USD. Systematic under-rating like this "
                f"is a weak-risk-selection signal even before losses emerge.")
    if t == "slip_mismatch":
        return (f"The signed slip ({ev.get('slip_reference')}) states a cession of {ev.get('slip_cession'):.0%} "
                f"but the bordereau for this cedant averages {ev.get('bordereau_avg_cession'):.0%}. "
                f"Contract terms and reported cessions disagree, which affects both pricing and exposure aggregation.")
    if t == "data_quality":
        return (f"{ev.get('count')} data-quality issues were found across the bordereaux "
                f"({', '.join(ev.get('by_category', []))}). Systematically incomplete or inconsistent data "
                f"is itself a risk-selection signal and degrades every downstream analytic.")
    return anom.get("title", "Anomaly detected.")


def _llm_narrative(anom):
    """Optional LLM-backed explanation. Returns None when unavailable."""
    if os.environ.get("BORDEAU_LLM") != "1":
        return None
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    model = os.environ.get("BORDEAU_LLM_MODEL", "gpt-4o-mini")
    prompt = (
        "You are a reinsurance underwriting analyst. Explain the following flagged "
        "bordereau anomaly in 2-3 sentences for an underwriter, naming the likely cause "
        "(fraud, adverse selection, data error, or pricing) and its financial significance.\n\n"
        + json.dumps(anom, default=str, indent=2)
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def investigate_anomaly(anom, max_impact):
    score, label = _priority(anom, max_impact)
    narrative = _llm_narrative(anom) or _local_narrative(anom)
    hypothesis = HYPOTHESIS.get(anom["type"], "Anomalous pattern")
    if anom["type"] == "exposure_outlier" and not anom.get("evidence", {}).get("under_priced"):
        hypothesis = "Large exposure / accumulation-limit risk"
    return {
        "id": anom["id"],
        "type": anom["type"],
        "title": anom["title"],
        "hypothesis": hypothesis,
        "narrative": narrative,
        "severity": anom["severity"],
        "confidence": anom["confidence"],
        "priority_score": score,
        "priority_label": label,
        "financial_impact_usd": anom.get("financial_impact_usd"),
        "affected_refs": anom["affected_refs"],
        "recommended_actions": ACTIONS.get(anom["type"], ["Review the flagged records."]),
        "evidence": anom.get("evidence", {}),
    }


def investigate_data_quality(dq_issues, dq_summary, max_impact):
    if not dq_issues:
        return None
    anom = {
        "id": "DQ-AGG",
        "type": "data_quality",
        "title": f"Bordereau data quality: {dq_summary['total']} issues",
        "severity": "high" if dq_summary["by_severity"].get("high") else "medium",
        "confidence": 0.95,
        "expected": 0,
        "actual": dq_summary["total"],
        "financial_impact_usd": None,
        "affected_refs": sorted({i["ref"] for i in dq_issues})[:10],
        "evidence": {"count": dq_summary["total"],
                     "by_category": list(dq_summary["by_category"].keys()),
                     "by_severity": dq_summary["by_severity"]},
    }
    score, label = _priority(anom, max_impact)
    return {
        "id": anom["id"],
        "type": "data_quality",
        "title": anom["title"],
        "hypothesis": HYPOTHESIS["data_quality"],
        "narrative": _local_narrative(anom),
        "severity": anom["severity"],
        "confidence": anom["confidence"],
        "priority_score": score,
        "priority_label": label,
        "financial_impact_usd": None,
        "affected_refs": anom["affected_refs"],
        "recommended_actions": ACTIONS["data_quality"],
        "evidence": anom["evidence"],
    }


def investigate(anomalies, dq_issues, dq_summary):
    max_impact = max([a.get("financial_impact_usd") or 0 for a in anomalies] + [1])
    findings = [investigate_anomaly(a, max_impact) for a in anomalies]
    dq_finding = investigate_data_quality(dq_issues, dq_summary, max_impact)
    if dq_finding:
        findings.append(dq_finding)
    findings.sort(key=lambda f: f["priority_score"], reverse=True)
    for i, f in enumerate(findings):
        f["rank"] = i + 1
    return findings
