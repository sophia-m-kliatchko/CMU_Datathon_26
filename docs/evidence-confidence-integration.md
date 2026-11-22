# Evidence Confidence facility–service integration

Implemented on `alice-evidence-confidence`. Pure standard-library Python; no Databricks operations, shared table changes, distance calculations or new numerical confidence model. All examples and integration tests are synthetic, not real-world validation.

## Public interfaces

```python
from evidence_confidence import build_facility_service_rows, join_geographic_candidates

rows = build_facility_service_rows(
    evidence_records, as_of=as_of,
    facility_services=[(canonical_facility_id, canonical_service)],
)
joined = join_geographic_candidates(
    geographic_candidates, rows, service=canonical_service, as_of=as_of,
)
```

`facility_services` is optional. Without it, requests are derived only from explicitly tagged service evidence. With it, empty requests produce U. Tags use the existing formatting normalization; this does not resolve synonyms or validate membership in a final team service vocabulary. Inputs must already contain reviewed canonical IDs and service mappings. No ID, match or service mapping is invented.

The builder groups all requested service evidence and non-service context for each facility before calling `evidence_tier`. Results are sorted by facility ID and service. The JSON-ready list can later become Spark rows after an agreed explicit Spark schema; this phase creates no table. Callers supply one explicit as-of date and policy per batch.

## Output contract

Grain: one row per `facility_id × service × as_of × framework_version`.

Rows retain all fields from `TierAssessment.to_dict()`: facility ID, canonical service, ISO as-of date, base/effective tiers, review status, structured flags, supporting families, distinct supporting-source-family count, supporting record count, basis, citations, explanation, record decisions, exclusions, duplicate diagnostics, non-service dimension IDs, assumptions, policy horizon and framework version (`evidence-tiers/1`). Additive fields are:

- `pending_stronger_tier`: strongest pending candidate tier strictly stronger than accepted base, or null. This is potential source semantics before identity acceptance, never verified support.
- `pending_source_families`: sorted families of pending/unknown positive records with a candidate tier, including weaker candidates. Individual IDs, source identity, temporal decisions and citations remain in decisions and records.
- `identity_review_required`: unresolved applicable positive identity associations; mirrors the existing identity-review flag for consumers.
- `flags.rejected_candidate_match`: a rejected candidate was retained diagnostically, without support credit or review promotion.
- `evidence_records`: retained serialized Evidence records, including source identity, source-record ID, facility-match decision, polarity, scope, statement, raw citation quote/locator, dates/precision, validity interval, current-listing assertion and qualifiers. This preserves certificate/provenance context rather than flattening it away.

`Evidence.source_record_id` is optional and appended to preserve existing constructor positional arguments. Registry adapters populate actual service-row/site-row IDs. Other source adapters retain their existing evidence IDs; upstream owners should provide stable source-record IDs when available. The site ID must not be substituted for a service-record ID.

Stable IDs deduplicate within source family, facility, service and scope. Conflicting versions of the same stable record fail with ValueError, requiring explicit upstream reconciliation; no version, validity date or contradictory assertion wins arbitrarily. Without stable IDs, the existing equivalent-payload deduplication remains. Distinct records from one family increase record count, never independent source-family count. Accepted/pending/negative records and quality context remain separately identifiable. Duplicate ingestion aliases are not separate support records.

Existing assessment function signatures and ranking APIs remain unchanged. New assessment fields have defaults. Consumers that enforce an exact JSON field set must accept the additive fields; framework version remains 1 because tier definitions and canonical service contract are unchanged.

## Identity examples (synthetic excerpts)

```json
{"facility_id":"synthetic-tier-facility","service":"emergency_c_section","base_tier":"T1","effective_tier":"T1","pending_stronger_tier":null,"identity_review_required":false,"supporting_record_count":1}
{"facility_id":"synthetic-tier-facility","service":"emergency_c_section","base_tier":"T3","effective_tier":"T3","pending_stronger_tier":"T1","pending_source_families":["laqshya"],"identity_review_required":true,"supporting_record_count":1}
{"facility_id":"synthetic-tier-facility","service":"emergency_c_section","base_tier":"U","effective_tier":"U","pending_stronger_tier":null,"identity_review_required":false,"supporting_record_count":0}
```

Ambiguous-only evidence remains R. Rejected-only evidence is U with a rejection diagnostic; accepted evidence is not displaced by unrelated rejected candidates. Accepted T1 plus pending T3 stays T1, while the pending family, decision and source record remain visible. Missing evidence is unknown, never proof of absence.

## Geographic integration contract

Elliot supplies one candidate per canonical `facility_id`, required `distance_km` and `geo_confidence`, and optional `location_uncertainty_km`, `distance_min_km`, `distance_max_km`. Distances are finite nonnegative kilometres or explicit null. Confidence is opaque upstream metadata (including explicit null), preserved without thresholds or reinterpretation.

The helper selects the requested service, ISO as-of date and framework version before a LEFT JOIN. It preserves candidate order and all supplied geographic fields. Evidence is nested under `service_evidence`; no eligible evidence produces a complete U assessment. Duplicate selected evidence keys or duplicate canonical candidate IDs raise ValueError instead of multiplying rows or arbitrarily picking evidence. Input keys `service_evidence` and `distance_interpretation` are reserved. An unsupported framework version is rejected so missing-evidence rows cannot silently mix policies.

