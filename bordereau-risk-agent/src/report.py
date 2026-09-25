"""Explanation + prioritization output.

Produces a machine-readable JSON result and a self-contained HTML report an
underwriter / risk analyst can open directly.
"""

from __future__ import annotations

import html
import json
from datetime import datetime

SEV_COLOR = {"high": "#c0392b", "medium": "#d68910", "low": "#7f8c8d"}
PRIO_COLOR = {"Critical": "#8e1b1b", "High": "#c0392b", "Medium": "#d68910", "Low": "#7f8c8d"}


def build_json(findings, dq_issues, dq_summary, meta):
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "data_quality": {"summary": dq_summary, "issues": dq_issues},
        "findings": findings,
    }


def _card(f):
    esc = html.escape
    actions = "".join(f"<li>{esc(a)}</li>" for a in f["recommended_actions"])
    refs = ", ".join(esc(r) for r in f["affected_refs"])
    impact = f"{f['financial_impact_usd']:,.0f} USD" if f.get("financial_impact_usd") else "&mdash;"
    pcolor = PRIO_COLOR.get(f["priority_label"], "#333")
    return f"""
    <div class="card">
      <div class="card-head">
        <span class="rank">#{f['rank']}</span>
        <span class="title">{esc(f['title'])}</span>
        <span class="prio" style="background:{pcolor}">{f['priority_label']} &middot; {f['priority_score']}</span>
      </div>
      <div class="tags">
        <span class="tag">Hypothesis: {esc(f['hypothesis'])}</span>
        <span class="tag">Severity: {esc(f['severity'])}</span>
        <span class="tag">Confidence: {f['confidence']:.0%}</span>
        <span class="tag">Est. impact: {impact}</span>
      </div>
      <p class="narrative">{esc(f['narrative'])}</p>
      <div class="refs"><strong>Affected:</strong> {refs}</div>
      <div class="actions"><strong>Recommended actions</strong><ul>{actions}</ul></div>
    </div>"""


def _dq_table(dq_issues):
    if not dq_issues:
        return "<p class='empty'>No data-quality issues detected.</p>"
    rows = "".join(
        f"<tr><td><span class='dot' style='background:{SEV_COLOR.get(i['severity'],'#999')}'></span>"
        f"{html.escape(i['severity'])}</td>"
        f"<td>{html.escape(i['category'])}</td>"
        f"<td>{html.escape(i['ref'])}</td>"
        f"<td>{html.escape(i['field'] or '')}</td>"
        f"<td>{html.escape(i['message'])}</td>"
        f"<td>{html.escape(i.get('suggested_fix') or '')}</td></tr>"
        for i in sorted(dq_issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["severity"], 3)))
    return f"""<table class="dq">
      <thead><tr><th>Severity</th><th>Category</th><th>Record</th><th>Field</th><th>Issue</th><th>Suggested fix</th></tr></thead>
      <tbody>{rows}</tbody></table>"""


def build_html(result, meta):
    esc = html.escape
    findings = result["findings"]
    dq = result["data_quality"]
    cards = "".join(_card(f) for f in findings) or "<p class='empty'>No anomalies detected.</p>"
    lr_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{v:.2f}</td></tr>"
        for k, v in sorted(meta.get("loss_ratios_by_cedant", {}).items(), key=lambda x: -x[1]))
    crit = sum(1 for f in findings if f["priority_label"] == "Critical")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bordereau Risk Intelligence &mdash; Prototype Report</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
         margin:0; background:#f4f6f8; color:#1f2933; }}
  header {{ background:#0f2d4a; color:#fff; padding:22px 32px; }}
  header h1 {{ margin:0 0 4px; font-size:22px; }}
  header p {{ margin:0; opacity:.8; font-size:13px; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:24px 32px 60px; }}
  .kpis {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px; }}
  .kpi {{ background:#fff; border-radius:10px; padding:16px 20px; flex:1; min-width:150px;
          box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .kpi .n {{ font-size:28px; font-weight:700; }}
  .kpi .l {{ font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:#667; }}
  h2 {{ font-size:16px; margin:28px 0 12px; border-bottom:2px solid #e1e6ea; padding-bottom:6px; }}
  .card {{ background:#fff; border-radius:10px; padding:16px 18px; margin-bottom:14px;
           box-shadow:0 1px 3px rgba(0,0,0,.08); border-left:4px solid #cbd5e0; }}
  .card-head {{ display:flex; align-items:center; gap:10px; }}
  .rank {{ font-weight:700; color:#8895a3; }}
  .title {{ font-weight:600; flex:1; }}
  .prio {{ color:#fff; font-size:12px; font-weight:600; padding:3px 10px; border-radius:20px; }}
  .tags {{ margin:8px 0; display:flex; gap:8px; flex-wrap:wrap; }}
  .tag {{ font-size:11px; background:#eef2f6; color:#4a5a6a; padding:3px 9px; border-radius:6px; }}
  .narrative {{ margin:8px 0; line-height:1.55; font-size:14px; }}
  .refs {{ font-size:12px; color:#556; margin-bottom:6px; }}
  .actions ul {{ margin:6px 0 0; padding-left:20px; font-size:13px; line-height:1.6; }}
  table {{ border-collapse:collapse; width:100%; background:#fff; border-radius:8px; overflow:hidden;
           box-shadow:0 1px 3px rgba(0,0,0,.08); font-size:13px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #eef1f4; }}
  th {{ background:#f0f3f6; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:#556; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }}
  .empty {{ color:#78838f; font-style:italic; }}
  footer {{ font-size:12px; color:#8892a0; margin-top:30px; text-align:center; }}
  .lr {{ max-width:360px; }}
</style></head>
<body>
<header>
  <h1>Bordereau Risk Intelligence Agent</h1>
  <p>Prototype report &middot; generated {esc(result['generated_at'])} &middot; {esc(meta.get('label',''))}</p>
</header>
<div class="wrap">
  <div class="kpis">
    <div class="kpi"><div class="n">{len(findings)}</div><div class="l">Findings</div></div>
    <div class="kpi"><div class="n" style="color:#8e1b1b">{crit}</div><div class="l">Critical</div></div>
    <div class="kpi"><div class="n">{dq['summary']['total']}</div><div class="l">Data-quality issues</div></div>
    <div class="kpi"><div class="n">{meta.get('risks',0)}</div><div class="l">Risks parsed</div></div>
    <div class="kpi"><div class="n">{meta.get('claims',0)}</div><div class="l">Claims parsed</div></div>
  </div>

  <h2>Prioritized investigation findings</h2>
  {cards}

  <h2>Data-quality issues (surfaced to analyst, not dropped)</h2>
  {_dq_table(dq['issues'])}

  <h2>Technical loss ratio by cedant</h2>
  <table class="lr"><thead><tr><th>Cedant</th><th>Loss ratio</th></tr></thead><tbody>{lr_rows}</tbody></table>

  <footer>Prototype &mdash; deterministic offline reasoning engine. Set BORDEREAU_LLM=1 with an OPENAI_API_KEY to delegate narratives to an LLM.</footer>
</div>
</body></html>"""


def write_reports(result, meta, out_dir):
    import os
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "findings.json")
    html_path = os.path.join(out_dir, "report.html")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(build_html(result, meta))
    return json_path, html_path
