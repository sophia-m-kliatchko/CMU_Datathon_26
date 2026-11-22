"""
Evidence + ranking through Alice's `evidence_confidence` package (vendored in app/evidence_confidence/,
commit recorded in app/EVIDENCE_CONFIDENCE_VERSION). This module only loads rows and converts formats;
tiers and ranking are entirely hers. Her files are never edited here.

Per search:
  1. candidates   every facility in the radius (backend/geography.py), no service filter, no top-k
  2. rows         links for those facilities, their registry sites, and the sites' service rows for the
                  requested service only. Service rows from empanelment / general accreditation sites are
                  dropped first: they can't support a service tier and her adapter rejects them (Alice's advice).
                  Also any reviewer decisions (registry_match_review.reviewer_decision, confirm/reject),
                  and the facilities' own claims (silver_facility_claims) for services her claim mapping covers.
  3. evidence     silver.adapt_registry_tables(reviews=...)  ->  registry Evidence (pending/rejected links kept)
                  service_claims.claim_evidence()             ->  self-reported Evidence (capped at T3)
  4. tier + rank  build_recommendation_response(): tiers, LEFT JOIN (no evidence = U), ranks the full set
  5. back in main.py: reshape for the page, then pick the top N and alternatives

This mirrors her evidence_confidence/pipeline.py (recommend()), but reads the tables with SQL instead of
from a local CSV bundle, since a Databricks App has no local copy of the silver tables.
Not included: NQAS / Kayakalp (don't change the tier; no facility links exist yet).
"""

import json
from pathlib import Path

from evidence_confidence import build_recommendation_response
from evidence_confidence.adapters import NON_SERVICE_CATEGORIES
from evidence_confidence.service_claims import CLAIM_PATTERNS, FIELDS as CLAIM_FIELDS, claim_evidence
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


# Coarse SQL prefilter for claims: a superset of her CLAIM_PATTERNS (claim_norm is lower case with
# punctuation removed), so only rows that could match are fetched. Her match_claim() makes the real decision.
CLAIM_PREFILTER = {"dialysis": "dialysis", "emergency_c_section": "section|esarean|lscs"}


def load_claims(facility_ids, service):
    """The candidates' own claims that could mention the service. Empty if her mapping doesn't cover it."""
    if not facility_ids or service not in CLAIM_PATTERNS:
        return []
    rows = db.query(
        f"""SELECT facility_id, claim_field, claim_position, claim_text, claim_norm
            FROM {config.t('silver_facility_claims')}
            WHERE array_contains(split(:ids, ','), facility_id)
              AND claim_field IN ({", ".join(f"'{f}'" for f in CLAIM_FIELDS)})
              AND claim_norm RLIKE :prefilter""",
        {"ids": ",".join(facility_ids), "prefilter": CLAIM_PREFILTER[service]})
    return [{**dict(r), "claim_position": int(r["claim_position"]) if r["claim_position"] is not None else None}
            for r in rows]


