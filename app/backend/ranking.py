"""
Ranking step: order the full candidate set (after evidence enrichment), then pick the top recommendations
and nearby alternatives.

PLUG-IN POINT. The ranking model belongs to the modelling team. Their ranker must provide:

  rank(candidates: list[dict], radius_km: float, urgency: str) -> list[dict]

Each candidate already has: distance_km, location_uncertainty_km, geo_confidence, tier, flags, items.
The ranker adds "rank_score" (0-100, higher = better) and "ranking_explanation" (one sentence) and
returns the list sorted best-first. Swap it in get_ranker() via the RANKER setting.

The PLACEHOLDER below is deliberately simple and transparent (evidence strength + distance +
geographic uncertainty, as in the pipeline diagram). It is NOT the team's scoring model.
"""

from . import config
from .evidence import TIER_ORDER

TIER_POINTS = {"T1": 100, "T2": 75, "T3": 50, "R": 40, "U": 10, "X": 0}


class PlaceholderRanker:
    name = "placeholder"

    def rank(self, candidates, radius_km, urgency):
        distance_weight = 60 if urgency == "emergency" else 35
        for c in candidates:
            ev = TIER_POINTS.get(c["tier"], 0)
            d_pen = distance_weight * min((c["distance_km"] or 0) / max(radius_km, 1), 1.0)
            u_pen = min(float(c.get("location_uncertainty_km") or 0), 10.0)
            score = max(0.0, min(100.0, ev - d_pen - u_pen))
            c["rank_score"] = round(score, 1)
            c["ranking_explanation"] = (
                f"Placeholder ranking: evidence tier {c['tier']} ({ev} pts), minus {d_pen:.0f} for distance "
                f"({c['distance_km']:.1f} km of {radius_km:g} km) and {u_pen:.0f} for location uncertainty"
                + (" (emergency: distance weighted more heavily)." if urgency == "emergency" else "."))
        return sorted(candidates, key=lambda c: (-c["rank_score"], TIER_ORDER.get(c["tier"], 9), c["distance_km"]))


def get_ranker():
    return PlaceholderRanker()


def select(ranked):
    """Top recommendations from facilities with some positive evidence, then nearby alternatives."""
    with_evidence = [c for c in ranked if c["tier"] in ("T1", "T2", "T3", "R")]
    top = with_evidence[: config.TOP_N]
    chosen = {c["facility_id"] for c in top}
    alternatives = sorted([c for c in ranked if c["facility_id"] not in chosen],
                          key=lambda c: (TIER_ORDER.get(c["tier"], 9), c["distance_km"]))[: config.ALTERNATIVES_N]
    return top, alternatives