`distance_interpretation` is `reported_estimate_with_bounds`, `reported_estimate_with_uncertainty`, or `reported_distance_precision_unspecified`. Supplied bounds and uncertainty are preserved; distances/bounds are never computed. Reversed bounds and reported point distances outside supplied bounds fail validation. A bare distance does not establish exactness. Geographic confidence never changes service tiers, and service evidence never upgrades geographic precision.

## Team integration requirements and deferred decisions

- William: stable registry record IDs, service-specific source semantics, current-listing/validity fields, citations and canonical facility/service mapping. Unknown source semantics remain unverified. Resolve conflicting record versions explicitly.
- Sophia: reviewed canonical identity associations, source IDs, provenance, dates and certificate scope. NQAS quality and Kayakalp historical cleanliness remain separate from service availability; historical awards are not current clinical safety, staffing or service capability evidence. Map her Silver `state`/`district` names explicitly in source adapters if downstream consumers expect `state_clean`/`district_clean`; this component changes neither schema.
- Elliot: canonical candidate IDs, duplicate resolution, confidence interpretation and distance/uncertainty units/bounds. The helper performs no geographic matching or distance computation.
- Alice/team: final canonical service vocabulary, actual Silver end-to-end fixtures, Spark schema and publication target, source currency assertions and policy/version governance. Validated live Silver integration has not been performed in this phase.

Ranking remains unchanged, including urgent capability safeguards. Distance bands, weights, two-panel presentation and final ranking policy remain deferred until team agreement and final Silver validation. This export is ready for local interface integration, not a claim that source truth, clinical operations or upstream identity matches have been validated.

## Verification

`python3 -m unittest discover -s tests -q`: 143 tests pass (117 baseline tests including two assertions updated to the corrected rejected-match contract; 26 new integration tests). Existing current/expired direct certification, current year-only NABH caveats and NCG snapshot temporal tests still pass. New tests cover pending stronger/weaker evidence, rejected-only U, record deduplication/conflicts, provenance/validity retention, source-family independence, contradictory evidence, deterministic grain, canonical input requirements, service/date filtering and geographic LEFT JOIN invariants.

`python3 -m compileall -q evidence_confidence tests` and `git diff --check` pass. Ranking implementation was compared against its pre-phase snapshot and is unchanged. No live Databricks or empirical clinical validation is claimed.

## Pre-Silver end-to-end contract (recommendation-response/1)

This section freezes **Alice's local consumer contract**. It is not evidence of team approval of geographic retrieval, ranking policy or frontend UX. The existing tier definitions, ranking helper, bands and urgent safeguards are unchanged. No new dependencies or deployment are required. The Streamlit consumer needs only ordinary JSON and does not import internal Evidence or TierAssessment objects.

### Inspection and interface differences

The existing join returns dictionaries, while `rank_candidates` requires `Candidate` with an actual `TierAssessment`. `recommendation.assessment_from_row()` bridges the builder's own serialized output back to that existing type; it does not classify source rows or change ranking. The original JSON assessment and records are preserved in the response rather than serialized from ranking's reduced metadata.

Read-only inspection of locally available `origin/Will_branch` confirmed `notebooks/05_registries_bronze_to_silver.py` emits `service_row_id`, `site_id`, `source`, `service`, `evidence_type`, `service_specific`, `status`, `evidence_date`, `valid_until`, `is_current` and provenance. `06_registry_matching.py` emits `facility_registry_links_silver` with `facility_id`, `site_id`, `match_score`, `needs_review`, `match_method`, `link_id` and review reasons. These fit the existing adapters; summary service arrays are insufficient substitutes. These refs were not fetched, so this inspection does not establish current upstream freshness.

Current shared `facilities_silver` documentation specifies lowercase UUID facility IDs and `name`; PIN centroids expose `centroid_quality`, geographic coordinates and PIN ambiguity rather than a finalized candidate response with `geo_confidence` and distance bounds. Read-only inspection of the locally available Elliot branch found no finalized ranking/website candidate API. A schema adapter and team agreement are required; no shared notebook was changed. Synthetic IDs deliberately use a `synthetic-` prefix and are validated against an explicitly synthetic inventory, not represented as valid real Silver UUIDs.

### Exact pipeline call sequence

1. Geographic provider retrieves **all eligible geographic candidates** for PIN/radius. Do not prefilter by a facility-name/service substring or take nearest 25 before enrichment. This module receives the full candidate list; it cannot detect rows omitted by upstream retrieval.
2. Source-specific adapters: `registry_match(link, reviewer_decision=...)` then `from_registry_service(service_row, match, site=optional_site)`. Use `from_facility_claim`, `from_nqas` and `from_kayakalp` for their respective scopes. Negative assertions require explicitly typed direct independent evidence, not string parsing or inference from missing rows.
3. `build_facility_service_rows(records, as_of=..., facility_services=[(candidate_id, requested_service), ...], policy=...)` aggregates all relevant evidence first.
4. `join_geographic_candidates(candidates, rows, service=..., as_of=...)` preserves every candidate once.
5. Convert the join's assessment with `assessment_from_row`, construct existing `Candidate` objects, and call unchanged `rank_candidates(..., mode=..., config=...)`.
6. Serialize the original joined evidence, geographic metadata and ranking annotations to ordinary JSON. `build_recommendation_response(request, records, candidates, today=None, ranking_config=None, tier_policy=None)` implements steps 3–6. `today` is an optional injected date for tests; absent request `as_of` resolves to the local execution date and is included in the response.

