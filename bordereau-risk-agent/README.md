# Bordereau Risk Intelligence Agent — Prototype

A working prototype of the pipeline:

```
Bordereau / Slip
      ↓  Slip Parser / Document Extraction   (src/slip_parser.py)
      ↓  Normalizer (schema + FX + dates)    (src/normalizer.py, src/util.py)
Structured Data
      ↓  Data Quality Checks                 (src/data_quality.py)
      ↓  ML / Statistical Anomaly Detection  (src/anomaly.py)
      ↓  AI Investigation Agent              (src/agent.py)
Explanation + Prioritization
      ↓  Report (HTML + JSON)                (src/report.py)
Human Underwriter / Analyst
```

Zero third-party dependencies — Python 3.10+ standard library only.

## Run it

```bash
python run.py                      # uses the bundled sample data
python run.py --out output         # choose report location
python run.py --policies P.csv --claims C.csv --slip S.txt
```

Outputs (in `output/`):
- `report.html` — prioritized findings, data-quality table, loss-ratio-by-cedant. Open in a browser.
- `findings.json` — machine-readable result for downstream systems.

## What it detects

| Detector | Signal | Maps to the business problem |
|---|---|---|
| `loss_ratio` | Cedant technical loss ratio vs portfolio median (robust z); escalates on high ceded share | High technical loss ratios / adverse selection |
| `duplicate_claim` | Same insured + loss date + amount appearing more than once, especially across cedants | Insurance fraud (double recovery) |
| `late_reporting` | Notification lag beyond threshold | Fraud / reserving manipulation |
| `exposure_outlier` | Large sum insured for the line; high severity only when also under-rated (rate-on-line below median) | Under-pricing / weak risk selection |
| `claim_frequency` | Claims-per-policy vs portfolio median | Weak risk selection |
| `slip_mismatch` | Signed slip terms vs reported bordereau cessions | Contract-vs-reporting inconsistency |
| Data quality | Missing fields, duplicate IDs, date logic, currency, referential integrity | Poor data discipline that masks true risk selection |

Each finding gets a **hypothesis**, a plain-language **narrative**, a **priority score**
(severity × confidence × financial impact), and **recommended actions**.

## The AI investigation agent

By default `src/agent.py` runs a **deterministic, offline reasoning engine** — no API key,
no network — so the prototype is fully reproducible. To delegate the narrative step to an
LLM instead:

```bash
export BORDEREAU_LLM=1
export OPENAI_API_KEY=sk-...
python run.py
```

Priority scoring and recommended actions stay deterministic even in LLM mode; only the
explanation text is delegated.

## Sample data

`sample_data/` contains a synthetic-but-realistic book (22 risks, 17 claims, 4 cedants,
1 unstructured slip) with deliberately planted issues: a distressed cedant (Alpha Mutual),
a cross-bordereau duplicate claim, a late notification, an under-priced large exposure, a
date-logic error, a missing field, and a currency inconsistency. Premiums are set at ~0.4%
of sum insured so the loss ratios land in a believable range.

## Interactive web app

`web-app/` is a browser-only version of the same pipeline (a faithful JS port of `src/`,
validated to produce identical findings on the sample data). An analyst uploads a policies
CSV, a claims CSV and an optional slip; the entire analysis runs **in-browser** — no server,
no data leaves the device, which suits sensitive bordereau data.

```bash
# serve locally (any static server works)
cd web-app && python -m http.server 8080
# open http://localhost:8080
```

Files: `index.html`, `styles.css`, `app.js` (UI), `pipeline.js` (logic), `sample-data.js`.
Because it is plain static files with no build step, it can be hosted on any static host
(including Qoder Sites) by uploading the `web-app/` directory.

## Prototype scope / what a production build needs


- **Parser**: the slip parser is regex over clean text and is an *input module only*, not a
  product. Production needs OCR + layout-aware extraction (scanned slips, tables, stamps).
- **Normalization**: static FX table and one canonical schema. Production needs an FX feed
  and a schema-mapping layer per cedant template.
- **Anomaly detection**: robust z-scores / rule detectors on a small book. Production needs
  per-line, per-peril, per-vintage baselines and enough history for real ML models.
- **Agent**: deterministic templates (optional LLM). Production needs retrieval over the
  actual claim/policy files and a human-feedback loop to tune thresholds.
- No persistence, auth, or audit trail — this is a detection/explanation prototype.