def load_reviews(facility_ids):
    """Reviewer decisions (confirm / reject) recorded in registry_match_review; her adapter applies them."""
    if not facility_ids:
        return []
    return [dict(r) for r in db.query(
        f"""SELECT link_id, facility_id, site_id, reviewer_decision
            FROM {config.t('registry_match_review')}
            WHERE reviewer_decision IS NOT NULL AND reviewer_decision <> ''
              AND array_contains(split(:ids, ','), facility_id)""", {"ids": ",".join(facility_ids)})]


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
    ids = [c["facility_id"] for c in candidates]
    links, sites, rows = load_rows(ids, service)
    reviews = load_reviews(ids)
    adapted = adapt_registry_tables([{"facility_id": i} for i in ids], sites, rows, links,
                                    canonical_services=[service], reviews=reviews)
    claims = load_claims(ids, service)
    claim_records, claim_report = claim_evidence(claims, service, facility_ids=ids)
    geo = [{"facility_id": c["facility_id"], "name": c.get("name") or None,
            "distance_km": float(c["distance_km"]), "geo_confidence": c.get("geo_confidence"),
            "location_basis": c.get("location_basis") or None,
            "location_uncertainty_km": (float(c["location_uncertainty_km"])
                                        if c.get("location_uncertainty_km") is not None else None),
            "distance_min_km": (float(c["distance_min_km"]) if c.get("distance_min_km") is not None else None)}
           for c in candidates]
    request = {"pin": pincode, "service": service, "radius_km": float(radius_km), "mode": MODE[urgency]}
    response = build_recommendation_response(request, tuple(adapted["evidence"]) + tuple(claim_records), geo)
    report = {"status": adapted["status"], "findings": adapted["findings"], "coverage": adapted["coverage"],
              "claim_mapping": {**claim_report, "included": True},
              "rows_loaded": {"links": len(links), "sites": len(sites), "service_rows": len(rows),
                              "reviewer_decisions": len(reviews), "claims_fetched": len(claims)}}
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
    # Covered by the "lists this as current but gives no expiry date" flag line.
    "Authoritative current-listing assertion is undated; no scrape/snapshot freshness inferred.": None,
    # Covered by the app's own "outside your radius, but it may be closer" line.
    "Reported distance exceeds request radius; upstream retrieval must explain inclusion.": None,
    "Historical direct verification supports past capability only; expiry does not establish service absence.":
        "The certification for this service has expired. It shows the service existed, not that it still does.",
}
FLAG_TEXT = {
    "conditional_certification": "The certification was granted conditionally.",
    "date_year_only": "The registry gives only a year for this record, not an exact date.",
    "current_listing_undated": "The registry lists this as current but gives no expiry date.",
    "temporal_uncertainty": "The evidence has no date of its own, so how current it is isn't known.",
    "conflicting_evidence": "Sources disagree about this service.",
    "missing_citation": "Part of the evidence has no citation.",
}
# Qualifiers her adapters attach to individual records -> one card line each.
QUALIFIER_TEXT = {
    "CLAIM_DOES_NOT_STATE_EMERGENCY":
        "The facility's own listing mentions C-sections but doesn't say they're available as an emergency.",
}
CLAIM_FIELD_TEXT = {"capability": "capability", "procedure": "procedures", "equipment": "equipment",
                    "specialties": "specialties"}
CLAIM_SOURCE = "Facility's own listing (Virtue Foundation dataset)"

NO_SUPPORT = "No accepted, eligible service support. Retain the facility; unknown is not unavailable."

BASIS_TEXT = {
    "training": "approval to train specialists",
    "membership": "network membership",
    "designation": "a government designation",
    "self_report": "the facility's own listing",
}


def _counted(se, kind):
    """Credited service-scope records from registries ('registry') or the facility's own claims ('self')."""
    credited = {d["evidence_id"] for d in se["decisions"] if d.get("credited")}
    return [r for r in se["evidence_records"] if r.get("scope") == "service" and r["evidence_id"] in credited
            and (r.get("source_id") == "virtue_foundation") == (kind == "self")]


def self_reported_only(se):
    return bool(_counted(se, "self")) and not _counted(se, "registry")


