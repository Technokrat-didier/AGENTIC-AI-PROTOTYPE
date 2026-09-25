"""Anomaly detection.

Statistical / ML-style detectors that compare each unit against a portfolio
baseline ("unusual" only means something relative to an expectation). Each
detector emits zero or more anomalies carrying evidence so the investigation
agent can reason over them.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def _robust_stats(sample):
    """Precompute median/MAD once per group so each record scores in O(1).
    Calling statistics.median per record made detection O(n^2 log n)."""
    if len(sample) < 3:
        return {"ok": False, "med": 0.0, "mad": 0.0}
    med = statistics.median(sample)
    mad = statistics.median([abs(v - med) for v in sample])
    return {"ok": True, "med": med, "mad": mad}


def _z_from_stats(x, st):
    """Median/MAD based robust z-score; robust to the outliers we are hunting."""
    if not st["ok"] or st["mad"] == 0:
        return 0.0
    return 0.6745 * (x - st["med"]) / st["mad"]


def _sev_from_z(z, hi=3.5, med=2.5):
    if z >= hi:
        return "high", min(0.98, 0.6 + (z - hi) * 0.08 + 0.2)
    if z >= med:
        return "medium", min(0.9, 0.5 + (z - med) * 0.1)
    return "low", 0.4


def _anom(atype, title, severity, confidence, metric, expected, actual,
          impact, refs, evidence):
    return {
        "type": atype,
        "title": title,
        "severity": severity,
        "confidence": round(confidence, 2),
        "metric": metric,
        "expected": expected,
        "actual": actual,
        "financial_impact_usd": round(impact, 0) if impact is not None else None,
        "affected_refs": refs,
        "evidence": evidence,
    }


def detect_loss_ratio(risks, claims):
    """Technical loss ratio per cedant vs portfolio median -> profitability / adverse selection."""
    prem = defaultdict(float)
    cession = defaultdict(list)
    for r in risks:
        if r.gross_premium_usd:
            prem[r.cedant] += r.gross_premium_usd * (r.ceded_share or 0)
        if r.ceded_share is not None:
            cession[r.cedant].append(r.ceded_share)
    incurred = defaultdict(float)
    for c in claims:
        if c.incurred_usd:
            incurred[c.cedant] += c.incurred_usd

    cedants = [k for k in prem if prem[k] > 0]
    ratios = {k: incurred.get(k, 0.0) / prem[k] for k in cedants}
    if len(ratios) < 3:
        return [], ratios
    sample = list(ratios.values())
    med = statistics.median(sample)
    st = _robust_stats(sample)

    out = []
    for cedant, lr in ratios.items():
        z = _z_from_stats(lr, st)
        if z >= 2.0:
            sev, conf = _sev_from_z(z, hi=3.0, med=2.0)
            avg_cession = statistics.mean(cession[cedant]) if cession[cedant] else None
            impact = incurred.get(cedant, 0.0) - med * prem[cedant]
            ev = {
                "loss_ratio": round(lr, 3),
                "portfolio_median_lr": round(med, 3),
                "robust_z": round(z, 2),
                "ceded_premium_usd": round(prem[cedant], 0),
                "incurred_usd": round(incurred.get(cedant, 0.0), 0),
                "avg_ceded_share": round(avg_cession, 3) if avg_cession else None,
            }
            title = f"Elevated technical loss ratio - {cedant}"
            if avg_cession and avg_cession >= 0.55:
                title += " (adverse selection suspect)"
                ev["adverse_selection"] = True
                sev = "high" if sev != "high" else sev
            out.append(_anom("loss_ratio", title, sev, conf, "technical_loss_ratio",
                             round(med, 3), round(lr, 3), impact, [cedant], ev))
    return out, ratios


def detect_sum_insured_outliers(risks):
    """Large exposure relative to the line. Only escalates to high severity when
    the risk is also under-rated (rate-on-line below the line median), because a
    big sum insured that is priced in line is an accumulation/limit question,
    not a loss."""
    out = []
    by_line = defaultdict(list)
    for r in risks:
        if r.sum_insured_usd:
            by_line[r.line_of_business or "Unknown"].append(r)
    for line, recs in by_line.items():
        vals = [r.sum_insured_usd for r in recs]
        if len(vals) < 3:
            continue
        med_si = statistics.median(vals)
        st_si = _robust_stats(vals)
        rates = [r.gross_premium_usd / r.sum_insured_usd
                 for r in recs if r.gross_premium_usd and r.sum_insured_usd]
        med_rate = statistics.median(rates) if rates else None
        for r in recs:
            z = _z_from_stats(r.sum_insured_usd, st_si)
            if z < 3.0:
                continue
            rate = (r.gross_premium_usd / r.sum_insured_usd) if (r.gross_premium_usd and r.sum_insured_usd) else None
            under_priced = bool(med_rate and rate is not None and rate < med_rate * 0.75)
            if under_priced:
                sev = "high"
                impact = (med_rate - rate) * r.sum_insured_usd
                title = f"Under-priced exposure outlier - {r.insured_name or r.policy_id} ({line})"
                conf = 0.85
            else:
                sev = "medium"
                impact = 0.0
                title = f"Large exposure - verify limits/accumulation - {r.insured_name or r.policy_id} ({line})"
                conf = 0.6
            out.append(_anom(
                "exposure_outlier", title, sev, conf, "sum_insured_usd",
                round(med_si, 0), round(r.sum_insured_usd, 0), impact,
                [f"{r.cedant}/{r.policy_id}"],
                {"line_of_business": line, "robust_z": round(z, 2),
                 "cedant": r.cedant, "sum_insured_usd": round(r.sum_insured_usd, 0),
                 "gross_premium_usd": round(r.gross_premium_usd or 0, 0),
                 "rate_on_line": round(rate, 5) if rate is not None else None,
                 "line_median_rate": round(med_rate, 5) if med_rate else None,
                 "under_priced": under_priced}))
    return out


def detect_duplicate_claims(claims):
    """Same insured + loss date + paid amount appearing more than once -> fraud signal."""
    out = []
    groups = defaultdict(list)
    for c in claims:
        key = (
            (c.insured_name or "").lower(),
            str(c.date_of_loss),
            round(c.paid_amount or 0, 2),
        )
        if key[0] and key[1] != "None" and key[2]:
            groups[key].append(c)
    for key, members in groups.items():
        if len(members) > 1:
            cedants = sorted({m.cedant for m in members})
            cross = len(cedants) > 1
            refs = [f"{m.cedant}/{m.claim_id}" for m in members]
            dup_amount = (members[0].paid_amount or 0) * (len(members) - 1)
            out.append(_anom(
                "duplicate_claim",
                "Potential duplicate / stacked claim" + (" across cedants" if cross else ""),
                "high", 0.85 if cross else 0.6,
                "duplicate_paid_amount", 0, members[0].paid_amount or 0,
                dup_amount, refs,
                {"insured_name": members[0].insured_name,
                 "date_of_loss": str(members[0].date_of_loss),
                 "paid_amount": members[0].paid_amount,
                 "occurrences": len(members),
                 "cedants": cedants,
                 "cross_bordereau": cross}))
    return out


def detect_late_reporting(claims, threshold_days=120):
    out = []
    for c in claims:
        if c.date_of_loss and c.reported_date:
            lag = (c.reported_date - c.date_of_loss).days
            if lag > threshold_days:
                sev = "high" if lag > 180 else "medium"
                out.append(_anom(
                    "late_reporting",
                    f"Late claim notification - {c.cedant}/{c.claim_id}",
                    sev, min(0.9, 0.5 + lag / 400),
                    "reporting_lag_days", threshold_days, lag,
                    c.incurred_usd, [f"{c.cedant}/{c.claim_id}"],
                    {"insured_name": c.insured_name, "date_of_loss": str(c.date_of_loss),
                     "reported_date": str(c.reported_date), "lag_days": lag,
                     "incurred_usd": round(c.incurred_usd or 0, 0),
                     "note": "Late reporting can indicate reserving pressure or fraud."}))
    return out


def detect_claim_frequency(risks, claims):
    out = []
    policies = defaultdict(int)
    for r in risks:
        policies[r.cedant] += 1
    claim_counts = defaultdict(int)
    for c in claims:
        claim_counts[c.cedant] += 1
    cedants = [k for k in policies if policies[k]]
    if len(cedants) < 3:
        return out
    freq = {k: claim_counts.get(k, 0) / policies[k] for k in cedants}
    sample = list(freq.values())
    st = _robust_stats(sample)
    for cedant, f in freq.items():
        z = _z_from_stats(f, st)
        if z >= 2.0:
            sev, conf = _sev_from_z(z, hi=3.0, med=2.0)
            out.append(_anom(
                "claim_frequency",
                f"High claim frequency - {cedant}",
                sev, conf, "claims_per_policy",
                round(st["med"], 3), round(f, 3), None, [cedant],
                {"claims": claim_counts.get(cedant, 0), "policies": policies[cedant],
                 "robust_z": round(z, 2)}))
    return out


def detect_slip_bordereau_mismatch(slip_parsed, risks):
    """Cross-check parsed slip terms against the cedant's bordereau."""
    out = []
    if not slip_parsed:
        return out
    cedant_name = (slip_parsed.get("reinsured") or "").lower().strip()
    if not cedant_name:
        return out
    cession = slip_parsed.get("cession_pct")
    matched = [r for r in risks if r.cedant.lower() in cedant_name or cedant_name in r.cedant.lower()]
    if not matched:
        return out
    if cession is not None:
        bord_cession = [r.ceded_share for r in matched if r.ceded_share is not None]
        if bord_cession:
            avg = statistics.mean(bord_cession)
            if abs(avg - cession) > 0.05:
                out.append(_anom(
                    "slip_mismatch",
                    f"Slip cession {cession:.0%} vs bordereau {avg:.0%} - {matched[0].cedant}",
                    "medium", 0.7, "ceded_share", round(cession, 3), round(avg, 3), None,
                    [matched[0].cedant],
                    {"slip_cession": cession, "bordereau_avg_cession": round(avg, 3),
                     "slip_reference": slip_parsed.get("slip_reference"),
                     "note": "Contract terms and reported cessions disagree."}))
    return out


