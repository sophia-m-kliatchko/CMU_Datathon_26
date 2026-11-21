# Development Log: CMU Datathon Fall 2026

A running record of every change made to this project: **what** changed, **how**, **when**, and **why**.
The newest entries go at the top. Times are US Eastern (UTC-05:00).

## How to add an entry

Copy this template and add it above the newest entry:

```markdown
### YYYY-MM-DD HH:MM: <short title>
- **Who:** <name, or "Claude (for <name>)">
- **What:** <what changed: files, tables, notebooks, settings>
- **How:** <commands run, tools used, approach taken>
- **Why:** <the reason or decision behind it>
- **Notes / follow-ups:** <open questions, known issues, next steps> (optional)
```

Log anything that changes the project: code and notebooks, Databricks tables and jobs, data-cleaning rules, scoring weights, environment setup, and decisions you made and why. If you made a tradeoff (for example, "we dropped records with no coordinates"), write it down. The challenge requires us to explain HOW we decided, and this log is where that comes from.

---

## Entries

### 2026-11-21 16:43: No script creates `*_clean` columns anymore, and a guard enforces it
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py`, `notebooks/04_pincode_bronze_to_silver.py`, `notebooks/common/reference_data.py`.
  - `notebooks/india_pincode_bronze_to_silver.py` (elliotl-ops's script: minimal rename plus a header note).
  - `CLAUDE.md`.
- **How:**
  - **Notebook 01:** cleaned columns are built under plain names from the start (`city`, `state`, `pincode`, `latitude`, `longitude`, `year_established`, `num_doctors`, `capacity`). Raw source columns with those names (raw `latitude`, `longitude`, `capacity`) are renamed `src_<name>` by the existing collision step and left out of silver. The end-of-pipeline rename block is removed. This means the temporary `_facilities_silver_stage` table no longer has `*_clean` columns either.
  - **Notebook 04:** raw `latitude`, `longitude` and `district` are renamed `*_raw` right after the duplicate collapse, and the cleaned values use the plain names throughout. The end rename block is removed.
  - **elliotl-ops's script:** `latitude_clean`/`longitude_clean`/`office_name_clean` → `latitude`/`longitude`/`office_name` (its raw values were already `*_raw`).
  - **Guard:** `assert_no_clean_columns()` runs before every silver write: inside `write_table()` (used by 02, 03, 04), inline before notebook 01's six writes, and before 04's direct writes. A write fails if any column ends in `_clean`.
- **Why:** Sophia asked that no script ever produce `*_clean` columns in silver tables. The previous change only renamed them at the end, and notebook 01's staging table still had them. The guard makes the rule hold for future edits too.
- **Notes / follow-ups:**
  - Local unit tests pass; all notebooks compile. Not yet run on Databricks.
  - elliotl-ops should know their script's output column names changed.

### 2026-11-21 16:27: No `_clean` suffix on silver column names
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01`–`04` and the docs.
  - **`facilities_silver`:** `city_clean`→`city`, `state_clean`→`state`, `pincode_clean`→`pincode`, `latitude_clean`→`latitude`, `longitude_clean`→`longitude`, `year_established_clean`→`year_established`, `num_doctors_clean`→`num_doctors`, `capacity_clean`→`capacity`.
    - The raw `latitude`, `longitude`, `coordinates`, `yearEstablished`, `numberDoctors` and `capacity` columns are now left out of silver; bronze keeps them.
    - `silver_possible_duplicates`: `pincode_clean_a/b`→`pincode_a/b` (latitude/longitude likewise).
  - **`nqas_silver`, `kayakalp_silver`:** `state_clean`→`state`, `district_clean`→`district` (raw stays in `state_raw`/`district_raw`).
  - **`pincode_silver`:** `latitude`, `longitude`, `state`, `district`, `office_name`; the raw district column is renamed `district_raw`.
  - `CLAUDE.md`: naming rule added.
- **How:**
  - **Notebooks 01 and 04:** the code keeps the `_clean` names internally and renames only at the final select, with an assertion that no names collide. This is because their raw columns use the same plain names.
  - **Notebooks 02 and 03:** a word-boundary rename, since raw values there are already `*_raw`.
  - Downstream code, comments and SQL checks were updated to the new names.
