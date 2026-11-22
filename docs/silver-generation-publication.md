# Silver generation and GitHub publication preflight

Status: **BLOCKED before execution/publication**, inspected 2026-11-21 23:25 US Eastern on `alice-evidence-confidence`. Existing HEAD: `236838212f1af6e389b46dd354700b76223051ef`. The worktree was clean at inspection. No pipeline job, table write, environment installation, commit, push, PR or merge was performed. No transformation was reimplemented.

## Stop condition reached

The requested workflow explicitly prohibits uploading datasets when redistribution rights are unclear and requires stopping before publication if prerequisites fail. `docs/data-sources.md` currently records:

- Virtue Foundation facilities (§1): Marketplace/datathon terms apply; copying the licence line is still TODO. This affects facilities, claims, potential duplicate/rejection outputs and cross-source links/summaries derived from them.
- NQAS (§2), Kayakalp (§3), NMC (§7), LaQshya (§9), trauma (§8): no explicit open-data licence documented.
- DNB/ANBAI (§6) and NABH (§11): no open redistribution licence documented.
- NCG (§10): “All rights reserved”; explicitly says to check with organizers before redistribution outside the datathon.
- PIN/NFHS (§4/§5): GODL is recorded conditionally, dependent on the actual source. Those conditions must be substantiated for the actual files before claiming redistribution clearance.

These are unresolved recorded terms, not a legal determination that use is prohibited. Public accessibility, citation, existing raw CSVs in Git, compression, a private branch, LFS or Releases do not establish permission to upload additional derived files. No restricted-source subset was silently omitted from an “all datasets” release. The content/privacy review of generated outputs has not run because no outputs were generated.

## Correct setup usage and runtime

The expected file **exists at `notebooks/setup_pipeline.py`**. It is a Databricks source notebook, not a standalone local CLI with `--catalog` arguments. It requires `dbutils`, an active Spark session and `databricks.sdk.WorkspaceClient`.

Its widgets are `catalog`, `schema`, `job_name`, `repo_root`, `run_job_after` (`no`/`yes`). It:

1. Locates the workspace Git folder and creates the configured schema.
2. Loads 12 missing Bronze tables from actual repository CSVs; existing Bronze tables are kept. It now correctly uses backslash escaping for the facilities CSV and quote escaping for the other CSVs.
3. Creates or **updates** the named serverless Lakeflow job with sequential tasks 00–06.
4. Runs that job only when `run_job_after=yes`.

It does **not** install a local Spark environment or write repository Silver export files. Setup alone, with the default `run_job_after=no`, does not execute the Silver transformations. Updating an existing shared job by its default name would affect teammates; a future authorized run must use an isolated schema and unique job name, with existence checks before overwriting any output.

`notebooks/run_pipeline.py` is the existing `dbutils.notebook.run` orchestrator, with logging to `pipeline_run_log`. The setup notebook explicitly warns not to use it on serverless notebook compute; the Lakeflow job is the intended serverless runner. On compatible local/classic execution its dependencies are 00 → 01/02/04/05, 01+05 → 06, with 03 independent. Setup's job instead runs 00–06 sequentially.

Local checks: Java 17.0.16 and Databricks CLI 1.27.0 exist. The active Python lacks PySpark, Delta, Databricks SDK, pytest and pdfplumber; pyarrow is available. The documented local harness is WSL/Linux-specific (`scripts/local_spark/setup_wsl.sh`, `run_all.sh`), expects `~/sparkcheck` and has not been provisioned on this macOS environment. Installing or switching runtimes was not attempted after the publication stop condition. Remote authentication, workspace paths, compute availability and write permissions were not checked or assumed valid.

## Actual inputs and expected outputs

Actual local inputs exist: five CSVs in `data/raw`/`data/external`, nine registry Bronze input CSVs and two registry reference CSVs. Presence/byte sizes were inspected; successful parsing or Bronze ingestion is not claimed. The facilities input is about 74.6 MB and requires the notebook's specific parser settings. No synthetic source is needed or allowed.

All output names below are **expected tables**, not newly generated files. Location is the explicitly chosen `<catalog>.<schema>`. No actual output row count/schema/type/nullability validation was performed in this attempt; each generation/validation status is **FAIL/BLOCKED (not executed)**, not an assertion of bad records.

