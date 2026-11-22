# Downloaded Silver audit — 2026-11-22

**CSV integrity: PASS WITH WARNINGS. Bundle completeness: INCOMPLETE. Evidence Confidence: PARTIAL. Geographic end-to-end validation and GitHub publication: BLOCKED.**

This audit used only the downloaded files at `/Users/jihyun/Desktop/cmu/F26/datathon/CMU_Datathon_26/silver_dataset`. It did not regenerate Silver, execute preprocessing or start/access Databricks jobs. Prior Databricks readback metadata was used only as a historical count comparison, never as a substitute for a missing downloaded file. Existing uncommitted work was preserved.

## Complete inventory

All 14 discovered files are CSVs in one flat directory, totaling **322,321,092 bytes (307.4 MiB)**. Every file was recursively inventoried, SHA-256 fingerprinted and parsed. No archive, unexpected file format, byte-identical duplicate file, strict parse error, record-width error, duplicate declared key or exact full-row duplicate was found. All input hashes remained unchanged after validation. Without a teammate-provided original checksum manifest, this proves local consistency and non-mutation, not transfer completeness against Google Drive.

CSV uses `escapechar="\\"`, `quotechar='"'`, `doublequote=True`, strict parsing and UTF-8 decoding. Default RFC-style parsing misreads escaped quotes and arrays; the explicit reader is part of this validation, not a source-data repair. No source file, value, field name or invalid record was silently corrected/discarded.

Each filename below is relative to the directory above. Source producer identification is inferred from repository code, headers and available provenance; no export commit/revision manifest was supplied.

| Filename | Rows | Bytes | Columns | Status | Source / producer |
|---|---:|---:|---:|---|---|
| `facilities_silver.csv` | 9,989 | 35,131,244 | 57 | WARNING | 01: facilities_bronze / Virtue Foundation Marketplace |
| `facility_registry_links_silver.csv` | 4,482 | 1,776,489 | 31 | WARNING | 06: facilities_silver + registry_sites_silver |
| `facility_registry_summary_silver.csv` | 9,989 | 1,239,295 | 12 | PASS | 06: facilities + links + registry_services_silver |
| `nfhs_silver.csv` | 705 | 678,179 | 39 | PASS | 04: nfhs_bronze (NFHS-5 district facts) |
| `nqas_silver.csv` | 989 | 920,987 | 30 | WARNING | 02: nqas_certified_facilities / NHSRC lists |
| `pincode_centroids_silver.csv` | 19,586 | 13,438,523 | 20 | PASS | 00: pincode_silver / India Post |
| `pincode_silver.csv` | 165,625 | 142,926,923 | 40 | PASS | 00: pincode_bronze / India Post directory |
| `pincode_silver_quality_history.csv` | 1 | 498 | 17 | WARNING | Legacy PIN quality producer; not a current 00 output |
| `registry_services_silver.csv` | 22,757 | 25,406,585 | 23 | PASS | 05: six registries / nine Bronze tables |
| `registry_sites_silver.csv` | 24,961 | 30,250,760 | 33 | PASS | 05: six registries / nine Bronze tables |
| `silver_dq_summary.csv` | 16 | 481 | 3 | WARNING | 01: facilities_silver DQ flags |
| `silver_facility_claims.csv` | 549,841 | 70,527,909 | 5 | PASS | 01: verbatim facilities_silver claim arrays |
| `silver_possible_duplicates.csv` | 32 | 6,213 | 10 | WARNING | 01: candidate facility pairs, not confirmed duplicates |
| `silver_rejected_facilities.csv` | 88 | 17,006 | 6 | PASS | 01: facilities_bronze rejected rows and reasons |

Full ordered column lists, per-column null counts, selected numeric/boolean/date/array validation, declared keys, source counts, DQ counts, example record positions and file hashes are in the local ignored artifact `shared/runs/evidence-confidence/downloaded-silver/audit.json`. CSV contains no authoritative Spark schema or nullability metadata. Validating serialized values does not recover the original Spark types; obtain a typed Parquet export or original schema JSON for full type-contract certification.

## Missing, unexpected and inconsistent outputs

Seven outputs expected from the current 00–06 setup are missing:

- `kayakalp_silver_validation` (no alternative Kayakalp export exists in the directory).
- `registry_match_review` (the supplied links have 1,444 pending associations; human review decisions cannot be reconstructed).
- `nfhs_quarantine`, `nfhs_quality_history`, `nfhs_quality_current` (persistent view).
- `pincode_rejected`, `pincode_dq_summary`.

