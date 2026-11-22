# Evidence Confidence component

## Primary interface: categorical evidence tiers

The deterministic Evidence Tier Framework is now the primary service-evidence output. See [tier implementation and Silver integration contract](../evidence_confidence/TIERS.md) for exact T1/T2/T3/U/R/X rules, temporal corrections, structured flags, source-family semantics, and the isolated provisional ranking helper. Call `evidence_tier(facility_id, service, evidence_records, as_of)` directly, or read the additive `assess(...).service_evidence` result. No numerical score assigns tiers.

The numerical baseline below is preserved for backward compatibility and internal comparison; it is **not** the primary service-evidence interface. Existing fields and callers remain available. Validity intervals now take precedence over issuance age, and year-only/NCG snapshot dates no longer masquerade as exact service-event dates.

## Status and purpose

Alice's modular baseline is implemented on `alice-evidence-confidence` in the isolated `evidence-confidence` worktree, based on current main `b5aba4dc5c4e6032c3dbe3fa3da56d472cbd4a02`. It runs entirely in standard-library Python 3.10+ with no Spark, database, network, model endpoint, credentials or new packages. It does not modify Silver, match facilities by name, infer service tags from text, or write tables. No teammate code or data is changed.

The legacy comparison result is an **interpretable 0-100 supporting-evidence score**, a category, an evidence status, citations and per-record explanations. It is **not a statistically calibrated probability, service-availability guarantee, clinical quality rating or recommendation**. A low score means weak positive evidence under this policy, not poor care or confirmed absence. No score (`None`/JSON `null`) means no scoreable positive support; missing sources are not negative evidence.

Separate outputs:

- `service_availability`: support for the requested canonical service at the supplied facility.
- `quality_evidence`: support for scoped quality/certification assertions, not overall clinical quality.
- `cleanliness_evidence`: support for historical cleanliness-award assertions.
- `identity_evidence`: support for explicit registry identity/listing assertions, when supplied.
- `location`: separately preserved location basis/uncertainty; it never adds service or quality points.

These scores must not be summed into an overall facility score. Facility-match confidence is also an explicit component of **each** evidence contribution; a facility ID alone is not independent proof of the association.

## Files and entry points

- `evidence_confidence/models.py`: typed immutable evidence, association, citation and result contracts.
- `evidence_confidence/policy.py`: validated configuration and deterministic policy fingerprint.
- `evidence_confidence/engine.py`: pure `assess()` function and lineage-aware scoring.
- `evidence_confidence/adapters.py`: read-only adapters for team rows, accepting dictionaries or Spark Rows.
- `config/evidence-confidence.json`: every default weight, reliability prior, cap and threshold.
- `evidence_confidence/examples.py`: ten fictional, realistic scenarios, explicitly marked synthetic.
- `tests/test_evidence_confidence.py`: offline semantic regression tests.

Run from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_evidence_confidence.py' -v
python3 -m evidence_confidence.examples --policy config/evidence-confidence.json
python3 -m evidence_confidence.examples --full
python3 -m compileall -q evidence_confidence tests
git diff --check
```

Default examples now print categorical tiers/flags/source citations first; `--full` emits every component, source statement, citation, qualifier, policy value, version and fingerprint as JSON. They do not assert facts about real facilities or registries. Generated output is not committed.

## Independent public interface

```python
from datetime import date
from evidence_confidence import (
    Citation, Directness, Evidence, FacilityMatch, MatchStatus, Polarity,
    Policy, Scope, SourceKind, Verification, assess,
)

