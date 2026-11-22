# Kayakalp validation and integration handoff

## Comprehensive read-only audit

[Kayakalp Silver audit](kayakalp-silver-audit.md) records fresh source/CSV/Bronze/Silver comparisons, all 18 independently recalculated DQ rules, full-row equality, Delta history/schema, postal-geography corroboration and latest Sophia compatibility. **Integrity PASS; overall PARTIAL for downstream readiness.** Newly confirmed risk: three blank `name_core` keys (368, 371, 559); geography leaves 291 awards in 218 state/district groups unresolved. No source awards removed or data changed. Audit run `793080827549335`; corrected supplemental SQL verifies 17 cross-category groups / 34 awards. Claude review unavailable (unauthenticated). See the report for severity, evidence, exact mapping and recommended actions.

Worktree branch: `codex/kayakalp-validation`, based on Sophia's `eb813a7af257f402f2d9f96e71aadd5b769dad9a`.
Fetched refs inspected: main `839a656fd30fb16f98da608cd228a03094f90b9f`, alice `e482006870e11cebba41ab5e22eef391f124a022`, sophia-wip as above.
The original alice checkout has uncommitted orchestration/configuration files; those were read and left untouched. Initially no push, merge, commit, Databricks write, canonical-ID change, or facility matching was performed. The subsequent authorized isolated Databricks Bronze import and validation are recorded below.

## Silver persistence compatibility fix — 2026-11-21

