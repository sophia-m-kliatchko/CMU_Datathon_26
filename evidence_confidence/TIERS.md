# Evidence Tier Framework: implementation and integration contract

This is the **primary service-evidence interface**. The original numerical engine remains available for backward compatibility and internal comparison. Tiers do not inspect numerical scores, source reliability weights, match-score thresholds, or score categories. No new continuous formula or scoring weights were introduced.

Implemented only in Alice's `alice-evidence-confidence` worktree. No teammate notebooks, datasets, matching/ranking pipelines, facility/service schema or Databricks objects are modified. The existing specification at `docs/evidence-tier-implementation.md` is the controlling design; it was not rewritten by implementation.

## Files changed in this implementation

- Modified component files: `__init__.py`, `adapters.py`, `engine.py`, `examples.py`, `models.py` under `evidence_confidence/`.
- New component files: `temporal.py`, `tiers.py`, `ranking.py` and this `TIERS.md`.
- New configuration: `config/evidence-tiers.json`, `config/evidence-ranking.json`. Original `config/evidence-confidence.json` and numerical `policy.py` are untouched.
- New tests: `tests/test_evidence_tiers.py`, `tests/test_evidence_ranking.py`. Original `tests/test_evidence_confidence.py` is untouched.
- Updated Alice-owned guide: `docs/evidence-confidence.md`. The controlling `docs/evidence-tier-implementation.md` and shared `DEVLOG.md` are untouched by this task.

## Public APIs

```python
from datetime import date
from evidence_confidence import evidence_tier, assess, TierPolicy

# records are existing Evidence objects from the row adapters or explicit callers.
tier = evidence_tier(facility_id, service, records, date(2026, 11, 21))
print(tier.base_tier.value, tier.effective_tier.value, tier.review_status)
print(tier.to_json(indent=2))

# Existing callers still work, including generator input. New primary field is additive.
comparison = assess(facility_id, service, records, as_of=date(2026, 11, 21))
print(comparison.service_evidence.effective_tier.value)  # Primary categorical result.
print(comparison.service_availability.score)           # Legacy internal comparison only.
```

`service` normalization remains formatting-only: exact canonical service tags, not substring matches, clinical synonyms or specialty-to-service inference. `as_of` is mandatory. Malformed inputs and conflicting payloads under the same evidence ID fail loudly. Evidence for another facility/service is explicitly excluded with a reason.

## Exact assignment rules

1. Restrict to the requested facility and relevant service. Keep quality, cleanliness and identity evidence in separate dimensions. Known NQAS/Kayakalp/HFR source families cannot become service evidence even if a generic caller mislabels their scope. NABH site-only/general accreditation qualifiers cannot establish service verification.
2. Determine source-specific basis. **LaQshya government certification** and **NABH service-specific accreditation** are the currently mapped direct families. They require independent verification, direct scope, a citation and no indirect-only flags. General NABH quality listings never enter the service adapter. Unknown direct-source semantics do not qualify merely because `source_kind` is government/accreditation: return U or identity-review R, retain the record and expose an assumption for William.
3. For qualifying direct evidence with an accepted, unflagged association: **T1** if an explicit validity interval contains `as_of`, or an authoritative source explicitly indicates a current listing without validity bounds; **T2** if validity expired or the listing is explicitly no longer current. Issuance age never downgrades an in-force multi-year certificate. A citation is required for both T1 and T2.
4. **T3** covers Virtue Foundation self-reports, NMC/DNB training, NCG membership, and sanctioned-but-not-confirmed-functional trauma records. These source families cannot produce T1/T2, even if a generic row erroneously labels them independent/direct. Direct LaQshya records with unknown validity or department scope are not automatically reinterpreted as historical certification or T3 training.
5. The strongest **accepted qualifying** base tier wins: T1, then T2, then T3. Otherwise base tier is **U**. Source counts never promote indirect evidence into direct verification. Missing evidence retains the facility and means unknown, not unavailable.
6. If relevant positive assertions exist but **every** applicable identity association is pending, unknown or identity-flagged, effective tier is **R** with base U. Rejected-only records have effective U and `review_status="not_applicable"`; `rejected_candidate_match` retains the diagnostic. Rejected records receive no attribution credit and do not change accepted evidence review status. Candidate tiers in per-record decisions describe source semantics before identity, not verified facility tiers. With accepted T3 plus a pending direct certificate, base/effective remains T3 and review status is partial. Extra unresolved records do not erase a separate accepted direct source.
7. **X** overlays the strongest accepted base when a credible unresolved negative assertion also exists. The negative must match this facility/service; be independent, direct, cited, exactly dated, temporally applicable and identity-accepted without review flags. Mapped authoritative sources or explicitly supplied independent checks can qualify. Self-reports, training, membership, designation, uncited/undated/year-only/future/expired assertions and unresolved/rejected associations do not override a valid direct source. All statements remain visible; X never deletes the underlying base tier or rewrites historical records.

