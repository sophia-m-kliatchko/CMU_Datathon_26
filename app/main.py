"""
Find the Right Care: web app over the team's Databricks pipeline.

Request flow (matches the team's end-to-end diagram):
  1. Geography  (Elliot)          PIN -> centre -> all facilities within the radius   [backend/geography.py]
  2. Evidence   (evidence engine) tier + flags + citations per facility x service     [backend/evidence.py]
     LEFT JOIN on facility_id: facilities with no evidence stay in as tier U
  3. Rank the complete candidate set (model team; placeholder for now)                [backend/ranking.py]
  4. Only then select the top 3-5 and nearby alternatives
  5. Optional AI explainer per recommendation                                          [backend/explain.py]

Run locally:  see app/README.md.   On Databricks: deployed as a Databricks App (app.yaml).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config, explain, ranking, services
from backend.evidence import TIER_LABEL, get_provider
from backend.geography import PinError

if config.DATA_MODE == "mock":
    from backend import mock as geo
    EVIDENCE = geo.MockEvidence()
else:
    from backend import geography as geo
    EVIDENCE = get_provider()
RANKER = ranking.get_ranker()

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Find the Right Care", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

GEO_LABEL = {"high": "Exact location", "medium_low_precision": "Approximate location (about 1 km)",
             "approximate_pin_centroid": "Location from PIN code only"}


class RecommendRequest(BaseModel):
    service: str
    pincode: str
    radius_km: float = Field(default=config.DEFAULT_RADIUS_KM, gt=0, le=config.MAX_RADIUS_KM)
    urgency: str = Field(default="routine", pattern="^(routine|urgent|emergency)$")


class ExplainRequest(BaseModel):
    service: str
    recommendation: dict


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "data_mode": config.DATA_MODE, "evidence_provider": EVIDENCE.name,
            "ranker": RANKER.name, "explainer": config.LLM_ENDPOINT if config.EXPLAINER_ENABLED else None}


@app.get("/api/services")
def list_services():
    return {"services": services.public_list()}


@app.get("/api/pin/{pincode}")
def pin(pincode: str):
    try:
        return geo.resolve_pin(pincode)
    except PinError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _warnings(c):
    w = []
    if c["geo_confidence"] == "approximate_pin_centroid":
        w.append(f"Location is only known to its PIN code (about ±{float(c.get('location_uncertainty_km') or 2):.0f} km).")
    elif c["geo_confidence"] == "medium_low_precision":
        w.append("Location is approximate (about ±1 km).")
    flag_text = {
        "MATCH_NEEDS_REVIEW": "A registry record was matched to this facility by name and place, but the match "
                              "hasn't been confirmed.",
        "CERTIFICATION_EXPIRED": "A certification for this service has expired; current status is unconfirmed.",
        "LISTING_WITHDRAWN_OR_SUSPENDED": "A registry lists an accreditation for this service as withdrawn or suspended.",
    }
    w += [flag_text.get(f, f.replace("_", " ").capitalize() + ".") for f in c.get("flags", [])]
    if c["tier"] == "T3":
        w.append("Only the facility's own listing mentions this service; no independent record was found.")
    if c["tier"] == "R":
        w.append("A registry lists this service, but the facility's own listing doesn't mention it.")
    w.append("Availability today is not confirmed. Call ahead before travelling.")
    return w


def _shape(c, service_tag):
    """Output schema from the team's design doc (+ a few display fields)."""
    items = c.get("items", [])
    return {
        "facility_id": c["facility_id"],
        "facility_name": c["name"],
        "location": ", ".join([x for x in (c.get("city"), c.get("state")) if x]),
        "pincode": c.get("pincode"),
        "distance_km": c["distance_km"],
        "geo_confidence": c["geo_confidence"],
        "geo_label": GEO_LABEL.get(c["geo_confidence"], c["geo_confidence"]),
        "location_uncertainty_km": c.get("location_uncertainty_km"),
        "requested_service": service_tag,
        "tier": c["tier"],
        "evidence_level": TIER_LABEL.get(c["tier"], c["tier"]),
        "service_match": "direct" if any(i["kind"] == "registry" for i in items) else
                         ("self_reported" if items else "none"),
        "evidence": items,
        "evidence_text": [i["text"] for i in items],
        "source_urls": sorted({i["url"] for i in items if i.get("url")}),
        "warnings": _warnings(c),
        "rank_score": c.get("rank_score"),
        "ranking_explanation": c.get("ranking_explanation"),
    }


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    if req.service not in services.BY_TAG:
        raise HTTPException(status_code=422, detail=f"Unknown service '{req.service}'.")
    try:
        origin = geo.resolve_pin(req.pincode)
    except PinError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 1. Geography: every candidate in the radius (no truncation by service yet)
    cands = geo.nearby_facilities(origin["latitude"], origin["longitude"], req.radius_km, config.MAX_CANDIDATES)
    # 2. Evidence: LEFT JOIN; missing = tier U
    ev = EVIDENCE.get_evidence([c["facility_id"] for c in cands], req.service)
    for c in cands:
        e = ev.get(c["facility_id"], {"tier": "U", "flags": [], "items": []})
        c.update(tier=e["tier"], flags=e.get("flags", []), items=e.get("items", []))
    # 3. Rank the complete set, 4. then select
    ranked = RANKER.rank(cands, req.radius_km, req.urgency)
    top, alternatives = ranking.select(ranked)

    tiers = {}
    for c in cands:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    return {
        "query": {"service": req.service, "service_label": services.BY_TAG[req.service]["label"],
                  "pincode": origin["pincode"], "radius_km": req.radius_km, "urgency": req.urgency},
        "origin": origin,
        "n_candidates": len(cands),
        "candidates_capped": len(cands) >= config.MAX_CANDIDATES,
        "tier_counts": tiers,
        "recommendations": [_shape(c, req.service) for c in top],
        "alternatives": [_shape(c, req.service) for c in alternatives],
        "provenance": {"data_mode": config.DATA_MODE, "evidence_provider": EVIDENCE.name, "ranker": RANKER.name,
                       "placeholder": EVIDENCE.name != "table" or RANKER.name == "placeholder"},
    }


@app.post("/api/explain")
def explain_one(req: ExplainRequest):
    label = services.BY_TAG.get(req.service, {"label": req.service})["label"]
    return explain.explain(req.recommendation, label)