The caller owns PIN/radius retrieval and the meaning of radius under approximate location. This component neither retrieves candidates nor implements a new radius/boundary policy. Supplied out-of-radius point estimates are preserved with a warning, not silently discarded. No top-k limit is applied. An optional website display limit must be applied after enrichment/ranking and must not be misrepresented as retrieval coverage.

### Request JSON schema

Only these keys are accepted:

- `pin`: required string matching `[1-9][0-9]{5}`. Syntax validation is not proof that the PIN exists.
- `service`: required nonblank string, normalized by the existing canonical formatting function; the team vocabulary must subsequently validate it.
- `radius_km`: required finite positive number, never boolean.
- `mode`: required string `routine` or `urgent`.
- `as_of`: optional ISO calendar date string `YYYY-MM-DD`; normalized response always includes it.

Python callers may pass a date object for `as_of`; the JSON interface uses strings. Unknown keys, malformed dates and invalid request types/values fail rather than becoming defaults. A date after the execution date is not automatically rejected; callers must deliberately choose an appropriate historical/current assessment date.

### Response JSON schema

Required top-level keys:

- `contract_version`: string, `recommendation-response/1`.
- `framework_version`: string, `evidence-tiers/1`.
- `request`: normalized request object with all five fields above and ISO `as_of`.
- `candidate_count`: integer, count received before enrichment; not a claim of upstream geographic coverage.
- `recommendations`, `alternatives`: arrays of the facility object below. Every input candidate appears exactly once across both. Routine returns all in recommendations; urgent separates capability-qualified recommendations from labelled alternatives.
- `requires_review`, `provisional`: booleans from the existing ranking helper.
- `status`: existing ranking status string, `requires_review` or `provisional`.
- `ranking_explanation`, `warnings`: arrays of explanatory strings, retained for display/audit.
- `ranking_config`: object containing `distance_bands_km` (number array), `tier_priority` (six tier-to-integer entries), and `ordinal_flag_order` (flag-name string array). These expose the existing provisional configuration, not new scoring weights.

Each facility object has exactly:

- `facility_id`: canonical string; `name`: source display string or null; `service`: canonical string.
- `distance_km`, `location_uncertainty_km`, `distance_min_km`, `distance_max_km`: nonnegative finite numbers or null. Missing optional fields become explicit null, never zero.
- `location_basis`: nonblank source string or null; `geo_confidence`: original JSON-compatible upstream value or null, not converted to a service tier or a new percentage.
- `distance_interpretation`: one of the three geographic interpretation strings documented above. No distance is labelled exact by this wrapper. The existing ranker uses the supplied point distance; approximate inputs remain approximate even though the unchanged ranking explanation calls its final distance tie-break “exact distance”.
- `service_evidence`: the complete builder row defined in Output contract above, including facility/service/as-of, base/effective tiers, review status, pending fields, flags, source-family and record counts, structured citations, explanations, decisions, full evidence records with validity, and framework version. U means unknown; it is not an unavailable-service claim.
- `source_urls`: sorted unique HTTP(S) citation locators only. Local table locators remain in structured citations rather than being fabricated into public URLs. Syntactic URL validation is a separate validation warning; no link availability is tested.
- `warnings`: explanatory string array, including tier limitations and missing name/location-basis notices.
- `capability_eligible`: explicit upstream boolean or null; `capability_basis`: supplied provenance string or null. Neither is inferred from a tier, distance or service name.
- `ranking`: object with `label` (existing ranker string), `distance_band` (integer), `ordinal_evidence_flags` (integer array), and `sort_key` (JSON array of integers, an integer array and/or finite distance/null, in the existing mode-specific order). Consumers should display `ranking_explanation`; they should not reimplement sorting from these annotations.

Citation objects remain `{label: string, locator: string, quote: string}`. The per-record serialized Evidence retains `evidence_id`, `source_record_id` (string/null), `source_id`, source kind, scope, statement, service, polarity, verification, directness, observed/validity/retrieval ISO dates or null, precision, current-status boolean/null, independence group, qualifiers, citations and full match metadata. Decisions retain evidence ID, family, basis, match and temporal statuses, candidate tier/null, credited/counterevidence booleans and reasons. Flags are the existing nine named booleans, including the rejection diagnostic. The authoritative complete field set is the tested `TierAssessment.to_dict()` output; new fields require consumer-compatible version review.

### Synthetic example

Request (not a real search):

```json
{"pin":"110001","service":"emergency_c_section","radius_km":50.0,"mode":"routine","as_of":"2026-11-21"}
```

A synthetic response excerpt (the full response contains 32 facility objects and all fields listed above):

```json
{
  "contract_version":"recommendation-response/1",
  "framework_version":"evidence-tiers/1",
  "candidate_count":32,
  "provisional":true,
  "recommendations":[{
    "facility_id":"synthetic-030",
    "name":"SYNTHETIC Remote Facility",
    "service":"emergency_c_section",
    "distance_km":31.0,
    "location_basis":"site_coordinates",
    "geo_confidence":"synthetic_site_coordinates",
    "capability_eligible":null,
    "service_evidence":{
      "base_tier":"T1",
      "effective_tier":"T1",
      "review_status":"clear",
      "pending_stronger_tier":null,
      "citations":[{
        "label":"SYNTHETIC source",
        "locator":"https://example.invalid/synthetic-laqshya-30",
        "quote":"SYNTHETIC source record synthetic-laqshya-30, page 1; not real evidence."
      }]
    }
  }]
}
```