Credible point-in-time negative notices use the pre-existing baseline's **365-day** freshness horizon, exposed as `TierPolicy.contradiction_max_age_days` / `config/evidence-tiers.json`. An explicit currently applicable negative interval takes precedence over its issuance age. This is a transparent temporal review policy, **not a new score/weight or clinically established cutoff**. The team must validate/tune that horizon on cleaned data; no empirical accuracy is claimed. A negative record alone yields U with its decision/citation retained, not a service-absence label.

Identity acceptance uses the upstream categorical decision and flags, **not** the old numerical match threshold. Even an explicit accepted association without a numerical confidence can satisfy the tier identity requirement; the legacy scorer still handles its missing numeric confidence as before. Elliot/William must own the meaning and review provenance of accepted vs pending/rejected links. The classifier does not authenticate source truth or perform new matching.

## Temporal fixes and uncertainty

`temporal_validity()` in `temporal.py` is shared by tiers and the legacy comparison engine:

- Explicit `valid_from <= as_of <= valid_until` is current, inclusively, regardless of certificate age. A cached build-date `is_current=false` does not override a complete current interval. If `valid_until < as_of`, evidence is historical; expiration is not evidence of service absence.
- The registry adapter preserves an explicit `valid_from`; otherwise it uses a known **exact direct certification issue/evidence date** as the interval start only when an explicit, consistent end date is available. A dated listing without expiry does not acquire an invented open-ended certificate interval. It does not fill starts for indirect records, year-only dates or an issue date later than the stated validity end. Complete invalid/future intervals get no temporal credit. Partial intervals alone do not establish currentness.
- With no validity bounds, an authoritative independent direct source's explicit `listing_current=true` or `is_current=true` supports current-listing T1, **always with `current_listing_undated` caveat**. Unknown current status does not qualify. An expired/no-longer-current listing can support T2.
- Year-only NABH dates are flagged and are no longer stored by the service adapter as fictitious January 1 event observations. A current year-only service listing can be T1 with both year-only and undated-current-listing caveats. The year remains part of the source citation/detail; no exact event day is asserted.
- NCG's `evidence_date` in notebook 05 is a **snapshot**, not a service verification date. The adapter clears it from `observed_on`, adds `SNAPSHOT_NOT_SERVICE_EVENT`, and leaves membership as T3 with missing-date uncertainty. Trauma's parliamentary document date similarly does not become an operational service event.
- `retrieved_on` and scrape/snapshot dates never establish positive freshness. A retrieval after a backdated `as_of` still blocks look-ahead credit. Kayakalp's financial-year endpoint remains an explicitly approximate reference date used only in its separate cleanliness/legacy lane.
- Current certification/listing **never guarantees operational staffing, emergency readiness, equipment uptime or patient acceptance**.

The original numerical formula/configuration is retained; only its temporal facts are corrected so an in-force interval is not called historical. Year-only dates are no longer aged from an invented January 1. Those are intentional bug fixes, not a second tier-scoring model. All original regression tests continue to pass without weakening their assertions.

## Output schema

`TierAssessment` is immutable and serializes to JSON:

