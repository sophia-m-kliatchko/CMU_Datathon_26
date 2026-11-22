# Recommendation pipeline (`recommendation-pipeline/1`)

Local, Spark-free end-to-end entrypoint over a downloaded Silver bundle. It adds no ranking policy:
the order is the existing `rank_candidates` routine order (tier priority, distance band, ordinal
caveat flags, exact distance, `facility_id`). The website's existing call
(`build_recommendation_response`, `recommendation-response/1`) is unchanged and still supported.

```python
from evidence_confidence.pipeline import load_bundle, recommend
bundle = load_bundle('<silver_dir>', geography_notebook='<path>/07_pin_nearby_facilities.py')  # ~8 s, once
result = recommend(bundle, {'service': 'dialysis', 'pincode': '400001', 'radius_km': 50,
                            'max_results': 5, 'max_alternatives': 5})
```

**Required tables** (CSV, `escapechar="\\"`): `facilities_silver`, `pincode_centroids_silver`,
`registry_sites_silver`, `registry_services_silver`, `facility_registry_links_silver`.
**Optional:** `silver_facility_claims` (self-reported claims), `registry_match_review` (reviewer
decisions), `nqas_silver`, `kayakalp_silver`. Missing optional tables are listed in `missing_optional_tables`.
Dependencies: Python ≥3.10 standard library only (`pyarrow` only for `geographic_validation` artifacts).

**Request:** `service` (notebook 05 tag), `pincode`, `radius_km`, `max_results` (1–50, default 5),
`max_alternatives` (0–50, default 5), optional `mode` (`routine`|`urgent`), `as_of` (ISO date),
`include_self_reported_claims` (default true).

**Order of operations:** validate PIN → every facility passing the producer radius rule
(`max(distance − uncertainty, 0) ≤ radius` in the newer 07 notebook; no top-K, no keyword filter)
→ registry evidence + mapped self-reported claims for those facilities → aggregation and LEFT JOIN
(missing ⇒ U) → full ranking → `recommendations` = ranks 1..K, `alternatives` = ranks K+1..K+A
of the same ranking (no duplicate IDs; checked).

**Response:** `status` (`provisional` | `requires_review` | `invalid_location` | `no_candidates` |
`unknown_service`), `query` (requested + canonical service, PIN, radius, query centre lat/lon,
centroid quality, ambiguity, radius rule), `geographic_candidates`, `ranked_candidates`,
`tier_distribution`, `coverage` (independently corroborated / self-reported only / pending review /
PIN-centre locations / centre outside radius), `claim_mapping`, `ranking_explanation`,
`ranking_config`, `recommendations`, `alternatives`, `nearest_first_top`, `warnings`.
Each facility: `rank`, `distance_only_rank`, `facility_id`, `name`, `city`, `district`, `state`,
`pincode`, `address`, `latitude`, `longitude`, `distance_km`, `distance_min_km`, `location_basis`,
`geo_confidence`, `location_uncertainty_km`, `evidence_tier`, `base_tier`, `review_status`,
`pending_stronger_tier`, `supporting_source_families`, `evidence_basis`, `flags`, `contradiction`,
`self_reported_claims[]`, `registry_evidence[]`, `pending_identity_review[]` (each with statement,
credited, match/temporal status, dates, citation), `independently_corroborated`,
`self_reported_only`, `source_urls`, `quality_signals` (NQAS/Kayakalp reported *unavailable*: no
canonical facility link), `ranking` (label, band, flags, sort key), `explanation[]`, `warnings[]`.
Absent values are `null`; nothing is inferred.

**Self-reported claim mapping (`service-claims/1`, `service_claims.py`)** — PROVISIONAL, needs team
approval. Only `dialysis` (`dialysis`, `haemodialysis`, `hemodialysis`, `peritoneal dialysis`) and
`emergency_c_section` (`c-section`, `caesarean`/`cesarean`, `LSCS`). Nephrology ≠ dialysis;
obstetrics/maternity ≠ C-section. Claims containing negation/qualifier words (no, not, without,
referred, planned, upcoming, shut down…) are skipped, never treated as counterevidence. All mapped
claims are self-reported and cap at T3; C-section claims carry `CLAIM_DOES_NOT_STATE_EMERGENCY`.
Other services get no claim evidence (`claim_mapping.reason = service_not_in_claim_mapping`).

