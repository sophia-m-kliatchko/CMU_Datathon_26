# Implement Evidence Tier Framework — CMU Datathon 2026

You are the implementation engineer for my Evidence Confidence component.

## Objective

Implement the agreed deterministic Evidence Tier Framework in my existing isolated worktree, without waiting for the final cleaned dataset.

The architecture has been independently reviewed by Claude. We are replacing continuous numerical confidence as the primary service-evidence output with categorical tiers and interpretable evidence flags.

**Do not redesign the framework or introduce another numerical scoring formula.**

## 1. Repository and scope

Repository: `CMU_Datathon_26`

Expected worktree: `../evidence-confidence`  
Expected branch: `alice-evidence-confidence`

Existing implementation:

- `evidence_confidence/engine.py`
- `evidence_confidence/adapters.py`
- `config/evidence-confidence.json`
- Existing unit tests (previously 57 passing)

First, inspect the actual repository structure, branch, and existing implementation.

If the expected worktree or branch is missing, stop and report it. Do not create a replacement or modify another branch without approval.

**Edit only my Evidence Confidence implementation, configuration, and directly related tests.**

Do not modify teammates' notebooks, datasets, matching pipelines, ranking implementations, or shared Databricks tables.

## 2. Implement deterministic evidence tiers

Implement a testable function:

`evidence_tier(facility_id, service, evidence_records, as_of)`

Use the existing models and interfaces where possible. Adapt the function signature if needed to preserve backward compatibility.

Assign one of six tiers:

**T1 — Current direct verification**

- Independent government certification or service-specific accreditation
- Relevant to the requested service
- Accepted facility identity match
- Source citation available
- Currently valid certification or confirmed current listing
- No indirect-only evidence flags

**T2 — Historical direct verification**

- Same direct-evidence requirements as T1
- Certification expired or listing explicitly no longer current
- Historical capability only; never interpret expiration as service absence

**T3 — Indirect or self-reported support**

- Virtue Foundation self-report
- NMC specialty training
- DNB/NBEMS specialty training
- National Cancer Grid membership
- Sanctioned but not confirmed functional trauma centre
- These sources must never independently produce T1 or T2

**U — Unknown**

- No eligible relevant service evidence
- Do not treat as unavailable
- Retain the facility in downstream outputs

**R — Needs review**

- Relevant supporting evidence exists, but every applicable facility match is ambiguous, rejected, or flagged for identity review
- Do not upgrade a facility to T1/T2 using an unresolved match
- Distinguish an ambiguous match from a definitively rejected match

**X — Conflicting**

- Credible, independent, cited, dated contradictory evidence exists alongside supporting evidence
- Contradiction must be relevant to the requested service and matched facility
- Do not let weak, stale, or unrelated negative records automatically override valid direct evidence
- Preserve the underlying base tier and explanation

Assign the strongest qualifying base tier, then apply applicable review/conflict flags.

Keep `base_tier`, `effective_tier`, and `review_status` separate where practical.

## 3. Fix temporal validity

The previous engine incorrectly classified some currently valid multi-year certifications as historical.

Implement these rules:

1. Explicit certificate validity takes precedence over issuance age.
2. If `valid_from <= as_of <= valid_until`, classify as current.
3. If `valid_until < as_of`, classify as historical.
4. If validity dates are absent but the authoritative source explicitly indicates `listing_current=true` or `is_current=true`, classify as current listing, with an undated caveat.
5. Do not interpret year-only dates as exact January 1 observations.
6. Never use `snapshot_date`, `retrieved_on`, or scrape dates to establish service-evidence freshness.
7. Preserve missing-date uncertainty rather than rewarding it.
8. Do not claim current operational staffing or patient acceptance from certification alone.

For example, a LaQshya certificate issued March 10, 2025 and valid until March 9, 2028 must be considered current on November 21, 2026.

Inspect the existing temporal logic before changing it, and preserve unrelated behavior.

## 4. Implement ordinal evidence flags

Return structured evidence metadata, including where available:

- `conditional_certification`
- `date_year_only`
- `current_listing_undated`
- `expired_certification`
- `identity_review`
- `conflicting_evidence`
- `supporting_source_families`
- `supporting_source_count`
- `evidence_basis` (direct certification, training, membership, self-report, etc.)
- `citations`
- `explanation`

Keep source families separate for LaQshya, NABH, NMC, DNB, NCG, trauma, and Virtue Foundation.

