# Kayakalp validation and integration handoff

Worktree branch: `codex/kayakalp-validation`, based on Sophia's `eb813a7af257f402f2d9f96e71aadd5b769dad9a`.
Fetched refs inspected: main `839a656fd30fb16f98da608cd228a03094f90b9f`, alice `e482006870e11cebba41ab5e22eef391f124a022`, sophia-wip as above.
The original alice checkout has uncommitted orchestration/configuration files; those were read and left untouched. No push, merge, commit, Databricks write, canonical-ID change, or facility matching was performed.

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

Tested with Python 3.10, Java 17 and Spark 4.2.1, with ANSI mode enabled. Databricks execution has NOT been performed. `try_element_at` requires Spark 3.5+; select a compatible Databricks runtime. Local Spark needs localhost socket access. Initial restricted-sandbox startup failed; a subsequent run exposed machine-wide Spark/Python version mismatch, resolved by using the venv's Spark distribution. Logs retain both failures.

## Databricks instructions (Sophia)

1. Keep the original PDF and committed CSV immutable. Upload the CSV as a **new** isolated Bronze table using strings (header enabled); verify 1,197 rows. Retain the PDF and the raw-table audit alongside it. Do not overwrite existing shared Bronze.
2. Import notebook 03 and its `common/reference_data` dependency preserving relative paths. Set catalog/schema to your sandbox, `bronze_table` to the uploaded table, and a new `silver_table` such as `kayakalp_silver_validation_sophia`. Widget identifiers accept simple names only; catalog/schema are separate widgets.
3. Leave `write_output=false`. Keep the existing NHSRC source URL. Run all cells; this produces the `silver` DataFrame and session-local `kayakalp_validation_result` view, and no persisted output. Check the counts/flags below. Retrieval date is inherited as 2026-11-21, the recorded conversion date; a distinct download timestamp has not been verified.
4. If the validation result is accepted, `write_output=true` can create a **new** table; `errorifexists` rejects any existing target. Alice's approval is required to replace shared tables or change shared schemas/IDs. This notebook provides no overwrite operation.
5. If table creation succeeds but its comment or readback fails, the new table remains. Inspect it read-only; reruns intentionally refuse to replace it. Do not drop a shared table to bypass that guard.
6. Compare the actual Databricks schema/metrics with local `silver_schema.json` and `silver_metrics.json`, then hand the candidate to Elliot for matching. These instructions are prepared, not executed.

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
