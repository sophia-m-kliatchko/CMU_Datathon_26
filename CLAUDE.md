# CLAUDE.md

## Project
CMU Datathon Fall 2026, "Find the right care": given a medical service and a location in India, recommend facilities from the Virtue Foundation dataset with cited, evidence-based explanations and honest uncertainty. Must run on Databricks Free Edition. Team of 4.

## Branches
- Claude's work for Sophia goes on the **`sophia-wip`** branch (tracking `origin/sophia-wip`).
- Claude's work for William goes on the **`Will_branch`** branch.
- Don't commit to `main` unless asked.

## Layout
- `notebooks/`: Databricks notebooks (source `.py` format).
  - `01_bronze_to_silver.py` builds the Virtue Foundation bronze/silver tables.
  - `02_nqas_bronze_to_silver.py` and `03_kayakalp_bronze_to_silver.py` build `nqas_silver` and `kayakalp_silver`.
  - `00_pincode_bronze_to_silver.py` builds the `pincode_*` tables (post offices and PIN centroids).
  - `05_registries_bronze_to_silver.py` builds `registry_sites_silver` and `registry_services_silver` from the scraped service registries in `datasets/external/*/` (see `docs/registries-silver.md`).
  - `06_registry_matching.py` links registry sites to `facilities_silver.facility_id`: `facility_registry_links_silver`, `facility_registry_summary_silver`, `registry_match_review` (see `docs/registries-silver.md`).
  - `04_nfhs_bronze_to_silver.py` (Elliot) builds the `nfhs_*` tables (NFHS-5 district indicators).
  - Table names follow `<dataset>_<layer>`, e.g. `facilities_silver`, `pincode_bronze`.
  - Column names in silver tables carry no `_clean` suffix: being in silver implies clean. A raw column that a cleaned one replaces is left out of silver (kept in bronze), or renamed `*_raw` if it's needed for citations. Don't create `*_clean` columns at all, not even temporarily: rename the colliding raw column first (`src_<name>` / `<name>_raw`), then build the cleaned one under the plain name. Every silver write goes through `assert_no_clean_columns()` (in `write_table()` in `common/reference_data.py`, and inline in notebook 01).
  - `common/reference_data.py` holds the shared lookups (states, name cleaning, facility types, provenance). `common/validation.py` holds the silver-vs-bronze check helpers. `common/address_parsing.py` and `common/coordinate_parsing.py` are plain-Python parsers with Spark UDFs, tested locally by `scripts/test_*.py`. Load them with `%run`.
- `scripts/`: local Python scripts that fetch or convert outside datasets (see `scripts/README.md`).
- `data/external/`: CSVs those scripts produce, for upload to Databricks.
- `docs/`: data citations (`data-sources.md`), dataset notes (`dataset-notes.md`) and the silver-table reference with filtering watch-outs (`silver-tables.md`).

## Run order and validation (required)
- **Run order:** `00_pincode` → `01_bronze_to_silver` (facilities) → `02_nqas` → `03_kayakalp` → `04_nfhs` → `05_registries` → `06_registry_matching`. 01, 02, 04 and 05 read the India Post tables from 00 (04 only for an optional district check); 06 needs 01 and 05.
- **Run everything in order on Databricks:** open `notebooks/run_pipeline.py` and Run all. It runs 00 → 06 with `dbutils.notebook.run`, skips steps whose prerequisites failed, appends one row per step to `pipeline_run_log` (status, seconds, error, failed validation checks), and fails at the end if any step failed.
- **Verify locally before pushing notebook changes:** `scripts/local_spark/run_all.sh` runs every notebook in that order on a local Spark (WSL) against the repo CSVs, and `run_all.sh audit` checks the outputs (see `scripts/local_spark/README.md`).
- Every silver notebook validates its output against its bronze table with `common/validation.py` (`run_validations()`), writes `<dataset>_validation`, and only publishes the silver table if every check passes. New silver notebooks must do the same.
- Coordinates that don't match the record's PIN or state are set to NULL, never kept.

## Data citations (required)
Every table that is scraped, downloaded, converted or assembled from outside data must have an entry in `docs/data-sources.md` (source, publisher, URL, retrieval date, licence, processing chain, limitations, "cite as"), added **in the same commit** as the data or code. Silver tables built from outside sources carry per-row citation columns (`source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by`, `row_citation`). Use `add_provenance()` in `notebooks/common/reference_data.py`.

## Change logging (required)
After every change to this project (code, notebooks, data or cleaning rules, scoring logic, environment or setup, or a design decision), add an entry at the top of the "Entries" section in `DEVLOG.md`, using the template in that file. Each entry records:
- **When:** date and local time (`Get-Date -Format "yyyy-MM-dd HH:mm"`)
- **Who:** the person, or "Claude (for <name>)"
- **What:** the exact files, tables or settings changed
- **How:** commands, tools or approach used
- **Why:** the reason, including any tradeoffs considered

Log the change in the same piece of work as the change itself, not afterward in a batch.
