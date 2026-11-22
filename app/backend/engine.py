"""
Evidence + ranking through Alice's `evidence_confidence` package (vendored in app/evidence_confidence/,
commit recorded in app/EVIDENCE_CONFIDENCE_VERSION). This module only loads rows and converts formats;
tiers and ranking are entirely hers. Her files are never edited here.

Per search:
  1. candidates   every facility in the radius (backend/geography.py), no service filter, no top-k
  2. rows         links for those facilities, their registry sites, and the sites' service rows for the
                  requested service only. Service rows from empanelment / general accreditation sites are
                  dropped first: they can't support a service tier and her adapter rejects them (Alice's advice).
  3. evidence     silver.adapt_registry_tables()  ->  Evidence records (pending/rejected links kept)
  4. tier + rank  build_recommendation_response(): tiers, LEFT JOIN (no evidence = U), ranks the full set
  5. back in main.py: reshape for the page, then pick the top N and alternatives

Not included yet (see app/README.md): self-reported claims (needs a reviewed claim -> service matcher),
NQAS / Kayakalp (don't change the tier; no facility links exist yet).
"""

from pathlib import Path

from evidence_confidence import build_recommendation_response
from evidence_confidence.adapters import NON_SERVICE_CATEGORIES
from evidence_confidence.silver import adapt_registry_tables

from . import config, db

VERSION_FILE = Path(__file__).resolve().parent.parent / "EVIDENCE_CONFIDENCE_VERSION"