- **Why:** Sophia: being in a silver table already implies a column is clean. Raw columns that would clash with the plain names are dropped from `facilities_silver`, consistent with the earlier address decision ("if it is not standard, drop it"). In the outside-data tables, raw text is kept as `*_raw` because their `row_citation` and source checks rely on it.
- **Notes / follow-ups:**
  - Earlier `facilities_silver` drafts kept the raw `coordinates`/`latitude`/`longitude`. The validated coordinates now carry those names instead; the raw ones are in bronze.
  - **Anything already querying `*_clean` columns must be updated.** Not yet run on Databricks.

### 2026-11-21 16:23: Raw address columns always dropped from silver; non-standard values left NULL
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py` (section 7 and header) and `docs/silver-tables.md`.
  - Replaces the "drop only when fully covered" rule from 16:18.
- **How:** `address_line1/2/3`, `address_city`, `address_stateOrRegion` and `address_zipOrPostcode` are always left out of `facilities_silver`. Where a value can't be standardized, `city_clean` / `state_clean` / `pincode_clean` stay NULL, and the notebook prints how many per column. The existing flags `STATE_UNRECOGNIZED` and `PINCODE_MISSING_OR_INVALID` still mark those rows.
- **Why:** Sophia's decision: a non-standard value (e.g. "Mumbai" in the state field, or "56" as a PIN) should not be kept in silver, either as a raw column or copied into a cleaned column. A briefly considered "copy the raw value into the cleaned column" approach was dropped before being committed. The originals remain in `facilities_bronze`.
- **Notes / follow-ups:** about 300 rows will have `state_clean` NULL unless the PIN fallback fills it, and about 70 will have `pincode_clean` NULL (local estimate). Not yet run on Databricks.

### 2026-11-21 16:18: Raw address columns dropped from silver only when fully covered by a cleaned column
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py` (section 7 and header).
  - `docs/silver-tables.md` (dropped-columns section and watch-out 22).
  - Replaces the unconditional drop of `address_line1/2/3` logged earlier at 16:17.
- **How:**
  - Pairs: `address_line1/2/3` → `address_full`, `address_city` → `city_clean`, `address_stateOrRegion` → `state_clean`, `address_zipOrPostcode` → `pincode_clean`.
  - For each pair, one aggregate counts rows that have a raw value but no cleaned value. A raw column is dropped only if that count is 0; otherwise it's kept, and the notebook prints the count.
- **Why:** Sophia asked to remove `address_city`, `address_stateOrRegion` and `address_zipOrPostcode` too, then specified "ONLY if there's a cleaned equivalent". Checking per value (not just whether a clean column exists) means silver never loses an address value. For example, "Mumbai" typed into the state field has no `state_clean`, so that column stays.
- **Local estimate** (approximate; the notebook decides at run time): `address_city` drops (0 uncovered). `address_stateOrRegion` likely stays (~297 uncovered before the PIN fallback). `address_zipOrPostcode` likely stays (~72 uncovered).
- **Notes / follow-ups:** if Sophia prefers dropping a column even when a few values have no cleaned equivalent, the rule could become a threshold. Not yet run on Databricks.

### 2026-11-21 16:17: `address_line1/2/3` removed from `facilities_silver`
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py`: the final select leaves out the three address-line columns, the header text is updated, and the address spot-check SQL now joins to `facilities_bronze` for the original lines.
  - `docs/silver-tables.md`: dropped-columns list and watch-out 22.
- **How:** a `REPLACED_BY_PARSED` list removes them only in the last step, because the lines are still needed earlier, for address parsing and for the `NO_COORDS_OR_ADDRESS` rule.
- **Why:** Sophia: once `address_full` and the split `address_street` / `address_region` / `address_landmark` exist, the raw lines are redundant in silver. They remain in `facilities_bronze` for exact quoting.
- **Notes / follow-ups:** `address_city`, `address_stateOrRegion` and `address_zipOrPostcode` are still in silver next to `city_clean`, `state_clean` and `pincode_clean`; they could be removed the same way if wanted. Notebook 01 is still unverified on Databricks; the last run there appears to have stopped before section 5.

### 2026-11-21 16:03: PIN directory notebook producing `pincode_*` tables
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/04_pincode_bronze_to_silver.py`, which writes:
    - `pincode_bronze`: raw copy.
    - `pincode_silver`: one row per post office.
    - `pincode_centroids_silver`: one row per PIN.
    - `pincode_rejected` and `pincode_dq_summary`.
  - New `notebooks/common/coordinate_parsing.py` (plain Python plus a Spark UDF) and `scripts/test_pincode_cleaning.py` (12 unit tests plus a dry run on the real CSV).
  - `docs/data-sources.md` and `CLAUDE.md` (layout and the `<dataset>_<layer>` naming rule) updated.
