/* UI wiring for the Bordereau Risk Intelligence Agent. All analysis runs
 * in-browser via window.Pipeline; uploaded files never leave the device. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { policiesText: null, claimsText: null, slipText: null };
  let lastResult = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const nf0 = (n) => Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const PRIO_COLOR = { Critical: "#8e1b1b", High: "#c0392b", Medium: "#d68910", Low: "#7f8c8d" };
  const SEV_COLOR = { high: "#c0392b", medium: "#d68910", low: "#7f8c8d" };
  const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB per input

  function readFile(file, cb, onerr) {
    const fr = new FileReader();
    fr.onload = () => cb(String(fr.result));
    fr.onerror = () => (onerr ? onerr(fr.error) : cb(null));
    fr.readAsText(file);
  }

  function setStatus(id, text, isError) {
    const el = $(id);
    el.textContent = text;
    el.classList.toggle("loaded", !isError);
    el.classList.toggle("error", !!isError);
  }

  function bindFile(inputId, key, statusId) {
    $(inputId).addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      if (f.size > MAX_FILE_BYTES) {
        setStatus(statusId, `${f.name} — rejected: over 5 MB limit`, true);
        state[key] = null;
        return;
      }
      readFile(
        f,
        (text) => { state[key] = text; setStatus(statusId, f.name, false); analyze(); },
        () => { setStatus(statusId, `Could not read ${f.name}`, true); state[key] = null; }
      );
    });
  }

  function loadSample() {
    const S = window.SAMPLE;
    state.policiesText = S.policies;
    state.claimsText = S.claims;
    state.slipText = S.slip;
    setStatus("st-policies", "bordereau_policies.csv (demo)", false);
    setStatus("st-claims", "bordereau_claims.csv (demo)", false);
    setStatus("st-slip", "slip_reinsurance.txt (demo)", false);
    analyze();
  }

  function errorPanel(errors) {
    const items = errors.map((e) => `<li>${esc(e.message)}</li>`).join("");
    return `<div class="alert error"><strong>Analysis could not be completed</strong><ul>${items}</ul></div>`;
  }

  function warningBanner(warnings) {
    if (!warnings || !warnings.length) return "";
    const items = warnings.map((w) => `<li>${esc(w.message)}</li>`).join("");
    return `<div class="alert warn"><strong>Heads up</strong><ul>${items}</ul></div>`;
  }

  function analyze() {
    const v = window.Pipeline.validateInputs(state);
    if (!v.ok) {
      lastResult = null;
      $("download").disabled = true;
      $("results").innerHTML = errorPanel(v.errors);
      return;
    }
    let res;
    try {
      res = window.Pipeline.analyze(state);
    } catch (err) {
      lastResult = null;
      $("download").disabled = true;
      $("results").innerHTML = errorPanel([{
        message: "The submitted files could not be analysed. Please check they are well-formed CSV/TXT and try again.",
      }]);
      if (window.console) console.error("Analysis error:", err);
      return;
    }
    lastResult = res;
    render(res, v.warnings);
  }

  function card(f) {
    const actions = f.recommended_actions.map((a) => `<li>${esc(a)}</li>`).join("");
    const refs = f.affected_refs.map(esc).join(", ");
    const impact = f.financial_impact_usd != null ? `${nf0(f.financial_impact_usd)} USD` : "&mdash;";
    const pcolor = PRIO_COLOR[f.priority_label] || "#333";
    return `<div class="card">
      <div class="card-head">
        <span class="rank">#${f.rank}</span>
        <span class="title">${esc(f.title)}</span>
        <span class="prio" style="background:${pcolor}">${esc(f.priority_label)} &middot; ${f.priority_score}</span>
      </div>
      <div class="tags">
        <span class="tag">Hypothesis: ${esc(f.hypothesis)}</span>
        <span class="tag">Severity: ${esc(f.severity)}</span>
        <span class="tag">Confidence: ${Math.round(f.confidence * 100)}%</span>
        <span class="tag">Est. impact: ${impact}</span>
      </div>
      <p class="narrative">${esc(f.narrative)}</p>
      <div class="refs"><strong>Affected:</strong> ${refs}</div>
      <details class="actions"><summary>Recommended actions</summary><ul>${actions}</ul></details>
    </div>`;
  }

  function dqTable(issues) {
    if (!issues.length) return "<p class='empty'>No data-quality issues detected.</p>";
    const order = { high: 0, medium: 1, low: 2 };
    const rows = [...issues].sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3)).map((i) =>
      `<tr><td><span class="dot" style="background:${SEV_COLOR[i.severity] || "#999"}"></span>${esc(i.severity)}</td>
       <td>${esc(i.category)}</td><td>${esc(i.ref)}</td><td>${esc(i.field || "")}</td>
       <td>${esc(i.message)}</td><td>${esc(i.suggested_fix || "")}</td></tr>`).join("");
    return `<table class="dq"><thead><tr><th>Severity</th><th>Category</th><th>Record</th><th>Field</th><th>Issue</th><th>Suggested fix</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function render(res, warnings) {
    const findings = res.findings, dq = res.data_quality;
    const crit = findings.filter((f) => f.priority_label === "Critical").length;
    const lrRows = Object.entries(res.meta.loss_ratios_by_cedant)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.toFixed(2)}</td></tr>`).join("");
    const cards = findings.map(card).join("") || "<p class='empty'>No anomalies detected.</p>";
    const slipNote = res.meta.slip
      ? `Slip parsed (extraction confidence ${Math.round((res.meta.slip_confidence || 0) * 100)}%).`
      : "No slip provided.";

    $("results").innerHTML = `
      ${warningBanner(warnings)}
      <div class="kpis">
        <div class="kpi"><div class="n">${findings.length}</div><div class="l">Findings</div></div>
        <div class="kpi"><div class="n" style="color:#8e1b1b">${crit}</div><div class="l">Critical</div></div>
        <div class="kpi"><div class="n">${dq.summary.total}</div><div class="l">Data-quality issues</div></div>
        <div class="kpi"><div class="n">${res.meta.risks}</div><div class="l">Risks parsed</div></div>
        <div class="kpi"><div class="n">${res.meta.claims}</div><div class="l">Claims parsed</div></div>
      </div>
      <p class="subnote">${esc(slipNote)}</p>
      <h2>Prioritized investigation findings</h2>
      ${cards}
      <h2>Data-quality issues (surfaced, not dropped)</h2>
      ${dqTable(dq.issues)}
      <h2>Technical loss ratio by cedant</h2>
      <table class="lr"><thead><tr><th>Cedant</th><th>Loss ratio</th></tr></thead><tbody>${lrRows}</tbody></table>`;
    $("download").disabled = false;
  }

  function download() {
    if (!lastResult) return;
    const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "bordereau-findings.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindFile("f-policies", "policiesText", "st-policies");
    bindFile("f-claims", "claimsText", "st-claims");
    bindFile("f-slip", "slipText", "st-slip");
    $("btn-sample").addEventListener("click", loadSample);
    $("btn-analyze").addEventListener("click", analyze);
    $("download").addEventListener("click", download);
    loadSample();
  });
})();