# Fictional example only. Real callers supply actual source citations/observations.
match = FacilityMatch(
    facility_id="synthetic-facility-001",
    status=MatchStatus.ACCEPTED,
    confidence=0.95,             # Explicit upstream heuristic, NOT a probability.
    method="reviewed_name_and_address",
    reference_id="synthetic-source-record-001",
)
evidence = Evidence(
    evidence_id="synthetic-evidence-001",
    source_id="synthetic-independent-source",
    source_kind=SourceKind.INDEPENDENT_CHECK,
    scope=Scope.SERVICE,
    service="dialysis",
    statement="Synthetic dated documentary assertion about dialysis at this branch.",
    match=match,
    polarity=Polarity.SUPPORTS,
    verification=Verification.INDEPENDENT,
    directness=Directness.DIRECT,
    observed_on=date(2026, 10, 21),
    retrieved_on=date(2026, 11, 21),
    citations=(Citation("Synthetic source", "fixture://source/001", "Synthetic exact quote."),),
)
result = assess(
    "synthetic-facility-001", "dialysis", [evidence],
    as_of=date(2026, 11, 21),
    policy=Policy.from_json("config/evidence-confidence.json"),
)
print(result.service_availability.score)
print(result.service_availability.status)
print(result.to_json(indent=2))
```

`as_of` is mandatory and reproducible; no implicit wall-clock time changes a score. ISO dates are parsed by adapters; the generic typed interface takes `date`, not free text/datetime. Missing dates stay missing. Malformed types, non-finite numbers, conflicting duplicate evidence IDs, invalid enums and incompatible join keys raise `ValueError` rather than silently filling in evidence. Invalid/future temporal intervals remain visible as zero-credit contributions. Future retrieval dates also block credit for backdated runs, preventing look-ahead evidence leakage.

`Evidence` requires a unique ID, stable source ID/kind, scope, source statement and explicit `FacilityMatch`. Service evidence additionally requires a canonical service tag. Optional fields hold assertion polarity (`supports`, `contradicts`, `unknown`), verification (`self_reported`, `independent`, `inferred`, `unknown`), directness, observed/validity/retrieval dates, date precision, source-current hint, source-lineage group, citations and qualifiers. Association states are `accepted`, `pending`, `rejected`, `unknown`; a missing numerical association confidence is not silently set to 1.

The generic engine trusts **supplied structured source assertions and linkage decisions**, not arbitrary medical prose. The service matcher must resolve synonym mapping, negation, branch identity and whether a claim is direct. `canonical_service()` only case-folds and normalizes spaces/hyphens to underscores; it never infers nephrology → dialysis, obstetrics → emergency C-section, broad cancer care → radiotherapy, or matches `ent` inside `equipment`. The baseline accepts evolving canonical tags without hardcoding an ontology. Supply the same reviewed tag on the request and source assertion; different service/facility evidence is explicitly excluded with reasons.

## Legacy numerical scoring policy and interpretation

The defaults are explicit engineering choices for a reviewable baseline. They were **not fitted, statistically validated or clinically calibrated**. Teams must agree or change them, then evaluate on labeled facility/service pairs before interpreting thresholds operationally. Changing any parameter changes the SHA-256 policy fingerprint included in every result; retain the full policy snapshot alongside outputs.

For an eligible evidence record:

1. Reliability `R` comes from its source kind, optionally overridden by stable `source_id`: self-report **0.45**, government registry **0.85**, accreditation **0.85**, independent check **0.90**, network **0.60**, unknown **0.20**. Authority increases documentary reliability, not the scope of the assertion.
2. Association `M` is the explicit upstream 0-1 heuristic match confidence. An accepted association with missing/zero confidence, or a rejected/unknown association, gets no attribution credit. This module does not invent match confidences from name/PIN/distance.
3. In-force explicit certification intervals are current regardless of issue age. Outside those intervals, legacy recency `T = 2^(-age_days/365)` comes from **observed event date**, with half-life configurable. An unknown event date uses **0.35**. An expired/not-current source multiplies `T` by **0.20**, retaining historical support. Retrieval dates never refresh events. Validity end is inclusive; dates override frozen source-current flags when a validity end is supplied by adapters. An expired certificate is not a negative service assertion.
4. Base strength is the weighted geometric mean:
   `G = exp((0.40*ln(R) + 0.35*ln(M) + 0.25*ln(T)) / sum(weights))`.
   Zero reliability, match or temporal credit remains a hard zero even if someone configures that component weight to zero.
5. Directness multiplies strength by **1.0** direct, **0.50** indirect or **0.25** context. Pending/identity-ambiguous associations multiply by **0.25** and cap at **0.25**; missing citation multiplies by **0.25** and caps at **0.25**. Conditional certification multiplies by **0.80**. Self-reports cap at **0.55**, indirect/unverified evidence at **0.60**, unknown/approximate dates at **0.45**, stale/expired evidence at **0.40**. Caps are on the 0-1 contribution scale.

Identity-review flags include ambiguous matches, source branch/head-office ambiguity, conflicting merged-row geography, health jurisdictions and explicitly flagged empty match keys. They prevent independent verification even if the original link was labeled accepted. Unrelated DQ flags are preserved rather than blanket-rejecting a facility. Service-designation, training, membership, department-unstated and LoP qualifiers cannot be promoted to direct service verification by a `service_specific=true` field alone.

Within each declared source lineage, take the **maximum positive strength** and **maximum contrary strength** separately. Do not sum courses, certificates, repeated service rows or both Kayakalp categories from the same source. Preserve all citations, records and same-lineage contradictions. Across distinct lineages:

```text
P = strongest_positive + 0.15 * (1 - strongest_positive)
                         * (1 - product(1 - other_positive_strengths))