This excerpt does not imply that synthetic-030 is first in the full order. It starts as the 31st nearest candidate, is retained through enrichment and appears third under the existing provisional routine ranker. `example.invalid` links intentionally do not resolve and are not real clinical citations. Obtain the complete serializable response using `run_smoke()['response']` from `evidence_confidence.synthetic_smoke`.

### Reusable real-Silver validation

`validate_integration(canonical_facility_ids=..., canonical_services=..., evidence_records=..., evidence_rows=..., geographic_candidates=..., joined_rows=..., as_of=..., response=None, tier_policy=None, ranking_config=None)` accepts already-loaded Python objects; it never connects to Databricks. Supply the same tier policy/ranking configuration used in production. Raw Spark/SQL schema checks and conversion to the existing typed Evidence objects remain source-adapter responsibilities.

It returns JSON with `status` (`PASS`, `PASS_WITH_WARNINGS`, `FAIL`), structured `errors` and `warnings` (`code`, `message`), input/output counts, tier distribution and unknown output/joined-candidate counts, plus limitations. The team must supply authoritative facility and service inventories. It recomputes assessment/provenance rows, replays the LEFT JOIN, and optionally replays the full response instead of trusting previous reports.

Hard failures: incompatible IDs/services, conflicting source-record/evidence-ID payloads, duplicate output grain or candidate keys, tampered identity credit or tier/provenance, invalid validity intervals, future retrieval dates, invalid join schema/bounds, lost/multiplied candidates, mixed slices, altered response, unsupported availability claims or urgent recommendations lacking explicit eligibility/basis/T1/known distance. The response replay also checks citation and pending-metadata preservation.

Warnings: identical repeated ingestion IDs (deduplicated before support), missing stable source-record IDs, missing/non-public source URLs or row quotes, missing citations, incomplete validity, expired sources, future observations/not-yet-valid records, missing display names/location confidence/basis and PIN-centroid uncertainty. Missing optional fields are never converted into verified evidence; the existing classifier's conservative semantics still apply. Warnings are not auto-repaired or silently treated as production readiness.

Checklist for real data: verify canonical IDs/vocabulary against owner inventories; resolve ID collisions and conflicting versions; inspect grain and join coverage; review T1/T2/T3/U/R/X distributions and unknown counts; inspect accepted/rejected/pending links and pending stronger evidence; require traceable row citations and appropriate public URLs; verify validity/observation/retrieval semantics; examine location basis and uncertainty; confirm unknown-not-absence wording; verify urgent capability provenance. This validates loaded pipeline consistency, not source truth, clinical readiness, URL availability or completeness of upstream retrieval.

### Current validation status and handoff

Implemented and tested locally: request normalization, minimal ranking adapter, JSON response, synthetic fixtures, full-path tests and reusable validation report. Validated synthetically: 32 candidates retained, 31st-nearest T1 not lost, all six tiers, duplicate record handling, pending stronger evidence, negative overlay, full provenance/validity preservation, approximate centroid separation, deterministic ranking, serialization and unchanged urgent gates.

Not yet validated: any real Silver dataset, final service vocabulary, current upstream branch changes, actual facility matching accuracy or geographic retrieval coverage. Not deployed: Databricks, a production table or a website.

William must supply full service rows and identity links, stable record IDs, source-specific assertions and provenance/validity. Sophia must supply scoped quality/cleanliness records and explicit canonical matches; historical cleanliness awards must not become current safety/service claims. Elliot must supply the complete pre-enrichment geographic candidate universe, canonical IDs/names, distances with units, location basis/confidence and uncertainty; an approximate-radius inclusion rule remains a team decision. The frontend must accept nested structured evidence and preserve unknown/review warnings rather than label U as “not offered”.

Remaining shared decisions: canonical service vocabulary and reviewed mappings, actual geographic candidate schema and confidence meanings, radius semantics at uncertain boundaries, capability-assessment source/expiry/provenance, final ranking policy and framework/contract version governance. No two-panel UX or new ranking policy is implemented. These are integration agreements, not permission to modify teammate-owned files.

Run locally:

```sh
python3 -m evidence_confidence.synthetic_smoke
python3 -m unittest discover -s tests -q
python3 -m compileall -q evidence_confidence tests
git diff --check
```

The smoke report intentionally returns `PASS_WITH_WARNINGS` (zero hard failures) for its synthetic expired certificate, incomplete validity, missing optional self-report stable ID and repeated ingestion row. These are fixtures exercising warning behavior, not unreported source defects.

Final pre-Silver verification: **174 tests pass** (143 prior tests unchanged plus 31 new smoke/validation tests); compilation and whitespace checks pass. The synthetic smoke retains 32/32 candidates, has zero hard validation failures and five expected warning entries. Tier counts are T1=3, T2=1, T3=3, U=23, R=1, X=1. Tier/ranking implementation and configuration are unchanged in this phase. Date checks also warn about retrieval preceding observation, observation after an expiry endpoint, and an empty geographic candidate batch rather than implying retrieval coverage.

