/* Bordereau Risk Intelligence Agent - client-side pipeline.
 * Faithful JS port of the Python reference implementation (src/*.py).
 * Pure logic: no DOM access. Exposed on window.Pipeline and module.exports.
 */
(function (root) {
  "use strict";

  // ---------- util ----------
  const BASE_CURRENCY = "USD";
  const FX_TO_USD = { USD: 1.0, EUR: 1.08, GBP: 1.27, CHF: 1.12, CAD: 0.74 };
  const CUR_RE = /\b(USD|EUR|GBP|CHF|CAD)\b/;

  const round = (n, d = 0) => {
    if (n == null || isNaN(n)) return n;
    const f = Math.pow(10, d);
    return Math.round((n + Number.EPSILON) * f) / f;
  };

  function parseNumber(v) {
    if (v == null) return null;
    if (typeof v === "number") return v;
    const s = String(v).trim();
    if (!s) return null;
    const m = s.match(/-?\d[\d,]*(?:\.\d+)?\s*(%)?/);
    if (!m) return null;
    const num = m[0].replace(/,/g, "").replace(/\s/g, "").replace(/%$/, "");
    const n = parseFloat(num);
    if (isNaN(n)) return null;
    return m[1] ? n / 100 : n;
  }

  const mkDate = (y, mo, d) => new Date(Date.UTC(y, mo - 1, d));

  function parseDate(v) {
    if (!v) return null;
    if (v instanceof Date) return v;
    const s = String(v).trim();
    if (!s) return null;
    let m;
    if ((m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/))) return mkDate(+m[1], +m[2], +m[3]);
    if ((m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})$/))) return mkDate(+m[3], +m[2], +m[1]);
    if ((m = s.match(/^(\d{2})-(\d{2})-(\d{4})$/))) return mkDate(+m[3], +m[2], +m[1]);
    return null;
  }

  const iso = (d) => (d instanceof Date ? d.toISOString().slice(0, 10) : String(d));

  function detectCurrency(text, def) {
    if (!text) return def;
    const m = String(text).match(CUR_RE);
    return m ? m[1] : def;
  }

  function toBaseCurrency(amount, currency) {
    if (amount == null) return { converted: null, rate: null, known: false };
    const cur = (currency || BASE_CURRENCY).toUpperCase();
    const rate = FX_TO_USD[cur];
    if (rate == null) return { converted: amount, rate: null, known: false };
    return { converted: amount * rate, rate, known: true };
  }

  // ---------- CSV ----------
  function parseCSV(text) {
    const rows = [];
    let row = [], cur = "", inQ = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (inQ) {
        if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += c;
      } else {
        if (c === '"') inQ = true;
        else if (c === ",") { row.push(cur); cur = ""; }
        else if (c === "\n") { row.push(cur); rows.push(row); row = []; cur = ""; }
        else if (c === "\r") { /* skip */ }
        else cur += c;
      }
    }
    if (cur.length || row.length) { row.push(cur); rows.push(row); }
    if (!rows.length) return [];
    const header = rows[0].map((h) => h.trim());
    return rows.slice(1)
      .filter((r) => r.some((c) => String(c).trim() !== ""))
      .map((r) => { const o = {}; header.forEach((h, i) => (o[h] = (r[i] != null ? r[i] : "").trim())); return o; });
  }

  // ---------- slip parser ----------
  const LABEL_MAP = {
    reinsured: ["reinsured", "reinsured cedant", "cedant", "reinsured name"],
    cedant_reference: ["cedant reference", "cedant ref", "contract reference"],
    period: ["contract period", "period", "reinsurance period"],
    line_of_business: ["line class", "line", "class", "class of business"],
    territory: ["territory", "territorial limits", "geographical scope"],
    basis: ["basis of cover", "basis"],
    cession: ["cession", "cession percent", "ceded share"],
    layer_attachment: ["layer attachment", "attachment", "deductible"],
    layer_limit: ["layer limit", "limit", "cover limit"],
    reinsurance_premium: ["reinsurance prem", "reinsurance premium", "premium"],
    reinsurer_share: ["reinsurer share", "share", "line held"],
    broker: ["broker", "reinsurance broker"],
    slip_reference: ["slip reference", "slip ref"],
    lead_underwriter: ["lead underwriter", "underwriter"],
    slip_signed_date: ["slip signed date", "signed", "date signed"],
  };
  const SPLIT_RE = /\s{2,}|\s*:\s*/;

  function extractLabels(text) {
    const found = {};
    for (const raw of String(text).split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("=")) continue;
      const m = line.match(SPLIT_RE);
      if (!m) continue;
      const label = line.slice(0, m.index).trim();
      let value = line.slice(m.index + m[0].length).trim();
      value = value.replace(/^[:\s]+/, "").trim();
      if (!value || label.length > 40) continue;
      const key = label.toLowerCase().replace(/[^a-z0-9 ]/g, "").replace(/\s+/g, " ").trim();
      found[key] = value;
    }
    return found;
  }

  function pick(labels, canonical) {
    for (const alias of LABEL_MAP[canonical] || [canonical]) if (labels[alias] != null) return labels[alias];
    return null;
  }

  function parseSlip(text) {
    const labels = extractLabels(text);
    const raw = {};
    for (const c of Object.keys(LABEL_MAP)) raw[c] = pick(labels, c);

    const period = raw.period || "";
    const dates = period.match(/\d{2}\/\d{2}\/\d{4}/g) || [];
    const inception = dates[0] ? parseDate(dates[0]) : null;
    const expiry = dates[1] ? parseDate(dates[1]) : null;
    const premText = raw.reinsurance_premium || "";
    const attachText = raw.layer_attachment || "";
    const limitText = raw.layer_limit || "";

    const parsed = {
      source: "slip",
      reinsured: raw.reinsured,
      cedant_reference: raw.cedant_reference,
      slip_reference: raw.slip_reference,
      broker: raw.broker,
      lead_underwriter: raw.lead_underwriter,
      territory: raw.territory,
      basis: raw.basis,
      line_of_business: ((raw.line_of_business || "").split("-")[0].trim()) || null,
      currency: detectCurrency(premText + " " + limitText, "USD"),
      inception_date: inception,
      expiry_date: expiry,
      cession_pct: parseNumber(raw.cession),
      reinsurer_share_pct: parseNumber(raw.reinsurer_share),
      layer_attachment: parseNumber(attachText.split(" xs ")[0]),
      xs_retention: attachText.indexOf(" xs ") >= 0 ? parseNumber(attachText.split(" xs ")[1]) : null,
      layer_limit: parseNumber(limitText),
      reinsurance_premium: parseNumber(premText),
      slip_signed_date: parseDate(raw.slip_signed_date),
    };
    const keys = Object.keys(LABEL_MAP);
    const hit = Object.values(raw).filter((v) => v != null && v !== "").length;
    parsed._extraction = {
      labels_found: hit,
      labels_expected: keys.length,
      confidence: round(hit / keys.length, 3),
      missing: keys.filter((c) => raw[c] == null || raw[c] === "").sort(),
      raw_labels: raw,
    };
    return parsed;
  }

  // ---------- normalizer ----------
  function loadPolicies(text) {
    return parseCSV(text).map((row) => {
      const si = parseNumber(row.sum_insured);
      const prem = parseNumber(row.gross_premium);
      const cur = (row.currency || "").trim() || null;
      const siC = toBaseCurrency(si, cur);
      const premC = toBaseCurrency(prem, cur);
      return {
        cedant: (row.cedant || "").trim(),
        policy_id: (row.policy_id || "").trim(),
        insured_name: (row.insured_name || "").trim() || null,
        line_of_business: (row.line_of_business || "").trim() || null,
        peril: (row.peril || "").trim() || null,
        inception_date: parseDate(row.inception_date),
        expiry_date: parseDate(row.expiry_date),
        sum_insured: si,
        currency: cur,
        gross_premium: prem,
        ceded_share: parseNumber(row.ceded_share),
        sum_insured_usd: siC.converted,
        gross_premium_usd: premC.converted,
        currency_known: siC.known,
        raw: row,
        source: "bordereau_policies",
      };
    });
  }

  function loadClaims(text) {
    return parseCSV(text).map((row) => {
      const paid = parseNumber(row.paid_amount);
      const outs = parseNumber(row.outstanding_amount) || 0;
      const cur = (row.currency || "").trim() || null;
      const incurred = paid == null ? null : paid + outs;
      const incC = toBaseCurrency(incurred, cur);
      return {
        cedant: (row.cedant || "").trim(),
        claim_id: (row.claim_id || "").trim(),
        policy_id: (row.policy_id || "").trim() || null,
        insured_name: (row.insured_name || "").trim() || null,
        date_of_loss: parseDate(row.date_of_loss),
        reported_date: parseDate(row.reported_date),
        paid_amount: paid,
        outstanding_amount: outs,
        currency: cur,
        cause_of_loss: (row.cause_of_loss || "").trim() || null,
        incurred,
        incurred_usd: incC.converted,
        currency_known: incC.known,
        raw: row,
        source: "bordereau_claims",
      };
    });
  }

  // ---------- data quality ----------
  const SEVERITY_WEIGHT = { high: 3, medium: 2, low: 1 };
  const issue = (category, severity, ref, field, message, fix) => ({ category, severity, ref, field, message, suggested_fix: fix || null });

  function dominantCurrency(records) {
    const counts = {};
    let best = null, bestN = 0;
    for (const r of records) {
      if (!r.currency) continue;
      counts[r.currency] = (counts[r.currency] || 0) + 1;
      if (counts[r.currency] > bestN) { bestN = counts[r.currency]; best = r.currency; }
    }
    return best;
  }

  function checkRisks(risks) {
    const out = [];
    const dom = dominantCurrency(risks);
    const seen = {};
    const required = {
      insured_name: "Insured name", line_of_business: "Line of business",
      sum_insured: "Sum insured", gross_premium: "Gross premium",
      inception_date: "Inception date", expiry_date: "Expiry date",
    };
    for (const r of risks) {
      const ref = `${r.cedant}/${r.policy_id}`;
      if (seen[r.policy_id]) {
        out.push(issue("duplicate", "high", ref, "policy_id",
          `Duplicate policy_id '${r.policy_id}' also in ${seen[r.policy_id]} -- possible double cession.`,
          "Reconcile with cedant and de-duplicate before booking."));
      } else seen[r.policy_id] = ref;

      for (const [f, label] of Object.entries(required)) {
        if (r[f] == null || r[f] === "") out.push(issue("missing", "medium", ref, f, `${label} is missing.`, `Request ${label.toLowerCase()} from ${r.cedant}.`));
      }
      if (r.inception_date && r.expiry_date && r.expiry_date < r.inception_date)
        out.push(issue("date_logic", "high", ref, "expiry_date", `Expiry ${iso(r.expiry_date)} precedes inception ${iso(r.inception_date)}.`, "Confirm period dates with the cedant; exposure may be mis-stated."));
      if (r.sum_insured != null && r.sum_insured < 0) out.push(issue("range", "high", ref, "sum_insured", "Negative sum insured.", "Correct sign / re-key value."));
      if (r.gross_premium != null && r.gross_premium < 0) out.push(issue("range", "high", ref, "gross_premium", "Negative gross premium.", "Correct sign / re-key value."));
      if (r.ceded_share != null && !(r.ceded_share >= 0 && r.ceded_share <= 1)) out.push(issue("range", "medium", ref, "ceded_share", `Ceded share ${r.ceded_share} outside 0-1.`, "Check whether value is a percentage or a fraction."));
      if (r.currency && dom && r.currency !== dom) out.push(issue("currency", "medium", ref, "currency", `Currency '${r.currency}' differs from bordereau base '${dom}'.`, "Confirm reporting currency; FX normalization applied for analytics."));
      if (!r.currency) out.push(issue("currency", "low", ref, "currency", "No currency stated; assumed base currency.", "Add explicit currency."));
    }
    return out;
  }

  function checkClaims(claims, riskIds) {
    const out = [];
    const dom = dominantCurrency(claims);
    const seen = {};
    for (const c of claims) {
      const ref = `${c.cedant}/${c.claim_id}`;
      if (seen[c.claim_id]) out.push(issue("duplicate", "high", ref, "claim_id", `Duplicate claim_id '${c.claim_id}'.`, "De-duplicate claim records."));
      else seen[c.claim_id] = ref;

      for (const [f, label] of Object.entries({ date_of_loss: "Date of loss", reported_date: "Reported date", paid_amount: "Paid amount", policy_id: "Policy reference" })) {
        if (c[f] == null || c[f] === "") out.push(issue("missing", "medium", ref, f, `${label} is missing.`, `Request ${label.toLowerCase()} from ${c.cedant}.`));
      }
      if (c.date_of_loss && c.reported_date && c.reported_date < c.date_of_loss) out.push(issue("date_logic", "high", ref, "reported_date", `Reported date ${iso(c.reported_date)} precedes loss date ${iso(c.date_of_loss)}.`, "Verify dates; possible keying error or back-dated report."));
      if (c.policy_id && riskIds && riskIds.size && !riskIds.has(c.policy_id)) out.push(issue("referential", "medium", ref, "policy_id", `Claim references unknown policy '${c.policy_id}'.`, "Match claim to a ceded policy; unmatched claims may be out of scope."));
      if (c.paid_amount != null && c.paid_amount < 0) out.push(issue("range", "high", ref, "paid_amount", "Negative paid amount.", "Confirm sign / re-key."));
      if (c.currency && dom && c.currency !== dom) out.push(issue("currency", "low", ref, "currency", `Currency '${c.currency}' differs from base '${dom}'.`, "Confirm currency; FX normalization applied."));
    }
    return out;
  }

  function checkSlip(parsed) {
    const out = [];
    const ex = parsed._extraction || {};
    const missing = ex.missing || [];
    const conf = ex.confidence || 0;
    const ref = parsed.slip_reference || "slip";
    if (conf < 1.0) out.push(issue("extraction", "medium", ref, missing.join(","), `Slip extraction incomplete (confidence ${(conf * 100).toFixed(0)}%); missing: ${missing.join(", ")}.`, "Manual review of un-extracted slip fields before binding."));
    if (parsed.inception_date && parsed.expiry_date && parsed.expiry_date < parsed.inception_date) out.push(issue("date_logic", "high", ref, "period", "Slip period end precedes start.", "Confirm contract period."));
    return out;
  }

  function summarizeDQ(issues) {
    const bySev = {}, byCat = {};
    let score = 0;
    for (const i of issues) {
      bySev[i.severity] = (bySev[i.severity] || 0) + 1;
      byCat[i.category] = (byCat[i.category] || 0) + 1;
      score += SEVERITY_WEIGHT[i.severity] || 1;
    }
    return { total: issues.length, by_severity: bySev, by_category: byCat, quality_score: score };
  }

  // ---------- statistics ----------
  const median = (a) => { const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  // Precompute median/MAD once per group, then score each record in O(1).
  // Calling median() per record made detection O(n^2 log n); this keeps the
  // exact same robust-z values while making each group O(n log n).
  function robustStats(sample) {
    if (sample.length < 3) return { ok: false, med: 0, mad: 0 };
    const med = median(sample);
    const mad = median(sample.map((v) => Math.abs(v - med)));
    return { ok: true, med, mad };
  }
  function zFromStats(x, st) {
    if (!st.ok || st.mad === 0) return 0;
    return (0.6745 * (x - st.med)) / st.mad;
  }
  function sevFromZ(z, hi = 3.5, med = 2.5) {
    if (z >= hi) return { sev: "high", conf: Math.min(0.98, 0.6 + (z - hi) * 0.08 + 0.2) };
    if (z >= med) return { sev: "medium", conf: Math.min(0.9, 0.5 + (z - med) * 0.1) };
    return { sev: "low", conf: 0.4 };
  }
  const anom = (type, title, severity, confidence, metric, expected, actual, impact, refs, evidence) => ({
    type, title, severity, confidence: round(confidence, 2), metric, expected, actual,
    financial_impact_usd: impact != null ? round(impact, 0) : null, affected_refs: refs, evidence,
  });

  // ---------- anomaly detectors ----------
  function detectLossRatio(risks, claims) {
    const prem = {}, cession = {}, incurred = {};
    for (const r of risks) {
      if (r.gross_premium_usd) prem[r.cedant] = (prem[r.cedant] || 0) + r.gross_premium_usd * (r.ceded_share || 0);
      if (r.ceded_share != null) (cession[r.cedant] = cession[r.cedant] || []).push(r.ceded_share);
    }
    for (const c of claims) if (c.incurred_usd != null) incurred[c.cedant] = (incurred[c.cedant] || 0) + c.incurred_usd;
    const cedants = Object.keys(prem).filter((k) => prem[k] > 0);
    const ratios = {}; cedants.forEach((k) => (ratios[k] = (incurred[k] || 0) / prem[k]));
    if (cedants.length < 3) return { out: [], ratios };
    const sample = Object.values(ratios), med = median(sample), out = [];
    const st = robustStats(sample);
    for (const [cedant, lr] of Object.entries(ratios)) {
      const z = zFromStats(lr, st);
      if (z >= 2.0) {
        let { sev, conf } = sevFromZ(z, 3.0, 2.0);
        const cs = cession[cedant] || [];
        const avgCession = cs.length ? mean(cs) : null;
        const impact = (incurred[cedant] || 0) - med * prem[cedant];
        const ev = { loss_ratio: round(lr, 3), portfolio_median_lr: round(med, 3), robust_z: round(z, 2), ceded_premium_usd: round(prem[cedant], 0), incurred_usd: round(incurred[cedant] || 0, 0), avg_ceded_share: avgCession != null ? round(avgCession, 3) : null };
        let title = `Elevated technical loss ratio - ${cedant}`;
        if (avgCession && avgCession >= 0.55) { title += " (adverse selection suspect)"; ev.adverse_selection = true; if (sev !== "high") sev = "high"; }
        out.push(anom("loss_ratio", title, sev, conf, "technical_loss_ratio", round(med, 3), round(lr, 3), impact, [cedant], ev));
      }
    }
    return { out, ratios };
  }

  function detectSumInsuredOutliers(risks) {
    const out = [], byLine = {};
    for (const r of risks) if (r.sum_insured_usd) { const k = r.line_of_business || "Unknown"; (byLine[k] = byLine[k] || []).push(r); }
    for (const [line, recs] of Object.entries(byLine)) {
      const vals = recs.map((r) => r.sum_insured_usd);
      if (vals.length < 3) continue;
      const medSi = median(vals);
      const stSi = robustStats(vals);
      const rates = recs.filter((r) => r.gross_premium_usd && r.sum_insured_usd).map((r) => r.gross_premium_usd / r.sum_insured_usd);
      const medRate = rates.length ? median(rates) : null;
      for (const r of recs) {
        const z = zFromStats(r.sum_insured_usd, stSi);
        if (z < 3.0) continue;
        const rate = r.gross_premium_usd && r.sum_insured_usd ? r.gross_premium_usd / r.sum_insured_usd : null;
        const under = !!(medRate && rate != null && rate < medRate * 0.75);
        let sev, impact, title, conf;
        if (under) { sev = "high"; impact = (medRate - rate) * r.sum_insured_usd; title = `Under-priced exposure outlier - ${r.insured_name || r.policy_id} (${line})`; conf = 0.85; }
        else { sev = "medium"; impact = 0; title = `Large exposure - verify limits/accumulation - ${r.insured_name || r.policy_id} (${line})`; conf = 0.6; }
        out.push(anom("exposure_outlier", title, sev, conf, "sum_insured_usd", round(medSi, 0), round(r.sum_insured_usd, 0), impact, [`${r.cedant}/${r.policy_id}`],
          { line_of_business: line, robust_z: round(z, 2), cedant: r.cedant, sum_insured_usd: round(r.sum_insured_usd, 0), gross_premium_usd: round(r.gross_premium_usd || 0, 0), rate_on_line: rate != null ? round(rate, 5) : null, line_median_rate: medRate ? round(medRate, 5) : null, under_priced: under }));
      }
    }
    return out;
  }

  function detectDuplicateClaims(claims) {
    const groups = {}, out = [];
    for (const c of claims) {
      const nm = (c.insured_name || "").toLowerCase();
      const dt = c.date_of_loss ? iso(c.date_of_loss) : "None";
      const amt = round(c.paid_amount || 0, 2);
      if (nm && dt !== "None" && amt) { const key = `${nm}|${dt}|${amt}`; (groups[key] = groups[key] || []).push(c); }
    }
    for (const members of Object.values(groups)) {
      if (members.length > 1) {
        const cedants = [...new Set(members.map((m) => m.cedant))].sort();
        const cross = cedants.length > 1;
        const dup = (members[0].paid_amount || 0) * (members.length - 1);
        out.push(anom("duplicate_claim", "Potential duplicate / stacked claim" + (cross ? " across cedants" : ""), "high", cross ? 0.85 : 0.6,
          "duplicate_paid_amount", 0, members[0].paid_amount || 0, dup, members.map((m) => `${m.cedant}/${m.claim_id}`),
          { insured_name: members[0].insured_name, date_of_loss: iso(members[0].date_of_loss), paid_amount: members[0].paid_amount, occurrences: members.length, cedants, cross_bordereau: cross }));
      }
    }
    return out;
  }

  function detectLateReporting(claims, threshold = 120) {
    const out = [];
    for (const c of claims) {
      if (c.date_of_loss && c.reported_date) {
        const lag = Math.round((c.reported_date - c.date_of_loss) / 86400000);
        if (lag > threshold) {
          const sev = lag > 180 ? "high" : "medium";
          out.push(anom("late_reporting", `Late claim notification - ${c.cedant}/${c.claim_id}`, sev, Math.min(0.9, 0.5 + lag / 400),
            "reporting_lag_days", threshold, lag, c.incurred_usd, [`${c.cedant}/${c.claim_id}`],
            { insured_name: c.insured_name, date_of_loss: iso(c.date_of_loss), reported_date: iso(c.reported_date), lag_days: lag, incurred_usd: round(c.incurred_usd || 0, 0), note: "Late reporting can indicate reserving pressure or fraud." }));
        }
      }
    }
    return out;
  }

  function detectClaimFrequency(risks, claims) {
    const policies = {}, counts = {};
    for (const r of risks) policies[r.cedant] = (policies[r.cedant] || 0) + 1;
    for (const c of claims) counts[c.cedant] = (counts[c.cedant] || 0) + 1;
    const cedants = Object.keys(policies).filter((k) => policies[k]);
    if (cedants.length < 3) return [];
    const freq = {}; cedants.forEach((k) => (freq[k] = (counts[k] || 0) / policies[k]));
    const sample = Object.values(freq), out = [];
    const st = robustStats(sample);
    for (const [cedant, f] of Object.entries(freq)) {
      const z = zFromStats(f, st);
      if (z >= 2.0) { const { sev, conf } = sevFromZ(z, 3.0, 2.0); out.push(anom("claim_frequency", `High claim frequency - ${cedant}`, sev, conf, "claims_per_policy", round(st.med, 3), round(f, 3), null, [cedant], { claims: counts[cedant] || 0, policies: policies[cedant], robust_z: round(z, 2) })); }
    }
    return out;
  }

  function detectClaimSeverity(claims) {
    const vals = claims.filter((c) => c.incurred_usd != null).map((c) => c.incurred_usd);
    if (vals.length < 5) return [];
    const med = median(vals), out = [];
    const st = robustStats(vals);
    for (const c of claims) {
      if (c.incurred_usd == null) continue;
      const z = zFromStats(c.incurred_usd, st);
      if (z < 3.5) continue;
      const sev = z >= 4.5 ? "high" : "medium";
      const conf = Math.min(0.95, 0.55 + (z - 3.5) * 0.08);
      out.push(anom("claim_severity", `Large claim severity - ${c.cedant}/${c.claim_id}`, sev, conf,
        "incurred_usd", round(med, 0), round(c.incurred_usd, 0), c.incurred_usd, [`${c.cedant}/${c.claim_id}`],
        { insured_name: c.insured_name, cause_of_loss: c.cause_of_loss, incurred_usd: round(c.incurred_usd, 0), portfolio_median_incurred: round(med, 0), robust_z: round(z, 2), date_of_loss: iso(c.date_of_loss) }));
    }
    return out;
  }

  function detectRateAdequacy(risks) {
    const out = [], byLine = {};
    for (const r of risks) if (r.sum_insured_usd && r.gross_premium_usd) { const k = r.line_of_business || "Unknown"; (byLine[k] = byLine[k] || []).push(r); }
    for (const [line, recs] of Object.entries(byLine)) {
      if (recs.length < 3) continue;
      const rates = recs.map((r) => r.gross_premium_usd / r.sum_insured_usd);
      const medRate = median(rates);
      const siVals = recs.map((r) => r.sum_insured_usd);
      if (medRate <= 0) continue;
      const stSi = robustStats(siVals);
      for (const r of recs) {
        const rate = r.gross_premium_usd / r.sum_insured_usd;
        if (rate >= medRate * 0.75) continue;
        if (zFromStats(r.sum_insured_usd, stSi) >= 3.0) continue;
        const shortfall = (medRate - rate) * r.sum_insured_usd;
        const sev = rate < medRate * 0.5 ? "high" : "medium";
        out.push(anom("rate_adequacy", `Under-priced risk (rate below line) - ${r.insured_name || r.policy_id} (${line})`, sev, 0.75,
          "rate_on_line", round(medRate, 5), round(rate, 5), shortfall, [`${r.cedant}/${r.policy_id}`],
          { cedant: r.cedant, insured_name: r.insured_name, line_of_business: line, rate_on_line: round(rate, 5), line_median_rate: round(medRate, 5), sum_insured_usd: round(r.sum_insured_usd, 0), gross_premium_usd: round(r.gross_premium_usd, 0) }));
      }
    }
    return out;
  }

  function detectSlipMismatch(slip, risks) {
    const out = [];
    if (!slip) return out;
    const name = (slip.reinsured || "").toLowerCase().trim();
    if (!name) return out;
    const cession = slip.cession_pct;
    const matched = risks.filter((r) => r.cedant.toLowerCase().includes(name) || name.includes(r.cedant.toLowerCase()));
    if (!matched.length) return out;
    if (cession != null) {
      const bc = matched.filter((r) => r.ceded_share != null).map((r) => r.ceded_share);
      if (bc.length) {
        const avg = mean(bc);
        if (Math.abs(avg - cession) > 0.05) {
          const avgR = round(avg, 3);
          const cessionR = round(cession, 3);
          out.push(anom("slip_mismatch", `Slip cession ${pctN(cessionR)} vs bordereau ${pctN(avgR)} - ${matched[0].cedant}`, "medium", 0.7,
            "ceded_share", cessionR, avgR, null, [matched[0].cedant],
            { slip_cession: cessionR, bordereau_avg_cession: avgR, slip_reference: slip.slip_reference, note: "Contract terms and reported cessions disagree." }));
        }
      }
    }
    return out;
  }

  const SEV_ORDER = { high: 3, medium: 2, low: 1 };
  function runAll(risks, claims, slip) {
    const { out: lr, ratios } = detectLossRatio(risks, claims);
    let anomalies = [].concat(lr,
      detectSumInsuredOutliers(risks),
      detectDuplicateClaims(claims),
      detectLateReporting(claims),
      detectClaimFrequency(risks, claims),
      detectClaimSeverity(claims),
      detectRateAdequacy(risks),
      detectSlipMismatch(slip, risks));
    anomalies.forEach((a, i) => (a.id = "AN-" + String(i + 1).padStart(3, "0")));
    anomalies.sort((a, b) => (SEV_ORDER[b.severity] - SEV_ORDER[a.severity]) || (b.confidence - a.confidence));
    const lrRound = {}; Object.entries(ratios).forEach(([k, v]) => (lrRound[k] = round(v, 3)));
    return { anomalies, stats: { loss_ratios_by_cedant: lrRound } };
  }

  // ---------- investigation agent ----------
  const SEV_WEIGHT_A = { high: 60, medium: 35, low: 15 };
  const CONF_WEIGHT = 20, IMPACT_WEIGHT = 20;
  const HYPOTHESIS = {
    duplicate_claim: "Insurance fraud (duplicate / stacked claim)",
    late_reporting: "Fraud or reserving manipulation (late notification)",
    loss_ratio: "Weak risk selection / adverse selection driving poor technical result",
    claim_frequency: "Weak risk selection (adverse frequency)",
    exposure_outlier: "Under-rated exposure / possible under-pricing",
    rate_adequacy: "Under-pricing / weak risk selection (rate inadequacy)",
    claim_severity: "Large/severe claim - potential exaggeration or cat event",
    slip_mismatch: "Contract-vs-reporting inconsistency (operational or selection risk)",
    data_quality: "Poor bordereau data discipline (masks true risk selection)",
  };
  const ACTIONS = {
    duplicate_claim: ["Pull claim files for the flagged references and compare loss adjuster reports.", "Check whether the same loss was ceded under more than one contract/cedant.", "If confirmed, raise SIU referral and recover the duplicate payment."],
    late_reporting: ["Request the cedant's notification log and explain the reporting lag.", "Re-test IBNR/reserves for the affected period.", "Add a bordereau timeliness clause/penalty at renewal."],
    loss_ratio: ["Re-price or reduce the cession for this cedant at renewal.", "Request the underlying risk schedule to test for adverse selection.", "Review whether high-cession, high-loss risks were systematically ceded."],
    claim_frequency: ["Analyse frequency by peril and insured segment for this cedant.", "Tighten underwriting criteria / attach experience-rating conditions."],
    exposure_outlier: ["Verify sum insured and premium adequacy for the outlier risk.", "Confirm the risk falls within the contract's underwriting guidelines.", "Re-check rate-adequacy for the whole line given the outlier."],
    rate_adequacy: ["Re-rate the risk to the line's technical price.", "Review the cedant's pricing/underwriting guidelines for this segment.", "Consider a rate-adequacy or minimum-rate condition at renewal."],
    claim_severity: ["Review the claim file and loss adjuster report for the severe claim.", "Check for exaggerated or inflated loss components (fraud).", "Confirm whether the loss is a single event or systemic to the segment."],
    slip_mismatch: ["Reconcile the signed slip terms against the reported bordereau cessions.", "Confirm the correct cession percentage with the broker."],
    data_quality: ["Return the bordereau to the cedant for correction of the flagged fields.", "Add the missing fields to the bordereau template / EDI validation.", "Hold booking of affected records until reconciled."],
  };

  const nf0 = (n) => Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const f2 = (n) => Number(n || 0).toFixed(2);
  const pctN = (n) => Math.round(Number(n || 0) * 100) + "%";
  const pct3 = (n) => (Number(n || 0) * 100).toFixed(3) + "%";

  function impactFactor(impact, maxImpact) {
    if (!impact || impact <= 0 || !maxImpact || maxImpact <= 0) return 0;
    return IMPACT_WEIGHT * (Math.log10(1 + impact) / Math.log10(1 + maxImpact));
  }
  function priorityScore(a, maxImpact) {
    const base = SEV_WEIGHT_A[a.severity] || 15;
    const conf = CONF_WEIGHT * (a.confidence || 0.5);
    const imp = impactFactor(a.financial_impact_usd, maxImpact);
    const score = Math.max(0, Math.min(100, base + conf + imp));
    const label = score >= 78 ? "Critical" : score >= 58 ? "High" : score >= 38 ? "Medium" : "Low";
    return { score: round(score, 1), label };
  }

  function localNarrative(a) {
    const t = a.type, ev = a.evidence || {};
    if (t === "duplicate_claim") {
      const cross = ev.cross_bordereau ? " under two different cedants/bordereaux" : "";
      return `The same insured (${ev.insured_name}), loss date (${ev.date_of_loss}) and paid amount (${nf0(ev.paid_amount)}) appear ${ev.occurrences} times${cross}. Identical loss details across separate cessions is a classic double-recovery / fraud pattern; estimated duplicated exposure is ${nf0(a.financial_impact_usd)} USD.`;
    }
    if (t === "late_reporting") {
      return `Claim ${a.affected_refs[0]} was reported ${ev.lag_days} days after the loss (loss ${ev.date_of_loss}, reported ${ev.reported_date}), against a ${a.expected}-day expectation. Incurred ${nf0(ev.incurred_usd)} USD. Extended notification delays distort reserves and can conceal late-manufactured claims.`;
    }
    if (t === "loss_ratio") {
      const adv = ev.adverse_selection ? " Average ceded share is high, so the cedant appears to be passing through a disproportionate share of poor risks (adverse selection)." : "";
      return `${a.affected_refs[0]} runs a technical loss ratio of ${f2(ev.loss_ratio)} versus a portfolio median of ${f2(ev.portfolio_median_lr)} (robust z=${ev.robust_z}). On ceded premium of ${nf0(ev.ceded_premium_usd)} USD this is roughly ${nf0(a.financial_impact_usd)} USD worse than the median book.${adv}`;
    }
    if (t === "claim_frequency") {
      const per = ev.policies ? round(ev.claims / ev.policies, 2) : 0;
      return `${a.affected_refs[0]} shows ${ev.claims} claims over ${ev.policies} policies (${per} per policy) versus a median of ${a.expected}. Elevated frequency points to weak risk selection rather than a single large loss.`;
    }
    if (t === "exposure_outlier") {
      const pid = a.affected_refs[0].split("/").pop();
      if (ev.under_priced) {
        return `${ev.cedant}/${pid} carries a sum insured of ${nf0(ev.sum_insured_usd)} USD in ${ev.line_of_business} (${ev.robust_z} robust-sigma above the line median) but is rated at ${pct3(ev.rate_on_line)} against a line median of ${pct3(ev.line_median_rate)}. The exposure is materially under-priced; estimated premium shortfall is ${nf0(a.financial_impact_usd)} USD.`;
      }
      return `${ev.cedant}/${pid} carries a sum insured of ${nf0(ev.sum_insured_usd)} USD in ${ev.line_of_business}, ${ev.robust_z} robust-sigma above the line median of ${nf0(a.expected)} USD. Rate-on-line (${pct3(ev.rate_on_line)}) is in line with the book, so this is an accumulation / limit-adequacy question rather than under-pricing -- confirm it sits within the contract's capacity and event limits.`;
    }
    if (t === "claim_severity") {
      return `${a.affected_refs[0]} (${ev.insured_name}, ${ev.cause_of_loss}) incurred ${nf0(ev.incurred_usd)} USD on ${ev.date_of_loss}, ${ev.robust_z} robust-sigma above the book median of ${nf0(ev.portfolio_median_incurred)} USD. Severities this far above the norm warrant a fraud/exaggeration review and a check on whether the loss is a single event or systemic to the segment.`;
    }
    if (t === "rate_adequacy") {
      const pid = a.affected_refs[0].split("/").pop();
      return `${ev.cedant}/${pid} (${ev.insured_name}) is rated at ${pct3(ev.rate_on_line)} in ${ev.line_of_business} against a line median of ${pct3(ev.line_median_rate)} -- an estimated premium shortfall of ${nf0(a.financial_impact_usd)} USD. Systematic under-rating like this is a weak-risk-selection signal even before losses emerge.`;
    }
    if (t === "slip_mismatch") {
      return `The signed slip (${ev.slip_reference}) states a cession of ${pctN(ev.slip_cession)} but the bordereau for this cedant averages ${pctN(ev.bordereau_avg_cession)}. Contract terms and reported cessions disagree, which affects both pricing and exposure aggregation.`;
    }
    if (t === "data_quality") {
      return `${ev.count} data-quality issues were found across the bordereaux (${(ev.by_category || []).join(", ")}). Systematically incomplete or inconsistent data is itself a risk-selection signal and degrades every downstream analytic.`;
    }
    return a.title || "Anomaly detected.";
  }

  function investigateAnomaly(a, maxImpact) {
    const { score, label } = priorityScore(a, maxImpact);
    let hypothesis = HYPOTHESIS[a.type] || "Anomalous pattern";
    if (a.type === "exposure_outlier" && !(a.evidence || {}).under_priced) hypothesis = "Large exposure / accumulation-limit risk";
    return {
      id: a.id, type: a.type, title: a.title, hypothesis, narrative: localNarrative(a),
      severity: a.severity, confidence: a.confidence, priority_score: score, priority_label: label,
      financial_impact_usd: a.financial_impact_usd, affected_refs: a.affected_refs,
      recommended_actions: ACTIONS[a.type] || ["Review the flagged records."], evidence: a.evidence || {},
    };
  }

  function investigateDQ(dqIssues, dqSummary, maxImpact) {
    if (!dqIssues.length) return null;
    const a = {
      id: "DQ-AGG", type: "data_quality", title: `Bordereau data quality: ${dqSummary.total} issues`,
      severity: dqSummary.by_severity.high ? "high" : "medium", confidence: 0.95,
      expected: 0, actual: dqSummary.total, financial_impact_usd: null,
      affected_refs: [...new Set(dqIssues.map((i) => i.ref))].sort().slice(0, 10),
      evidence: { count: dqSummary.total, by_category: Object.keys(dqSummary.by_category), by_severity: dqSummary.by_severity },
    };
    const { score, label } = priorityScore(a, maxImpact);
    return {
      id: a.id, type: "data_quality", title: a.title, hypothesis: HYPOTHESIS.data_quality, narrative: localNarrative(a),
      severity: a.severity, confidence: a.confidence, priority_score: score, priority_label: label,
      financial_impact_usd: null, affected_refs: a.affected_refs, recommended_actions: ACTIONS.data_quality, evidence: a.evidence,
    };
  }

  function investigate(anomalies, dqIssues, dqSummary) {
    const maxImpact = Math.max(...anomalies.map((a) => a.financial_impact_usd || 0), 1);
    const findings = anomalies.map((a) => investigateAnomaly(a, maxImpact));
    const dqf = investigateDQ(dqIssues, dqSummary, maxImpact);
    if (dqf) findings.push(dqf);
    findings.sort((a, b) => b.priority_score - a.priority_score);
    findings.forEach((f, i) => (f.rank = i + 1));
    return findings;
  }

  // ---------- input validation ----------
  // Structural gate run BEFORE analysis. Catches wrong-shape / empty / oversized
  // inputs and turns them into specific, human-readable messages instead of a
  // raw exception or (worse) silently-empty findings. Per-row data problems are
  // NOT errors here; they belong to the data-quality layer.
  const MAX_ROWS = 50000;
  const REQUIRED_COLUMNS = {
    policies: ["cedant", "policy_id", "sum_insured", "gross_premium"],
    claims: ["cedant", "claim_id", "date_of_loss", "paid_amount"],
  };

  function csvHeader(text) {
    const firstLine = String(text == null ? "" : text).split(/\r?\n/, 1)[0] || "";
    return firstLine.split(",").map((h) => h.replace(/^"|"$/g, "").trim()).filter(Boolean);
  }

  function validateInputs(state) {
    const errors = [], warnings = [];
    const s = state || {};
    const nonEmpty = (t) => t != null && String(t).trim() !== "";
    const hasP = nonEmpty(s.policiesText), hasC = nonEmpty(s.claimsText), hasS = nonEmpty(s.slipText);

    if (!hasP && !hasC) {
      errors.push({ file: "inputs", code: "no_files",
        message: "No bordereau loaded. Upload a policies or claims bordereau (CSV), or use “Load demo dataset”." });
      return { ok: false, errors, warnings };
    }

    function checkCsv(text, kind, label) {
      const header = csvHeader(text);
      if (!header.length) {
        errors.push({ file: label, code: "empty_or_unparseable",
          message: `${label} looks empty or is not valid CSV (no header row found).` });
        return;
      }
      const missing = REQUIRED_COLUMNS[kind].filter((c) => !header.includes(c));
      if (missing.length) {
        errors.push({ file: label, code: "missing_columns",
          message: `${label} is missing required column(s): ${missing.map((m) => `'${m}'`).join(", ")}.` });
        return;
      }
      const n = parseCSV(text).length;
      if (n === 0) warnings.push({ file: label, code: "no_data_rows", message: `${label} has a header but no data rows.` });
      else if (n > MAX_ROWS) warnings.push({ file: label, code: "large_file",
        message: `${label} has ${n.toLocaleString("en-US")} rows (over ${MAX_ROWS.toLocaleString("en-US")}); analysis may be slow.` });
    }

    if (hasP) checkCsv(s.policiesText, "policies", "Policies bordereau");
    if (hasC) checkCsv(s.claimsText, "claims", "Claims bordereau");
    if (hasS && String(s.slipText).trim().length < 3)
      warnings.push({ file: "Slip", code: "slip_short", message: "Reinsurance slip looks too short to parse." });

    return { ok: errors.length === 0, errors, warnings };
  }

  // ---------- orchestration ----------
  function analyze({ policiesText, claimsText, slipText }) {
    const risks = policiesText ? loadPolicies(policiesText) : [];
    const claims = claimsText ? loadClaims(claimsText) : [];
    const slip = slipText ? parseSlip(slipText) : null;
    const riskIds = new Set(risks.map((r) => r.policy_id));
    let issues = [].concat(checkRisks(risks), checkClaims(claims, riskIds));
    if (slip) issues = issues.concat(checkSlip(slip));
    const summary = summarizeDQ(issues);
    const { anomalies, stats } = runAll(risks, claims, slip);
    const findings = investigate(anomalies, issues, summary);
    return {
      meta: {
        risks: risks.length, claims: claims.length, slip: !!slip,
        slip_confidence: slip ? slip._extraction.confidence : null,
        loss_ratios_by_cedant: stats.loss_ratios_by_cedant,
      },
      data_quality: { summary, issues },
      anomalies, findings,
    };
  }

  const Pipeline = {
    parseNumber, parseDate, parseCSV, parseSlip, loadPolicies, loadClaims,
    checkRisks, checkClaims, checkSlip, summarizeDQ, runAll, investigate, analyze, iso,
    validateInputs, csvHeader, MAX_ROWS, REQUIRED_COLUMNS,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = Pipeline;
  if (typeof window !== "undefined") window.Pipeline = Pipeline;
  if (root) root.Pipeline = Pipeline;
})(typeof globalThis !== "undefined" ? globalThis : this);
