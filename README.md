# Find the Right Care: CMU Datathon Fall 2026

> *A patient needs a specific kind of care. Where should they go, and why should they trust that answer?*

Given a **medical service** (dialysis, emergency C-section, NICU, trauma care…) and a **location in India** (city, district, PIN code or coordinates), recommend the best facilities, **with the evidence behind each recommendation and honest uncertainty**.

The core data is the Virtue Foundation dataset of about 10,000 Indian healthcare facilities, extracted from web pages. Every field in it is a claim, not a fact. This repository turns that data, plus eight outside sources used to check it (the India Post PIN directory, NFHS-5, NQAS, Kayakalp, NABH, DNB, NMC, LaQshya, NCG and the national trauma-centre list), into clean, validated, citable **silver** tables on **Databricks Free Edition**.

---

## Contents
- [The pipeline](#the-pipeline)
- [Run it on Databricks](#run-it-on-databricks)
- [What you get: the silver tables](#what-you-get-the-silver-tables)
- [How we keep the data honest](#how-we-keep-the-data-honest)
- [Data sources](#data-sources)
- [Repository layout](#repository-layout)
- [Verify changes locally](#verify-changes-locally)
- [Working on this repo](#working-on-this-repo)
- [Known issues](#known-issues)

---

## The pipeline

Notebooks in `notebooks/` run in this order. Each reads **bronze** (raw) tables and writes **silver** (clean, validated) tables in `workspace.datathon`.

```
                     ┌─────────────────────────────────────────────┐
 00 PIN directory ──►│ pincode_silver, pincode_centroids_silver    │──┐ (PIN → location, state/district checks)
                     └─────────────────────────────────────────────┘  │
 01 Facilities ◄───────────────────────────────────────────────────────┤  facilities_silver (+ claims, duplicates, rejected)
 02 NQAS        ◄──────────────────────────────────────────────────────┤  nqas_silver
 03 Kayakalp                                                          │  kayakalp_silver_validation (validation mode by default)
 04 NFHS-5      ◄──────────────────────────────────────────────────────┤  nfhs_silver
 05 Registries  ◄──────────────────────────────────────────────────────┘  registry_sites_silver, registry_services_silver
 06 Registry matching (needs 01 + 05) ──► facility_registry_links_silver, facility_registry_summary_silver
```

| Step | Notebook | Builds | Depends on |
|---|---|---|---|
| 00 | `00_pincode_bronze_to_silver.py` | India Post offices (`pincode_silver`) and one centre point per PIN (`pincode_centroids_silver`) | — |
| 01 | `01_bronze_to_silver.py` | Virtue Foundation facilities (`facilities_silver`, `silver_facility_claims`, `silver_possible_duplicates`, `silver_rejected_facilities`) | 00 |
| 02 | `02_nqas_bronze_to_silver.py` | NQAS quality certifications (`nqas_silver`) | 00 |
| 03 | `03_kayakalp_bronze_to_silver.py` | Kayakalp cleanliness/infection-control awards (validation mode unless `write_output=true`) | — |
| 04 | `04_nfhs_bronze_to_silver.py` | NFHS-5 district health indicators (`nfhs_silver`) | 00 (optional check) |
| 05 | `05_registries_bronze_to_silver.py` | LaQshya, trauma centres, NMC, DNB, NCG and NABH as `registry_sites_silver` + `registry_services_silver` | 00 (recommended) |
| 06 | `06_registry_matching.py` | Links registry sites to facilities, with match scores and review flags | 01, 05 |
| 07 | `07_pin_nearby_facilities.py` | Builds `facility_geo_ready` and searches facilities near a PIN code | 00, 01 |

Shared code lives in `notebooks/common/` and is loaded with `%run`:
- `reference_data.py`: state names and aliases, facility types, name cleaning, provenance columns, and the `write_table()` helper.
- `validation.py`: silver-vs-bronze checks, plus a NULL-safe distance helper.
- `address_parsing.py`: splits addresses into street / locality / landmark.
- `coordinate_parsing.py`: repairs coordinates (degree signs, degrees-minutes-seconds, swapped lat/lon).

---

## Run it on Databricks

### First time in a workspace
1. **Add the repo:** *Workspace → Create → Git folder*, pointing at this repository. Use `main` for the verified pipeline, or `sophia-wip` for work in progress.
2. **Get the facilities data:** add the Virtue Foundation dataset from the Databricks Marketplace. `setup_pipeline` can also build the `facilities` table from `data/raw/facilities.csv`.
3. **Run `notebooks/setup_pipeline.py` once** (Run all, serverless). It:
   - creates the schema `workspace.datathon`;
   - creates any missing bronze tables from this repo's CSVs: NQAS, Kayakalp, the 9 registry tables, and facilities. Existing tables are never overwritten.
   - creates or updates the Lakeflow Job **"CMU Datathon pipeline 00-07"**: notebooks 00 → 07 as sequential tasks on serverless job compute.

### Every time
1. **Pull first:** in the Git folder, *Git → Pull*. Always pull before you commit from Databricks; committing from a stale Git folder has already overwritten newer work twice.
2. **Run the job** "CMU Datathon pipeline 00-07" from *Jobs & Pipelines*. A failed task shows which notebook and cell broke; dependent tasks don't run.
3. **Check results:** each notebook also prints its checks and writes a `<dataset>_validation` table, for example:
   ```sql
   SELECT * FROM workspace.datathon.facilities_validation;
   SELECT * FROM workspace.datathon.silver_dq_summary ORDER BY n_facilities DESC;
   ```

> `notebooks/run_pipeline.py` runs 00 → 07 with `dbutils.notebook.run` and writes a `pipeline_run_log` table. That doesn't work on **serverless notebook compute** ("Cluster … does not exist"), so on Free Edition use the job. `run_pipeline.py` still works with the local Spark check below and on classic clusters.

You can also run any single notebook by hand, in dependency order. Each has widgets at the top (catalog, schema, input path or table).

---

## What you get: the silver tables

| Table | One row per | Highlights |
|---|---|---|
| `facilities_silver` | facility | Standardized `state`, `city`, `pincode`; parsed address (`address_full`, `address_street`, `address_region`, `address_landmark`); validated `latitude`/`longitude`; `dq_flags`; `possible_duplicate_ids`; original text kept for quoting |
| `silver_facility_claims` | facility × claimed service/equipment item | `claim_text` (verbatim, to quote as evidence) and `claim_norm` (to match on) |
| `silver_rejected_facilities` | removed record | Why it was removed (`INVALID_ID`, `NAME_MISSING`, `NO_COORDS_OR_ADDRESS`, `UNDER_MIN_FILLED_SHARE`, …) |
| `pincode_centroids_silver` | PIN code | **Turns a user's PIN into a location**: median point of its post offices, main district/state, `pin_ambiguous` |
| `nqas_silver` | certification listing | NQAS certification, dates, department scope (historical: all certificates expired 2019–2023) |
| `nfhs_silver` | state + district | NFHS-5 indicators, small-sample and estimate flags |
| `registry_sites_silver` / `registry_services_silver` | registry site / site × service | Outside evidence of what a place provides (accreditation, teaching programmes, certifications) |
| `facility_registry_links_silver` | facility ↔ registry site | `match_score`, `needs_review`, `review_reason` |

Column-by-column reference and **watch-outs for filtering** (e.g. lists are never NULL, and missing doesn't mean zero): [`docs/silver-tables.md`](docs/silver-tables.md) and [`docs/registries-silver.md`](docs/registries-silver.md).

**Naming:** tables are `<dataset>_<layer>` (e.g. `pincode_bronze`, `pincode_silver`). Silver columns never have a `_clean` suffix: being in silver means clean. Raw versions stay in bronze.

---

## How we keep the data honest

The challenge's one rule is **show your reasoning**. The pipeline is built around that:

- **Bronze is never changed.** Every raw column stays in the bronze tables, so any silver value can be traced back.
- **Problems are flagged, not hidden.** `dq_flags` record issues; flags are information, not filters. Rows are removed only by explicit rules, and removed rows are logged with the reason (`silver_rejected_facilities`, `pincode_rejected`, `nfhs_quarantine`).
- **Every silver table is checked against its bronze table before it's written:**
  - row counts reconcile;
  - every ID, name, PIN, coordinate, state and number comes from that record's bronze rows.

  Results go to `<dataset>_validation`. **If any check fails, the silver table isn't overwritten.**
- **Coordinates must match the address.** A facility's point must be near its PIN's centre and inside its state, and a post office must be within 50 km of its PIN's median. Otherwise the coordinates are set to NULL, with the reason in `coord_status`.
- **Every row can be cited.** Silver tables built from outside data carry `source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by` and a ready-to-quote `row_citation`.
- **Garbage records are removed by rule.** About 88 rows in the raw facilities file are fragments of other records: a description with line breaks spilled into new rows with shifted columns, giving "IDs" like *oculoplasty*. Rows whose ID isn't a real UUID are removed and logged.

Background on the raw data's quirks: [`docs/dataset-notes.md`](docs/dataset-notes.md).

---

## Data sources

Full citations (publisher, URL, retrieval date, licence, processing chain, limitations, "cite as") are in **[`docs/data-sources.md`](docs/data-sources.md)**. Every table added must be documented there.

| Source | What it adds | Where in the repo |
|---|---|---|
| Virtue Foundation facilities (Databricks Marketplace) | The ~10k facilities and their claimed services | `data/raw/facilities.csv` |
| India Post All India Pincode Directory | PIN → location; address checks | `data/raw/india_post_pincode_directory.csv` |
| NFHS-5 district fact sheets (IIPS/MoHFW) | District health context | `data/raw/nfhs_5_district_health_indicators.csv` |
| NQAS certified facilities (NHSRC) | Public-facility quality certification | `data/external/nqas_certified_facilities.csv` (`scripts/scrape_nqas.py`) |
| Kayakalp winners FY 2021-22 (NHSRC) | Cleanliness/infection-control awards | `data/external/kayakalp_2021_22.csv` (`scripts/kayakalp_pdf_to_csv.py`) |
| LaQshya, NABH, DNB (ANBAI), NMC, NCG, MoHFW trauma centres | Accreditation, specialty training, maternity-care certification, cancer network, trauma care | `datasets/external/*_bronze/` (`scrapers/`) |

---

## Repository layout

```
notebooks/            Databricks notebooks (source .py format), in pipeline order 00-07
  common/             shared helpers loaded with %run
  07_pin_nearby_facilities.py  builds facility_geo_ready and performs PIN-based nearby search
  setup_pipeline.py   one-time workspace setup + the Lakeflow Job
  run_pipeline.py     00->07 runner with pipeline_run_log (local Spark / classic clusters only)
data/raw/             core raw datasets (facilities, PIN directory, NFHS-5)
data/external/        CSVs produced by scripts/ (NQAS, Kayakalp) + the Kayakalp source PDF
datasets/external/    registry bronze CSVs produced by scrapers/ (LaQshya, NABH, DNB, NMC, NCG, trauma)
scrapers/             scrapers for the registry sources
scripts/              NQAS scraper, Kayakalp PDF converter, local tests and dry runs (see scripts/README.md)
  local_spark/        run every notebook on a local Spark to catch bugs before Databricks
tests/                tests for the Kayakalp extractor and transforms
docs/                 data sources, dataset notes, silver-table references, per-source notes
DEVLOG.md             every change: what, how, when, who and why
CLAUDE.md             project rules (branches, run order, validation, citations, logging)
```

---

## Verify changes locally

Before pushing a notebook change, you can run the **whole pipeline on a local Spark** (PySpark 4.0 + Delta in WSL, ANSI mode on) against the repo's CSVs. A small harness emulates the Databricks widgets, `%run`, `%sql`, `%pip` and `dbutils.notebook.run`:

```powershell
wsl -d Ubuntu -- bash "/mnt/c/<path-to-repo>/scripts/local_spark/setup_wsl.sh"     # once (~550 MB, no admin rights)
wsl -d Ubuntu -- bash "/mnt/c/<path-to-repo>/scripts/local_spark/run_all.sh"       # notebooks 00-07 in order
wsl -d Ubuntu -- bash "/mnt/c/<path-to-repo>/scripts/local_spark/run_all.sh" audit # check the outputs
```

Details and limits are in [`scripts/local_spark/README.md`](scripts/local_spark/README.md).

**Then verify on Databricks itself.** A local run can't prove a notebook works on serverless, so test changes in a separate schema before they reach `main`. With the Databricks CLI signed in (`databricks auth login --profile datathon`):
1. Upload the changed notebooks to a test folder.
2. Submit a one-time serverless run with `catalog=workspace`, `schema=datathon_verify`.
3. Wait for it with `scripts/databricks/watch_run.ps1`, which prints each task's state and error.
4. Read the validation results back with the `scripts/databricks/verify_outputs.py` notebook.

On 2026-11-21 the full pipeline (00 → 06) ran this way on serverless: every task succeeded, and every `*_validation` check passed. Step 07 must be included in the next job run. A local run can't catch serverless-only restrictions, such as `dbutils.notebook.run` and GPU environment settings. Quick checks without Spark:

```powershell
python scripts/test_address_parsing.py
```
```powershell
python scripts/test_pincode_cleaning.py
```
```powershell
python scripts/dryrun_coordinate_checks.py
```

---

## Working on this repo

- **Branches:**
  - `main` holds the verified pipeline.
  - `sophia-wip` is Sophia's working branch (and Claude's); work reaches `main` through pull requests after verification.
  - Teammates use their own branches (e.g. `Will_branch`, `elliot_branch`).
- **Log every change** at the top of [`DEVLOG.md`](DEVLOG.md) (what, how, when, who, why), in the same commit as the change.
- **Cite every new dataset** in [`docs/data-sources.md`](docs/data-sources.md) in the same commit, and give silver tables the citation columns (`add_provenance()`).
- **New silver notebooks** follow the same pattern: widgets for catalog/schema/input, `<dataset>_*` table names, a `<dataset>_validation` check before writing, no `_clean` columns, and no `.cache()` (not supported on serverless).
- **In Databricks: Pull before you Commit & Push.**

---

## Known issues

- **NQAS is historical:** every certificate in the scraped list expired between 2019 and 2023. Treat it as "was certified".
- **Notebook 03** runs in validation-only mode by default, so it doesn't persist a Kayakalp silver table unless `write_output=true`.
- **`setup_pipeline` before 2026-11-21 read `facilities.csv` with the wrong escape character,** which garbled `latitude` in about 9,700 rows. It's fixed now. If you built `workspace.datathon.facilities` with an older `setup_pipeline`, drop that table and run setup again.
- **Two files from a Databricks commit** (`Preprocessing ETL/transformations/init_transforms.py`, `describe_given_data.sql.dbquery.ipynb`) are unverified and kept on `sophia-wip` only.
- **A missing file:** `docs/kayakalp-validation-handoff.md` links to `docs/kayakalp-silver-audit.md`, which isn't in the repo.
- **Some citations are incomplete:** `docs/data-sources.md` still has ⚠ TODOs for the exact source and date of the PIN-directory and NFHS-5 files.

---

**Team:** Sophia, Alice, Elliot and William. Built for the CMU Datathon, Fall 2026.