def detect_claim_severity(claims):
    """Individual claims whose incurred amount is a robust outlier vs the book.
    Large severities warrant a fraud/exaggeration check and a cat-vs-attritional review."""
    vals = [c.incurred_usd for c in claims if c.incurred_usd is not None]
    if len(vals) < 5:
        return []
    med = statistics.median(vals)
    st = _robust_stats(vals)
    out = []
    for c in claims:
        if c.incurred_usd is None:
            continue
        z = _z_from_stats(c.incurred_usd, st)
        if z < 3.5:
            continue
        sev = "high" if z >= 4.5 else "medium"
        conf = min(0.95, 0.55 + (z - 3.5) * 0.08)
        out.append(_anom(
            "claim_severity",
            f"Large claim severity - {c.cedant}/{c.claim_id}",
            sev, conf, "incurred_usd", round(med, 0), round(c.incurred_usd, 0),
            c.incurred_usd, [f"{c.cedant}/{c.claim_id}"],
            {"insured_name": c.insured_name, "cause_of_loss": c.cause_of_loss,
             "incurred_usd": round(c.incurred_usd, 0), "portfolio_median_incurred": round(med, 0),
             "robust_z": round(z, 2), "date_of_loss": str(c.date_of_loss)}))
    return out


def detect_rate_adequacy(risks):
    """Risks rated materially below their line's median rate-on-line. Systematic
    under-rating is a weak-risk-selection signal. Size outliers are left to
    detect_sum_insured_outliers to avoid double-flagging the same risk."""
    out = []
    by_line = defaultdict(list)
    for r in risks:
        if r.sum_insured_usd and r.gross_premium_usd:
            by_line[r.line_of_business or "Unknown"].append(r)
    for line, recs in by_line.items():
        if len(recs) < 3:
            continue
        rates = [r.gross_premium_usd / r.sum_insured_usd for r in recs]
        med_rate = statistics.median(rates)
        si_vals = [r.sum_insured_usd for r in recs]
        if med_rate <= 0:
            continue
        st_si = _robust_stats(si_vals)
        for r in recs:
            rate = r.gross_premium_usd / r.sum_insured_usd
            if rate >= med_rate * 0.75:
                continue
            if _z_from_stats(r.sum_insured_usd, st_si) >= 3.0:
                continue  # covered by the exposure-outlier detector
            shortfall = (med_rate - rate) * r.sum_insured_usd
            sev = "high" if rate < med_rate * 0.5 else "medium"
            out.append(_anom(
                "rate_adequacy",
                f"Under-priced risk (rate below line) - {r.insured_name or r.policy_id} ({line})",
                sev, 0.75, "rate_on_line", round(med_rate, 5), round(rate, 5),
                shortfall, [f"{r.cedant}/{r.policy_id}"],
                {"cedant": r.cedant, "insured_name": r.insured_name, "line_of_business": line,
                 "rate_on_line": round(rate, 5), "line_median_rate": round(med_rate, 5),
                 "sum_insured_usd": round(r.sum_insured_usd, 0),
                 "gross_premium_usd": round(r.gross_premium_usd, 0)}))
    return out


def run_all(risks, claims, slip_parsed=None):
    anomalies = []
    lr_anoms, ratios = detect_loss_ratio(risks, claims)
    anomalies += lr_anoms
    anomalies += detect_sum_insured_outliers(risks)
    anomalies += detect_duplicate_claims(claims)
    anomalies += detect_late_reporting(claims)
    anomalies += detect_claim_frequency(risks, claims)
    anomalies += detect_claim_severity(claims)
    anomalies += detect_rate_adequacy(risks)
    anomalies += detect_slip_bordereau_mismatch(slip_parsed, risks)
    for i, a in enumerate(anomalies):
        a["id"] = f"AN-{i+1:03d}"
    anomalies.sort(key=lambda a: (SEVERITY_ORDER.get(a["severity"], 0),
                                  a["confidence"]), reverse=True)
    return anomalies, {"loss_ratios_by_cedant": {k: round(v, 3) for k, v in ratios.items()}}