N = same bounded aggregation applied to explicit contrary assertions
supporting_evidence_score = 100 * P * (1 - 1.0 * N)
```

No positive strength gives `score=None`, even when explicit counterevidence exists. `N` is returned separately; it is not a probability of absence. Material counterevidence (`N >= 0.20`) yields `conflicting`, caps the score at **35**, and suppresses the independent-current-support label. Weak counterevidence still reduces the score and remains visible. Missing rows, empty service arrays, registry non-membership, expiry and poor cleanliness are never converted into contrary service assertions.

Default source groups are `virtue_foundation`, each `registry:<source>`, `nhsrc:nqas`, and `nhsrc:kayakalp:<FY>`. These are conservative provenance groupings, not a statistical proof of independence. Callers must share `independence_group` for syndicated copies or common underlying documents. The engine cannot infer hidden correlation from URLs. Legitimate distinct source assertions are retained even when only the strongest affects the aggregate.

Categories are **unknown** for no positive score, **low** below 40, **medium** at/above 40, **high** at/above 70 only with the `independently_supported` status. That status additionally requires direct independent evidence, an accepted unambiguous match with `M >= 0.85`, exact observed date no more than 365 days old, unexpired/effective dates, citations, and effective strength at least 0.65. Self-report/network/unknown sources cannot qualify. Custom numeric weights/caps do not bypass the independent-status gate for the high category. Documentary support does **not** prove current staff, equipment uptime, emergency readiness, appointments or operating availability.

Other statuses are `self_reported`, `indirect_or_unverified`, `historical_only`, `needs_review`, `counterevidence_only`, `conflicting`, and `unknown`. Always display the status and explanation with a score; never show a bare number as a probability or infer unavailability from `None`/low support. Counterevidence-only cases keep a null positive score. Quality/cleanliness/identity lanes use the same transparent support mechanics, but describe confidence in their scoped source assertions rather than care quality or available services.

## William: registry interface

Inspected current `Will_branch` **`ab113d724fe6709e9a090295ba6279995a2d533e`**, including `docs/registries-silver.md`, `notebooks/05_registries_bronze_to_silver.py` and `notebooks/06_registry_matching.py`, before implementation. No stable application/scoring API exists in current main; the integration interface is currently the documented row contracts.

Use `registry_services_silver` joined to `facility_registry_links_silver` by **`site_id`** (and the source/site consistency checks), preserving these fields:

- Service row: `service_row_id`, `site_id`, `source`, `service`, `evidence_type`, `service_specific`, `evidence_detail`, `status`, `evidence_date`, `valid_until`, `is_current`, `dq_flags`, `row_citation`, `source_name`, `source_url`, `retrieved_on`.
- Link row: `facility_id`, `site_id`, `match_score` (0-100), `needs_review`, `match_method`; retain `review_reason` externally and use explicit `reviewer_decision` confirm/reject where reviewed. The adapter divides the heuristic `match_score` by 100; this does not calibrate it. Missing linkage fields do not become accepted. Human confirmation does not fabricate a missing numeric confidence. A supplied decision is caller-owned; it does not write `registry_match_review`.
- Optional site row: matching `site_id`, `source`, `listing_category`, `dq_flags`. Pass it when available to preserve head-office, repaired-name and other uncertainty. It must refer to the same source/site; a general accreditation/empanelment row cannot be consumed as service evidence.

```python
from evidence_confidence.adapters import registry_match, from_registry_service
link = registry_match(link_row)  # Or explicit caller-reviewed reviewer_decision="confirm".
e = from_registry_service(service_row, link, site=site_row)
result = assess(link.facility_id, service_row["service"], [e], as_of=as_of)
```

NMC/DNB course-to-service tags remain **indirect**. NCG membership remains indirect/network support, including for broad cancer care; it does not establish radiotherapy or equipment inspection. Trauma sanctions remain indirect/designation support: notebook 05's parliamentary answer date is not the original sanction date or current functionality verification, so this adapter leaves the service event date unknown. LoP, department-not-stated and sanctioned-not-functional qualifiers block direct verification. Service-specific LaQshya/NABH assertions can provide independent documentary support when all identity/date/scope gates pass; maternity OT certification still is not a real-time emergency C-section guarantee. NABH's year-only dates remain approximate.

Use `from_registry_site(site_row, match)` for general quality/accreditation or identity/listing evidence. Scheme empanelment and unspecified AYUSH listings stay identity/listing assertions rather than being relabeled hospital accreditation. It never creates a requested-service assertion. `facility_registry_summary_silver.services_evidenced` is **insufficient** for scoring because it drops source-row dates, scope, qualifications and citations. Do not promote that aggregate array directly to verified services.

Missing source tables, missing joins or an empty registry-service array yield no evidence, never an invented negative record. Do not run William's preprocessing/writers as part of this baseline.

## Virtue Foundation self-reported services

Inspected `silver_facility_claims` in notebook 01: `facility_id`, `claim_field`, `claim_position`, verbatim `claim_text`, `claim_norm`. Claim fields are specialties, capability, procedure and equipment. `source_urls` were removed from `facilities_silver`; recover actual external URLs from Bronze if required. Completeness scores and equipment counts are not independent service verification.

`from_facility_claim(row, service=<reviewed tag>, polarity=<explicit interpretation>, direct=<bool>, observed_on=<event date or None>, citations=<actual citations>, facility_flags=<facility DQ flags>)` preserves the exact claim. The canonical source association is to that row's existing `facility_id`, not a new cross-source facility match. Pass merged-identity conflict flags; a source row can represent mixed branch claims after upstream merging. Equipment and specialties stay indirect even if `direct=True` is supplied. Free-text descriptions require explicit generic `Evidence` and reviewed negation/scope interpretation.

There is no automatic text classifier here. "Referred out for dialysis", "no ICU", or a broad specialty is not automatically interpreted as an affirmative service claim. The caller supplies `polarity=UNKNOWN` when not resolved; only an explicit negative assertion, tied to the requested facility/service, is counterevidence. A default citation falls back to the actual source row tuple (facility/field/position/text), not a fabricated website. Citation locators are logical table/row references when no actual URL exists; callers should supply fully qualified/source URLs when available. The module does not HTTP-verify links or validate the truth of source prose.

## Sophia: NQAS and Kayakalp interfaces

Inspected NQAS/Kayakalp contracts on main and latest `sophia-wip` **`e7f701b062a15191e3758f771410ddd204a70ee9`**, plus the existing isolated Kayakalp validation/audit documentation. No canonical schema or validated transformation changed.

`from_kayakalp(row, match)` requires `match.reference_id == award_id`; `from_nqas(row, match)` requires `match.reference_id == certification_id`. The caller must provide a real accepted/pending/rejected source-record link. Source records alone have no canonical facility ID. No source-name/geography-only match is fabricated.

- Kayakalp consumes `award_id`, `financial_year`, `award_raw`/`row_citation`, `dq_flags`, `retrieved_on`, `source_name`, `source_url`. It emits **cleanliness** evidence only. FY end 31 March is an explicitly flagged **reference-period endpoint**, not a known award/inspection day or a bound on when the award was announced (`DatePrecision.FINANCIAL_YEAR`); the 2026 conversion/retrieval date does not refresh FY 2021-22. Multiple awards/categories stay separate records but share a source lineage. An award rank never scales a clinical or service score.
- NQAS consumes `certification_id`, `department_assessed`, `covers_all_departments`, `validity_from`, `validity_to`, `certification_status`, source/provenance and DQ fields. It emits **quality** evidence only, even if assessed departments mention dialysis/ICU. Expiry is recomputed from dates and the supplied `as_of`; partial/unknown department scope remains visible. The reviewed 2026 scrape is historical; it is not current full-facility certification.
- Neither adapter requires a particular district/state column name to fabricate links. Existing isolated Silver has `district_clean`/`state_clean`, while Sophia's latest convention uses `district`/`state`; the recommended downstream projection remains explicit aliases, subject to team agreement. This module accepts the already-linked evidence without mutating either contract. Alias conflicts in location rows raise errors rather than silently picking a version.
- The preceding Kayakalp audit found three empty `name_core` values (serials 368, 371, 559), 291 awards in 218 geography groups without exact postal corroboration, 47 type conflicts, and 11 health-jurisdiction records. Those are matching/scoring qualifiers, not grounds for source deletion or forced geography. Never join on blank `name_core`; accepted reviewed links may use other independent identity evidence. No new quality-to-service inference is introduced.

NABH general accreditation and NQAS do not establish every service; Kayakalp is historical supporting cleanliness evidence, not clinical safety, clinical outcomes, staffing, available services or appointment availability. Missing quality records do not imply poor quality.

## Elliot: identity and location interface

Inspected the existing India Post processing and `pincode_centroids_silver` contract in `notebooks/india_pincode_bronze_to_silver.py` / `04_pincode_bronze_to_silver.py`. No separately published Elliot application/API branch was present in the repository inventory; a finalized matching handoff is still needed.

`location_context(row, basis="site_coordinates" | "pin_centroid" | "unknown")` accepts current `latitude`/`longitude`/`state`/`district` or legacy `_clean` aliases, `coord_status`, `dq_flags`, `pin_ambiguous`, `centroid_quality`, and optional `facility_id`. A PIN centroid stays a PIN centroid, with an explicit uncertainty flag. Invalid/unusable source coordinate status/flags null both coordinates; numerical coordinates are checked for finite world bounds, not independently geocoded. The caller must use validated Silver coordinates and retain PIN spread/precision metadata upstream. A known location facility ID must match the assessment target. Centroid rows without a facility ID are context assigned explicitly by the caller, not proof of a facility association.

Use `FacilityMatch(facility_id, status, confidence, method, reference_id, flags)` for accepted source-to-facility associations. Confidence is an upstream heuristic, not a hidden fuzzy-name match or probability. The engine does not transfer postal-office coordinates to hospitals, compute distances, resolve administrative boundaries, or raise service confidence because a facility has precise coordinates. Keep location ranking and identity resolution separate; carry their warnings into explanations and matching inputs. Confirm future changes to link/status/ID contracts with Elliot before an actual batch join.

## Output, reproducibility and limits

`Assessment.to_dict()` / `.to_json()` emits facility ID, requested canonical service, explicit as-of date, model version, policy/fingerprint, the four lanes, optional location, excluded records/reasons, exact duplicate IDs and limitations. Each lane includes score/category/status, positive/counter strength, agreement gain and pre-cap contradiction reduction (0-1 scale), number of positive contributing source groups, qualified independent-current evidence IDs, all source evidence IDs/citations, explanations and contribution breakdowns. Every contribution carries the original typed evidence, reliability/match/recency components, effective strength, temporal status, qualifiers and gate reasons. Exact duplicate IDs with identical payloads are idempotent; conflicting payloads fail loudly. Inputs and policy snapshots are immutable; evidence order does not change results.

The component can be called from a backend or within a Databricks task after explicit reads/joins; distribute the package via the team's normal code path. It uses no implicit catalog/schema, Spark import, `.collect()`, `.write`, managed-table naming or deployment hooks. For a large batch, apply the pure function per facility/service in upstream-controlled partitions; a tested Spark UDF/batch writer and production deployment are **not** included or claimed verified. Unknown fields in source row mappings are tolerated; malformed required fields are not silently accepted. There is no statistical/medical validation dataset, trained probability model or live availability feed in this baseline.

## Tests and implementation handoff

Focused tests cover no evidence vs explicit negatives; cross-facility/service exclusions; self-report/indirect/current/expired/undated/future evidence; validity/as-of behavior and look-ahead; pending/rejected/unknown identity; alias and join conflicts; wrong source scope; score bounds, recency/match monotonicity and configurable weights; source-lineage repetition/correlation and same-source conflicts; preservation of citations/unknown assertions; JSON reproducibility; no quality/location leakage into services; source rows not mutated; and all ten examples.

Executed on Python **3.10.4**: **57 focused tests passed**, all **10 synthetic examples** ran with full JSON serialization and both default/file-loaded policy, **5 existing address-parser** and **12 existing coordinate-parser** focused cases passed, `compileall` and `git diff --check` passed. The existing full-data parser dry runs and unrelated Spark ETL pipelines were not rerun. Validation artifacts are local/ignored or temporary; no datasets were generated into versioned paths.

Implementation has no local runtime blocker. Integration requires:

1. A reviewed canonical service vocabulary and assertion/polarity mapper for self-reported claims; no automatic substring or specialty assumptions.
2. William's service/site/link rows with source scope/dates/citations, review decisions and match scores; agreed meaning of accepted vs pending identity links. Keep course/membership/designation inferences labeled indirect.
3. Accepted source-record links for Sophia's quality data, plus agreement on geographic aliases and historical scope. Do not join quality records on names alone.
4. Elliot's finalized identity/location uncertainty interface; no automatic PIN-based identity certainty.
5. Team review of policy weights, recency, independence groupings and thresholds; a labeled evaluation set and precision/error analysis before any probability-like or production confidence claim.

No end-to-end live Databricks scoring job, real facility match evaluation, source HTTP validation, probability calibration or clinical validation was performed. This is an independently runnable, unit-tested integration baseline, not a completed production scoring integration. No push, merge, PR or shared-table modification is authorized by this implementation.

## Facility–service integration phase

The [integration contract](evidence-confidence-integration.md) documents corrected rejected-match handling, pending stronger evidence, deterministic aggregation, provenance-preserving export and the geographic LEFT JOIN. It includes synthetic examples, current verification and upstream Silver integration requirements.

The [real Silver validation attempt](evidence-confidence-integration.md#real-silver-validation-attempt--2026-11-21) profiles the actual locally available Kayakalp snapshot and records the blocked end-to-end status, missing core Silver exports, main-branch schema mappings, upstream geographic truncation risk, component fixes and reproducible commands. No synthetic output is represented as real validation.