**Not verified:** current availability, staffing, emergency capability (urgent mode never confirms a
facility), road distance, ground-truth locations, ranking quality (no labelled data).

## Website entrypoint

```python
from evidence_confidence.pipeline import recommend_facilities
result = recommend_facilities('dialysis', '400001', 50, max_results=5, max_alternatives=5,
                              silver_dir='/path/to/silver_dataset')   # or bundle=load_bundle(...), or EVIDENCE_SILVER_DIR
```
Returns the `recommendation-pipeline/1` dict above (JSON-safe). The bundle is loaded once per
directory and cached in-process; later calls only do the per-query work. Bad PIN / unknown service
come back as `status`; bad argument types (e.g. `max_results=0`) raise `ValueError`. Extra keyword
options: `mode`, `as_of`, `include_self_reported_claims`. `geography_notebook=` (or
`EVIDENCE_GEO_NOTEBOOK`) overrides the notebook; since the merge of `origin/Elliot_New_Branch` the default
is `notebooks/07_pin_nearby_facilities.py` (uncertainty-aware radius rule). Local CSV bundle only: on Databricks the
same tables must be exported or read into dicts first (not yet verified there).

## Website (`origin/website`, `app/backend/`) — handoff, files not edited

1. **Radius rule.** `geography.nearby_facilities` keeps `distance_km <= :radius` and builds the bounding
   box from `radius_km` alone. The pipeline rule is
   `greatest(distance_km - coalesce(location_uncertainty_km, 0), 0) <= :radius`, with the box widened by
   `max(location_uncertainty_km)` over `facility_geo_ready`. Re-measured 2026-11-22 on the downloaded
   Silver data: the old rule drops 110001: 12, 400001: 3, 600001: 2 candidates, all `pin_centroid`
   facilities whose centre lies beyond 50 km. Also return `distance_min_km` (= the left-hand side).
2. **Cap.** `LIMIT MAX_CANDIDATES` (5000) is applied before evidence; fine for 50 km queries (max seen
   700) but `candidates_capped` must stay visible.
3. **Selection policy differs.** `engine.shape()` (routine) shows only T1–T3 as recommendations and
   reorders alternatives (non-U first). The pipeline policy is ranks 1..K and K+1..K+A of one ranking.
   Either keep `shape()` (it consumes `recommendation-response/1`, unchanged) or call
   `recommend_facilities` and map its fields — needs a team decision.
4. **No adapter needed** for the current website: `build_recommendation_response` and
   `adapt_registry_tables` signatures and contract are unchanged (tested).

## Merging `origin/Elliot_New_Branch` (not done; needs approval)

Verified 2026-11-22 by three-way `git merge-file` simulation in a scratch directory (worktree untouched),
`origin/Elliot_New_Branch` @ `385b0db`:
- Committed HEAD merges with no conflicts (`git merge-tree`). Conflicts come only from this
  worktree's **uncommitted** edits, so commit them first.
- `run_pipeline.py`: **merges cleanly** (Elliot's `07` row and `00 → 07` text plus this branch's `03` params).
- `setup_pipeline.py`: **one conflicting hunk** after `step_06_matching`. Resolve by keeping both:
  `step_07_nearby` (Elliot's params) depends on `step_06_matching`; `validate_silver` depends on
  **`step_07_nearby`**. This branch's step_03 Kayakalp params and the 00-07 job name merge cleanly.
  A checked resolution (compiles, no markers) is at
  `/private/tmp/claude-501/-Users-jihyun-Desktop-cmu-F26-datathon-CMU-Datathon-26/6dc06b67-7a55-4406-a483-943054191045/scratchpad/mergesim2/setup_pipeline.py.resolved`.
- Elliot's commit is a **rename**: `notebooks/common/pin_nearby_facilities.py` disappears after the
  merge. `default_notebook()` and the tests already prefer `notebooks/07_pin_nearby_facilities.py`.
Steps (need approval): commit this branch's work → `git merge --no-ff origin/Elliot_New_Branch` →
resolve `setup_pipeline.py` as above → `python3 -m unittest discover -s tests` (pytest is not
installed here) → commit.

**Notebook location.** With no `geography_notebook` argument, `default_notebook()` uses `notebooks/07_pin_nearby_facilities.py` (Elliot_New_Branch, sha256 `848f182e…`, identical to the version validated here) and falls back to the legacy `notebooks/common/pin_nearby_facilities.py`.
