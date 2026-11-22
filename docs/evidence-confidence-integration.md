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