Deduplicate genuinely duplicated records within each source family.

Do not assume that more indirect records automatically verify service capability.

## 5. Separate evidence dimensions

Service evidence, facility identity, quality, and cleanliness must remain distinct.

- LaQshya and service-specific NABH accreditation may contribute to T1/T2.
- NMC, DNB, NCG, sanctioned trauma, and Virtue self-report contribute to T3.
- NQAS and general NABH accreditation contribute to quality, not service verification.
- Kayakalp contributes to cleanliness, not service verification.
- HFR/facility matching determines identity, not service capability.

Use source-specific mapping and flags rather than blindly relying on a generic evidence type.

If source semantics are unclear, mark them as assumptions and document the decision needed from William or Elliot.

## 6. Preserve the existing scoring engine

Do not delete the current numerical scoring implementation.

Instead:

- Keep it available for backward compatibility and internal comparison.
- Make categorical tiers the primary service-evidence output.
- Do not use the continuous score to assign tiers.
- Do not expose a 0–100 score as a calibrated probability.
- Preserve existing callers and tests wherever possible.

Avoid unnecessary refactoring.

## 7. Add a ranking interface, but do not finalize ranking parameters

If a clean integration point exists, implement a small, isolated helper:

`rank_candidates(candidates, mode="routine", config=None)`

Routine ranking should support lexicographic ordering:

`(tier_priority, distance_band, ordinal_evidence_flags, exact_distance)`

Urgent ranking should support capability-aware distance priority.

However:

- Keep distance bands configurable.
- Treat 0–10, 10–25, 25–50, and 50+ km as provisional defaults only.
- Do not hardcode the proposed 10 km urgent detour as an established clinical rule.
- Do not present U/R/X facilities as confirmed emergency-capable.
- Retain nearby unknown facilities in an appropriately labelled alternative list.
- If the required capability-eligibility information is missing, explicitly mark urgent ranking as requiring review rather than inferring capability from proximity.

Do not modify teammates' ranking code.

## 8. Tests

Add unit tests covering at least:

1. Current valid certificate older than 365 days → T1.
2. Expired direct certification → T2.
3. Current NABH service listing with year-only date → T1 with caveat.
4. NCG snapshot date does not establish recency.
5. Virtue self-report cannot become T1/T2.
6. NMC/DNB/NCG remain indirect evidence.
7. Conditional LaQshya certification is flagged.
8. Ambiguous identity match → R when no accepted evidence exists.
9. Rejected match cannot establish verification.
10. Credible unresolved contradiction → X with underlying base tier retained.
11. Unrelated or weak contradiction does not override T1.
12. No relevant evidence → U.
13. NQAS/Kayakalp do not affect service tier.
14. Duplicate evidence does not create false corroboration.
15. Missing evidence never removes the base facility.
16. Routine ranking follows the documented lexicographic order.
17. Urgent ranking does not claim unknown capability as verified.
18. Existing regression tests continue passing.

Use synthetic or real-schema-shaped fixtures. Do not claim these establish real-world ranking quality.

## 9. Execution workflow

1. Inspect the existing code and tests.
2. Identify the minimal changes required.
3. Implement the classifier and temporal corrections.
4. Add ordinal flags and explanations.
5. Add the isolated ranking interface if feasible.
6. Run relevant and full available tests.
7. Review the diff for unintended changes.
8. Document the implementation and integration contract.

Do not wait for my approval between routine implementation and testing steps.

Stop and ask only if a change requires modifying a teammate-owned interface, shared data, or an unresolved consequential service-verification rule.

## 10. Deliverables

Report:

- Files changed
- Exact tier-assignment logic
- Temporal validity changes
- Output schema
- Tests passed/failed
- Remaining ambiguities
- Integration requirements for the final cleaned Silver dataset
- Any decisions requiring my approval

Provide at least three synthetic examples:

- Current direct certification → T1
- Indirect training evidence → T3
- No external evidence → U

## 11. Restrictions

- Work only in `alice-evidence-confidence`.
- Do not modify teammates' files.
- Do not write to Databricks.
- Do not commit, push, merge, or open a PR.
- Do not silently change the facility/service schema.
- Do not invent empirical validation results.
- Do not introduce new arbitrary scoring weights.
- Do not remove base facilities without external evidence.

**Success criterion:** A deterministic, tested Evidence Tier Framework is implemented in my isolated worktree and is ready to consume the final cleaned dataset for empirical validation.