- `facility_id`, `service`, `as_of`, `framework_version`.
- `base_tier`, `effective_tier`, `review_status` (`clear`, `pending`, `rejected`, `unknown`, `partial`, `mixed_unresolved`, `not_applicable`).
- `flags`: `conditional_certification`, `date_year_only`, `current_listing_undated`, `expired_certification`, `identity_review`, `conflicting_evidence`, `missing_citation`, `temporal_uncertainty`.
- `supporting_source_families`, `supporting_source_count` (distinct **accepted qualifying families**, not row count), `supporting_record_count`, and `evidence_basis` (direct certification, service accreditation, training, membership, self-report, designation).
- `citations`, `explanation` and `decisions`. Each decision retains the evidence ID, source family, basis, categorical match/temporal status, candidate tier before identity, credited status, credible-contradiction status and reasons.
- `duplicate_of` (alias ID, canonical ID); `excluded` (ID, reason); `quality_evidence_ids`, `cleanliness_evidence_ids`, `identity_evidence_ids`.
- `assumptions` for unmapped source semantics and `contradiction_max_age_days` for reproducibility.

Repeated IDs with identical payloads are idempotent; conflicting payloads raise errors. Equivalent payloads under different IDs **within a source family** are counted once; differing dates, statements, polarity, associations or citations are retained, including same-source contradictions. Duplicate IDs remain traceable in `duplicate_of`; source records/tables are never deleted. Genuine distinct award/course rows may remain distinct, but source families still count once. Families LaQshya, NABH, NMC, DNB, NCG, trauma and Virtue Foundation stay separate. No source count is statistical proof of independence.

`assess()` adds `service_evidence` as its primary categorical result, preserving `service_availability`, `quality_evidence`, `cleanliness_evidence`, `identity_evidence` and all previous numerical fields for existing callers. `tier_policy=` is an optional keyword for the new temporal contradiction policy; existing calls need no change. No canonical Silver schema is altered.

## Isolated provisional ranking interface

```python
from evidence_confidence import Candidate, RankingConfig, rank_candidates

routine = rank_candidates([
    Candidate(facility_id=facility_id, evidence=tier, distance_km=12.5),
    Candidate(facility_id="another-base-facility", distance_km=1.0),  # U, retained.
])

urgent = rank_candidates([
    Candidate(facility_id=facility_id, evidence=tier, distance_km=12.5,
              capability_eligible=True,
              capability_basis="Caller-supplied, reviewed capability assessment reference"),
    Candidate(facility_id="another-base-facility", distance_km=1.0),
], mode="urgent")
```

This helper imports no teammate ranking code and introduces no weighted ranking formula. It returns `RankingResult(mode, ranked, alternatives, requires_review, status, provisional, explanation, config)`. Rows retain their original Candidate, tier, label, band, ordinal flags and serializable sort-key metadata. Each base facility appears **exactly once** across ranked/alternatives. Duplicate facility IDs or mixed requested services/as-of dates raise errors instead of silently merging unrelated candidates.

- **Routine**: lexicographic `(tier_priority, distance_band, ordinal_evidence_flags, exact_distance)`, with facility ID as a stable final tie-break. Missing exact distances sort last within the appropriate priority. U/R/X candidates remain in the output with review/unknown labels. Default priorities are T1, T2, T3, then equally prioritized U/R/X; review flags and distance order those unresolved alternatives.
- **Urgent**: a T1 tier is **not sufficient**. Inclusion in `ranked` requires an explicit upstream `capability_eligible=True`, nonblank `capability_basis`, and known distance. Eligible rows use **exact distance first**, then ordinal flags/tier for ties. Other candidates remain in `alternatives`, ordered by proximity, explicitly labelled as unconfirmed or needing capability review. U/R/X never enter the eligible list even if the boolean is mistakenly true. Historical T2 and indirect T3 likewise remain alternatives. Missing capability eligibility/basis/distance yields `requires_review`, never an inferred capability from proximity.
- Default bands **0-10, >10-25, >25-50, >50 km** are **provisional only**. Unknown distance has its own final bin. `config/evidence-ranking.json` exposes bands, ordinal tier priorities and flag order; all require team agreement/empirical validation. The default flag tie-break order is conflict, identity review, expired certification, undated current listing, year-only date, conditional certification. This is provisional ordinal ordering, not measured clinical risk.
- No fixed **10 km urgent detour**, clinical cutoff, live dispatch choice or emergency-care guarantee is implemented. The helper never labels a U/R/X facility confirmed emergency-capable. Even eligible T1 rows are labelled only `eligible_by_supplied_capability_assessment`; the scorer has not independently verified that upstream operational assessment.