Some missing auxiliary tables may be intentionally empty or omitted views, but that must be declared in a manifest; absence is not assumed equivalent to zero rows. `pincode_silver_quality_history.csv` is an additional legacy quality export, not an output in the current setup's notebook 00. `facility_geo_ready` and request-specific geographic candidate exports are also absent. The current setup does not produce those in its 00–06 job; their absence still blocks geographic recommendation validation.

The bundle is internally referentially consistent but is not the same snapshot as the earlier independently generated pipeline run:

- Links: **4,482**, compared with **4,241** in the prior run (+241).
- Duplicate-facility candidate pairs: **32**, compared with **53** (-21).
- Facility DQ summary: **16 flag types**, compared with **19** (-3).
- Other comparable table counts agree with the prior readback.

Those differences are warnings, not proof of corrupt downloads. They require the teammate's source hashes, export timestamps and preprocessing commit before reconciliation. Do not mix this link/summary snapshot with a different matching run.

Facilities use eight legacy fields: `city_clean`, `state_clean`, `pincode_clean`, `latitude_clean`, `longitude_clean`, `year_established_clean`, `num_doctors_clean`, `capacity_clean`. Current main expects the names without `_clean`. The file also retains raw `latitude`/`longitude`; these must not silently stand in for validated coordinates. Geographic checks explicitly read the legacy cleaned coordinate/PIN columns. No in-place rename or raw-value overwrite was performed. Pair exports similarly have `pincode_clean_a/b` rather than `pincode_a/b`. Evidence ID/service adapters remain usable because they consume existing canonical keys rather than guessing geographic aliases.

## Data-quality findings

**PASS — parsing, identity and relationships.** All complete CSV rows were processed with the declared dialect. There are 9,989 distinct canonical lowercase UUID facility IDs, 24,961 unique site IDs, 22,757 unique service-record IDs and 4,482 unique link IDs. Declared composite keys (including all 549,841 claim positions and 32 facility pairs) are unique and nonblank. No invalid value was found in the selected numeric/boolean/ISO-date checks, malformed JSON arrays, malformed non-null checked PINs, half coordinate pairs or cleaned coordinate points outside the configured India box. Original Spark type/nullability metadata remains unavailable.

Checked foreign keys have zero orphan violations: claims → facilities; links → facilities and sites; services → sites; summaries → facilities; both pair endpoints → facilities; centroid PINs → office-directory PINs. Summary link counts and accepted/pending service sets were independently recomputed and agree for all facilities. The **2,281 site/service groups with multiple evidence rows** are legitimate evidence grain, not duplicate record IDs; records were retained.

**WARNING — geography/reference coverage, not invented corrections.**

- Facilities: **205** non-null PINs absent from the supplied directory (examples: data records 12, 26, 48).
- Facilities: **69** cleaned state/PIN reference disagreements (records 351, 420, 500).
- NQAS: **234** `district_in_state=false` reference flags (records 5, 9, 10); one null state and one null district; two null district/state-check values.
- NQAS: all **989** rows carry `CERTIFICATION_EXPIRED`; 77 have unknown facility type.

Example numbers are one-based CSV data-record positions excluding the header, not physical lines: embedded newlines can span lines. Missing PINs and district-reference disagreements may reflect source errors, incomplete/older references or boundary/name changes; they are not all verified geographic errors. No district, coordinate or facility match was invented and no uncertain award/facility record was deleted.

**PASS/PARTIAL — provenance and availability.** Applicable registry/NQAS/PIN/NFHS source metadata and row citations passed presence/URL-shape checks; no citation URL availability/network test was performed. Facility provenance instead uses `_source_table`, `_ingested_at` and `source_row_ids`, with claim text retained verbatim. Missing public facility citation/licensing fields were not invented. NQAS is present but has no canonical link export. Kayakalp is absent. Quality/cleanliness alignment is therefore incomplete and cannot be represented as current clinical safety or service availability.

## Real Evidence Confidence results from these downloads

Actual downloaded core records were fed into the existing source adapters and `build_facility_service_rows()`, with as-of **2026-11-22** and the actual 61-tag `SERVICES` vocabulary parsed from notebook 05 without executing it. No canonical IDs or service mappings were invented.