- **How:** profiled `data/raw/india_post_pincode_directory.csv`: 165,627 offices, 19,586 PINs, about 7% "NA" coordinates, a few junk values ("28.43° N", "17°57'17.7", "28.4 32628"), swapped pairs, 2 exact duplicate rows, 0 invalid PINs.
  - Coordinates: plain numbers are used as-is; degree signs and N/E letters are removed; degrees-minutes-seconds are converted; spaces inside decimals are removed; values are checked against India's bounding box, and swapped pairs are fixed. The method is recorded in `lat_how`/`lon_how`.
  - Each PIN's centroid is the median of its offices' locations, leaving out offices more than 50 km from the PIN's median.
  - The source can be a CSV path (Volume) or a table.
- **Why:** Sophia asked for a PIN-directory pipeline like 02/03, named `pincode_*`. The centroid table is what turns a user's PIN into coordinates for distance ranking.
  - **Builds on elliotl-ops's `notebooks/india_pincode_bronze_to_silver.py`:** its "NA" handling, junk-latitude findings, PIN ambiguity, office-name suffix cleaning and deterministic `office_id` were kept; that file was left untouched.
  - **Differences from it:**
    - Swapped lat/lon pairs and recoverable junk are repaired rather than set to NULL, and every repair is flagged.
    - `.cache()` is avoided, because Free Edition's serverless compute doesn't support it.
    - The "quality gate" that refuses to write is replaced by a flags table.
    - Per-row citations are added.
- **Dry-run results:**
  - 91.2% of offices are usable as given and 0.5% after a swap fix; 7.3% have no coordinates; 1.1% are outside India.
  - 99.9% of PINs get a centroid; the median PIN spread is 10.5 km.
  - **12,102 offices (7%) sit more than 50 km from their PIN's median point.** These are probably wrong coordinates in the source; they're flagged `COORDS_FAR_FROM_PIN`.
- **Notes / follow-ups:**
  - **Not yet run on Databricks.**
  - Upload the CSV to `/Volumes/workspace/datathon/external/` first, or point the `source` widget at a table.
  - The team should decide whether to keep both PIN notebooks or retire the older one.

### 2026-11-21 15:47: Corrected DEVLOG timestamps
- **Who:** Claude (for Sophia)
- **What:** the times in the headings of the entries from 12:28 to 15:45 in this file.
- **How:** compared each entry with its git commit time (`git log --date=format-local:%H:%M`) and used the commit time. Entries without their own commit use the nearest commit, marked `~`.
- **Why:** Claude had estimated times instead of reading the clock, so several entries were stamped later than the actual current time (e.g. "18:05" at 15:45). From now on each entry uses `Get-Date`, as `CLAUDE.md` requires.