## Real Silver validation attempt — 2026-11-21

**Overall readiness: BLOCKED for real facility–service end-to-end validation.** Actual real Silver award records were read and profiled, but the canonical facility, registry-link and geographic candidate outputs are not accessible locally. No Databricks access was attempted, and no raw or synthetic records were substituted for missing Silver. The 32-candidate path remains synthetic regression evidence only.

Repository state inspected: branch `alice-evidence-confidence`, HEAD `f6a6cc020fdff26cf80cf905bde5b715069299e1`; locally available `origin/main` is `e1f23257124e3bec96b13056f58ad3d62b5c3ea4`. No remote fetch or workspace inspection was performed, so “latest” here means the main revision already pulled into this worktree, not a live upstream guarantee.

### Actual data inventory and production trace

- **Real local Silver snapshot:** `../kayakalp-validation/shared/runs/kayakalp-validation/kayakalp_silver_local.json`, 1,197 rows, 30 columns. SHA-256 `e0dbf709d6da70bf936872d817939ed8ad1bb2a08e59166c9bb264690b26940b`. This is an earlier isolated local Spark export, not a newly read Delta table or proof of the latest pipeline's contents. The sibling CSV/schema/metrics exist too; this run independently read the JSON rows rather than accepting those earlier metrics as results.
- **Missing local Silver:** `facilities_silver`, `registry_sites_silver`, `registry_services_silver`, `facility_registry_links_silver`, `nqas_silver`, `facility_geo_ready`, `pincode_centroids_silver`, `pincode_silver`, `silver_facility_claims`. No Parquet/JSONL/CSV Silver exports or local Spark warehouse/metastore were found in this worktree. The documented local runtime directory `/Users/jihyun/sparkcheck` does not exist.
- **Missing real request output:** an untruncated `geographic_candidates` export with PIN/radius context. `facility_geo_ready` is a point inventory; it does not contain request-specific distances and cannot be substituted directly for candidates.
- **Available raw inputs, not Silver:** `data/external/kayakalp_2021_22.csv` has 1,197 extracted award rows; `nqas_certified_facilities.csv` has 989 scraped rows. Registry bronze CSV counts independently read this run: LaQshya facilities 1,343/certifications 2,173; NMC colleges 911/courses 11,583; DNB hospitals 655/specialties 2,596; NCG 421; NABH 21,582; trauma 196. Reference CSVs have 71 DNB specialty rows and 103 NMC specialty rows. None of these counts is reported as a Silver count. The raw facilities CSV contains NUL bytes and ordinary Python CSV parsing failed; it was not silently cleaned and treated as `facilities_silver`.

Production chain (inspected code, not executed):

- `00_pincode_bronze_to_silver.py`: India Post input → `pincode_silver` and `pincode_centroids_silver`.
- `01_bronze_to_silver.py`: raw/Marketplace facilities + geographic checks → `facilities_silver` (`facility_id`, lowercase UUID), `silver_facility_claims` (`facility_id`, `claim_field`, `claim_position`, `claim_text`, `claim_norm`) and DQ/rejection tables. Claims do not themselves provide a reviewed canonical service/polarity mapping.
- `02_nqas_bronze_to_silver.py`: scraped listings → `nqas_silver`, keyed by `certification_id`, with department scope, `validity_from`/`validity_to`, `certification_status`, raw dates and provenance. No canonical facility link is emitted.
- `03_kayakalp_bronze_to_silver.py`: PDF-extracted award CSV → award-level Silver with `award_id`, FY, raw award, PDF page/serial, DQ and provenance. `write_output` defaults false; the default output name is `kayakalp_silver_validation`. `setup_pipeline.py` does not pass `write_output=true`, so running the setup job does not by itself establish that a persistent Kayakalp Silver output was created. No output was created in this task.
- `05_registries_bronze_to_silver.py`: six external registries → `registry_sites_silver` (PK `site_id`, source-prefixed) and `registry_services_silver` (PK `service_row_id`, FK `site_id`), using the actual 61-tag literal `SERVICES` mapping. It can skip missing sources; a successful notebook run alone does not prove complete source coverage.
- `06_registry_matching.py`: canonical facilities ↔ registry sites → `facility_registry_links_silver` (PK `link_id`, `facility_id`, `site_id`, `match_score`, `needs_review`, `match_method`), summaries and review queue. Only these explicit links can attribute registry evidence to canonical facilities. `reviewer_decision` is an optional explicit supplemental review input, not assumed populated in the output.
- `notebooks/common/pin_nearby_facilities.py`: facilities/PIN centroids → `facility_geo_ready`, then request-specific distances. `location_basis` is `facility_coordinates` or `pin_centroid`; `geo_confidence` is `high`, `medium_low_precision` or `approximate_pin_centroid`; uncertainty is supplied separately.

Default pipeline table location in the code is `workspace.datathon`; actual catalog/schema names, remote presence, permissions, runtime row counts and Delta metadata remain **NOT VERIFIED**. A local clone of notebook source is not a table export. `setup_pipeline.py` creates bronze tables and configures a remote job; it was not run because it accesses/writes Databricks.

### Real source-level results and issues

