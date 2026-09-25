"""Slip Parser / Document Extraction.

Turns an unstructured reinsurance placing slip into a structured record.
This is an INPUT module only -- it is not a standalone product. It uses a
label:value extractor plus a canonical field map. In production this layer
would be backed by an OCR + layout model; here we parse clean text so the
rest of the pipeline can be demonstrated end to end.
"""

from __future__ import annotations

import re

from .util import detect_currency, parse_date, parse_number

# Maps a canonical field to the slip labels (lowercased, punctuation-stripped)
# that may carry it.
LABEL_MAP = {
    "reinsured": ["reinsured", "reinsured cedant", "cedant", "reinsured name"],
    "cedant_reference": ["cedant reference", "cedant ref", "contract reference"],
    "period": ["contract period", "period", "reinsurance period"],
    "line_of_business": ["line class", "line", "class", "class of business"],
    "territory": ["territory", "territorial limits", "geographical scope"],
    "basis": ["basis of cover", "basis"],
    "cession": ["cession", "cession percent", "ceded share"],
    "layer_attachment": ["layer attachment", "attachment", "deductible"],
    "layer_limit": ["layer limit", "limit", "cover limit"],
    "reinsurance_premium": ["reinsurance prem", "reinsurance premium", "premium"],
    "reinsurer_share": ["reinsurer share", "share", "line held"],
    "broker": ["broker", "reinsurance broker"],
    "slip_reference": ["slip reference", "slip ref"],
    "lead_underwriter": ["lead underwriter", "underwriter"],
    "slip_signed_date": ["slip signed date", "signed", "date signed"],
}

_LINE_SPLIT = re.compile(r"\s{2,}|\s*:\s*")


def _extract_labels(text: str) -> dict[str, str]:
    """Return {normalized_label: raw_value} for every 'Label   value' line."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("="):
            continue
        parts = _LINE_SPLIT.split(line, maxsplit=1)
        if len(parts) != 2:
            continue
        label, value = parts[0].strip(), parts[1].strip()
        value = re.sub(r"^[:\s]+", "", value).strip()
        if not value or len(label) > 40:
            continue
        key = re.sub(r"[^a-z0-9 ]", "", label.lower())
        key = re.sub(r"\s+", " ", key).strip()
        found[key] = value
    return found


def _pick(labels: dict[str, str], canonical: str):
    for alias in LABEL_MAP.get(canonical, [canonical]):
        if alias in labels:
            return labels[alias]
    return None


def parse_slip(text: str) -> dict:
    """Parse raw slip text into a structured record with extraction metadata."""
    labels = _extract_labels(text)

    raw = {c: _pick(labels, c) for c in LABEL_MAP}

    period = raw.get("period") or ""
    dates = re.findall(r"\d{2}/\d{2}/\d{4}", period)
    inception = parse_date(dates[0]) if len(dates) > 0 else None
    expiry = parse_date(dates[1]) if len(dates) > 1 else None

    prem_text = raw.get("reinsurance_premium") or ""
    attach_text = raw.get("layer_attachment") or ""
    limit_text = raw.get("layer_limit") or ""

    parsed = {
        "source": "slip",
        "reinsured": raw.get("reinsured"),
        "cedant_reference": raw.get("cedant_reference"),
        "slip_reference": raw.get("slip_reference"),
        "broker": raw.get("broker"),
        "lead_underwriter": raw.get("lead_underwriter"),
        "territory": raw.get("territory"),
        "basis": raw.get("basis"),
        "line_of_business": (raw.get("line_of_business") or "").split("-")[0].strip() or None,
        "currency": detect_currency(prem_text + " " + limit_text, "USD"),
        "inception_date": inception,
        "expiry_date": expiry,
        "cession_pct": parse_number(raw.get("cession")),
        "reinsurer_share_pct": parse_number(raw.get("reinsurer_share")),
        "layer_attachment": parse_number(attach_text.split(" xs ")[0]),
        "xs_retention": parse_number(attach_text.split(" xs ")[1]) if " xs " in attach_text else None,
        "layer_limit": parse_number(limit_text),
        "reinsurance_premium": parse_number(prem_text),
        "slip_signed_date": parse_date(raw.get("slip_signed_date")),
    }

    # Extraction confidence: fraction of canonical labels successfully located.
    hit = sum(1 for v in raw.values() if v not in (None, ""))
    parsed["_extraction"] = {
        "labels_found": hit,
        "labels_expected": len(LABEL_MAP),
        "confidence": round(hit / len(LABEL_MAP), 3),
        "missing": sorted(c for c, v in raw.items() if v in (None, "")),
        "raw_labels": raw,
    }
    return parsed


def parse_slip_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return parse_slip(fh.read())