**Created and verified:** [`labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation`](https://dbc-5d71d4f7-4568.cloud.databricks.com/explore/data/labuser_alice083073/alice_kayakalp_validation_20261121_215928/kayakalp_silver_validation), a managed **Delta** table owned by `alice083073@gmail.com` (Unity Catalog table ID `e311a3b9-552d-4d75-9550-a12a60c7624b`). The blocked/absent-table reports in the older sections below are historical and superseded by this creation run.

[Successful creation run 401124689166111](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/805156129230276/run/401124689166111), [task 448184821358158](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/805156129230276/run/448184821358158), ran the patched notebook plus readback assertions in a new isolated notebook `persistence_ctas_verified`. Automatic retries were disabled. Profile `CMU_Datathon_26`; existing Free Edition serverless STANDARD; Spark Connect 4.2.0. No Bronze ingestion, shared-resource modification, or cluster/warehouse creation was performed. The original-named workspace notebook remains the prior audit snapshot; use the verified new execution artifact or current local source for this fix. Relative `%run ./common/reference_data` loads the unchanged isolated dependency.

Only persistence changed: after the original pre-write validations, `spark.catalog.tableExists(SILVER)` explicitly rejects an existing target; a uniquely named temporary view registers the already-transformed DataFrame in that same Spark session. Plain CTAS rejects a concurrent creation as well. No `IF NOT EXISTS`, table overwrite/replacement, DROP or TRUNCATE is used. Executed SQL (after `USE CATALOG labuser_alice083073` and `USE SCHEMA alice_kayakalp_validation_20261121_215928`):

```sql
CREATE TABLE `kayakalp_silver_validation` USING DELTA AS
SELECT * FROM `kayakalp_silver_to_persist_551be76d378c4284a8740b9f857d482a`;
```

That source view existed inside the creation session; no separate job was expected to see it. The table comment was retained. Immediately after creation, both `silver.exceptAll(persisted).count()` and `persisted.exceptAll(silver).count()` were zero. No cleaning, citation, identity, filtering, sorting-key, or 30-column schema logic changed; the region before the write branch was compared byte-for-byte with HEAD.

Actual persisted readback results:

- Bronze rows **1,197**; Silver rows **1,197**; unique award IDs **1,197**.
- **30 columns**, with names, order and data types matching the validated baseline. Full persisted schema JSON is retained in `persistence_ctas/result.json` and table metadata. Existing column contract below remains unchanged.
- Complete source provenance and row citations: zero nulls across `source_file`, `source_page`, `source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by`, and `row_citation`; full-row equality also verifies their exact values. No missing award identity/name/clean district/state/facility level.
- All **1,197 full rows** match the previously validated output, including raw values, arrays, dates and citations. Canonical full-row SHA-256: `9662107fc18ff74e9db70cc2498c4981f383905ebeaa7738ba5a4cdd13556472`.
- DQ flag counts: locality **112**, district repairs **17**, duplicate candidates **20**, health jurisdictions **11**, type conflicts **47**, ordinal ranks **11**, verified spacing **2**; no additional flags. Every column null count matches baseline, including 475 missing name-derived types and 1,085 absent localities.
- `DESCRIBE DETAIL` reports **delta**, one data file, 88,868 bytes. Unity Catalog independently reports **MANAGED / DELTA / 30 columns**.

Independent read-only verification: [run 292844685607275](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/335598850036350/run/292844685607275), task `332622733279674`, reads the fully qualified persistent table from a distinct job/session, with no transformation or creation-session view. It completed **SUCCESS**, returning **PASS** for every check: 1,197 rows/unique IDs, 30 names/types, Delta format, all provenance/null/DQ metrics and the identical full-row baseline hash. This proves persistent-table queryability independently of the creation session. The creation harness reused the reader's descriptive `session` string; actual independence is established by these distinct execution IDs, not that label.

### Latest Sophia naming assessment

Checked `sophia-wip` at [`e7f701b062a15191e3758f771410ddd204a70ee9`](https://github.com/sophia-m-kliatchko/CMU_Datathon_26/commit/e7f701b062a15191e3758f771410ddd204a70ee9), now 13 commits ahead of the common base, while this branch has its one validation commit plus local changes. Her [Kayakalp notebook](https://github.com/sophia-m-kliatchko/CMU_Datathon_26/blob/e7f701b062a15191e3758f771410ddd204a70ee9/notebooks/03_kayakalp_bronze_to_silver.py) still emits `district` and `state`. Her [reference helper](https://github.com/sophia-m-kliatchko/CMU_Datathon_26/blob/e7f701b062a15191e3758f771410ddd204a70ee9/notebooks/common/reference_data.py) still rejects `_clean` names in `write_table` and then uses overwrite. Neither shared helper nor Sophia's notebook was changed or invoked for writing.

Recommended downstream mapping, subject to agreement: **`district_clean AS district` and `state_clean AS state`**. Apply it in an explicitly reviewed consumer projection; keep this persistent validation snapshot's 30 columns intact. Retain `district_raw`, `state_raw`, `state_pdf`, `award_id`, all provenance/citations and DQ flags. This naming projection alone is not facility matching or permission to rewrite any canonical schema. Elliot's accepted match contract and historical-evidence limitations below still apply. No compatibility view or canonical rename was created.

### Verification artifacts and limitations

Artifacts are gitignored under `shared/runs/kayakalp-validation/databricks/persistence_ctas/`: exact executed harness/export, submission, source checks, creation result/output/state, persisted schema/table metadata, independent results, current Sophia sources/comparison and local-check notes. Generated data/credentials were not committed. Validation queries are retained with the previous audit under `persistence/validation_queries.sql` (use the fully qualified persistent table now); exact-row multiset checks run in the creation notebook, and canonical baseline-hash checks run in both readers.

CTAS preserves column names/order/types and values but persists all fields as nullable; uniqueness and provenance are verified data properties, not NOT NULL/primary-key constraints. Expected local DataFrame non-nullability is not an enforced table contract. The supplied PDF's retrieval metadata remains the recorded 2026-11-21 conversion date. Sophia's effective SELECT access has not been independently authenticated; no grants changed. Claude CLI remains unauthenticated, so independent Claude review is **unavailable**, not required to finish persistence. Local selected tests: three extraction tests passed, seven Spark tests failed at Java gateway startup (`JAVA_GATEWAY_EXITED`), two local write tests deliberately not run; actual Databricks creation/readback is the substantive persistence test. Compile and whitespace checks passed. No push, merge or PR.

## Persistence follow-up — 2026-11-21: blocked by runtime compatibility

The authorized creation attempt used profile `CMU_Datathon_26`, catalog `labuser_alice083073`, schema `alice_kayakalp_validation_20261121_215928`, Bronze `kayakalp_bronze`, Silver `kayakalp_silver_validation`, and `write_output=true`. Target fully qualified name: `labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation`. **This is an intended target, not a verified persistent table.** Delta format, persisted schema, persisted row counts, full-row equality, provenance, DQ counts and separate-session queryability cannot be certified unless creation succeeds.

Current schema inventory initially contained only managed Delta Bronze, owned by `alice083073@gmail.com`; Bronze metadata still reported 1,197 rows. Schema is owned by the same user. Schema/table grants APIs returned empty objects; this does not establish Sophia's effective access. No grants were changed. Exported notebook 03 and `common/reference_data` match the validated local source byte-for-byte (SHA-256 `e760f9901fffb7e8b887edcaef1b803e12066f7d59f732a45783192dfffa6c70` and `5d7683965c3e583cc99bcc8737dd5304e3d39b6455a98a3b13ae3d212f5f8eb0`). No transformation or write behavior was modified.

[Persistence run 435719543418633](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/361631103308538/run/435719543418633), using existing workspace serverless STANDARD, failed in [task 11684085239436](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/361631103308538/run/11684085239436) at `silver.write.mode("errorifexists").saveAsTable(SILVER)`: **`[UNSUPPORTED_OPERATION] errorifexists is not supported.`** The client raises while constructing the write command, before table creation. Pre-write row-preservation, identity, FY and uniqueness assertions were reached without failure. Databricks scheduled an automatic retry; Codex canceled it after confirming this deterministic error, so the parent run is CANCELED and the first task attempt is FAILED. No alternate CREATE/overwrite implementation was substituted. Persistence cannot be completed under the requirement to keep this exact unsupported behavior on this runtime.

Independent read-only session: [run 694938706475969](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/867605608007611/run/694938706475969), using a new audit notebook in Alice's existing isolated workspace folder. It reads fully qualified Bronze and checks the persistent Silver catalog entry without loading the transformation or temporary view. It completed successfully on Spark 4.2.0 and returned `bronze_rows=1197`, `silver_exists=false`, `status=BLOCKED_NO_PERSISTED_SILVER`. A separate Unity Catalog `tables get` also returned table does not exist. The read-only job succeeded as an inspection; the requested Silver persistence goal remains blocked. No partial table exists, so persisted row/ID/column counts, equality, provenance, flags and Delta format are unverified rather than failed data checks.

Audit artifacts are gitignored under `shared/runs/kayakalp-validation/databricks/persistence/`: submission specifications, unchanged source exports/hashes, failure traceback, independent readback notebook/results, `validation_queries.sql`, branch comparison and Claude review. The independent notebook includes all requested checks if a table exists: 1,197 rows/IDs, 30 ordered names/types, exact full-row baseline hash, every null count/provenance field, DQ counts and Delta `DESCRIBE DETAIL`. Expected values remain those in the successful validation-only section below; they are not persisted-table results.

Claude CLI independent review was requested with supplied actual failure evidence, source hashes, submission parameters and integration findings, using `claude -p --permission-mode plan --tools '' --no-session-persistence`. It exited 1 with **`Not logged in · Please run /login`**. No review verdict was obtained; prior validation-only Claude PASS does not cover this persistence attempt. Review prompt and raw CLI response are retained in the ignored persistence audit folder.

Read-only validation queries (Silver queries are prepared but **not executed**, because the table is absent):

```sql
SELECT count(*) AS bronze_rows
FROM labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_bronze;
-- Independent session executed the equivalent spark.table(FQN).count(): 1197.
SELECT count(*) AS awards, count(DISTINCT award_id) AS award_ids
FROM labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation;
DESCRIBE TABLE labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation;
DESCRIBE DETAIL labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation;
SELECT flag, count(*) AS awards
FROM (SELECT explode(dq_flags) AS flag
      FROM labuser_alice083073.alice_kayakalp_validation_20261121_215928.kayakalp_silver_validation)
GROUP BY flag ORDER BY flag;
```

Full provenance-null SQL is retained in `validation_queries.sql`. The independent readback implementation hashes all ordered rows and all 30 columns with the same canonical JSON serialization as the validated baseline (`9662107fc18ff74e9db70cc2498c4981f383905ebeaa7738ba5a4cdd13556472`); those Silver checks were skipped because the table is absent. Expected schema and all seven expected DQ counts are recorded below. `git diff --check` passed; no code changed, so no transformation regression rerun was needed.

### Sophia integration recommendations

GitHub connector comparison pinned latest `sophia-wip` at [`106316d2d81db70755e8e94aaaef2241e0d4f2fd`](https://github.com/sophia-m-kliatchko/CMU_Datathon_26/commit/106316d2d81db70755e8e94aaaef2241e0d4f2fd). Current branch HEAD remains `ef8f86ab06751f3acd469f3c085a4424d6628ac5`; branches diverged from `eb813a7af257f402f2d9f96e71aadd5b769dad9a`, with Sophia 11 commits ahead and this branch one commit ahead of that base. Existing local handoff/DEVLOG changes were preserved. Shell git could not resolve GitHub; the connected GitHub API supplied the current comparison and pinned notebook sources. No branch checkout, merge, push or remote ref update was performed.

- Sophia's current notebook outputs `district` and `state`; this validated 30-column snapshot uses `district_clean` and `state_clean`. Agree on a downstream projection (`district_clean AS district`, `state_clean AS state`) or an approved revised contract before Evidence Confidence integration; do not rename this validation snapshot silently.
- Her updated reference helper adds `assert_no_clean_columns` and calls it in `write_table`; that helper then uses overwrite/overwriteSchema. Do not route this isolated snapshot through that helper. Preserve creation-only semantics and separately resolve the unsupported mode with explicit authorization to change the requested write behavior or a compatible existing runtime.
- Reconcile notebook 03 and `common/reference_data.py` together, preserving validated spacing repairs, flags, row-level provenance, and identity guards. Review overlapping `DEVLOG.md`, `docs/data-sources.md`, and `docs/silver-tables.md` edits; do not replace Sophia's changes wholesale. Her unrelated pincode, coordinate and NFHS work needs no change here.
- Keep award grain and accepted Elliot facility matches; retain ambiguous/unmatched records, all raw fields, FY, citations and flags. Award rank is not a calibrated clinical score. Confirm Sophia has effective USE CATALOG, USE SCHEMA and SELECT access before review; no access grant was inferred or applied.
- Gate downstream use on successful persistent readback and exact baseline equality. Current status blocks Evidence Confidence ingestion from this target.

## Databricks validation completed — 2026-11-21

Follow-up review refreshed the existing table metadata and successful run/output without rerunning the transformation or starting compute. Bronze still exists, with statistics of 1,197 rows agreeing with the actual count assertion in the successful run. Remote output was compared again with local baseline metrics, 30 names/types and full-row hash; all matched.

The original-named notebook was missing as a separate workspace object (its exact body had already run inside the harness). Added it without overwrite or execution: [03_kayakalp_bronze_to_silver](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#notebook/4423157661544813). Its exported contents and [common/reference_data](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#notebook/4423157661544807) match local source exactly. [Executed validation notebook](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#notebook/4423157661544812). [Retained isolated Bronze table](https://dbc-5d71d4f7-4568.cloud.databricks.com/explore/data/labuser_alice083073/alice_kayakalp_validation_20261121_215928/kayakalp_bronze).

Claude CLI independently reviewed the final remotely retrieved results and local report and returned **PASS for validation-only**. No metric/provenance discrepancy blocks the result. Limits: tested all-string Bronze, compared names/order/types rather than nullability, did not execute the newly separate original-named notebook, and did not validate the optional Silver write branch. No rerun is needed for the requested validation. Final review and refreshed evidence are under `shared/runs/kayakalp-validation/databricks/review/`. No tables overwritten, shared/Sophia resources modified, compute created, or branches merged during follow-up.

The existing `CMU_Datathon_26` profile authenticated as `alice083073@gmail.com`; no profile or credential changes. Current branch is `alice-kayakalp-validation`, HEAD `ef8f86ab06751f3acd469f3c085a4424d6628ac5`. The pipeline and reference dependency match HEAD, and uploaded source exports match local files byte-for-byte.

[Successful Databricks run 485076506625337](https://dbc-5d71d4f7-4568.cloud.databricks.com/?o=7474648724543803#job/534609618194805/run/485076506625337) completed on serverless STANDARD, Spark 4.2.0, with `write_output=false`. (The exact run URL is retained in `run_state_v2.json`.) All assertions passed:

- Bronze rows, Silver rows, unique award IDs: **1,197 each**.
- **30 column names, order and data types match** the local schema. Nullability is recorded separately; persistence/runtime can change inferred nullability.
- All 1,197 complete output rows match the local reference, including every provenance field, raw value and citation. Canonical full-row SHA-256: `9662107fc18ff74e9db70cc2498c4981f383905ebeaa7738ba5a4cdd13556472`.
- CSV SHA-256 matches the immutable source: `1fa942e710285a2adcc2ab88ac70dac7f2806111915cb4760ec510d86941c9d2`.
- DQ counts: locality fields 112; repaired district 17; possible duplicate awards 20; health jurisdictions 11; facility type conflicts 47; raw ordinal ranks 11; verified district spacing 2. All column null counts match baseline, including 475 absent name-derived types and 1,085 null localities; no missing provenance, name, clean district/state or facility level.
- No persisted Silver table exists. Existing personal/shared tables and Sophia's data were not modified; no branches merged or pushed.

Isolation: new schema `labuser_alice083073.alice_kayakalp_validation_20261121_215928`, containing only the new `kayakalp_bronze` table. Workspace artifacts live under `/Workspace/Users/alice083073@gmail.com/alice-kayakalp-validation/20261121_215928`, including the immutable CSV/PDF, raw PDF audit, matching `common/reference_data`, and execution notebooks. These audit resources are intentionally retained. The pipeline body was included unchanged between isolated staging and result assertions; job parameters select the sandbox explicitly and v2 asserts them before staging.

Discovery inspected all five catalogs and their schemas, personal-table inventory, workspace folders, jobs, pipelines and compute. No classic clusters, persisted jobs or Lakeflow pipelines were present initially; one Serverless Starter Warehouse (`64ecbf7c9160e517`, 2X-Small) was initially stopped. Existing campus Bronze/Silver/Gold tables were avoided. Genie found no existing Kayakalp table; manual catalog/schema inventory confirmed the personal catalog as the isolated target.

Initial run `313746975724142` failed during staging before table creation because this Spark Connect client rejects the `errorifexists` save-mode alias. Retry harness v2 uses creation-only SQL `CREATE TABLE ... USING DELTA AS SELECT` without REPLACE or IF NOT EXISTS; the original transformation is unchanged. Its optional `write_output=true` branch was **not tested** and uses that same unsupported alias; it needs a compatible creation-only implementation before future persistence. This does not affect the successful validation-only run.

Claude was involved through the existing read-only `claude -p --permission-mode plan` CLI workflow. First review lacked submission context and raised three findings; second review received actual base parameters and matching source hashes and explicitly cleared all three. Claude did not execute Databricks or independently recompute hashes. The v2 staging compatibility fix was executed and verified by Codex.

Evidence: `shared/runs/kayakalp-validation/databricks/` contains config, submit specifications, both harnesses and workspace exports, source hashes, initial failure output, successful run metadata/output, parsed `result.json`, resource inventories, and both Claude reviews. This folder is gitignored, as are the earlier local audit artifacts. No approval is needed to accept these validation results; persisting Silver or changing shared data is outside this run.

## Validation results

The committed PDF was re-extracted using Sophia's parser. All 1,197 rows and all 13 CSV fields match the committed CSV exactly. Serials are 1–1197, with no gaps/repeats. All CSV fields are populated; all states are recognized. FY is 2021-22 throughout. Categories: 1,148 Kayakalp and 49 Eco-friendly. Ranks: 1,149 Winner, 38 Runner Up, 4 Joint Winner, 4 Joint Runner Up, 2 Best. Types: DH 76, SDH/CHC 79, PHC 536, UPHC 140, HWC 361, UCHC 4, CHC 1. There are 31 represented states/UTs; this is not a completeness claim about India.

The raw table audit has 1,199 rows: 1,197 serial-bearing awards plus a title and header, with no unclassified rows and no continuation merges. This validates the supplied PDF only; arbitrary future layouts, restarted numbering, interleaved states, or continuation pages still need human review.

Before → after (actual local Spark execution of old/new transforms):

- Rows / unique award IDs: 1,197 / 1,197 → unchanged.
- Missing name, district, state, source-page, row citation, source URL: 0 → unchanged.
- Reconstructed district rows: 17 → 17; mixed locality/district fields: 112 → 112.
- Possible duplicate award flags: 20 → 20, all retained (10 Uttar Pradesh pairs, each crossing UPHC/HWC reported types; these may be legitimate distinct awards, not duplicate determinations).
- Verified joined-word district errors: 2 → 0. New `DISTRICT_SPACING_VERIFIED`: 2.
- Newly visible uncertainty: 11 health/HD/municipal jurisdictions, 47 type/name conflicts, 11 raw ordinal ranks.
- Name-based type missing: 475 → 475; all reported types still yield a facility level. Locality is null in 1,085 rows, which is expected for district-only source fields.

PDF SHA-256: `6af952e2caa017f6f9ad92f916848caffa357f08db7556309805a44977607680`.
CSV SHA-256: `1fa942e710285a2adcc2ab88ac70dac7f2806111915cb4760ec510d86941c9d2`.

## Confirmed fixes and remaining uncertainty

PDF page 10 and its independent Poppler layout extraction explicitly show **North Garo Hills** (S.No 607) and **East Khasi Hills** (608). Sophia's spill repair joined their last words. Silver now applies those exact replacements only for Meghalaya, retaining `district_raw`, `state_raw`, source page/serial and a repair flag. No PDF or Bronze/committed CSV values were changed.

Rendered pages 4, 10 and 18 show district text spilling under the colored state column. Poppler text corroborates the repaired spellings, including 248/250/255–257/262/266/267/275 on page 4, 279 on page 5, 606–608/611/612/614 on page 10, and 1178 on page 18. The images alone do not make all overlapped letters legible. All 17 repairs retain uncertainty flags; the general subsequence heuristic is not a geographic authority.

Do not convert health jurisdictions (Basirhat, Diamond Harbour, Bishnupur HD, Nandigram HD, Rampurhat HD) or municipal corporations to civil districts without Elliot's review. The existing last-comma district heuristic is a matching candidate only. Preserve source spellings such as Ahmedaabd and Kutchh; no external geographic corrections were invented. Facility-type conflicts include UCHC Mogab being reported UPHC (246), while another award reports UCHC (211); do not merge or select a type automatically. Ordinal runner-up distinctions survive in `award_raw`; `award_rank_order` is a sort key, not a clinical or calibrated quality score.

## Files and behavior

- `notebooks/03_kayakalp_bronze_to_silver.py`: ANSI-safe empty-array access; two verified spacing repairs; additional DQ flags; identity/year/row-count/uniqueness checks before writing; default validation-only execution; creation-only output prevents overwriting existing tables. Existing 30 output columns and award IDs remain unchanged.
- `scripts/validate_kayakalp.py`: reproducible extraction/CSV comparison, hashes, metrics, and all raw table cells including headers/unclassified content. Fails on extraction drift or unclassified rows; never replaces source files.
- `scripts/kayakalp_pdf_to_csv.py`: documentation corrected to list all existing output fields; extraction behavior unchanged.
- `scripts/requirements-kayakalp.txt`, `tests/test_kayakalp.py`: reproducible local dependencies and extraction/Spark regression checks.
- Existing source/table docs and `DEVLOG.md`: pointers and verified change log.

## Reproduce locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements-kayakalp.txt
.venv/bin/python scripts/validate_kayakalp.py
# Unset a machine-wide SPARK_HOME so pip's Spark distribution and Python agree.
env -u SPARK_HOME .venv/bin/python -m pytest tests -q
python3 -m compileall -q scripts notebooks tests
git diff --check
```

Tested with Python 3.10, Java 17 and Spark 4.2.1, with ANSI mode enabled. Databricks validation-only execution subsequently passed; see the completed-run section above. `try_element_at` requires Spark 3.5+; select a compatible Databricks runtime. Local Spark needs localhost socket access. Initial restricted-sandbox startup failed; a subsequent run exposed machine-wide Spark/Python version mismatch, resolved by using the venv's Spark distribution. Logs retain both failures.

## Databricks instructions (Sophia)

1. Keep the original PDF and committed CSV immutable. Upload the CSV as a **new** isolated Bronze table using strings (header enabled); verify 1,197 rows. Retain the PDF and the raw-table audit alongside it. Do not overwrite existing shared Bronze.
2. Import notebook 03 and its `common/reference_data` dependency preserving relative paths. Set catalog/schema to your sandbox, `bronze_table` to the uploaded table, and a new `silver_table` such as `kayakalp_silver_validation_sophia`. Widget identifiers accept simple names only; catalog/schema are separate widgets.
3. Leave `write_output=false`. Keep the existing NHSRC source URL. Run all cells; this produces the `silver` DataFrame and session-local `kayakalp_validation_result` view, and no persisted output. Check the counts/flags below. Retrieval date is inherited as 2026-11-21, the recorded conversion date; a distinct download timestamp has not been verified.
4. If the validation result is accepted, the patched notebook with `write_output=true` can create a **new** Delta table using an explicit existence check and same-session SQL CTAS; an existing target is rejected. The old workspace snapshot using `errorifexists` is incompatible with this Spark Connect client. Alice's approval is required to replace shared tables or change shared schemas/IDs. This notebook provides no overwrite operation.
5. If table creation succeeds but its comment or readback fails, the new table remains. Inspect it read-only; reruns intentionally refuse to replace it. Do not drop a shared table to bypass that guard.
6. Compare the actual Databricks schema/metrics with local `silver_schema.json` and `silver_metrics.json`, then hand the candidate to Elliot for matching. These instructions were used for the completed isolated validation described above.

Read-only SQL in the same notebook session:

```sql
SELECT count(*) AS awards, count(DISTINCT award_id) AS ids,
       count_if(state_clean IS NULL) AS missing_state,
       count_if(source_url IS NULL OR source_page IS NULL OR row_citation IS NULL) AS missing_citation
FROM kayakalp_validation_result;

SELECT financial_year, award_category, award_rank, count(*) AS awards
FROM kayakalp_validation_result GROUP BY financial_year, award_category, award_rank;

SELECT flag, count(*) AS awards
FROM (SELECT explode(dq_flags) AS flag FROM kayakalp_validation_result)
GROUP BY flag ORDER BY awards DESC;

SELECT s_no, facility_name, district_raw, district_clean, state_raw, state_clean, dq_flags, row_citation
FROM kayakalp_validation_result
WHERE size(dq_flags) > 0 ORDER BY s_no;

SELECT financial_year, award_category, name_norm, district_clean, state_clean,
       collect_list(s_no) AS source_serials, count(*) AS candidate_awards
FROM kayakalp_validation_result
GROUP BY financial_year, award_category, name_norm, district_clean, state_clean
HAVING count(*) > 1;
```

## Silver schema and evidence contract (Alice)

No shared schema change is proposed. The existing 30 columns are:

- Strings: `award_id`, `financial_year`, `facility_name`, `facility_type_reported`, `facility_type_from_name`, `facility_level`, `locality`, `district_clean`, `state_clean`, `award_category`, `award_rank`, `name_norm`, `name_core`, `row_citation`, `award_raw`, `district_raw`, `state_pdf`, `state_raw`, `source_file`, `source_name`, `source_publisher`, `source_url`, `source_license`, `produced_by`.
- Integers: `award_rank_order`, `s_no`, `source_page`.
- Boolean: `district_repaired`. Date: `retrieved_on`. Array of strings: `dq_flags`.

Grain: one source award, keyed by `kayakalp-{financial_year}-{s_no}` for this verified PDF. Repeated facility names and multiple award categories remain separate records. A future source with restarted serials needs an approved identity design, not automatic reuse of this contract.

Use Kayakalp as **historical supporting hygiene/cleanliness evidence for FY 2021-22**. It establishes neither current clinical safety nor clinical outcomes, service availability, staffing, appointment access or treatment suitability. Missing awards do not imply poor cleanliness or absent services. Do not calibrate confidence or count correlated categories as independent evidence without a separate scoring decision.

Elliot owns the facility match and canonical identifier. Keep unmatched/ambiguous awards; do not force matches based on names or `name_core`. Join only accepted matches, carrying the award key, match status/method and geographic uncertainty in Elliot's existing matching contract. Alice should carry the exact category/rank/raw rank, FY, flags, citation URL, PDF/page/serial, and match confidence into evidence scoring. Neither this work nor an award changes canonical facility IDs.

## Checks, Claude review and artifacts

The run folder `shared/runs/kayakalp-validation/` holds prompts, Claude research and reviews, test logs, raw PDF rows, page renders, extraction comparison, local Silver CSV/JSON, schema, before/after metrics, metadata and handoff. It is ignored by the repository intentionally; preserve it separately when sharing the branch. The local Silver export is an audit deliverable, not a Databricks table.

The existing orchestrator in the original alice checkout supports read-only `claude -p` research followed by Codex review. Its `run_agent` helper was reused for the first attempt; after a sandbox failure, direct read-only CLI invocation with supplied source text succeeded. No second implementation agent edited files. Notion sync is not configured (`NOTION_TOKEN` absent); no Notion write was attempted. Its existing summary generator describes research-only runs, so this task keeps an accurate local summary instead.

Executed checks: **12 Kayakalp regression tests passed in 22.41s**, including actual persisted-table create/overwrite guards and all notebook validation SQL; PDF/CSV audit passed; `compileall` and `git diff --check` passed. Five focused existing address regressions passed, but the existing full-data address dry run fails with `_csv.Error: line contains NUL`; this unrelated raw-file/encoding problem was not changed.

Claude research completed with code-only evidence and explicit limitations. First actual diff review returned REVISE: requested table comment preservation, persisted readback checks, overwrite protection regression, complete flag docs, and completed reproducibility/status notes. Codex addressed these and reran the expanded suite. Second/final Claude review returned **REVISE (minor; nothing blocks)**: code and tests were judged sound, with three documentation findings (a split summary table, a pending review-status placeholder, and repeated pointer text). Codex fixed all three; no third review was requested, respecting the two-cycle limit. Final `compileall` and `git diff --check` passed. No review has been represented as a PDF inspection by Claude.

## Approval boundaries

Alice must approve pushing/merging/deployment or shared-table replacement. Shared schema/ID changes, deleting source awards, touching Sophia's active branch, or resolving insufficiently evidenced geography would also require approval; none was performed. Unresolved duplicate/jurisdiction/type cases are handed off without a proposed automatic correction.