1. **PASS — Kayakalp source completeness (informational, real export).** 1,197 rows and 1,197 distinct award IDs; zero null/duplicate award IDs. All source serials match the 1,197-row extraction CSV: zero missing or extra serials. All rows are FY 2021-22, with 31 state values and PDF pages 1–18. These are award counts, not canonical facility counts.
2. **PASS — Kayakalp provenance (informational, real export).** Zero missing values in each of `source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by`, `row_citation`; zero syntactically invalid HTTP(S) URLs; zero missing PDF pages/serials. Example: `kayakalp-2021-22-1`, DISTRICT HOSPITAL, ATMAKUR, page 1, serial 1. No network URL availability test or current inspection claim was made.
3. **PARTIAL — Legacy/current geography schema (medium, snapshot compatibility).** All 1,197 snapshot rows use `state_clean`/`district_clean`; current main emits `state`/`district`. No conflicting simultaneous aliases exist in the snapshot. Map aliases explicitly at a boundary if geography is consumed; preserve original fields/provenance. The source adapter does not use these names for facility identity, so no new match was invented.
4. **BLOCKED — Canonical alignment and service coverage (high, missing upstream outputs).** All 1,197 real award rows lack canonical `facility_id` and `service`; that is expected for award-level Silver. No reviewed Kayakalp facility-link export is available. No real awards were assigned to facilities, no award became direct service evidence, and no T1/T2/T3/U/R/X distribution was fabricated. NQAS alignment is also blocked because its Silver and canonical links are absent locally.
5. **PARTIAL — Existing Kayakalp DQ (medium, upstream review, real export).** Independently recounted flags: locality 112, district repair 17, possible duplicate awards 20, health-jurisdiction ambiguity 11, facility-type conflicts 47, raw ordinal ranks 11, verified spacing corrections 2. There are ten same normalized name/geography/FY/category candidate groups containing 20 rows; these are not duplicate award IDs and were retained. Examples: `kayakalp-2021-22-54` (HWC New Lainwang, locality flag), `kayakalp-2021-22-102` (HWC APHC Champanagar, type conflict), `kayakalp-2021-22-213` (PHC Upardal, locality flag). No geography or facility ambiguity was repaired here.
6. **BLOCKED — Core data-integrity metrics (high, missing exports).** Canonical facility counts/uniqueness, duplicate facility–service grain, source-link accepted/rejected/pending counts, registry orphan counts, real contradictions, unknown service coverage and facilities without support cannot be calculated. Their values are **not zero**; they are unverified. Six-registry source/service/facility coverage cannot be inferred from bronze or prior notebook reports.
7. **FAIL — Geographic retrieval interface for evidence enrichment (high, upstream code).** The current search defaults `max_results=25`, applies `claim_norm.contains(service_keyword)` through a left-semi join, then `.orderBy(...).limit(limit_n)` before evidence enrichment. This can remove the farther independently supported facility and facilities without a self-report substring. Recommendation integration must receive the complete radius-filtered `near` candidate relation before that filter/limit. This is a proposed upstream interface change only; Elliot's notebook was not edited. Inspect the statements using `rg -n 'max_results|contains\(keyword\)|left_semi|limit\(limit_n\)' notebooks/common/pin_nearby_facilities.py`.
8. **PASS locally / BLOCKED on real records — Enrichment, ranking and JSON.** Synthetic regression retains 32/32 candidates, including the 31st-nearest T1; pending/counterevidence/citations/uncertainty survive. No real facility/service/location batch was available, so real retention, ranking distribution, response contract conformity and operational capability safety remain unverified. The ranking and tier implementation files and configuration were not changed.
9. **PARTIAL — Runtime dependencies (medium, environment).** Python 3.10.4 has pandas and pyarrow but no pytest, pdfplumber, PySpark or Delta package; the sibling repository venv has the same missing packages. The existing WSL local Spark harness cannot run here without its runtime. Dependency installation or notebook execution was not attempted. `scripts/requirements-kayakalp.txt` describes an environment; it does not establish that those packages are installed.

### Component changes supported by schema inspection

- Added `silver.adapt_registry_tables(facilities, sites, services, links, canonical_services=...)`: explicit joins through real keys, no name/substr matching, accepted/pending/rejected retained, source conflicts/orphan IDs/unknown services/duplicate link pairs reported with source, count, severity and representative examples. Source records without links remain unattached and their coverage is reported. If any hard error exists, do not publish its partial records.
- Added `silver.adapt_quality_tables(...)`: an explicit supplemental link input for NQAS/Kayakalp. Link fields are `facility_id`, `source_record_id`, `status` (`accepted`, `pending`, `rejected`, `unknown`), `method`, optional `flags`. This is Alice's adapter contract, **not a claimed existing shared output**. Empty links produce no facility evidence. Existing source adapters continue to separate quality/cleanliness from services.
- Fixed omitted stable `source_record_id` in NQAS/Kayakalp adapters using their actual `certification_id`/`award_id`.
- Added optional `Evidence.source_provenance=()` at the end of the dataclass: immutable sorted `(field, original scalar value)` pairs preserving publisher, licence, row citation, producer, source file, PDF page/serial, original dates/FY/award and other selected source metadata. JSON uses arrays of pairs; existing structured Citation objects are unchanged. This is additive within `evidence_records`, with no tier/score effect, constructor positional compatibility preserved, and no inferred missing metadata. Exact-schema consumers must accept this additive field. Real source profiling exposed the fields, while linked serialization behavior was tested with explicitly synthetic identity fixtures.
- Fixed validation recomputation cost: build the expected assessment batch once rather than sorting/rescanning every Evidence record separately for each facility–service output. Existing semantics and comparisons remain unchanged.
- Added `real_silver_validation` local-export runner and `silver.local_inventory/profile_table/read_local_export`. It reads actual files, fingerprints and profiles them, fails closed on missing/invalid/ambiguous exports, reads the actual notebook vocabulary through AST without executing the notebook, and can run the existing pipeline when complete inputs are provided. It does not create Silver, compute distance or manufacture IDs.