- **00:** India Post CSV → `pincode_bronze` → `pincode_silver` (PK `office_id`; PIN, office type/delivery, district/state, coordinates/status, ambiguity, raw fields, DQ/provenance) and `pincode_centroids_silver` (PK `pincode`; median coordinates, spread, office/district/state counts and confidence/ambiguity). Also `pincode_rejected`, `pincode_dq_summary`, `pincode_validation`. Source schema is defined by notebook 00's `ORDER` and centroid projection. Temporary `_pincode_*_stage` tables are not release datasets.
- **01:** facilities CSV/Marketplace Bronze plus PIN reference → `facilities_silver` (PK canonical lowercase UUID `facility_id`; cleaned display/address, coordinates/PIN/status, facility facts, retained text claims and DQ/merge metadata). Also `silver_facility_claims` (facility × claim field × position), `silver_possible_duplicates` (candidate pairs), `silver_rejected_facilities`, `silver_dq_summary`, `facilities_validation`. Schema/projections are in notebook 01 and `docs/silver-tables.md`; actual types require readback. `_facilities_*` staging/check tables are excluded from publication.
- **02:** `nqas_certified_facilities`/configured Bronze + PIN district reference → `nqas_silver` (PK `certification_id`; facility/type/geography, department scope, parsed/raw validity dates, status, names, DQ and seven provenance fields). Static `ORDER` has 30 columns. Validation table: `nqas_validation`. `_nqas_silver_check` is intermediate.
- **03:** extracted `kayakalp_bronze` → default `kayakalp_silver_validation` (PK `award_id`; FY, facility/type, locality/district/state, award rank/category, PDF page and serial, raw source values, DQ, provenance). Static `ORDER` has 30 columns. **Execution defect for the requested full-generation goal:** both setup's task and `run_pipeline.py` omit `write_output=true`, while notebook 03 defaults false. Therefore a green job is insufficient proof of persisted Kayakalp Silver. A future run must explicitly pass `write_output=true` and a new output name; existing outputs are creation-only and must not be replaced. No change was applied because execution/publication is blocked.
- **04:** NFHS source CSV/table → `nfhs_bronze` → `nfhs_silver` (state/district grain, typed indicators, normalized keys, survey/sample/quality/geographic checks, provenance), `nfhs_quarantine`, `nfhs_quality_history`, `nfhs_quality_current` (view), `nfhs_validation`. Its schema is the final projection in notebook 04. `_nfhs_stage` is intermediate. Historical health indicators are not facility service availability.
- **05:** nine registry Bronze tables (LaQshya facilities/certifications, trauma, NMC colleges/courses, DNB hospitals/specialties, NCG members, NABH organisations) plus optional PIN reference → `registry_sites_silver` (PK `site_id`, 33 static projected columns including source ID, names, listing scope/status, geography, DQ/provenance) and `registry_services_silver` (PK `service_row_id`, 23 static projected columns including FK `site_id`, canonical service, evidence type/directness/detail, date/validity/current status, DQ/provenance). Full columns are `SITE_ORDER`/`SERVICE_ORDER` in notebook 05. Missing sources can be skipped by the notebook; a future all-source release must explicitly verify source inventory rather than accept a successful partial run.
- **06:** `facilities_silver` + registry sites/services → `facility_registry_links_silver` (PK `link_id`, facility/site FKs, match score/method, review state/reasons and geographic match evidence), `facility_registry_summary_silver` (PK `facility_id`, registry/service aggregates), `registry_match_review` (review queue). Use final projections in notebook 06. Matching and canonical service semantics must remain unchanged.
- **Separate geographic producer:** `notebooks/common/pin_nearby_facilities.py` builds `facility_geo_ready` and produces request distances; it is **not included in setup's 00–06 job**. Its displayed search uses substring filtering and a nearest-25 default, so it is not an acceptable complete pre-enrichment candidate export without an agreed upstream integration change.