### 2026-11-21 15:45: Renamed tables: `bronze_facilities` → `facilities_bronze`, `silver_facilities` → `facilities_silver`
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py`: table writes, reads, comments and SQL checks. The internal staging table is now `_facilities_silver_stage`.
  - Text references in `notebooks/02_*` and `03_*`, `docs/silver-tables.md` and `docs/data-sources.md`.
- **How:** word-boundary `sed` replacement; older DEVLOG entries are left as written, since they record history.
- **Why:** Sophia's naming convention puts the dataset first and the layer second, matching `nqas_bronze`/`nqas_silver` and `kayakalp_bronze`/`kayakalp_silver`.
- **Notes / follow-ups:**
  - Anyone who already ran notebook 01 will still have the old `bronze_facilities` / `silver_facilities` tables in their workspace. Drop them by hand (`DROP TABLE IF EXISTS workspace.datathon.bronze_facilities`, and the same for `silver_facilities`).
  - The other outputs of notebook 01 keep their names: `silver_facility_claims`, `silver_possible_duplicates`, `silver_dq_summary`, `silver_rejected_facilities`.

### 2026-11-21 15:44: Decision: `source_urls` stays out of silver
- **Who:** Sophia (decision), Claude (logged it)
- **What:** no code change. `source_urls` remains dropped from `silver_facilities`, as implemented in `notebooks/01_bronze_to_silver.py`.
- **How:** Sophia answered "Drop it as asked" when asked whether to keep it for evidence citations.
- **Why:** to keep silver to the agreed column set. The URLs are not lost: they remain in `bronze_facilities` and can be joined back on `unique_id` (documented in `docs/silver-tables.md`, watch-out 24) if a recommendation needs to show the web pages a record came from.

### 2026-11-21 15:43: Merged `main` into `sophia-wip`; citations updated for the teammate additions
- **Who:** Claude (for Sophia)
- **What:**
  - Merge commit bringing `main` into `sophia-wip`. This adds `data/KAYAKALP WINNER FACILITIES 21-22.pdf` (from Sophia) and `notebooks/india_pincode_bronze_to_silver.py` (from elliotl-ops).
  - `docs/data-sources.md`: the Kayakalp PDF copy is now in the repo; the PIN directory's processing chain points at the new notebook and its `india_post_offices_silver` table.
- **How:** `git merge origin/main` (no conflicts; the branches had diverged, so it couldn't fast-forward), then edited the citations doc.
- **Why:** to keep `sophia-wip` current with the team, and to follow the citation rule for tables other people add.
- **Notes / follow-ups:** the PIN notebook is a standalone PySpark script with placeholder paths (`path/to/bronze/...`, `catalog.schema...`). elliotl-ops should set the real paths and confirm the source date.

### 2026-11-21 15:42: Silver facilities: row-removal rules, column drops, standardized addresses
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py`: new rule settings in section 0, `%run ./common/address_parsing`, column drop, UUID check, a coordinates fallback, address parsing, the row rules, a new table `silver_rejected_facilities`, flags, column comments, and 2 SQL check cells.
  - New `notebooks/common/address_parsing.py` (plain-Python parser plus Spark UDF).
  - New `scripts/test_address_parsing.py` (5 unit tests, plus a dry run of the rules on `data/raw/facilities.csv`).
  - `docs/silver-tables.md` updated.
- **How:**
  - Profiled the real `data/raw/facilities.csv` first. It escapes quotes with backslashes (`\"`); with the right parser it gives 10,088 rows × 51 columns.
  - Rules, in order:
    1. `unique_id` must match the UUID pattern (`INVALID_ID`, checked before merging).
    2. Name must not be missing (`NAME_MISSING`) or list-shaped (`NAME_IS_LIST`).
    3. A facility must have usable coordinates or at least one address field (`NO_COORDS_OR_ADDRESS`).
    4. `source_fill_share` must be ≥ 0.30 over the 25 kept source columns (`UNDER_MIN_FILLED_SHARE`).

    Rules 2–4 run on the merged record. Removed rows go to `silver_rejected_facilities` with the reason.
  - **Dropped columns:** the 14 named columns, plus everything after `recency_of_page_update` except `coordinates`, `latitude` and `longitude`. They are dropped from silver only; bronze is unchanged.
  - **The `coordinates` GeoJSON** is now a fallback when latitude/longitude are empty.
  - **Addresses:** line1–3 are split on commas, and each piece is classified as landmark (near/opp/behind…), street (road/lane/marg/NH-x, a house number, or a building/floor), or region (nagar/colony/sector/layout…). Pieces that repeat the city, state, PIN or an earlier piece are dropped. A valid PIN found inside the text replaces an invalid PIN field.
- **Why:** Sophia's rules. Garbage IDs like "oculoplasty" turned out to be fragments of *other* records: where a description had line breaks, the rest of the row spilled into new rows with shifted columns (88 rows). Dry run on the CSV:
  - **Rows:** 88 removed (all `INVALID_ID`, including all 54 blank-name and 9 list-name rows), 0 by the other rules, 10,000 kept.
  - **Address coverage:** street filled for 93% of facilities, region 78%, landmark 50%; 13 PINs recovered from address text.
  - **Tradeoffs:**
    - Removed rows are logged, not silently deleted.
    - Bronze keeps every column, so dropping `source_urls` (useful for citations) is reversible by joining to bronze on `unique_id`.
    - "Region" was read as the locality/neighbourhood; the state is in `state_clean`. A separate `address_landmark` column keeps the directions rather than discarding them.