## Synthetic examples and tests

Run `python3 -m evidence_confidence.examples`. The existing ten scenarios now display tiers, flags, source families, citations and tier explanations first. `--full` retains the whole Assessment, including legacy numerical comparison fields. Three examples required by the specification:

- `current_scoped_documentary_support`: accepted, cited, currently valid direct service certification -> **base/effective T1**.
- `training_is_indirect`: NMC specialty training mapped to the service -> **base/effective T3**, no direct upgrade.
- `no_evidence`: no relevant records -> **base/effective U**, facility ID retained, no unavailable assertion.

All names/locators/scenarios are explicitly synthetic. These examples/tests establish deterministic code behavior, not real-world matching accuracy, clinical suitability, ranking quality or statistical calibration.

```sh
python3 -m unittest discover -s tests -v
python3 -m evidence_confidence.examples
python3 -m evidence_confidence.examples --full --policy config/evidence-confidence.json
python3 -m compileall -q evidence_confidence tests
git diff --check
```

## Executed validation and scope review

- **117 unit tests passed**: all **57 original tests unchanged**, plus **60 tier/ranking/temporal tests**. Current multi-year validity, expired direct evidence, current year-only NABH listing, NCG snapshot dates, conditional certification, pending vs rejected identity, credible vs weak/stale/unrelated contradictions, dimensions, duplicate handling, retained unknown facilities, lexicographic ranking and urgent eligibility/alternatives are covered.
- All ten synthetic scenarios ran in primary-tier and full/backward-compatible JSON modes. Required example outcomes are T1, T3 and U as shown above. Numerical source weights do not assign tiers (explicitly tested).
- Syntax compilation, JSON serialization, new-file trailing-whitespace checks and `git diff --check` passed. The existing address/coordinate parser unit cases are also exercised as compatibility checks; their full-data/Spark ETL runs are outside scope.
- Diff review against a before-edit snapshot confirms the numerical contribution/aggregation function ASTs and original weight configuration are unchanged. All pre-existing tracked files, including teammate notebooks/data/matching/ranking code and shared DEVLOG, are unchanged in this task. Implementation changes are confined to Alice's component, its configuration/tests and component-owned documentation. No commit/push/merge/PR, Databricks operation or empirical validation occurred.

## Remaining integration decisions (no shared-interface change made)

- **William**: confirm authoritative service-specific listing semantics, date precision/validity fields, `is_current`/`listing_current` as-of meaning, and clear distinction from general NABH accreditation/empanelment. A copied old current flag is not independently refreshed by this library; the caller must supply an authoritative current-listing assertion applicable to the requested `as_of`. Unknown source mappings stay U/R with explicit assumptions. Confirm LaQshya service mappings and department scope; no operating-hours guarantee is inferred.
- **Elliot / match owner**: confirm accepted/pending/rejected decision provenance and how identity-review flags are resolved. This framework trusts categorical accepted links, not numerical match thresholds, and performs no new name/coordinate/PIN matching. Rejected links must not be recycled as ambiguous verification candidates.
- **Quality inputs**: preserve NQAS partial/expired certification and Kayakalp historical cleanliness scope. Require explicit source-record-to-facility associations; state/district aliases remain upstream projections by agreement, not schema rewrites here.
- **Ranking owner**: agree distance bins, ordinal flag priorities, capability-eligibility contract/provenance and the intended urgent alternatives UX. The 365-day point-notice contradiction horizon also needs empirical review. No urgent detour threshold or clinical ranking policy was finalized.
- **Cleaned Silver validation**: exercise exact row-shaped fixtures, reconcile source-family and identity-review distributions, inspect T1/T2/T3/U/R/X outcomes and contradiction false positives, and evaluate ranking with reviewed labels. No live Silver batch, Databricks write, empirical validation or clinical verification has occurred in this task.

No implementation change currently requires editing a teammate interface or shared data. The component is ready to consume final cleaned Silver through the existing adapters for empirical validation; the decisions above remain explicit integration prerequisites, not claimed settled facts.


## Facility–service integration phase

See [the integration contract](../docs/evidence-confidence-integration.md) for aggregation, pending evidence, provenance export, geographic LEFT JOIN and current test results. The earlier 117-test result above is the pre-integration baseline.
