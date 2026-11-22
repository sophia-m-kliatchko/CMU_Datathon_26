# Real Silver identity-review audit — 2026-11-22

Overall **PARTIAL**: actual local evidence classification and controlled-geography integration pass. Real radius retrieval is **BLOCKED pending teammate handoff**; this audit neither runs nor modifies geographic retrieval, Databricks or preprocessing. No tier/ranking policy changes were needed.

## Reproduction and evidence

Input: `../CMU_Datathon_26/silver_dataset/` (14 CSV files). Parse with explicit backslash escaping. All source SHA-256 hashes remained unchanged. Full inventory and key/schema checks: [downloaded audit](evidence-confidence-downloaded-silver-audit.md).

```sh
python3 -m evidence_confidence.evidence_review_audit \
  --directory '../CMU_Datathon_26/silver_dataset' \
  --as-of 2026-11-22 \
  --output-dir shared/runs/evidence-confidence/review-audit-NEW
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_evidence*.py' -q
python3 -m evidence_confidence.synthetic_smoke
```

The runner refuses to overwrite previous reports. Local detailed evidence is in `shared/runs/evidence-confidence/review-audit-20261122/review-audit.json`; `r-assessment-ledger.jsonl` contains **every one of 1,771 R pairs**, exact evidence/link IDs, overlapping review reasons and an exclusive bucket. Generated artifacts are not staged for publication.

## Classification — PASS within snapshot; ground-truth identity accuracy PARTIAL

4,191 observed facility–service pairs: **T1 281; T2 77; T3 2,061; R 1,771; U 1; X 0**. These are observed pairs, not coverage across every facility × every service. Of 9,989 canonical facilities, 2,745 have links and 7,244 do not. 4,482 links comprise 3,038 accepted and 1,444 pending; there are no rejected links in this snapshot.

All R pairs reference actual links with `needs_review=true`: 2,264 service-record decisions. No rejected-only R, missing identity-link R, or unknown canonical service tag was found. Exclusive buckets prioritize competing candidates, then weak distinctive name, generic-type uncertainty, below-threshold score and distance-only review; overlapping reasons remain in the ledger:

- **816 below-threshold**: example `02331520-e043-4073-ad2c-f649608a1890`, `cancer_care`.
- **534 weak distinctive name**: `008f8550-efd3-4da5-bab2-66b6254cf24b`, `emergency_c_section`. Siliguri United Daycare Centre is pending against Siliguri District Hospital, service record `f1b22b6600dce7fb`; it is not credited.
- **244 distance-only review**: `08344cdb-f455-4c22-8d31-a0a8e849124b`, `cancer_care`.
- **169 competing candidates**: `0807980c-f911-4d0d-a963-52896acd5b42`, `cancer_care`.
- **8 generic type unconfirmed**: `6cd599ab-b8bd-4104-b01f-be37bff75feb`, `normal_delivery`.

These labels explain review routing; they do not independently adjudicate which candidate is correct. One R pair includes two nonqualifying scope/validity records; this is not an unmapped-service defect and cannot promote a tier.

All **eight T3 + pending T1 pairs remain T3**, covering six facilities (Manipal has three services). Example: `320add3e-1571-45a1-b56f-27736f35c4aa`, `emergency`: accepted DNB `c477ed78dcd12c56` supports T3; pending NABH `2b550aec3d99656c` has distance-review status and cannot establish T1. Citations, source identity and pending metadata remain visible. All eight detailed source comparisons are in the JSON report.

Independent premise checks found **zero violations**: credited decisions are accepted, correctly scoped and assigned to the same canonical facility/service; strongest supported base tier and source counts agree. Credited decisions: T1 296, T2 103, T3 2,440 (records can support overlapping pairs). T1 includes authoritative current listings without certificate interval endpoints; this is the existing rule, not inferred certificate validity. Example T1: Dvita Eye Care `0053872c-0599-4a0d-bfaf-e1a9fc5c0320`, `eye_care`; T2: `09ce740e-05d5-4eb6-803d-1f146ed6f658`, `imaging`, explicitly withdrawn accreditation; T3: Bankers Heart `00fd1dbd-dc4d-47ea-9ffa-68ddf7e5d13f`, `cardiac_care`, training evidence.

The sole observed U is `4e172891-8e97-4976-91d8-83b13a733b6c`, `obstetrics`: two accepted LaQshya records lack sufficient service-specific certification/validity support. U means insufficient evidence, not absent service. Rejected-only → U and credible contradiction → X remain regression-tested; **neither occurs in these real records**. All 9,986 adapted assertions are positive; absence of observed contradictions is not proof of agreement or safety.

## Canonical identity and provenance — PARTIAL

Downloaded primary-key/FK checks found no checked orphan references or duplicate declared keys. Adapter construction succeeds with zero adapter errors. Canonical IDs come exclusively from the facility/link tables. No identity or service is inferred from a facility name. 20,487 registry sites and 17,274 service records are unlinked coverage gaps, not invalid foreign-key orphans and not evidence of service absence.