- **Notes / follow-ups:**
  - **Not yet run on Databricks;** the numbers above are from the local CSV. The Marketplace table may differ.
  - The real record that each fragment belongs to may be missing its tail fields (it was cut at the line break). Stitching fragments back is possible but not done.
  - ~~Consider keeping `source_urls` in silver~~: decided 2026-11-21 15:44, see the entry above.

### 2026-11-21 15:18: Added the Kayakalp PDF source URL to the citations
- **Who:** Claude (for Sophia)
- **What:** `docs/data-sources.md` (Kayakalp entry: landing page, PDF URL, checksum, "cite as"); `notebooks/03_kayakalp_bronze_to_silver.py` (`source_url` widget default, publisher now NHSRC, `row_citation` now ends with the URL and retrieval date); `scripts/README.md` (link to the PDF).
- **How:** Sophia gave the NHSRC page https://qps.nhsrcindia.org/kayakalp-swachh-swasth-sarvatra/quality-LOKWF. Its HTML links the PDF at `/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf`. I downloaded that file to a scratch folder and compared SHA-256 checksums with Sophia's copy: they are identical (`6af952e2…7680`, 788,186 bytes).
- **Why:** this closes the Kayakalp TODO from the citation rule. The checksum proves our CSV came from the official published file. The publisher was changed to NHSRC because NHSRC hosts and lists the file.
- **Notes / follow-ups:** the PIN and NFHS-5 sources still need confirming by JhK830.