- **4,482 links:** 3,038 accepted and 1,444 pending; no rejected review decisions were supplied. The absent review queue was not replaced with synthetic decisions.
- **2,745/9,989 facilities** have at least one registry association, accepted or pending; **7,244** have none. Association coverage is not independently verified service coverage.
- **4,474 sites** are associated; **20,487 registry sites** are unmatched. These are unlinked records, not foreign-key violations or evidence of service absence.
- **9,986 adapted Evidence objects**, zero adapter errors. **173** tagged NABH empanelment/general-listing records were retained as non-service context with IDs/citations, not promoted to service evidence. This follows the existing scope guard.
- **4,191 observed facility/service pairs:** T1=281, T2=77, T3=2,061, R=1,771, U=1, X=0. This grain excludes facilities with no tagged evidence and is not an all-services population distribution.
- **1,786** rows expose potential stronger pending evidence; **8 real accepted-T3 + pending-T1 cases** remain T3 with the pending evidence preserved.
- Real rejected-only and credible negative-assertion cases are not present in these exports. Those semantics remain covered by existing regression tests, not claimed independently proven by new real examples. Expiry is historical evidence, not a negative availability assertion.

The actual geographic chain cannot run because there is no geographic candidate export. To exercise join/ranking/serialization without fabricating geography, separate **non-geographic inventory probes** used the 9,989 real facility IDs/names and downloaded evidence, with distances, geographic confidence and location basis explicitly null. No radius filter or distance computation was applied. The request envelope is a test interface invocation, not a Delhi search result.

| Inventory probe | Input / joined / response facilities | Tier counts | Hard errors |
|---|---|---|---|
| C-section, routine | 9,989 / 9,989 / 9,989 | T1 9; T2 20; T3 85; R 77; U 9,798 | 0 |
| Dialysis, routine | 9,989 / 9,989 / 9,989 | T1 1; T3 35; R 28; U 9,925 | 0 |
| C-section, urgent | 9,989 retained as alternatives | Same underlying tiers; **0 confirmed urgent recommendations** | 0 |

These probes use adapters → aggregate → LEFT JOIN → existing ranker → ordinary JSON and replay validation. They confirm no input row loss/fanout, duplicate output grain, citation/validity loss or pre-enrichment top-25 cut in Alice's component. They do **not** establish geographic search coverage, radius correctness, real distance ordering or actual location uncertainty. The 9,989 missing-geography warnings per probe are intentional, explicit and not a substitute for Elliot's output.

Global evidence-source warnings in those probes: **2,254 incomplete validity records** and **192 expired adapted records**; these counts cover the loaded linked evidence, not only positive support for the requested service. T1 evidence does not create a staffing, current availability or emergency-capability guarantee. Ranking parameters and tier semantics were not changed.

## Publication decision: BLOCKED

The connected GitHub API confirmed `sophia-m-kliatchko/CMU_Datathon_26` is **public** and the account has push permission. Push permission is not a source redistribution licence. The independent metadata result is recorded in ignored `publication-check.json`.

