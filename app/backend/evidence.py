"""
Evidence step: for each candidate facility and the requested service, return a tier, flags and citations.

FALLBACK ONLY. The real evidence and ranking come from Alice's package (backend/engine.py,
EVIDENCE_PROVIDER=evidence_confidence). This placeholder stays for demos and mock mode
(EVIDENCE_PROVIDER=placeholder), with this interface:

  get_evidence(facility_ids: list[str], service: str) -> dict[facility_id -> Evidence]

  Evidence = {
    "tier": "T1" | "T2" | "T3" | "R" | "U" | "X",
    "flags": [str],                 # e.g. "MATCH_NEEDS_REVIEW", "CERTIFICATION_EXPIRED"
    "items": [ {"kind": "self_reported" | "registry", "text": str, "source": str, "url": str | None,
                "current": bool | None} ],
    "provider": "placeholder",
  }
  Facilities missing from the dict are treated as tier "U" (no evidence), per the pipeline diagram
  ("LEFT JOIN on canonical facility ID + service; retain facilities with no evidence as U").

The PLACEHOLDER tiers are provisional and only for building/demoing the interface:
  T1  facility claims the service AND a confidently matched registry certifies/designates that exact
      service and it is current (e.g. current LaQshya maternity OT, NABH dialysis centre)
  T2  facility claims it AND there is other independent registry evidence (specialty training,
      expired certification, network membership, or a match that needs review)
  T3  only the facility's own claim
  R   a registry says yes but the facility doesn't claim it
  X   the only registry evidence has been withdrawn/suspended and the facility doesn't claim it
  U   no evidence either way
"""

from . import config, db, services

TIER_ORDER = {"T1": 0, "T2": 1, "T3": 2, "R": 3, "U": 4, "X": 5}
# Labels follow Alice's tier definitions (app/evidence_confidence/TIERS.md).
TIER_LABEL = {
    "T1": "Current certification", "T2": "Expired certification", "T3": "Indirect or self-reported",
    "R": "Match under review", "U": "No evidence found", "X": "Contradicted",
}


def _ids_param(facility_ids):
    return ",".join(facility_ids)


class PlaceholderEvidence:
    name = "placeholder"

    def get_evidence(self, facility_ids, service):
        if not facility_ids:
            return {}
        svc = services.BY_TAG.get(service)
        pattern = "|".join(svc["synonyms"]) if svc else r"\b" + service.replace("_", " ") + r"\b"
        ids = _ids_param(facility_ids)

        claims = db.query(
            f"""SELECT facility_id, collect_set(claim_text) AS texts
                FROM {config.t('silver_facility_claims')}
                WHERE array_contains(split(:ids, ','), facility_id) AND claim_norm RLIKE :pat
                GROUP BY facility_id""", {"ids": ids, "pat": pattern})
        reg = db.query(
            f"""SELECT l.facility_id, l.source, l.match_score, l.needs_review, l.site_name,
                       v.evidence_type, v.service_specific, v.is_current, v.evidence_detail, v.source_url,
                       v.source_name, v.dq_flags
                FROM {config.t('facility_registry_links_silver')} l
                JOIN {config.t('registry_services_silver')} v ON v.site_id = l.site_id
                WHERE array_contains(split(:ids, ','), l.facility_id) AND v.service = :svc""",
            {"ids": ids, "svc": service})

        out = {}
        claim_by = {r["facility_id"]: db.as_list(r["texts"])[:3] for r in claims}
        reg_by = {}
        for r in reg:
            reg_by.setdefault(r["facility_id"], []).append(r)

        for fid in set(claim_by) | set(reg_by):
            items, flags = [], []
            for txt in claim_by.get(fid, []):
                items.append({"kind": "self_reported", "text": f"Facility lists: “{txt}”",
                              "source": "Virtue Foundation facility record", "url": None, "current": None})
            strong = other = withdrawn = 0
            for r in sorted(reg_by.get(fid, []), key=lambda r: (r["needs_review"], not r["service_specific"],
                                                               r["is_current"] is not True)):
                dq = db.as_list(r["dq_flags"])
                items.append({"kind": "registry", "text": r["evidence_detail"], "source": r["source_name"],
                              "url": r["source_url"], "current": r["is_current"],
                              "match": {"score": r["match_score"], "needs_review": r["needs_review"],
                                        "registry_name": r["site_name"]}})
                if r["needs_review"]:
                    flags.append("MATCH_NEEDS_REVIEW")
                if "LISTING_NOT_CURRENT" in dq:
                    withdrawn += 1
                    flags.append("LISTING_WITHDRAWN_OR_SUSPENDED")
                elif r["is_current"] is False:
                    flags.append("CERTIFICATION_EXPIRED")
                if not r["needs_review"] and r["service_specific"] and r["is_current"] is True:
                    strong += 1
                else:
                    other += 1
            claimed = bool(claim_by.get(fid))
            n_reg = len(reg_by.get(fid, []))
            if claimed and strong:
                tier = "T1"
            elif claimed and n_reg:
                tier = "T2"
            elif claimed:
                tier = "T3"
            elif n_reg and withdrawn == n_reg:
                tier = "X"
            elif n_reg:
                tier = "R"
            else:
                tier = "U"
            out[fid] = {"tier": tier, "flags": sorted(set(flags)), "items": items[:8], "provider": self.name}
        return out


def get_provider():
    return PlaceholderEvidence()