Existing output directories `data/processed`, `datasets/silver`, `spark-warehouse` and `metastore_db` do not exist in this worktree. Ignored `shared/runs/evidence-confidence/real-silver` contains prior audit/regression reports, not a complete Silver release. A sibling worktree's earlier 1,197-row Kayakalp export is preserved and is not reported as generated by this attempt. No valid existing table/file was overwritten.

## GitHub publication preflight

- Tracked working-tree file content totals 121,357,845 bytes (about 115.7 MiB); this is not a push pack or generated Silver size. Largest tracked file is the facilities CSV, 74,606,937 bytes. `.git` has about 46.20 MiB loose objects and 4.50 MiB packs; `git count-objects` also reported a pre-existing 64-byte worktree refs garbage item. No cleanup was attempted.
- `.gitignore` excludes `data/processed/`, `shared/runs/`, `.venv`, caches and environment secrets. `.gitattributes` only specifies LF for shell scripts; no LFS tracking rules exist. No force-add or LFS configuration change was made.
- GitHub warns above 50 MiB and blocks regular Git files above 100 MiB ([official file-size limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)); a single push is limited to 2 GiB ([official push limit](https://docs.github.com/en/get-started/using-git/troubleshooting-the-2-gb-push-limit)). Generated Parquet sizes cannot be known until generation/export. No arbitrary splitting, LFS or Releases upload was attempted.
- A later authorized, licensed release should export compact compressed Parquet plus a deterministic manifest (source hashes, code revision, schemas/types/nullability, primary keys, counts, validation findings and licences). Include no credentials, personal contact details, temporary stage/check data, Spark metastore, checkpoints, caches or unnecessary raw/intermediate artifacts. Actual contents need review before staging; public facility directories alone are not proof that every text field is non-personal.

## Reproduction and validation gates after blockers are cleared

1. Establish dataset-specific redistribution permission and actual-source licence/attribution requirements. Resolve the Marketplace TODO and NCG restriction; do not assume facts or citations waive these requirements.
2. Provision the existing documented local Spark/Delta harness in an isolated compatible environment, or use the existing authenticated Databricks profile `CMU_Datathon_26` with explicit isolated catalog/schema/job parameters. Do not target existing shared schemas/jobs. Run setup as a notebook via widgets; set `run_job_after=no` until job parameters are reviewed, then ensure step 03 is explicitly persisted to a new name and all nine registry sources exist before execution.
3. Capture actual per-step logs/timings/check results and read each generated table back in an independent session. Verify keys, required nulls, record counts, PIN/coordinate validity, facility/site FKs, canonical service vocabulary, DQ/quarantine conservation, citations, validity and accepted/pending/rejected handling. Export schema and data only after every dataset's status is recorded; never call skipped datasets successful. Compare source/documented expectations without promoting historical counts to new-run results.
4. Export licensed, validated final outputs to a new run-specific directory; compare hashes/row sets where deterministic. Date/status columns based on current time and run metadata need an explicit fixed as-of or documented nondeterministic exclusions. Teammates can load a resulting file with `pyarrow.parquet.read_table(path)` or `spark.read.parquet(path)`; **no release file path exists yet**.
5. Review exact staged files and byte sizes, source rights, secret/personal-data checks and validation manifest. Only then commit intended pipeline/docs/data files and push non-forcibly to `origin/alice-evidence-confidence`. Verify remote commit and file hashes/paths. Never include unrelated Evidence Confidence changes, main updates, or a PR.

## Results of this attempt

- Setup execution: **BLOCKED/not run**. Bronze-to-Silver execution: **BLOCKED/not run**.
- Newly generated Silver datasets: **none**. New output row counts/schemas: **not measured**.
- Pipeline validation: **not run**; no PASS claims. Redistribution clearance: **FAIL/unresolved**. Local execution prerequisites: **WARNING/incomplete**.
- Published data: **0 bytes**, zero files. New commit SHA: **none**. Target branch remains `alice-evidence-confidence`; no remote modification occurred.
- Teammate access paths: no new Silver files are available from this attempt. Existing source notebooks and documentation remain the reproducibility entry points.
- Evidence Confidence readiness: **BLOCKED** on complete real Silver generation/exports, explicit cross-source links and complete geographic candidates; prior synthetic results do not establish real-data readiness.