All 9,986 adapted records have source record IDs and citations; zero temporally invalid records. Reusable integration checks report 2,254 incomplete-validity and 192 expired-source warnings across the adapted batch, not just selected fixture facilities. URL presence does not authenticate external certificates. Preserve these caveats. 173 general/non-service listings with service tags remain context, never service support.

NQAS has 989 records but no canonical links; Kayakalp and an explicit review queue are absent. VF claims lack reviewed canonical service mappings. Thus quality alignment, rejected adjudications and full source coverage remain incomplete. Historical awards and cleanliness evidence never establish current clinical safety, emergency capability or service availability.

## Geographic warnings — PARTIAL, source-owner review required

- **205 missing-directory PINs**: 49 affected facilities have 77 links (56 accepted, 21 pending). Their observed pairs include T1 4, T2 3, T3 45, R 9. Bankers Heart (`00fd1dbd-dc4d-47ea-9ffa-68ddf7e5d13f`, PIN 390015) illustrates a linked case. Missing centroid lookup prevents PIN fallback for that PIN, but does not invalidate an independently sourced facility point. Matching may lose PIN corroboration; existing coordinate/name/PIN methods must be reviewed, not automatically rejected.
- **69 state/PIN disagreements**: 7 facilities have 10 links (7 accepted, 3 pending); observed pairs T2 5, T3 11, R 6. Example `08debf77-bd13-4128-a085-15f9d4083ce6`, PIN 390008, Gujarat, has a name+PIN link. These are reference disagreements, not verified wrong states. Check state synonyms/reference vintage, facility source and identity before using state/PIN as corroboration or radius origin. Do not automatically downgrade evidence or choose a different location.
- **234 NQAS district-reference flags**: zero canonical linked rows and zero current service-tier impact. Examples PHC Mandoni (`7c771924186ea553`) and PHC Antela, Dahod (`1321673c78e8704d`). These require Sophia's district-reference review before district-based matching/geographic quality alignment; they are unresolved reference issues, not proven district errors.

None of these warnings justifies deleting records or interpreting evidence absence. The detailed report includes IDs, original values, link methods and overlaps.

## Controlled integration — PASS, not real geographic validation

Actual source adapters → aggregation → LEFT JOIN → existing ranking adapter/ranker → recommendation JSON ran for `emergency_c_section` and `emergency`, each using **40 real canonical IDs/names and real evidence, with explicitly controlled distances/confidence/uncertainty**. No coordinates were assigned and the fixture PIN is not an actual search origin. Both retain **40/40**, no fanout; a T1 placed 40th survives, missing evidence becomes U, pending T1 remains explanatory, ordering is deterministic, structured provenance and uncertainty replay correctly, and urgent recommendations remain zero without capability evidence. Duplicate evidence join keys fail. No synthetic source evidence was substituted.

## Severity and next steps

1. **High / BLOCKED integration:** obtain complete teammate-produced `facility_geo_ready` and request-specific untruncated candidates; validate real origins, radius boundaries and uncertainty. See [exact contract](evidence-confidence-integration.md#facility_geo_ready-handoff-contract).
2. **High / PARTIAL identity coverage:** William must supply reviewed pending decisions/queue and resolve unlinked records. Current software respects decisions but cannot establish their real-world accuracy.
3. **Medium / PARTIAL quality coverage:** Sophia must provide canonical NQAS/Kayakalp links, scopes, citations and dates; quality must remain separate from service support.
4. **Medium / PARTIAL reference quality:** Elliot/source owners review PIN/state warnings; Sophia reviews district-reference flags. No automatic repairs or tier changes.
5. **Medium / PARTIAL source dates:** owners verify incomplete validity and withdrawn/expired status. No fresh service event inferred from a snapshot date.

After handoff: check unique canonical point IDs; verify coordinate/basis/uncertainty lineage; obtain complete radius candidates before claim filters/top-N; repeat retention/fanout/provenance/JSON and urgent safeguards on actual requests across multiple locations. Ranking/radius uncertainty policy remains a team decision; this audit changes neither.

## Verification results

- Evidence Confidence unittest discovery: **223 passed**, including nine added review-audit tests. Real snapshot tests skip explicitly when downloads are unavailable; portable synthetic regressions remain runnable without downloaded data.
- Full repository unittest discovery: **223 passed, one import error** (`test_kayakalp`, missing `pdfplumber`); 224 discovery entries. No shared dependency or teammate test code changed.
- `python3 -m pytest -q`: unavailable (`No module named pytest`).
- Existing synthetic smoke: **32/32 retained**, zero hard errors, five expected warnings; synthetic regression evidence only.
- `python3 -m compileall -q evidence_confidence tests`, `git diff --check` and `git diff --cached --check`: passed. No changes staged or committed.
- Final replay artifacts: `shared/runs/evidence-confidence/review-audit-20261122-final/`; explicitly compares the complete evidence payload and geographic uncertainty before/after ranking and JSON serialization, in addition to independent pipeline replay.