### Reproduction and missing-input contract

The actual invocation in this worktree was:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m evidence_confidence.real_silver_validation \
  --export-dir shared/runs/evidence-confidence/real-silver \
  --as-of 2026-11-21 \
  --kayakalp-export ../kayakalp-validation/shared/runs/kayakalp-validation/kayakalp_silver_local.json
```

Exit code **1** is expected for this run: `readiness=BLOCKED`, source profiling PASS, and real end-to-end BLOCKED due to missing inputs. The full compact profile is in ignored `shared/runs/evidence-confidence/real-silver/validation.json`. No generated data/report file was added to Git.

To unblock, provide local exports (JSONL/JSON arrays or Parquet preferred) in a caller-owned input directory, using these exact basenames:

- `facilities_silver`: unique canonical `facility_id`, name and available display/geography fields.
- `registry_sites_silver`: `site_id`, `source`, listing category/current status, `dq_flags`, row/source provenance.
- `registry_services_silver`: `service_row_id`, `site_id`, `source`, canonical `service`, evidence type/specificity/detail, status, dates, `dq_flags`, provenance.
- `facility_registry_links_silver`: `link_id`, `facility_id`, `site_id`, `match_score`, `needs_review`, `match_method`; source and explicit reviewer decision if available. Do not filter away review/rejected records before exporting.
- `geographic_candidates`: full pre-enrichment rows for one declared PIN/radius request, with canonical `facility_id`, `name`, `distance_km`, `geo_confidence`, `location_basis` and uncertainty. Request origin uncertainty also remains an upstream integration concern; no distance/bounds are invented here.
- Optional `nqas_silver`, `kayakalp_silver`, and supplemental `nqas_facility_links`/`kayakalp_facility_links`. A persisted `kayakalp_silver_validation` can be exported under the logical basename explicitly; the adapter still uses the real award IDs. Missing links remain unassigned. Reviewed facility-claim service/polarity mappings are additionally required for the self-report lane; the runner does not invent these from descriptions.

Use a single format per basename: `.jsonl`, `.json`, `.parquet` or `.csv`. CSV `dq_flags` must be a valid JSON array, not Spark's display notation. Parquet reading uses the already available optional pyarrow package; the core adapters remain standard library. Preserve nulls/date precision and identify the actual source catalog/schema, export snapshot and request context. No exact shared export location or permission is known yet; no remote permission check was made. Default remote names in pipeline code are `workspace.datathon.<table>`, but those names are **not a verified remote inventory**.

Once a real candidate batch and the four core Silver exports exist, add `--pin <PIN> --service <actual_SERVICES_tag> --radius-km <radius> [--mode routine|urgent]` to the command. The runner uses source adapters → build → LEFT JOIN → ranking adapter → unchanged ranker → recommendation JSON, then runs integrity checks and returns coverage/tier/contradiction/citation/retention statistics. A successful registry-only run remains PARTIALLY READY until quality alignment, reviewed self-reports, retrieval completeness, multiple real locations/services and capability-source agreements are validated. The runner intentionally cannot proclaim global READY from one candidate batch.

Alternative local reproduction of Silver requires provisioning the documented local PySpark/Delta/Java runtime and running notebooks 00–06 with an isolated local metastore. Those executions write local tables, so they were not substituted for inspecting existing datasets in this task. Accessing Databricks, exporting there or running `setup_pipeline.py` requires explicit authorization under the current request.

### Test results and readiness boundaries

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence*.py' -q`: **193 passed**, comprising the prior 174 tests plus 17 schema-contract/adapter tests and two actual source-export tests. Actual-export tests skip explicitly if that external snapshot is absent; a skip is not a real-data PASS.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m evidence_confidence.synthetic_smoke`: PASS_WITH_WARNINGS, 32 input/output candidates, zero hard failures and five intentional fixture warnings. This remains synthetic.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q`: unavailable, exits 1 (`No module named pytest`).
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q`: 193 successful tests plus one import error in shared `test_kayakalp`, because `pdfplumber` is absent (194 discovery entries, one error). Shared tests were not modified to hide the dependency failure.
- Compilation and `git diff --check` passed. Tier/ranking policy files and all shared preprocessing files remain unchanged; no tables or remote resources were accessed or written.

**Ready locally:** source-level profiling, real-schema adapters, explicit join contracts and synthetic regressions. **Not yet ready:** real Silver end-to-end certification, final geographic retrieval integration or deployment. Do not interpret historical FY 2021-22 cleanliness awards, quality certificates, proximity or missing evidence as current clinical safety, service availability or emergency capability.

## Downloaded CSV snapshot audit — 2026-11-22

The [downloaded Silver audit](evidence-confidence-downloaded-silver-audit.md) inventories all 14 local exports and their actual schemas/counts/sizes. Basic integrity passes with warnings; the snapshot has missing outputs, legacy fields and different link counts. Actual evidence classification and explicitly non-geographic all-facility join/ranking probes ran locally. Geographic search validation and public GitHub publication remain blocked. No Databricks job or regeneration was performed for this audit.

## facility_geo_ready handoff contract

Latest [real evidence review audit](evidence-confidence-review-audit.md) supersedes earlier availability statements for the downloaded snapshot. Evidence rules pass locally; actual geographic retrieval in this audit awaits the teammate handoff.

**Point inventory produced by Elliot (one row per canonical facility):**

- `facility_id`: nonblank string, unique, exactly matching `facilities_silver.facility_id`; no newly generated IDs.
- `name`: string (missing names must be flagged; no invented names).
- `geo_latitude`, `geo_longitude`: double or null, valid paired WGS84 coordinates. Preserve unavailable locations as null and report unlocatable coverage.
- `location_basis`: string or null; distinguish `facility_coordinates` from `pin_centroid`. Facility coordinates are source-reported points, not guaranteed exact locations.
- `geo_confidence`: upstream categorical string or null, with documented semantics. Existing notebook labels include `high`, `medium_low_precision`, `approximate_pin_centroid`; these are separate from service tiers.
- `location_uncertainty_km`: finite nonnegative double or null; null means unknown, never zero by default. Preserve uncertainty methodology/source. Retain source PIN, coordinate status and DQ flags for lineage.

Downloaded facilities use `latitude_clean`, `longitude_clean`, `pincode_clean`, `state_clean`; an explicit upstream adapter must map these to retrieval's expected names. Do not silently substitute raw coordinate columns. Confirm actual produced schema rather than assuming these proposed output fields already exist.

**Computed by geographic retrieval for each request, not required in the point inventory:** `distance_km` (finite nonnegative numeric or null), optional `distance_min_km`/`distance_max_km` (same type; ordered and containing the point estimate), query PIN/origin, radius, origin basis/uncertainty and candidate selection diagnostics. Bounds must have a defensible method; never invent them. Preserve point uncertainty separately from origin uncertainty. Supply the entire eligible radius candidate set before top-25 truncation or service-substring filters. Report unlocatable/excluded rows separately; do not invent distances.

**Supplied by the request/evidence layer:** canonical `service` string, `as_of` date and `framework_version`. A service identifier is not required in `facility_geo_ready`, whose grain is facility, not facility–service. Pass service explicitly to `join_geographic_candidates`; any optional candidate service field must agree with the request. Evidence rows must be unique by facility/service/date/version. No service mapping is inferred from names or geographic proximity.

The actual Python join signature is `join_geographic_candidates(candidates, evidence_rows, *, service, as_of, framework_version='evidence-tiers/1')`. Its minimal candidate fields are `facility_id: str`, `distance_km: int|float|None`, and present `geo_confidence` (opaque JSON metadata or null). For a meaningful recommendation handoff also supply name, location basis and uncertainty above. Coordinates are retrieval inputs; the join does not require them or compute distances. Optional distance bounds are checked. Duplicate candidate IDs or duplicate evidence slice keys fail; missing evidence produces U. Candidate order and metadata survive the LEFT JOIN. Recommendation JSON preserves location basis, confidence, distance uncertainty and structured evidence; it does not currently export point coordinates.

Read-only local audit and controlled-fixture regression commands are documented in the linked audit. Fixture distances are explicitly labelled and are **not real radius-search validation**. No shared geographic implementation was changed.

See also `docs/recommendation-pipeline.md` for the end-to-end entrypoint.

## Geographic producer → join contract (2026-11-22)

Producer: teammate notebook `07_pin_nearby_facilities.py` (read-only). Repo copy `notebooks/common/pin_nearby_facilities.py` (sha256 `21adb9d4…`) uses `distance_km <= radius`; the newer downloaded version (sha256 `848f182e…`, not committed here) uses `uncertainty_adjusted_distance_km = max(distance_km − location_uncertainty_km, 0) <= radius` and widens the bounding box by the table-wide max uncertainty. `GeographicProducer` evaluates either version's own expressions locally (no Spark); `--geography-notebook` selects the file. The Spark-only `max_uncertainty` aggregate is recomputed locally only if its source text matches the inspected definition, otherwise construction fails.

`to_join_candidate(row)` copies, never recomputes:

| Producer `near` column | Join/response field |
|---|---|
| `facility_id`, `name`, `city`, `state`, `pincode`, `coord_status`, `dq_flags` | same |
| `distance_km` (haversine from query PIN centroid, rounded 2 dp) | `distance_km` |
| `location_basis`, `geo_confidence`, `location_uncertainty_km` | same |
| `uncertainty_adjusted_distance_km` (new version only) | `distance_min_km` |
| — | `distance_max_km` absent (producer emits no upper bound; none invented) |

Rules: every radius-eligible row is passed on (no `max_results`, no `service_keyword` semi-join); `limit`/display truncation happens only after `build_recommendation_response`. Validation re-runs the producer rule with box filters skipped and requires zero box omissions. Facilities with no point (2 of 9,989 in the downloaded bundle) are unsearchable by distance and are reported, not ranked.