### 2026-11-21 15:15: NQAS and Kayakalp bronze → silver notebooks; data-citation rule and `docs/data-sources.md`
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/02_nqas_bronze_to_silver.py` (`nqas_bronze` → `nqas_silver`) and `notebooks/03_kayakalp_bronze_to_silver.py` (`kayakalp_bronze` → `kayakalp_silver`).
  - New shared helper `notebooks/common/reference_data.py`: states, name cleaning, facility-type patterns, provenance.
  - New `docs/data-sources.md`: citations for every table.
  - `CLAUDE.md`: new "Data citations (required)" rule and updated layout.
  - `scripts/README.md`: bronze upload steps.
  - Re-ran `scripts/scrape_nqas.py`: 989 rows, identical to the committed CSV.
- **How:** PySpark + SQL Databricks notebooks that load the shared helper with `%run ./common/reference_data`. Local Python syntax check only. The facility-type patterns were tested in plain Python on the real CSV names, which led to adding FHC (Kerala Family Health Centre), GH (General Hospital) and taluk hospital patterns.
- **Why:** Sophia asked for bronze → silver scripts for both outside tables, and for every scraped or assembled table to have citations in GitHub. Design decisions:
  - **Grain:** `nqas_silver` has one row per certification listing; `kayakalp_silver` has one row per award. A facility can have several of each, so they are not collapsed to one row per facility.
  - **Citations:** every row carries citation columns, including a ready-to-quote `row_citation`. For Kayakalp this gives the PDF page and S.No, which meets the challenge rule to cite the underlying text.
  - **NQAS status:** `certification_status` is computed from the run date. All listings are expired, so `CERTIFICATION_EXPIRED` is expected on every row.
  - **Kayakalp district field:** the last comma-separated part becomes `district_clean` and the rest `locality`, because some states wrote "village, block, district".
  - **Duplicates:** exact duplicate NQAS listings are collapsed, with the count kept in `n_listings`. Possible duplicate Kayakalp awards are only flagged.
  - **Matching:** `name_norm` / `name_core` follow the normalization in notebook 01. `name_core` drops facility-type words so "PHC Majri" can match "Majri Primary Health Centre".
- **Notes / follow-ups:**
  - **Not yet run on Databricks.**
  - The Kayakalp PDF's download URL is unknown. Sophia to supply it for `docs/data-sources.md` and notebook 03's `source_url` widget.
  - JhK830 to confirm the source and date of the PIN and NFHS-5 files in `data/raw/`.
  - Notebook 01 still has its own copy of the state lookup; consider switching it to `common/reference_data`.

### 2026-11-21 14:26: Added the NQAS certified-facilities CSV; synced sophia-wip with main; installed the GitHub CLI
- **Who:** Claude (for Sophia)
- **What:**
  - New `data/external/nqas_certified_facilities.csv` (989 rows: 796 full certification, 193 partial).
  - `sophia-wip` fast-forwarded to `main` (commit `0c56abd`). This brings in the teammate-added `data/raw/` files: `facilities.csv`, the India Post PIN directory and NFHS-5.
  - GitHub CLI 2.105.0 installed via winget and signed in as `sophia-m-kliatchko`.
  - The temporary `docs/pr-drafts/` folder was removed (its text is in PR #2).
- **How:** ran `python scripts/scrape_nqas.py` (460 requests at a 0.5 s delay), then `git merge --ff-only origin/main` and `git push`.
- **Why:** to finish the NQAS download, and keep `sophia-wip` level with `main` so the next PR is clean. PR #2 (NQAS scraper and Kayakalp converter) had already been opened by Sophia in the browser and merged, so no duplicate PR was created.
- **Notes / follow-ups:**
  - **NQAS completeness:** the site reports 994 rows; we got 989 unique. A plain page walk got only 872 unique rows, so splitting queries by state and district recovered 117. The last 5 are probably true duplicate listings on the site, but this isn't proven.
  - **The list is historical:** certificate expiry dates run 2019–2023, so none are current. Use it only as a "was ever certified" signal, and look for a current NQAS source (the NHSRC dashboard reports about 21k certified facilities).
  - `.DS_Store` files (macOS clutter) arrived from `main`. Consider removing them and adding them to `.gitignore`.
  - Now that the real `data/raw/facilities.csv` is in the repo, check the silver notebook against its actual columns.

### 2026-11-21 14:13: Scripts to turn outside quality datasets into CSVs (NQAS website, Kayakalp PDF)
- **Who:** Claude (for Sophia)
- **What:**
  - New `scripts/scrape_nqas.py`, `scripts/kayakalp_pdf_to_csv.py` and `scripts/README.md` (includes how to upload to Databricks).
  - New `data/external/kayakalp_2021_22.csv` (1,197 rows).
  - `CLAUDE.md` layout updated.
- **How:**
  - **NQAS:** standard-library Python scraper for qps.nhsrcindia.org (10 rows per page; "full" and "partial" certification lists), with a 0.5 s delay between requests.
  - **Kayakalp:** `pdfplumber` table extraction from Sophia's downloaded PDF. pdfplumber was installed with pip; the PDF is locked against editing but readable.
- **Why:** Sophia wants these quality signals (government quality certification, Kayakalp cleanliness and infection-control awards) as CSVs to upload to Databricks and match against our facilities. Findings and decisions:
  - **The NQAS site's paging is unstable.** A simple page-by-page walk gave 994 rows with 122 repeats, meaning other rows were silently skipped. The script now splits queries by state, then district, until each query's unique rows match the count the site reports.
  - **The NQAS list looks like an old snapshot.** In the first pass every certificate expired between 2019 and 2023, and the list has about 1k rows versus about 21k certified facilities on the NHSRC dashboard. Treat it as historical, and look for a current source.
  - **Kayakalp:** in 17 rows, long district names spilled into the State column, garbling it (e.g. "aGrUJARAT"). Because the state's letters stay in order, the script recovers the state and moves the leftover letters back to the district. Those rows are flagged `district_repaired`.
  - **Award rank and category** (Kayakalp vs Eco-friendly) are parsed into separate columns; the raw text is kept.
- **Notes / follow-ups:**
  - The full NQAS scrape was still running at commit time, so its CSV will follow in a later commit.
  - The PDF itself is not committed; only the CSV is.
  - Kayakalp covers public facilities only (PHC, HWC, UPHC, CHC, DH). Matching to Virtue Foundation facilities is still to do.

### 2026-11-21 13:24: Listed outside datasets for checking care quality, with links
- **Who:** Claude (for Sophia)
- **What:** Added the section "Outside datasets for checking care quality and reliability" to `docs/dataset-notes.md`, with about 25 sources in four groups (priority 1, specific services, existence and location, context) and links.
- **How:** Web searches on 2026-11-21 for each source's official portal or data.gov.in / AIKosh page. Portals were mostly not opened, so availability and formats still need checking.
- **Why:** Sophia asked for free datasets to judge the quality and reliability of care at each facility, so the team can corroborate claims instead of trusting the Virtue Foundation fields. Decision recorded: **a match is evidence for a facility; no match is not evidence against it**, because most of these lists only cover public hospitals or members of one scheme.
- **Notes / follow-ups:**
  - Team to choose which sources to bring in.
  - The top candidates are PM-JAY (specialty approvals), NABH, PMNDP dialysis centres, LaQshya, and the blood bank directory.
  - No links found yet for SNCU, trauma centres, NOTTO or Kayakalp.
  - PM-JAY, NABH and HFR appear to be search-only portals, so they'd need scraping. Check each site's terms of use first.

### 2026-11-21 12:45: Added the bronze → silver ETL notebook and silver-table docs
- **Who:** Claude (for Sophia)
- **What:** New `notebooks/01_bronze_to_silver.py` (Databricks notebook, Python + PySpark + SQL) and `docs/silver-tables.md`. Made on the `sophia-wip` branch.
- **How:** The notebook writes 5 Delta tables to `workspace.datathon` (settable with widgets):
  - `bronze_facilities`: raw copy of the source with NUL and other control characters removed.
  - `silver_facilities`: one row per `facility_id`, cleaned, with `*_clean` columns and `dq_flags`.
  - `silver_facility_claims`: one row per claimed service or equipment item.
  - `silver_possible_duplicates`
  - `silver_dq_summary`

  Steps:
  1. Copy the source to bronze.
  2. Profile how filled-in each column is.
  3. Auto-detect which column is which (with manual overrides).
  4. Clean each row: trim text, set "null"-like values to NULL, parse lists, and add new clean columns for PIN, state, city, coordinates, year, doctors and beds.
  5. Merge rows that share a `unique_id`.
  6. Search for near-duplicates.
  7. Add flags and write the tables.
  8. Run SQL checks.
- **Why:** Sophia asked for a pipeline that brings all the data to silver standard, based on the known data problems (see `docs/dataset-notes.md`). Key decisions and tradeoffs:
  - **The original text is kept unchanged** next to the new `*_clean` columns, because the challenge requires quoting the facility's own text.
  - **Duplicate IDs are merged, not dropped.** The previous team found that dropping rows can lose the correct coordinates. Lists are combined; single values come from the most complete row. Latitude and longitude always come from the same row.
  - **Near-duplicates and quality problems are flagged, never deleted.** Deleting would hide uncertainty, and the challenge asks us to communicate it.
  - **Missing lists become empty arrays (never NULL)**, so code can always use `size()`.
  - **Year must be between 1800 and this year.** Pre-1947 years are kept, because many Indian hospitals predate independence. Doctors and beds must be between 1 and 10,000; 0 is treated as unknown.
  - **Coordinates:** India bounding box lat 6–37.5, lon 68–97.5. Swapped values are fixed.
  - **State:** a 36-state/UT list plus common aliases. Filled from the PIN prefix only when the reported state is missing and the prefix maps to exactly one state.
  - **Near-duplicate rules:** same PIN code or ~1 km grid square, names ≥85% similar or one containing the other, within 2 km. Grid squares with more than 500 facilities are skipped as likely city-centre placeholders.
- **Notes / follow-ups:**
  - **Not yet run on Databricks.** Only a local Python syntax check was done, because there's no Spark here. The first run needs checking: the column mapping printout, the profile, and `silver_dq_summary`.
  - The default source table name may differ from what Sophia named the catalog. Set it in the `source_table` widget, then update the default.
  - The thresholds above are first guesses; tune them once real counts are visible.
  - Possible later improvements: PIN-centroid coordinates from the India Post directory, and point-in-polygon state checks using district boundaries.

### 2026-11-21 12:45: Started using the `sophia-wip` branch
- **Who:** Sophia (created the branch), Claude (switched to it)
- **What:** Sophia created `sophia-wip` on GitHub. The local repo now tracks `origin/sophia-wip`, and `CLAUDE.md` records that Claude's work goes there.
- **How:** `git fetch origin` then `git switch sophia-wip`.
- **Why:** Sophia wants `sophia-wip` to be the main place Claude's work goes, keeping `main` clean for the team.

### 2026-11-21 12:30: First commit and push to GitHub
- **Who:** Claude (for Sophia)
- **What:** Committed `DEVLOG.md`, `CLAUDE.md` and `docs/dataset-notes.md`, then pushed them to `origin/main`. This creates the `main` branch on GitHub.
- **How:** `git add`, `git commit`, then `git push -u origin main`.
- **Why:** So all collaborators can see the log, the logging rule and the dataset notes, and build on them.
- **Notes / follow-ups:** Claude's push failed because Git wasn't signed in to GitHub yet. Sophia then ran `git push -u origin main` in their own terminal and signed in through the browser using Git Credential Manager. The push worked, and the login is now saved on this machine.

### 2026-11-21 ~12:29: Set Git identity on Sophia's machine
- **Who:** Sophia
- **What:** Set the global Git `user.name` (`sophia-m-kliatchko`) and `user.email`.
- **How:** `git config --global user.name ...` and `git config --global user.email ...`
- **Why:** Git needs an author identity before it will make commits.

### 2026-11-21 ~12:28: Added dataset notes from a previous team's write-up
- **Who:** Claude (for Sophia)
- **What:** Created `docs/dataset-notes.md`.
- **How:** Read the previous DAIS 2026 hackathon team's dataset overview and their data-quality issue log on GitHub (petertadrous/2026-dbx-hackathon). Summarized the table location, key columns, known data problems and optional extra datasets in my own words. Compared their coverage numbers with our challenge brief.
- **Why:** So all four of us start out knowing the data's problems: duplicate `unique_id`s, NUL bytes, bad coordinates, PIN codes that map to several places, and implausible years. These directly affect our cleaning and trust scoring.
- **Notes / follow-ups:**
  - Check the table name in our own Marketplace listing.
  - Run `DESCRIBE TABLE`: the brief says 51 columns, but only 12 are documented.
  - The coverage numbers disagree (99.7% vs 92.5% and 77% for procedure and equipment). Check for empty arrays.

### 2026-11-21 12:27: Created this development log
- **Who:** Claude (for Sophia)
- **What:** Added `DEVLOG.md` (this file) and `CLAUDE.md` at the repo root.
- **How:** Wrote both files by hand. `CLAUDE.md` tells Claude Code (for any team member who uses it) to add an entry here after each change.
- **Why:** Sophia asked for a detailed log of what changes, how, when, and why. That keeps four collaborators in sync and gives us the material to answer the challenge's "HOW did you decide?" question.
- **Notes / follow-ups:** Nothing committed yet. Git's user name and email still need to be set (see the entry below).

### 2026-11-21 ~12:20: Connected the local folder to the GitHub repo
- **Who:** Claude (for Sophia)
- **What:** The local folder `C:\Users\sophi\OneDrive\Bookmarks\Datathon Project Code` is now a clone of `https://github.com/sophia-m-kliatchko/CMU_Datathon_26`, with the remote `origin` and the branch `main`.
- **How:** `git clone https://github.com/sophia-m-kliatchko/CMU_Datathon_26 .` run inside the empty project folder.
- **Why:** To put the project under version control, linked to the shared team repo.
- **Notes / follow-ups:**
  - The GitHub repo was empty when cloned, so `main` has no commits yet. The first push will create it.
  - Git's user name and email are not set on this machine yet. Run `git config --global user.name "..."` and `git config --global user.email "..."` before the first commit.
  - Git was not on the PATH of the session that installed it, so new terminals may be needed before `git` is recognized.

### 2026-11-21 ~12:15: Installed Git on Sophia's machine
- **Who:** Claude (for Sophia)
- **What:** Installed Git for Windows 2.56.1 (64-bit) at `C:\Program Files\Git`.
- **How:** `winget install --id Git.Git -e --source winget --silent`. The installer hash was verified by winget.
- **Why:** Git was not installed, and it's needed to connect the project folder to GitHub.
- **Notes / follow-ups:** None.

### 2026-11-21: Project context (challenge brief)
- **Who:** Sophia
- **What:** The team is taking on the CMU Datathon Fall 2026 challenge "Find the right care". Given a **service** (for example dialysis, NICU, emergency C-section) and a **location** (city, district, PIN code, or coordinates), return the best facilities, with an evidence-based explanation for each.
- **Constraints:** Must run on Databricks Free Edition, use the Virtue Foundation dataset of about 10,000 Indian facilities with 51 attributes each, support a non-technical user workflow, cite the facility text behind every claim or score, and communicate uncertainty.
- **Team:** Sophia (the most experienced with Databricks) plus 3 collaborators.
- **Why logged:** To keep the goal and the rules in one place for everyone.