- `pincode_silver.csv`: **142,926,923 bytes (136.3 MiB)** exceeds GitHub's regular-Git **100 MiB** file limit.
- `silver_facility_claims.csv`: **70,527,909 bytes (67.3 MiB)** exceeds the 50 MiB warning threshold. Total raw CSV size is 307.4 MiB; total size alone is not the per-file blocker. [Official limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
- `.gitattributes` has no LFS tracking rules. Global LFS filter settings exist, but `git lfs version` fails because git-lfs is not installed. LFS was not installed/configured and would not resolve licensing or privacy restrictions.
- Virtue Foundation Marketplace/datathon redistribution terms remain TODO in `docs/data-sources.md`. Downloaded facilities have no licence column; `_source_table` points to the Marketplace dataset.
- Downloaded NCG metadata says copyright NCG, all rights reserved, factual use for non-commercial research with citation. It provides no public GitHub redistribution grant. The repository also explicitly requires organizer review before redistribution outside the datathon.
- Downloaded DNB/ANBAI, NMC, LaQshya, trauma, NQAS and NABH metadata record no explicit open-data licence. PIN/NFHS GODL statements are conditional; verify the actual source and terms. No blanket permission was inferred from public access, existing raw files in Git, successful processing or Google Drive sharing.
- Facility CSV has **8,538 nonempty email cells**, with email-like patterns in **8,135 rows**, and **9,492 nonempty phone cells** with phone-like digits. These may include organizational contacts, but private/personal versus business status was not established. Free text also requires privacy review. Values were not reproduced or redacted automatically. The limited private-key/AWS-key pattern screen found no matches; this is not a comprehensive secret/PII certification.

No files were copied into a Git-tracked dataset directory, force-added, staged, committed, pushed, split or converted for public distribution. **Published files: 0; published bytes: 0; publication commit SHA: none.** Source downloads remain in their original directory.

Use the existing access-controlled Drive or versioned Unity Catalog/Delta storage for internal sharing. Keep a small schema/row-count/hash/code-revision manifest alongside the data. Typed compressed Parquet may improve transport later, but no Parquet was generated here and compression, LFS or Releases must not be used to bypass unresolved redistribution rights. Public publishing requires source-specific grants and privacy approval first.

## Tests and reproduction

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m evidence_confidence.downloaded_silver_audit \
  --directory /Users/jihyun/Desktop/cmu/F26/datathon/CMU_Datathon_26/silver_dataset \
  --as-of 2026-11-22 \
  --prior-report shared/runs/evidence-confidence/alice_silver_20261122_044418/persistence-output.json \
  --output shared/runs/evidence-confidence/downloaded-silver/audit.json

PYTHONDONTWRITEBYTECODE=1 python3 -m evidence_confidence.real_silver_validation \
  --export-dir /Users/jihyun/Desktop/cmu/F26/datathon/CMU_Datathon_26/silver_dataset \
  --as-of 2026-11-22 --csv-escapechar '\'

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence*.py' -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 python3 -m evidence_confidence.synthetic_smoke
python3 -m compileall -q evidence_confidence tests
git diff --check
```

- Downloaded-file audit: **PASS WITH WARNINGS**, no hard structural findings, incomplete bundle, partial compatibility and non-geographic probes only. Full per-file hashes/schemas/nulls are in ignored `audit.json`.
- Existing real-Silver runner with the explicit CSV dialect: **BLOCKED**, exits 1 because `geographic_candidates` is absent. No old Databricks candidate rows or synthetic rows were substituted.
- Evidence unit/integration tests: **214 passed** (prior 208 plus six new CSV/audit tests). Existing tests include earlier source-export fixtures; those do not fill files missing from this bundle.
- Full unittest discovery: **214 successful tests plus one import error** (215 entries) because shared `test_kayakalp` requires missing `pdfplumber`. Shared tests were not modified to hide this.
- `python3 -m pytest -q`: cannot start; `pytest` is missing. Therefore the complete repository suite is not reported all-green.
- Synthetic smoke: **32/32 candidates retained**, zero hard errors and five expected fixture warnings. This remains synthetic regression evidence only.
- Compilation and Git whitespace checks pass. No Databricks jobs or preprocessing were executed in this task.

Component changes are limited to an explicit optional CSV escape parameter and strict record-width checking in the existing reader/CLI, a reusable streaming download auditor, focused tests and documentation. The original default RFC CSV convention remains available. Tier logic, ranking, shared preprocessing notebooks and the downloaded files are unchanged by this task; all prior uncommitted pipeline work remains intact.

## Required next inputs

1. Obtain a same-run export manifest with code commit, source hashes, original table schemas/types/nullability, row counts, dates and file checksums. Reconcile the 241-link, 21-pair and three-DQ-type differences.
2. Supply the missing Kayakalp output, explicit canonical NQAS/Kayakalp links, review queue and omitted validation/auxiliary outputs, or document intentionally empty/omitted artifacts. Preserve pending/rejected decisions.
3. Supply Elliot's complete pre-enrichment candidate batches for actual PIN/radius requests, with location basis, confidence and uncertainty, without substring filtering or nearest-25 truncation. A facility/PIN directory is not that candidate batch.
4. Agree and implement an explicit legacy-column boundary mapping with typed values, retaining raw latitude/longitude separately. Do not silently rename or regenerate the source files.
5. Review the 205 missing-directory PINs, 69 state/PIN disagreements and 234 NQAS district-reference flags with source owners. Preserve unresolved cases.
6. Obtain source-specific redistribution grants and privacy clearance before public distribution, resolve storage size in an approved shared store, and restore pytest/pdfplumber to run the remaining repository test entry points.

**Final assessment: partially ready for local service-evidence integration; blocked for a complete geographic/quality integration claim and blocked for public GitHub publication.**