def _explanation_warnings(f, radius_km):
    out = []
    se = f["service_evidence"]
    if se["effective_tier"] == "T3" and self_reported_only(se):
        out.append("Only the facility's own listing mentions this service. No registry confirms it.")
    d, u = f.get("distance_km"), f.get("location_uncertainty_km")
    if d is not None and radius_km is not None and d > radius_km:
        out.append(f"Its approximate location is {d:g} km away, outside your {radius_km:g} km radius. It's included "
                   f"because its location is only known to within ±{u:g} km, so it may be closer.")
    for r in _counted(se, "self") + _counted(se, "registry"):
        for q in r.get("qualifiers") or ():
            if q in QUALIFIER_TEXT and QUALIFIER_TEXT[q] not in out:
                out.append(QUALIFIER_TEXT[q])
    for line in f["service_evidence"]["explanation"] + f["warnings"]:
        if line.startswith("Base "):
            continue
        if se["effective_tier"] == "R" and line == NO_SUPPORT:
            continue  # R cards say the record is under review; "no record found" would contradict it
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
        self_rep = r.get("source_id") == "virtue_foundation"
        text, source = r["statement"], cite.get("label") or r.get("source_id")
        if self_rep:
            # Her locator is "silver_facility_claims:[facility_id, field, position, text]".
            try:
                field = json.loads(str(cite.get("locator", "")).split(":", 1)[1])[1]
            except (IndexError, ValueError, TypeError):
                field = None
            text = f"Listed under {CLAIM_FIELD_TEXT[field]}: \u201c{text}\u201d" if field in CLAIM_FIELD_TEXT else text
            source = CLAIM_SOURCE
        items.append({"kind": "self_reported" if self_rep else "registry",
                      "text": text, "source": source, "url": url,
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
    if se["effective_tier"] == "T3" and self_reported_only(se):
        s += " Its evidence is the facility's own listing (self-reported), so it ranks below registry evidence."
    elif se["effective_tier"] == "T3" and basis:
        s += f" Its evidence is indirect ({', '.join(dict.fromkeys(basis))})."
    return s


def self_reports(facility_ids, service):
    """{facility_id: [claim texts]} for facilities whose own listing mentions the service
    (silver_facility_claims, matched with the service's synonyms). Not verified: shown as U."""
    from . import services
    svc = services.BY_TAG.get(service)
    if not facility_ids or not svc:
        return {}
    rows = db.query(
        f"""SELECT facility_id, collect_set(claim_text) AS texts
            FROM {config.t('silver_facility_claims')}
            WHERE array_contains(split(:ids, ','), facility_id) AND claim_norm RLIKE :pat
            GROUP BY facility_id""",
        {"ids": ",".join(str(i) for i in facility_ids), "pat": "|".join(svc["synonyms"])})
    return {r["facility_id"]: db.as_list(r["texts"])[:3] for r in rows}


def shape(response, candidates, tier_label, top_n, alternatives_n, claims=None):
    """Returns (recommendations, unconfirmed, alternatives, tier_counts), each facility in the page's format.
    claims: {facility_id: [self-reported texts]} from self_reports(); only these may fill empty slots."""
    claims = claims or {}
    extra = {c["facility_id"]: c for c in candidates}
    mode = response["request"]["mode"]
    radius_km = response["request"].get("radius_km")
    edges = response["ranking_config"]["distance_bands_km"]

    def one(f):
        se = f["service_evidence"]
        c = extra.get(f["facility_id"], {})
        items = _items(se)
        tier = se["effective_tier"]
        if tier not in DOCUMENTARY and not any(i["kind"] == "self_reported" for i in items):
            items += [{"kind": "self_reported", "text": f"Facility's own listing mentions: “{t}”",
                       "source": "Virtue Foundation listing (self-reported, not verified)", "url": None,
                       "status": "not verified", "match": {"needs_review": False}}
                      for t in claims.get(f["facility_id"], [])]
        return {
            "facility_id": f["facility_id"], "facility_name": f.get("name") or "(name not listed)",
            "location": ", ".join(x for x in (c.get("city"), c.get("state")) if x), "pincode": c.get("pincode"),
            "distance_km": f["distance_km"], "geo_confidence": f.get("geo_confidence"),
            "location_uncertainty_km": f.get("location_uncertainty_km"),
            "requested_service": se["service"], "tier": tier, "base_tier": se["base_tier"],
            "evidence_level": tier_label.get(tier, tier), "review_status": se["review_status"],
            "service_match": "direct" if any(i["status"] == "counted" and i["kind"] == "registry" for i in items)
                             else "self_reported" if any(i["status"] == "counted" for i in items)
                             else ("under_review" if items else "none"),
            "self_reported_only": self_reported_only(se),
            "distance_min_km": f.get("distance_min_km"),
            "evidence": items, "evidence_text": [i["text"] for i in items], "source_urls": f["source_urls"],
            "explanation_warnings": _explanation_warnings(f, radius_km),
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
        # If fewer than top_n have documentary evidence, fill the remaining slots with the NEAREST
        # facilities whose own listing claims the service (still labelled U). Never unrelated facilities.
        claimed = sorted((f for f in rest if f["facility_id"] in claims),
                         key=lambda f: (f["distance_km"] is None, f["distance_km"] or 0))
        fill = claimed[:max(0, top_n - len(top))]
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
    # Unknowns only if their own listing claims the service, so unrelated facilities never appear.
    unknown = [f for f in rest if f["service_evidence"]["effective_tier"] == "U" and f["facility_id"] in claims]
    alternatives = (with_evidence + unknown)[:alternatives_n]
    return [one(f) for f in top], [one(f) for f in unconfirmed], [one(f) for f in alternatives], counts
