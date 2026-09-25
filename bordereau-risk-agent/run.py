#!/usr/bin/env python3
"""Bordereau Risk Intelligence Agent - prototype runner.

Pipeline:
    Slip / Bordereau  ->  Parser  ->  Normalizer  ->  Data Quality
    ->  Anomaly Detection  ->  AI Investigation Agent  ->  Report

Usage:
    python run.py                       # use bundled sample data
    python run.py --policies P.csv --claims C.csv --slip S.txt
    python run.py --out output          # where reports are written
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import anomaly, data_quality as dq, report as report_mod
from src.normalizer import load_claims, load_policies
from src.slip_parser import parse_slip_file

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "sample_data")

REQUIRED_COLUMNS = {
    "policies": ["cedant", "policy_id", "sum_insured", "gross_premium"],
    "claims": ["cedant", "claim_id", "date_of_loss", "paid_amount"],
}


def _fail(msg: str) -> None:
    """Print a human-readable error and exit instead of dumping a traceback."""
    print(f"\nERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def validate_csv(path: str, kind: str, label: str) -> None:
    if not os.path.exists(path):
        _fail(f"{label} not found at '{path}'.")
    if os.path.getsize(path) == 0:
        _fail(f"{label} is empty ('{path}').")
    with open(path, newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh), None)
    if not header:
        _fail(f"{label} has no header row ('{path}').")
    header = [h.strip() for h in header]
    missing = [c for c in REQUIRED_COLUMNS[kind] if c not in header]
    if missing:
        _fail(f"{label} is missing required column(s): {', '.join(repr(m) for m in missing)}.")


def main():
    ap = argparse.ArgumentParser(description="Bordereau Risk Intelligence Agent (prototype)")
    ap.add_argument("--policies", default=os.path.join(SAMPLE, "bordereau_policies.csv"))
    ap.add_argument("--claims", default=os.path.join(SAMPLE, "bordereau_claims.csv"))
    ap.add_argument("--slip", default=os.path.join(SAMPLE, "slip_reinsurance.txt"))
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    args = ap.parse_args()

    print("=" * 64)
    print("  Bordereau Risk Intelligence Agent  -  prototype run")
    print("=" * 64)

    # 1. Parse / load inputs
    validate_csv(args.policies, "policies", "Policies bordereau")
    validate_csv(args.claims, "claims", "Claims bordereau")
    risks = load_policies(args.policies)
    claims = load_claims(args.claims)
    slip_parsed = parse_slip_file(args.slip) if args.slip and os.path.exists(args.slip) else None
    print(f"[1/5] Parsed  risks={len(risks)}  claims={len(claims)}  "
          f"slip={'yes' if slip_parsed else 'no'}")
    if slip_parsed:
        ex = slip_parsed["_extraction"]
        print(f"      slip extraction confidence={ex['confidence']:.0%} "
              f"({ex['labels_found']}/{ex['labels_expected']} fields)")

    # 2. Data quality
    risk_ids = {r.policy_id for r in risks}
    issues = []
    issues += dq.check_risks(risks)
    issues += dq.check_claims(claims, risk_ids)
    if slip_parsed:
        issues += dq.check_slip(slip_parsed)
    summary = dq.summarize(issues)
    print(f"[2/5] Data quality: {summary['total']} issues "
          f"{summary['by_severity']}")

    # 3. Anomaly detection
    anomalies, stats = anomaly.run_all(risks, claims, slip_parsed)
    print(f"[3/5] Anomaly detection: {len(anomalies)} anomalies flagged")

    # 4. Investigation agent
    from src.agent import investigate
    findings = investigate(anomalies, issues, summary)
    print(f"[4/5] Investigation agent: {len(findings)} prioritized findings")

    # 5. Report
    meta = {
        "label": f"{len(risks)} risks, {len(claims)} claims",
        "risks": len(risks),
        "claims": len(claims),
        "loss_ratios_by_cedant": stats["loss_ratios_by_cedant"],
        "slip": {k: v for k, v in (slip_parsed or {}).items() if k != "_extraction"},
    }
    result = report_mod.build_json(findings, issues, summary, meta)
    json_path, html_path = report_mod.write_reports(result, meta, args.out)
    print(f"[5/5] Reports written:\n      {json_path}\n      {html_path}")

    # Console digest
    print("\n" + "-" * 64)
    print("TOP FINDINGS")
    print("-" * 64)
    for f in findings[:8]:
        impact = f"{f['financial_impact_usd']:,.0f} USD" if f.get("financial_impact_usd") else "n/a"
        print(f"  #{f['rank']:<2} [{f['priority_label']:<8} {f['priority_score']:>5}] "
              f"{f['title']}")
        print(f"        -> {f['hypothesis']}  (impact: {impact})")
    print("-" * 64)
    print(f"Open the HTML report for the full investigation: {html_path}")


if __name__ == "__main__":
    main()
