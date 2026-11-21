# CLAUDE.md

## Project
CMU Datathon Fall 2026, "Find the right care": given a medical service and a location in India, recommend facilities from the Virtue Foundation dataset with cited, evidence-based explanations and honest uncertainty. Must run on Databricks Free Edition. Team of 4.

## Branches
- Claude's work for Sophia goes on the **`sophia-wip`** branch (tracking `origin/sophia-wip`). Don't commit to `main` unless asked.

## Layout
- `notebooks/`: Databricks notebooks (source `.py` format).
  - `01_bronze_to_silver.py` builds the Virtue Foundation bronze/silver tables.
  - `02_nqas_bronze_to_silver.py` and `03_kayakalp_bronze_to_silver.py` build `nqas_silver` and `kayakalp_silver`.
  - `common/reference_data.py` holds the shared lookups (states, name cleaning, facility types, provenance); load it with `%run`.
- `scripts/`: local Python scripts that fetch or convert outside datasets (see `scripts/README.md`).
- `data/external/`: CSVs those scripts produce, for upload to Databricks.
- `docs/`: data citations (`data-sources.md`), dataset notes (`dataset-notes.md`) and the silver-table reference with filtering watch-outs (`silver-tables.md`).

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