def package_commit():
    for line in VERSION_FILE.read_text().splitlines():
        if line.startswith("commit:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


COMMIT = package_commit()
NAME = f"evidence_confidence@{COMMIT[:7]}"

# The app's three urgency levels -> her two modes. Emergency also shows the 112/108 notice on the page.
MODE = {"routine": "routine", "urgent": "urgent", "emergency": "urgent"}

LINK_SUBQUERY = f"SELECT site_id FROM {config.t('facility_registry_links_silver')} " \
                f"WHERE array_contains(split(:ids, ','), facility_id)"


def _clean(row, array_cols=("dq_flags",)):
    """SQL connector rows -> plain dicts her adapters accept (ARRAY columns arrive as JSON text)."""
    r = dict(row)
    for col in array_cols:
        if col in r:
            r[col] = db.as_list(r[col])
    return r


def load_rows(facility_ids, service):
    if not facility_ids:
        return [], [], []
    p = {"ids": ",".join(facility_ids)}
    links = db.query(
        f"""SELECT link_id, facility_id, site_id, source, match_score, needs_review, match_method
            FROM {config.t('facility_registry_links_silver')}
            WHERE array_contains(split(:ids, ','), facility_id)""", p)
    sites = db.query(
        f"""SELECT site_id, source, name, listing_type, listing_category, listing_status, listing_current,
                   dq_flags, row_citation, source_name, source_publisher, source_url,
                   retrieved_on, source_license, produced_by
            FROM {config.t('registry_sites_silver')} WHERE site_id IN ({LINK_SUBQUERY})""", p)
    rows = db.query(
        f"""SELECT service_row_id, site_id, source, service, evidence_type, service_specific, evidence_detail,
                   status, evidence_date, valid_until, is_current, dq_flags, row_citation, source_name,
                   source_publisher, source_url, retrieved_on, source_license, produced_by
            FROM {config.t('registry_services_silver')}
            WHERE service = :service AND site_id IN ({LINK_SUBQUERY})""", {**p, "service": service})
    sites = [_clean(s) for s in sites]
    category = {s["site_id"]: s.get("listing_category") for s in sites}
    rows = [_clean(r) for r in rows if category.get(r["site_id"]) not in NON_SERVICE_CATEGORIES]
    links = [{k: (float(v) if k == "match_score" and v is not None else v) for k, v in dict(l).items()}
             for l in links]
    return links, sites, rows


def evaluate(candidates, service, pincode, radius_km, urgency):
    """Run her pipeline over the full candidate list. Returns (response JSON, adapter report)."""
    links, sites, rows = load_rows([c["facility_id"] for c in candidates], service)
    adapted = adapt_registry_tables([{"facility_id": c["facility_id"]} for c in candidates],
                                    sites, rows, links, canonical_services=[service])
    geo = [{"facility_id": c["facility_id"], "name": c.get("name") or None,
            "distance_km": float(c["distance_km"]), "geo_confidence": c.get("geo_confidence"),
            "location_basis": c.get("location_basis") or None,
            "location_uncertainty_km": (float(c["location_uncertainty_km"])
                                        if c.get("location_uncertainty_km") is not None else None)}
           for c in candidates]
    request = {"pin": pincode, "service": service, "radius_km": float(radius_km), "mode": MODE[urgency]}
    response = build_recommendation_response(request, adapted["evidence"], geo)
    report = {"status": adapted["status"], "findings": adapted["findings"], "coverage": adapted["coverage"],
              "rows_loaded": {"links": len(links), "sites": len(sites), "service_rows": len(rows)}}
    return response, report


# ---------------------------------------------------------------------------------------------------
# Her response -> the page's format. Display only: her order is kept; nothing is re-scored or re-sorted.
# ---------------------------------------------------------------------------------------------------

DOCUMENTARY = ("T1", "T2", "T3")

# Her explanation strings are written for auditors; these are the patient-facing versions.
# None = drop (covered elsewhere on the card, e.g. the "call ahead" line or the location line).
EXPLANATION_TEXT = {
    "No accepted, eligible service support. Retain the facility; unknown is not unavailable.":
        "No record of this service was found for this facility. That doesn't mean it isn't offered.",
    "All applicable supporting associations are unresolved; no verification credit. Rejected links are "
    "excluded from support.":
        "A registry record for this service may belong to this facility, but the match is still under review, "
        "so it isn't counted.",
    "Pending identity evidence is explanatory only; candidate tiers do not establish verification.": None,
    "Certification/listing is not proof of current staffing, operational readiness or patient acceptance.": None,
    "Reported distance is approximate; supplied uncertainty is retained.": None,
    "Historical direct verification supports past capability only; expiry does not establish service absence.":
        "The certification for this service has expired. It shows the service existed, not that it still does.",
}
FLAG_TEXT = {
    "conditional_certification": "The certification was granted conditionally.",
    "date_year_only": "The registry gives only a year for this record, not an exact date.",
    "current_listing_undated": "The registry lists this as current but gives no expiry date.",
    "temporal_uncertainty": "The registry record has no date of its own, so how current it is isn't known.",
    "conflicting_evidence": "Sources disagree about this service.",
    "missing_citation": "Part of the evidence has no citation.",
}
BASIS_TEXT = {
    "training": "approval to train specialists",
    "membership": "network membership",
    "designation": "a government designation",
    "self_report": "the facility's own listing",
}


def _explanation_warnings(f):
    out = []
    for line in f["service_evidence"]["explanation"] + f["warnings"]:
        if line.startswith("Base "):
            continue
        text = EXPLANATION_TEXT.get(line, line)
        if text and text not in out:
            out.append(text)
    for flag, on in f["service_evidence"]["flags"].items():
        if on and flag in FLAG_TEXT and FLAG_TEXT[flag] not in out:
            out.append(FLAG_TEXT[flag])
    return out


def _items(se):
    decisions = {d["evidence_id"]: d for d in se["decisions"]}
    items = []
    for r in se["evidence_records"]:
        if r.get("scope") != "service":
            continue
        d = decisions.get(r["evidence_id"], {})
        match = (r.get("match") or {}).get("status")
        if d.get("credited"):
            status = "counted"
        elif match in ("pending", "unknown"):
            status = "match under review"
        elif match == "rejected":
            status = "match rejected"
        else:
            status = "not counted"
        cite = (r.get("citations") or [{}])[0]
        url = cite.get("locator") if str(cite.get("locator", "")).startswith(("http://", "https://")) else None
        items.append({"kind": "self_reported" if r.get("source_id") == "virtue_foundation" else "registry",
                      "text": r["statement"], "source": cite.get("label") or r.get("source_id"), "url": url,
                      "status": status, "match": {"needs_review": match != "accepted"}})
    items.sort(key=lambda i: i["status"] != "counted")
    return items


def _band_text(band, edges):
    if band >= len(edges) + 1:
        return "distance unknown"
    if band == 0:
        return f"within {edges[0]:g} km"
    if band < len(edges):
        return f"{edges[band - 1]:g}–{edges[band]:g} km away"
    return f"more than {edges[-1]:g} km away"


def _ranking_text(f, tier_label, mode, edges):
    se = f["service_evidence"]
    if mode == "urgent":
        return ("For urgent and emergency searches, a facility is recommended only if it has a current "
                "certification (T1) and a confirmed emergency-capability record. No source supplies that record "
                "yet, so facilities are listed by distance instead.")
    basis = [BASIS_TEXT[b] for b in se.get("evidence_basis") or [] if b in BASIS_TEXT]
    s = (f"Ordered by evidence level first, then distance band (within 10, 25 or 50 km), then warning flags, "
         f"then exact distance. This facility: {tier_label.lower()}, {_band_text(f['ranking']['distance_band'], edges)}.")
    if se["effective_tier"] == "T3" and basis:
        s += f" Its evidence is indirect ({', '.join(dict.fromkeys(basis))})."
    return s


def shape(response, candidates, tier_label, top_n, alternatives_n):
    """Returns (recommendations, unconfirmed, alternatives, tier_counts), each facility in the page's format."""
    extra = {c["facility_id"]: c for c in candidates}
    mode = response["request"]["mode"]
    edges = response["ranking_config"]["distance_bands_km"]

    def one(f):
        se = f["service_evidence"]
        c = extra.get(f["facility_id"], {})
        items = _items(se)
        tier = se["effective_tier"]
        return {
            "facility_id": f["facility_id"], "facility_name": f.get("name") or "(name not listed)",
            "location": ", ".join(x for x in (c.get("city"), c.get("state")) if x), "pincode": c.get("pincode"),
            "distance_km": f["distance_km"], "geo_confidence": f.get("geo_confidence"),
            "location_uncertainty_km": f.get("location_uncertainty_km"),
            "requested_service": se["service"], "tier": tier, "base_tier": se["base_tier"],
            "evidence_level": tier_label.get(tier, tier), "review_status": se["review_status"],
            "service_match": "direct" if any(i["status"] == "counted" and i["kind"] == "registry" for i in items)
                             else ("under_review" if items else "none"),
            "evidence": items, "evidence_text": [i["text"] for i in items], "source_urls": f["source_urls"],
            "explanation_warnings": _explanation_warnings(f),
            "ranking_label": f["ranking"]["label"],
            "ranking_explanation": _ranking_text(f, tier_label.get(tier, tier), mode, edges),
        }

    everyone = response["recommendations"] + response["alternatives"]
    counts = {}
    for f in everyone:
        t = f["service_evidence"]["effective_tier"]
        counts[t] = counts.get(t, 0) + 1

    if mode == "routine":
        # Her routine list ranks everyone; the page recommends only facilities with documentary evidence.
        top = [f for f in response["recommendations"] if f["service_evidence"]["effective_tier"] in DOCUMENTARY][:top_n]
        chosen = {f["facility_id"] for f in top}
        rest = [f for f in response["recommendations"] if f["facility_id"] not in chosen]
        # Always show top_n cards: if fewer have documentary evidence, fill with the next best in her order
        # (some evidence first, then the nearest unknowns). Their tier stamp and ledger say what's missing.
        fill = ([f for f in rest if f["service_evidence"]["effective_tier"] != "U"]
                + [f for f in rest if f["service_evidence"]["effective_tier"] == "U"])[:top_n - len(top)]
        top += fill
        filled = {f["facility_id"] for f in fill}
        rest = [f for f in rest if f["facility_id"] not in filled]
        unconfirmed = []
    else:
        # Urgent: recommended = her capability-eligible list (empty until a capability source exists).
        # Her alternatives are already in distance order; those with documentary evidence are shown as
        # cards under "nearest facilities, emergency capability not confirmed" (a filter, not a re-sort).
        top = response["recommendations"][:top_n]
        rest = response["recommendations"][top_n:] + response["alternatives"]
        unconfirmed = [f for f in rest if f["service_evidence"]["effective_tier"] in DOCUMENTARY][:top_n]
        shown = {f["facility_id"] for f in unconfirmed}
        rest = [f for f in rest if f["facility_id"] not in shown]
    # Table of alternatives: ones with some evidence (incl. R / X) first, then the nearest unknowns.
    # Both groups keep her order.
    with_evidence = [f for f in rest if f["service_evidence"]["effective_tier"] != "U"]
    unknown = [f for f in rest if f["service_evidence"]["effective_tier"] == "U"]
    alternatives = (with_evidence + unknown)[:alternatives_n]
    return [one(f) for f in top], [one(f) for f in unconfirmed], [one(f) for f in alternatives], counts
