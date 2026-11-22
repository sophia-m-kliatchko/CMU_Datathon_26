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

### 2026-11-21 20:47: PR #10 merged: `main` now has the verified pipeline
- **Who:** Sophia (approved the merge), Claude (merged)
- **What:**
  - PR #10 (`verified-pipeline` → `main`) merged as merge commit `4ba4065`, then brought into `sophia-wip`.
  - Remote branch `verified-pipeline` deleted.
- **How:** `gh pr merge 10 --merge --match-head-commit 4a789a5` (merged only if the head was still the verified commit), then `git merge origin/main` on `sophia-wip`.
- **Why:** Sophia approved merging after the local end-to-end verification (20:44 entry).
- **Notes / follow-ups:**
  - **`main` and `sophia-wip` now differ only by the two unverified Databricks files** (`Preprocessing ETL/transformations/init_transforms.py`, `describe_given_data.sql.dbquery.ipynb`), plus this DEVLOG entry until the next sync.
  - **Next:** Pull `main` (or `sophia-wip`) in the Databricks Git folder, then run 00 → 01 → 02 → 03 → 05 → 06 once on Databricks to catch anything serverless-specific.

### 2026-11-21 20:45: Removed Elliot's superseded NFHS script from `sophia-wip`; verified files proposed for `main`
- **Who:** Claude (for Sophia)
- **What:**
  - Deleted `notebooks/nfhs_district_silver.py` on `sophia-wip`. Elliot had deleted it on `main` (`3ca16f7`) and replaced it with `notebooks/NFHS_Bronze_to_Silver.py`; it survived on `sophia-wip` only through a merge.
  - New branch `verified-pipeline` (from `main`) and a PR into `main`.
- **How:** in a separate worktree, `verified-pipeline` was cut from `origin/main`, then every file was taken from `sophia-wip` except three:
  - `Preprocessing ETL/transformations/init_transforms.py` and `describe_given_data.sql.dbquery.ipynb`: from the Databricks commit `e7f701b`, never run locally, so they stay on `sophia-wip` only.
  - `notebooks/nfhs_district_silver.py`: deleted by Elliot.
- **Why:** Sophia asked that `main` and `sophia-wip` be consistent, with less-sure changes only on `sophia-wip`. Everything in the PR was run end to end on local Spark (see the 20:44 entry).
- **Notes / follow-ups:** merging the PR is Sophia's call. After it merges, `main` = `sophia-wip` minus the two unverified Databricks files.

### 2026-11-21 20:44: Verified the whole pipeline by running it on a local Spark; merged Elliot's NFHS notebook into `sophia-wip`
- **Who:** Claude (for Sophia)
- **What:**
  - New `scripts/local_spark/`: `nbrun.py` (runs Databricks source notebooks locally), `run_all.sh`, `setup_wsl.sh`, `audit.py`, `audit_links.py`, `summary.sh`, `README.md`.
  - `CLAUDE.md`: full run order and the local verification step.
  - Merge of `main` (PR #9, `notebooks/NFHS_Bronze_to_Silver.py`) into `sophia-wip`.
  - A draft `notebooks/04_nfhs_bronze_to_silver.py` was written and then deleted unused: Sophia said Elliot owns the NFHS notebook.
- **How:**
  - **Environment:** WSL Ubuntu, Java 17, Python 3.12, PySpark 4.0.1 + Delta 4.0, ANSI mode on, local Hive metastore so tables persist between notebooks. Each notebook ran in order against the repo CSVs; Databricks widgets, `%run`, `%sql`, `%pip` and `display` were emulated.
  - **Audit:** a separate pass checked the outputs: key uniqueness, NULLs, coordinates inside India, staging leftovers, `_clean` columns, orphan rows and link quality.
- **Results** (`sophia-wip` versions):
  - **00 pincode OK, 12/12 checks pass.** 165,627 → 165,625 offices; 19,586 PINs. Coordinates nulled as far from their PIN: 12,070, separate from 12,009 missing, confirming the 20,015 km fix.
  - **01 facilities OK, 13/13 pass.** 10,088 → 88 invalid IDs → 9,989 facilities. 1,598 coordinates nulled for PIN mismatch, 5 for state; 8,350 keep coordinates. 53 near-duplicate pairs.
  - **02 NQAS OK, 8/8 pass.** **03 Kayakalp OK.** **05 registries OK** (24,961 sites).
  - **06 matching OK.** 4,241 links: all 3,087 accepted links are within 25 km; the wrong-looking pairs are all `needs_review`.
  - **Audit:** all keys unique and non-NULL, no coordinates outside India, no half-missing coordinate pairs, no orphan claims, no leftover staging tables, no `_clean` columns.
- **Findings for teammates:**
  - **`NFHS_Bronze_to_Silver.py` (Elliot) fails on the repo's NFHS file.**
    - Its quality gate reports 706/706 rows unparseable and 100% NULL indicators: counts are written like `882.0`, which its whole-number pattern rejects.
    - It reads a file in Elliot's personal workspace and writes to `labuser_elliotl.silver…`, so it won't run for others or into `workspace.datathon`.
    - It uses `df.cache()`, which serverless compute may not support.
    - It has no `<dataset>_validation` table or citation columns (CLAUDE.md rules). Left unchanged for Elliot.
  - **Notebook 06 (Will):** 800 facilities are linked to more than one NABH site; possibly separate NABH programmes per hospital, to confirm.
- **Why:** Sophia asked to verify that `main` and `sophia-wip` are consistent, and that every notebook runs in order without errors in cleaning or filtering.
- **Notes / follow-ups:**
  - `main` lacks the `sophia-wip` fixes (NULL-distance fix, notebook 01 validation and coordinate checks, etc.); they'll go to `main` through a PR.
  - Two files from the Databricks commit `e7f701b` (`Preprocessing ETL/transformations/init_transforms.py`, `describe_given_data.sql.dbquery.ipynb`) are unverified and stay on `sophia-wip` only.

### 2026-11-21 20:19: Merged `main` (Will_branch: registries, notebooks 05/06, PIN notebook renamed to 00) into `sophia-wip`; resolved PR #8 conflicts
- **Who:** Claude (for Sophia)
- **What:**
  - Merge commit bringing `origin/main` (including PR #7 from `Will_branch`) into `sophia-wip`, which resolves the conflicts in PR #8 ("updated ver 8:13pm", `main` → `sophia-wip`).
  - Files touched to resolve it: `DEVLOG.md`, `notebooks/india_pincode_bronze_to_silver.py` (deleted), and the references to the renamed PIN notebook in `CLAUDE.md`, `docs/data-sources.md`, `docs/silver-tables.md`, `docs/registries-silver.md`, `notebooks/00_pincode_bronze_to_silver.py`, `01`, `02`, `05`, `scripts/dryrun_coordinate_checks.py` and `scripts/test_pincode_cleaning.py`.
- **How:**
  - **`DEVLOG.md`:** both branches had added entries, and `sophia-wip` still contained unresolved `Updated upstream` / `Stashed changes` markers from `e7f701b`. The Entries section was rebuilt as the union of both sides: 33 + 41 entries became 50 unique, sorted newest first. No entry text was changed; where the same heading appeared on both sides, the longer text was kept. No conflict markers remain.
  - **`india_pincode_bronze_to_silver.py`:** Will deleted it on `main` and `sophia-wip` had edited it. The deletion was accepted, because `00_pincode_bronze_to_silver.py` replaces it.
  - **Rename `04_pincode` → `00_pincode`:** git carried the NULL-distance fix into the renamed file. References were updated (including the "run notebook 00 first" checks in 01 and 02); DEVLOG history keeps the old name.
- **Why:** Sophia asked to resolve the merge conflicts after pulling Will's work.
- **Notes / follow-ups:**
  - All notebooks compile and the local tests pass; not re-run on Databricks.
  - **Run order is now 00 → 01, 02 → 05 → 06** (05/06 per Will's docs).
  - The DEVLOG has two "Dropped stale duplicate tables" entries (~15:15 and ~16:05) from the Databricks side; both kept as written.

### 2026-11-21 20:15: Fixed 20,015 km distances for missing coordinates; restored notebook 01 after an accidental rollback
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/common/validation.py` (`haversine_km_col`).
  - `notebooks/04_pincode_bronze_to_silver.py` (`km_from_pin_median`, `coords_far_from_pin`).
  - `notebooks/01_bronze_to_silver.py`: restored and fixed.
  - `DEVLOG.md`: restored 3 entries.
- **How:**
  - **Bug:** Spark's `F.least()` skips NULLs, so `least(1.0, sqrt(NULL))` returned 1.0, i.e. 2 × 6371 × asin(1) = 20,015 km for any missing point.
    - **Effects:** in 04, every office without coordinates was flagged far from its PIN and given status `nulled_far_from_pin`. In 01, near-duplicate pairs where one side had no coordinates got 20,015 km, so the "no coordinates → compare names only" rule never fired. `km_from_pin_centre` was 20,015 for facilities without coordinates.
    - **Fix:** `haversine_km_col` returns NULL when its input is NULL. Notebook 04 uses it, with a NULL distance counting as "not far". Notebook 01's `haversine_km` now calls it.
  - **Restore:** commit `e7f701b` ("minor corrections/adaptations to Databricks") was made from a Databricks Git folder that hadn't pulled. It replaced notebook 01 with the ~15:45 version, left a conflict marker, truncated the file at line 998 with "...", and deleted the 16:27, 16:43 and 17:18 DEVLOG entries.
    - Notebook 01 was restored from `0b51ac7`, and that commit's three real changes were re-applied: the Databricks environment header, the cell title "Possible near-duplicates", and the near-duplicate `TypeError` fix (pass `F.col(...)` rather than column-name strings to `haversine_km`).
    - The three entries were re-inserted from `0b51ac7`. The Databricks-side entries (13:45–16:35) were kept.
    - Notebooks 02 and 04 were not rolled back; their new environment headers and 02's `nqas_certified_facilities` bronze default are kept.
- **Why:** Sophia reported the 20,015 km bug and chose to restore the newer notebook 01 rather than keep the rolled-back one.
- **Notes / follow-ups:**
  - **In Databricks, always Pull before Commit & Push** in the Git dialog.
  - Notebooks compile locally; not yet re-run on Databricks.

### 2026-11-21 20:05: Merged `main` (Kayakalp validation, PR #5) into `Will_branch`
- **Who:** Claude (for William)
- **What:** Merged `origin/main` up to `7daea47` into `Will_branch`. It brings in JhK830's Kayakalp validation: `notebooks/03_kayakalp_bronze_to_silver.py` changes, `scripts/validate_kayakalp.py`, `scripts/requirements-kayakalp.txt`, `tests/test_kayakalp.py`, `docs/kayakalp-validation-handoff.md`, and edits to `docs/silver-tables.md` and `docs/data-sources.md`.
- **How:** `git merge --no-ff origin/main`. No conflicts. Alice's DEVLOG entry stays at the bottom of the file, where it is on main.
- **Why:** So the pull request from `Will_branch` into `main` is clean and includes everyone's latest work. None of the incoming files are used by notebooks 05/06.

### 2026-11-21 20:00: Registry silver tables built on Databricks; serverless fixes to notebooks 05 and 06
- **Who:** Claude (for William)
- **What:**
  - **Databricks CLI:** v1.27.0 installed in `~/.local/bin`, from the official GitHub release with its SHA-256 checked. Homebrew was refused because Xcode/CLT are older than macOS 27. Profile `datathon` added.
  - **William's workspace:** created schema `workspace.datathon` and Volume `workspace.datathon.external`; uploaded the 9 registry `*_bronze.csv` files and `india_post_pincode_directory.csv`; created the Git folder `/Users/<William>/CMU_Datathon_26` on `Will_branch`.
  - **Ran notebook 05** as a one-off serverless job. It wrote `registry_sites_silver` (24,961 rows) and `registry_services_silver` (22,757), plus 8 raw bronze tables. Counts per source match the local test exactly.
  - **Code fixes:**
    - Notebook 05: `reduce(DataFrame.unionByName, …)` → `reduce(lambda a, b: a.unionByName(b), …)`.
    - Notebook 06: `.cache()` / `.unpersist()` removed.
- **How:**
  - The CLI commands used: `databricks schemas create`, `volumes create`, `fs cp`, `repos create` / `repos update --branch Will_branch`, `jobs submit` (serverless notebook task), `jobs get-run-output`, and the SQL Statements API for the check.
  - The fixed notebooks were uploaded into the Databricks Git folder with `workspace import --overwrite`, as uncommitted edits there.
- **Why:** William wanted the registry silver tables as soon as possible. The first serverless run failed with `[JVM_ATTRIBUTE_NOT_SUPPORTED] … '_jdf'`: serverless uses Spark Connect, where the classic `DataFrame` class (and DataFrame caching) isn't available. The local tests use classic Spark, so they didn't catch it.
- **Notes / follow-ups:**
  - The serverless fixes and the notebook 06 dual-naming change are **not committed yet**. Once pushed, discard the matching uncommitted edits in the Databricks Git folder before pulling.
  - Notebook 04 hasn't run yet, so `pin_latitude`/`pin_longitude` are empty. Run 04, then rerun 05, to add them.
  - Notebook 06 needs `facilities_silver` (notebook 01, blocked by the line-753 bug on main).

### 2026-11-21 19:53: Notebook 06 accepts either facilities_silver column naming
- **Who:** Claude (for William)
- **What:** `notebooks/06_registry_matching.py` now reads `facilities_silver` columns through a small `fcol()` helper:
  - `<name>_clean` if that column exists (it's the cleaned value);
  - otherwise the plain `<name>`;
  - otherwise NULL, with a note printed.

  It prints which columns it used. Notes added to the notebook header and `docs/registries-silver.md`.
- **How:** Tested locally on two copies of `facilities_silver`: one with plain names (as on main) and one with `state_clean`, `pincode_clean`, `city_clean`, `latitude_clean`, `longitude_clean`. Both produced the same 4,482 links (no differences in either direction).
- **Why:** `origin/main` has nothing new since our merge. But on `origin/sophia-wip`, the latest commit `e7f701b` ("minor corrections/adaptations to Databricks") brings back `*_clean` column names in notebook 01. That reverses the earlier "no `_clean` in silver" rule, and also removes the validation step and the PIN-based coordinate check. Until Sophia confirms which version is final, notebook 06 shouldn't depend on either. Also noted:
  - `sophia-wip` fixes the line-753 `haversine_km` bug in notebook 01 (all its versions).
  - The notebook 04 `F.least()` NULL bug is still present there.
  - Nothing from `sophia-wip` was merged into this branch.

### 2026-11-21 18:28: Registry sites matched to facilities (notebook 06)
- **Who:** Claude (for William)
- **What:**
  - New `notebooks/06_registry_matching.py`. It writes:
    - `facility_registry_links_silver` (facility ↔ registry site, with match score and evidence);
    - `facility_registry_summary_silver` (one row per facility);
    - `registry_match_review` (links for a person to confirm).
  - Matching section added to `docs/registries-silver.md`; layout line added to `CLAUDE.md`.
- **How:**
  - **Candidates:** same state + a shared distinctive name word (join on state and word, ignoring words in more than 250 names) + nearby (coordinates within 3 km, same PIN, PIN area within 5 km, or the town/district named in the address).
  - **Distinctive-word check:** after removing generic words and place names, mismatched distinctive words → rejected; words on one side only → review.
  - **Score:** `rapidfuzz` name similarity + location, type, ownership and clinic adjustments.
  - **Decision:** link at ≥ 85; review for 70–84, near-ties, distance over 10 km, or one-sided words. Known duplicates are linked together.
  - **Tested locally:** notebooks 01 → 04 → 05 → 06 on local Spark 4.0. `facilities_silver` came from `data/raw/facilities.csv`, which uses **backslash-escaped quotes** (load it with Spark's default escape).
  - **Result:** 4,482 links; 2,745 of 9,989 facilities (27%) linked; 1,444 links need review.
  - **Hand checks:** NABH 15/15 correct; other sources 29/30.
- **Why:** This makes all registry evidence joinable on `facility_id`, as the structure agreed with William requires (links table, not a list column on facilities). Decisions:
  - Precision over recall: uncertain matches are kept but marked `needs_review`, not dropped.
  - Generic-word-only matches were the main source of false links (e.g. "ESIC Medical College" vs "Osmania Medical College"); the distinctive-word check removes them.
- **Bugs found in teammates' notebooks** (reported to William; not changed here, since the files are Sophia's/Elliot's):
  1. **`notebooks/01_bronze_to_silver.py` line 753:** `haversine_km("latitude_a", …)` passes column **names** as plain strings, so Python fails with `TypeError: unsupported operand type(s) for -: 'str' and 'str'`. The near-duplicate step, and with it the whole notebook, can't finish. Fix: wrap each name in `F.col(...)`. The local test used a patched scratch copy.
  2. **`notebooks/04_pincode_bronze_to_silver.py`:** `F.least(F.lit(1.0), F.sqrt(h))` returns 1.0 when coordinates are NULL (`least` skips NULLs). So every office **without coordinates** gets `km_from_pin_median` = 20,015 km and the `COORDS_FAR_FROM_PIN` flag: about 12k of the 12,102 flagged offices. The centroids are unaffected, but the flag counts and the note in `docs/data-sources.md` §4 are wrong. Fix: `F.when(h.isNotNull(), …)`. The same guard is used in notebook 06.

### 2026-11-21 18:16: NABH directory scraped and added to the registries silver tables
- **Who:** Claude (for William)
- **What:**
  - New `scrapers/nabh_organisations.py`, `datasets/external/nabh_bronze/nabh_organisations_bronze.csv` (21,582 listings) and `docs/nabh.md`. The API pages are in `raw/pages/` (82 MB, git-ignored).
  - `notebooks/05_registries_bronze_to_silver.py` gains a `nabh` source, plus new site columns for every source: `latitude`, `longitude`, `listing_type`, `listing_category`, `listing_status`, `listing_current`, `state_listed`. `dental` is added to the service list.
  - `docs/data-sources.md`: entry 11 and a summary row.
  - `docs/registries-silver.md` updated.
- **How:**
  - NABH's directory posts its search form to `admin-ajax.php` (allowed by robots.txt). 865 requests, 1.5 s apart, each page cached; 2 dropped connections succeeded on retry. Phone numbers aren't saved.
  - The programme comes from the accreditation-number prefix (35 prefixes, each checked against status text and certificate folder).
  - The state comes from the address, with a last-state-in-text fallback: 79% → 99.4% coverage.
  - Notebook 05 tested locally again, with all six sources: 24,961 sites, 22,757 service rows, all checks passed.
- **Why:** NABH fills gaps the blocked sources left: 127 blood centres (blood bank directory blocked), 49 dialysis centres (PMNDP blocked), 90 emergency departments, 15 stroke centres. It also covers private hospitals, which the government sources miss. Decisions:
  - **Only service-specific programmes become service rows.** Hospital, entry-level and empanelment listings are general quality and stay as site-level `listing_category`.
  - **Travel facilitators and ethics committees are excluded**; they aren't care sites.
  - **For NABH, the PIN's state wins** when it disagrees with NABH's listed state (389 sites; e.g. an Agra hospital listed as South Delhi). The original is kept in `state_listed`. Other sources are flagged only, because it's unclear there which side is wrong.
  - Empanelment numbers' **E/C letter is read as ECHS/CGHS** (labelled "inferred"). This separates two listings of one hospital that aren't duplicates: duplicate flags went from 3,303 to 397.
- **Notes / follow-ups:** Notebook 06 (matching to `facilities_silver`). NABH coordinates (93% of listings) should make matching much easier.

### 2026-11-21 17:34: Service registries brought to silver (notebook 05)
- **Who:** Claude (for William)
- **What:**
  - New `notebooks/05_registries_bronze_to_silver.py`. It loads each uploaded `*_bronze.csv` as a raw table of the same name, then builds `registry_sites_silver` (one row per registry place) and `registry_services_silver` (one row per place × service × evidence).
  - New `docs/registries-silver.md`.
  - `docs/data-sources.md`: the five summary rows now point to notebook 05 and its tables.
  - `CLAUDE.md`: layout line for notebook 05.
- **How:**
  - Follows notebooks 02–04: `%run ./common/reference_data`, the shared `state_from_text` / `name_norm` / `name_core`, `dq_flags`, per-row `row_citation` and citation columns, `write_table`.
  - One mapping function per source (LaQshya, trauma, NMC, DNB, NCG); all are unioned into the shared columns.
  - Optional enrichment from `pincode_centroids_silver` (PIN location, `PIN_STATE_MISMATCH`).
  - **Tested locally:** PySpark 4.0 in a scratchpad virtualenv, with a small harness that stubs `dbutils`, `display` and `%sql`. Notebook 04 ran first (building the PIN centroids), then 05, against the real CSVs. Results: 3,481 sites, 19,198 service rows, all assertions passed (unique IDs, no orphan services).
  - The local run caught a summary query that Spark rejects (correlated subquery inside GROUP BY); it now joins two aggregates.
- **Why:** William wants all his data at silver, ready for teammates, in a structure that makes confidence easy to calculate later. Decisions:
  - **Facilities aren't given a list column of sources.** The registries are separate tables that link to `facility_id` through a links table (notebook 06), so each piece of evidence keeps its own detail, date, validity, citation and, later, match score. `facilities_silver` is unchanged.
  - **Reliability is described per evidence row, not per dataset:** `evidence_type`, `service_specific`, `is_current`, `status`. That's because one dataset can hold both strong and weak evidence (current vs expired, DM vs MD). **No scores at silver**; points belong in gold.
  - `surgery_support` (anaesthesiology) is dropped as not a patient-facing service. NCG NGOs, societies and research members are left out, as they aren't care sites.
- **Notes / follow-ups:**
  - Notebook 06 (matching to `facilities_silver`).
  - Add NABH once its download finishes.
  - 3 sites have a PIN from another state: source errors, flagged.

### 2026-11-21 17:18: Silver-vs-bronze validation for facilities, pincode and NQAS; coordinates nulled when they don't match the address
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/common/validation.py`: `run_validations()`, `mismatch_rows()`, `haversine_km_col()`, `same_number()`.
  - Notebooks `01`, `02` and `04` updated.
  - New `scripts/dryrun_coordinate_checks.py`.
  - Docs: `docs/silver-tables.md`, `scripts/README.md`, `CLAUDE.md` (run order and validation rule).
  - New tables: `facilities_validation`, `pincode_validation`, `nqas_validation`.
- **How:**
  - **Pincode (04):** an office's coordinates are set to NULL if they're more than 50 km from its PIN's median point (`coord_status = nulled_far_from_pin`).
    - Silver and centroids are staged and checked against `pincode_bronze`: row reconciliation; PIN, office name and raw coordinate text equal bronze; coordinates equal the re-parsed bronze values; state and district derived from bronze; no kept coordinate far from its PIN; unique `office_id`; each centroid inside its offices' box.
    - Then published.
  - **Facilities (01):** coordinates must be within 25 km plus the PIN's spread of the PIN centroid, and inside the state's box (from `pincode_silver`, padded 0.25°); otherwise set to NULL (`nulled_pin_mismatch` / `nulled_state_mismatch`).
    - New columns: `km_from_pin_centre`, `pin_in_directory`, `state_matches_pin`.
    - New flags: `COORDS_NULLED_PIN_MISMATCH`, `COORDS_NULLED_STATE_MISMATCH`, `PIN_NOT_IN_DIRECTORY`, `STATE_NOT_SERVED_BY_PIN`.
    - Checks against `facilities_bronze`: row reconciliation (merged + rejected); IDs in bronze, UUID-shaped and unique; name, PIN, coordinates (exact, or swapped back), state and the numbers all come from the facility's bronze rows; no kept coordinate breaks the PIN or state rule.
  - **NQAS (02):** the district must exist in that state in `pincode_silver` (flag `DISTRICT_NOT_IN_STATE`; there are no coordinates to null).
    - Checks: row reconciliation; every listing exists in bronze; dates match the bronze day/month/year; state and district come from bronze; status matches the dates; unique ID.
  - **All three** write the candidate silver to a staging table and validate it. If a check fails, the run stops and the existing silver table is left untouched.
- **Why:** Sophia wants all silver data accurate to bronze, with PINs, addresses/regions and coordinates consistent with each other, and coordinates set to NULL when they don't match.
- **Tradeoffs:**
  - The PIN check allows each PIN's own spread, so large rural PINs aren't penalized.
  - The state check uses a padded bounding box (cheap, no polygons), so it only catches clearly wrong states.
  - NQAS district matching is exact on a letters-only key, so old or alternate district names will be flagged.
- **Dry-run results (local CSVs):**
  - **Facilities:** about 1,492 lose their coordinates for PIN mismatch (e.g. "Aravind Eye Hospital": Delhi PIN 110002, point ~1,870 km away, consistent with merged records), 5 for being outside their state; 8,467 keep theirs.
  - **Post offices:** 12,102 lose their coordinates.
  - **NQAS:** 236 of 989 listings are flagged `DISTRICT_NOT_IN_STATE`.
- **Notes / follow-ups:**
  - **Run order is now 04 → 01, 02** (enforced by an assertion).
  - Not yet run on Databricks.
  - Kayakalp (03) wasn't in scope; it could get the same treatment.

### 2026-11-21 17:12: Data-source citations for William's scraped datasets
- **Who:** Claude (for William)
- **What:** `docs/data-sources.md` gets five summary rows and entries 6–10:
  - DNB/ANBAI
  - NMC colleges and courses
  - MoHFW trauma care facilities
  - LaQshya
  - National Cancer Grid

  Each has the publisher, URL, retrieval date, licence or terms, processing chain, limitations, "cite as" line and per-row citation columns.
- **How:** Wrote the entries from the scraper docs (`docs/anbai-dnb.md`, `nmc-colleges.md`, `trauma-care-facilities.md`, `laqshya.md`, `ncg-members.md`), following the file's template. Checked that each cited column exists in its CSV.
- **Why:** CLAUDE.md (merged from main) requires a citation entry for every outside dataset. These five were committed before that rule reached this branch. Notes:
  - **NABH** gets its entry in the same commit as its data; its download is still running.
  - **NCG:** the site footer says "All rights reserved", so the entry asks the team to check with the organizers before redistributing it outside the datathon.
  - **NMC:** the entry records that personal staff contacts were dropped.

### 2026-11-21 17:08: Merged `main` into `Will_branch`
- **Who:** Claude (for William)
- **What:** Merged `origin/main` (26 commits, up to b5aba4d) into `Will_branch`. It brings in:
  - the NQAS, Kayakalp and PIN-directory notebooks;
  - `notebooks/common/`;
  - `scripts/` and `data/`;
  - the renamed `facilities_bronze` / `facilities_silver` tables, and silver columns without the `_clean` suffix.
- **How:** `git fetch`, then `git merge --no-ff origin/main`. Two conflicts were resolved by hand:
  - `.gitignore`: kept the rules from both sides.
  - `DEVLOG.md`: kept every entry from both branches, interleaved newest first by timestamp. One entry existed twice ("Listed outside datasets…", 14:10 on this branch and 13:24 on main, whose timestamps had been corrected); main's copy was kept.
- **Why:** William asked to pull the teammates' new scripts into his branch so his work builds on them.
- **Notes / follow-ups:** Main's conventions differ from this branch's scraper work:
  - main uses `scripts/` and `data/external/`; this branch uses `scrapers/` and `datasets/external/`;
  - `docs/data-sources.md` doesn't yet have entries for the ANBAI, NMC, trauma, LaQshya, NCG and NABH datasets, which CLAUDE.md now requires.

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

### 2026-11-21 ~16:35: Fixed `notebooks/india_pincode_bronze_to_silver.py` — read the PIN directory as a UC table, not a CSV
- **Who:** Claude (for Sophia)
- **What:** Single-cell script `india_pincode_bronze_to_silver.py`, focused-cell fix only. Changes: (1) `BRONZE_PATH` corrected to `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory` — the old value had catalog/schema segments repeated 4×; (2) read changed from `spark.read.csv(...)` to `spark.read.table(...)`, since the source is a Delta Sharing table, not a data.gov.in CSV file; (3) the CSV `nullValue="NA"` option replaced with an explicit "NA"→NULL mapping after the read; (4) `pincode` cast to string (it arrives as bigint) so the PIN-format regex still works; (5) `source_file` now records the source table name (`_metadata.file_path` exists only for file reads); (6) `HAS_LONGITUDE = True` — the source table verifiably has a populated `longitude` column.
- **How:** Diagnosed `CloudInvalidPathException: Path must be absolute` from `.csv()` receiving a table name. Verified the real table schema (pincode bigint, longitude present) and NA-token counts (12,007 NA latitudes, 715 NA statenames) before writing the fix. Then ran the fixed cell end-to-end on its attached compute.
- **Why:** The script was written against a raw CSV from data.gov.in, but the actual source is the Unity Catalog shared table. The error can only be fixed by reading it as a table; the NA/pincode/source_file changes replicate what the CSV reader options used to do.
- **Notes / follow-ups:** Full run passed the quality gate: 165,627 bronze → 165,625 silver rows (2 duplicates dropped), 19,586 unique PINs, 151,840 valid latitudes (91.6%), 1,775 out-of-range, 3 unparseable, 715 missing state/district, 0 invalid PINs. `workspace.datathon.pincode_silver` written, `pincode_silver_quality_history` appended, `pincode_silver_quality_current` view created.

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

### 2026-11-21 16:23: Scraped National Cancer Grid members; blood bank directory blocked
- **Who:** Claude (for William)
- **What:** New `scrapers/ncg_members.py`, new `docs/ncg-members.md`, and new `datasets/external/ncg_bronze/ncg_members_bronze.csv` (421 rows). The raw HTML fragments are in `raw/`, which is git-ignored. `docs/dataset-notes.md` gets a new NCG row and a note on the blood bank blocker.
- **How:**
  - NCG members: the ncgindia.org member page loads its table from `/hospitalsandinstitutions/_index`; robots.txt allows everything. The script made 5 requests, 1 s apart: all Indian members, then one per member type to label them. It takes the PIN code from each address and maps states to the silver names.
  - Blood banks: AIKosh's page only links to `info.nhp.gov.in/api/blood-banks.csv` (GODL licence). That host doesn't connect from here, AIKosh has no direct download, and its API returns 403.
  - tmc.gov.in/ncg is behind a firewall that rejects scripted requests. It wasn't worked around; the official ncgindia.org was used instead.
- **Why:** William asked for the next dataset. The blood bank directory was first in line but is blocked, so the next reachable source was used. NCG cancer centres give evidence for cancer care and partly cover the blocked AERB radiotherapy list. Decisions:
  - Only the `cancer_centre` type is tagged `cancer_care`.
  - Membership is rated medium strength: it isn't a licence or an inspection.
- **Notes / follow-ups:**
  - Blood bank directory: needs an Indian connection, or a download by hand from AIKosh or data.gov.in.
  - NCG: not yet matched to `silver_facilities`. Use PIN + name.

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

### 2026-11-21 16:18: ANBAI and NMC scrapers now write to the bronze names
- **Who:** Claude (for William)
- **What:**
  - `scrapers/anbai_dnb.py` now writes to `datasets/external/anbai_dnb_bronze/`, and `scrapers/nmc_colleges.py` to `datasets/external/nmc_bronze/`.
  - Every output file has the `_bronze` suffix, e.g. `dnb_hospitals_bronze.csv` and `nmc_colleges_bronze.sqlite`.
  - Updated `docs/anbai-dnb.md` and `docs/nmc-colleges.md` to match.
  - Table names inside the SQLite files are unchanged, matching the files William renamed.
- **How:**
  - Replaced the default output folder and the output file names in both scripts and docs.
  - Checked the result:
    - NMC: `--offline` rebuilt into `nmc_bronze/` with no git diff, so it's identical.
    - ANBAI: rebuilt from the saved HTML into a scratch folder; contents identical apart from the `scraped_at` timestamp.
- **Why:** Closes the follow-up from the 15:14 bronze rename. Before this, re-running either scraper would have recreated the old `anbai_dnb/` and `nmc/` folders next to the bronze ones.

### 2026-11-21 16:17: `address_line1/2/3` removed from `facilities_silver`
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/01_bronze_to_silver.py`: the final select leaves out the three address-line columns, the header text is updated, and the address spot-check SQL now joins to `facilities_bronze` for the original lines.
  - `docs/silver-tables.md`: dropped-columns list and watch-out 22.
- **How:** a `REPLACED_BY_PARSED` list removes them only in the last step, because the lines are still needed earlier, for address parsing and for the `NO_COORDS_OR_ADDRESS` rule.
- **Why:** Sophia: once `address_full` and the split `address_street` / `address_region` / `address_landmark` exist, the raw lines are redundant in silver. They remain in `facilities_bronze` for exact quoting.
- **Notes / follow-ups:** `address_city`, `address_stateOrRegion` and `address_zipOrPostcode` are still in silver next to `city_clean`, `state_clean` and `pincode_clean`; they could be removed the same way if wanted. Notebook 01 is still unverified on Databricks; the last run there appears to have stopped before section 5.

### 2026-11-21 16:07: Built the LaQshya maternity certification dataset
- **Who:** Claude (for William)
- **What:** New `scrapers/nhsrc_laqshya.py`, new `docs/laqshya.md`, and new outputs in `datasets/external/laqshya_bronze/`:
  - `laqshya_certifications_bronze.csv` (2,173 rows)
  - `laqshya_facilities_bronze.csv` (1,343 rows)

  The source PDF is in `raw/`, which is git-ignored. Updated the LaQshya row in `docs/dataset-notes.md`. Installed `pdfplumber` (0.11.11) with `pip install pdfplumber`.
- **How:**
  - Downloaded the NHSRC "LaQshya Master data" PDF dated 2026-04-08, a public government document. The site's robots.txt returns "forbidden", so it sets no rules.
  - Read the table with `pdfplumber`, which follows the grid lines; that's the only way to tell the Certified and Conditional columns apart.
  - Repaired cells where text overflows into the next column and the letters interleave:
    - 129 type/district cells, with a rule that reads the type code in order within the cell;
    - state overflow;
    - 3 department cells;
    - 9 facility names fixed by hand.

    Every repair is flagged, and the raw values are kept.
  - Rolled certifications up to facilities, and checked validity against the build date.
  - Validation: serials 1–2,173 complete and unique, all dates parsed, all states mapped.
- **Why:** William picked LaQshya as the next outside source. A certified maternity OT is direct government evidence of C-section capability, which also covers the FRU gap. Decisions:
  - Expired certifications are kept, with two strengths: valid now, or had the capability. Only 200 of the 901 maternity OT facilities are currently valid, and dropping the rest would throw away real evidence.
  - Conditional certifications are kept and flagged.
  - Rows with no department are never counted as C-section evidence.
- **Notes / follow-ups:** Not yet matched to `silver_facilities`. Match on state + district, then fuzzy name.

### 2026-11-21 ~16:05 (approx.): Dropped stale duplicate tables `bronze_facilities` and `silver_facilities`
- **Who:** Claude (for Sophia)
- **What:** Dropped `workspace.datathon.bronze_facilities` and `workspace.datathon.silver_facilities` from the metastore.
- **How:** Verified identical row counts to the current tables first (`bronze_facilities` 10,088 = `facilities_bronze`; `silver_facilities` 10,077 = `facilities_silver`), dropped both, then listed `workspace.datathon` to confirm only the tables the notebooks write remain. (This restores an entry lost when DEVLOG.md was concurrently updated from git; the exact time was not recorded.)
- **Why:** They were leftovers from notebook 01's original table names, renamed at 15:45; nothing writes the old names anymore. Sophia confirmed the drop. This also closes the follow-up note in the 15:45 entry.

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

### 2026-11-21 15:27: Built the trauma care facilities dataset from a Rajya Sabha answer
- **Who:** Claude (for William)
- **What:** New `scrapers/mohfw_trauma_centres.py`, new `docs/trauma-care-facilities.md`, and new `datasets/external/trauma_care_bronze/trauma_care_facilities_bronze.csv` (196 rows). The source PDF is in `raw/`, which is git-ignored. Updated the trauma centres row in `docs/dataset-notes.md`. Installed `pypdf` (7.1.1) on William's machine with `pip install pypdf`.
- **How:**
  - Downloaded Rajya Sabha Unstarred Q. 2048 (10 Mar 2026), a public Parliament PDF; sansad.in has no robots.txt.
  - Read Annexure-I with `pypdf`, grouped the lines into rows by serial number, and carried the merged state cells forward across page breaks.
  - Took the trauma level (I/II/III) from the end of each row.
  - Added a hand-checked `place` column (corrected spellings, current names) and a keyword-based `facility_type`.
  - The script refuses to write output unless it finds 196 rows, each with a state, level and place.
- **Why:** William wanted outside evidence for trauma and emergency care. These are the government's designated Level I–III trauma facilities. Decisions:
  - The printed name is kept unchanged (typos included) for quoting.
  - Corrected place names go in a separate column, to help matching.
  - Every row is marked `sanctioned`, because the answer doesn't confirm which facilities are functional.
  - The output is bronze, following William's convention.
- **Notes / follow-ups:**
  - Not yet matched to `silver_facilities`.
  - Many Level I/II facilities are medical colleges that can be cross-linked to the NMC data.
  - The FRU list is still open: no facility-level source has been found yet.

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

### 2026-11-21 ~15:15: Dropped stale duplicate tables `bronze_facilities` and `silver_facilities`
- **Who:** Claude (for Sophia)
- **What:** Dropped `workspace.datathon.bronze_facilities` and `workspace.datathon.silver_facilities`.
- **How:** Verified first that they were stale duplicates of the current tables — identical row counts (`bronze_facilities` 10,088 = `facilities_bronze`; `silver_facilities` 10,077 = `facilities_silver`) and same schema shapes. These were the notebook's *original* table names (see the 12:45 entry) before a later run renamed the outputs to `facilities_bronze` / `facilities_silver`; nothing in the current notebook writes the old names. Dropped both via SQL, then listed `workspace.datathon` to confirm only the 5 current tables remain.
- **Why:** Sophia asked where the silver tables are saved and confirmed dropping the two leftovers, so the schema holds only the tables the notebook actually writes.
- **Notes / follow-ups:** `workspace.datathon` now contains exactly: `facilities_bronze`, `facilities_silver`, `silver_facility_claims`, `silver_dq_summary`, `silver_possible_duplicates`.

### 2026-11-21 15:14: Renamed scraped datasets to bronze
- **Who:** William (renamed the files), Claude (logged and committed)
- **What:**
  - Folders: `datasets/external/anbai_dnb/` → `anbai_dnb_bronze/`, and `datasets/external/nmc/` → `nmc_bronze/`.
  - Every CSV and SQLite file in them gained a `_bronze` suffix, e.g. `nmc_colleges.csv` → `nmc_colleges_bronze.csv`.
  - The `raw/` folders moved with them and are still git-ignored.
- **How:** William renamed the files by hand. Claude committed the renames with `git add -A` and pushed to `Will_branch`.
- **Why:** The teammates haven't verified these datasets yet. Calling them bronze marks them as unverified, following the project's bronze → silver convention.
- **Notes / follow-ups:** The scrapers (`scrapers/anbai_dnb.py`, `scrapers/nmc_colleges.py`) and the docs (`docs/anbai-dnb.md`, `docs/nmc-colleges.md`) still use the old folder and file names. Re-running a scraper will write to the old names until they're updated.

### 2026-11-21 14:35: Added .gitignore; committed scraper work to `Will_branch`
- **Who:** Claude (for William)
- **What:** New `.gitignore` that ignores `.DS_Store` and `datasets/external/*/raw/`. Committed the ANBAI and NMC scrapers, outputs and docs, then pushed `Will_branch` to `origin`.
- **How:** `git add -A`, `git commit`, then `git push -u origin Will_branch`.
- **Why:** William asked to keep the raw scraper responses out of git (NMC `raw/` is about 23 MB). The CSV and SQLite outputs are committed so teammates can use them without re-scraping. Tradeoff: page snapshots stay only on William's machine, and `--offline` rebuilds need them. The scrape dates are recorded in the CSVs (`scraped_at` / `snapshot_date`).

### 2026-11-21 ~14:30: Full notebook verified end-to-end; all 5 tables written and cleaning rules independently checked
- **Who:** Claude (for Sophia)
- **What:** Ran every executable cell of `notebooks/01_bronze_to_silver` in the workspace with no errors, including sections 8-10 which had never run (`silver_facility_claims` 549,851 rows, `silver_dq_summary` 16 flags, table/column comments applied, `_silver_facilities_stage` dropped). Then ran an independent verification pass (separate SQL, using the notebook's own constants) over all five tables in `workspace.datathon`.
- **How:** Executed remaining cells in dependency order on serverless compute; then a standalone check script: null-like tokens and control chars in all string/array columns, PIN format, India bounding box, state whitelist, year/doctor/capacity ranges, array dedup, facility_id uniqueness, claims completeness, and duplicate-pair rule conformance.
- **Why:** Sophia asked to verify the whole notebook runs clean and that the saved tables are properly cleaned and processed.
- **Notes / follow-ups:** Every check returned zero violations. `silver_facilities`: 10,077 rows, 10,077 distinct facility_id; 9,953 usable coords; 9,913 valid PINs; 9,833 with state; avg completeness 0.812. Top flags: STATE_UNRECOGNIZED 244 (2.4%), PINCODE_MISSING_OR_INVALID 164 (1.6%), MISSING_COORDS 118. Notebooks's cell IDs shifted at some point (an old nuid no longer resolved); runs used freshly-read nuids.

### 2026-11-21 14:27: Scraped NMC medical colleges and their MBBS/PG courses
- **Who:** Claude (for William)
- **What:** New `scrapers/nmc_colleges.py`, new `docs/nmc-colleges.md`, and new outputs in `datasets/external/nmc/`:
  - `nmc_colleges.csv`
  - `nmc_college_courses.csv`
  - `nmc_specialty_reference.csv`
  - `nmc_colleges.sqlite`, which holds those 3 tables plus the view `v_service_evidence`
  - `raw/`, which holds the API responses

  Also updated the NMC row in `docs/dataset-notes.md`.
- **How:**
  - The NMC pages load their tables with JavaScript from JSON endpoints. The script calls those endpoints directly; robots.txt allows all paths.
    - `/college-courses/list`: MBBS, 1 request.
    - `/college-courses/pg-list`: PG, 11 requests of 1,000 rows each.
    - `/college-courses/detail/<id>`: one per college, 911 in total, 0.5 s apart and cached.
  - Removed degree prefixes and diploma suffixes from the course names to get specialty names.
  - Tagged related challenge services with regex rules, using the same tags as the ANBAI/DNB data.
  - Mapped state names to the silver names.
- **Result:**
  - 911 colleges: 611 with a valid PIN, 219 with super-specialty courses.
  - 11,583 course rows across 103 PG specialties.
  - Super-specialty evidence: dialysis at 82 colleges, NICU at 36, ICU at 40.
- **Why:** William wanted NMC as a second source of outside evidence that specialties are really practised. A PG course needs a working department with enough patients and faculty, and the detail records give the address and PIN, which makes matching easier than with the DNB names. Decisions:
  - **Named staff contacts, mobile numbers and emails are dropped before saving.** We don't need personal data.
  - Course levels are kept so evidence can be weighted (DM/M.Ch. strong, MD/MS broad, MBBS weak).
  - `recognition_status` is kept as published text.
  - Service tags are marked as our hints, not as claims by NMC.
- **Notes / follow-ups:**
  - Bugs caught while checking the output: "neurology" matched the urology rule, and Gynaecological Oncology was tagged as C-section. Both are fixed.
  - Not yet matched to `silver_facilities`.
  - `raw/` is about 23 MB; decide whether to keep it out of git.

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

### 2026-11-21 ~14:05: Re-ran sections 0-7 in the workspace after a Python restart; `silver_facilities` written
- **Who:** Claude (for Sophia)
- **What:** Notebook `01_bronze_to_silver` sections 0-7 re-run end to end on serverless compute. No code changed. The `silver_facilities` table now exists (83 columns: clean fields, counts, `dq_flags`, `possible_duplicate_ids`, variants). Earlier tables (`bronze_facilities`, `_silver_facilities_stage`, `silver_possible_duplicates`) refreshed by the same run.
- **How:** The Python process had restarted, so cell 25 (section 7) failed with `NameError: name 'qc' is not defined` — stale session state, not a code bug. Re-ran the full prerequisite chain (cells 3-23) in dependency order, then cell 25.
- **Why:** A kernel/compute restart clears all notebook variables; `qc` and the rest are defined in earlier cells and just needed re-running.
- **Notes / follow-ups:** Section 8 (SQL checks) still not run. The fix from the ~13:45 entry held up: the near-duplicates cell ran clean again.

### 2026-11-21 13:58: William's work goes on `Will_branch`
- **Who:** William (created the branch), Claude (recorded the rule)
- **What:** Added a line to `CLAUDE.md` saying Claude's work for William goes on `Will_branch`. The ANBAI scraper work (entry below) moved to this branch uncommitted.
- **How:** Edited `CLAUDE.md`.
- **Why:** Each teammate works on their own branch, so `main` stays clean.

### 2026-11-21 13:54: Scraped DNB-accredited hospitals and their specialties (ANBAI)
- **Who:** Claude (for William)
- **What:** New `scrapers/anbai_dnb.py`, new `docs/anbai-dnb.md`, and new outputs in `datasets/external/anbai_dnb/`:
  - `dnb_hospitals.csv`
  - `dnb_hospital_specialties.csv`
  - `dnb_specialty_reference.csv`
  - `anbai_dnb.sqlite`, which holds those 3 tables plus the view `v_service_evidence`
  - `raw/anbai_dnb_2026-11-21.html`

  Also updated the NBEMS row in `docs/dataset-notes.md`.
- **How:**
  - Fetched https://anbai.org/DNB_accredited_institutions.php in one request with `requests`. The site has no robots.txt.
  - The page is static HTML with one collapsible section per state, and a Hospital | City | Specialties table in each. Parsed it with BeautifulSoup.
  - Split the specialty cells on commas and repaired broken or missing commas against a 71-name canonical list, plus aliases.
  - Fixed old state names, and moved 3 hospitals in Telangana cities that were listed under Andhra Pradesh.
  - Added a hand-written `related_services` hint for each specialty (e.g. Nephrology → dialysis).
- **Why:** William wanted DNB accreditation as outside evidence that a specialty is really practised at a hospital. Training accreditation needs real patient volume and faculty. Decisions:
  - The ANBAI HTML page was used instead of the NBEMS PDFs, because it's one structured table.
  - Raw text is kept next to the cleaned values.
  - Same-name, same-city listings are kept separate (they have different specialty lists, so they're probably branches).
  - Specialty → service links are marked as hints, not claims.
- **Notes / follow-ups:**
  - The page has no update date, and its Andhra Pradesh / Telangana listings look out of date, so cite the snapshot date.
  - Not yet matched to `silver_facilities`; the suggested approach is in `docs/anbai-dnb.md`.
  - Not yet loaded into Databricks.

### 2026-11-21 ~13:45: Fixed `TypeError` in the near-duplicates cell of `01_bronze_to_silver`
- **Who:** Claude (for Sophia)
- **What:** `notebooks/01_bronze_to_silver.py` (Databricks notebook, section 6 "Possible near-duplicates", cell 23): fixed the `TypeError: unsupported operand type(s) for -: 'str' and 'str'`.
- **How:** The `haversine_km` helper subtracts its arguments (`lat2 - lat1`), but the call passed bare column-name strings (`"latitude_clean_a"` etc.); Python cannot subtract two strings, so the cell failed before Spark ever ran. Wrapped the four call-site arguments in `F.col(...)` (minimal fix; the helper itself is unchanged). Re-ran all prerequisite cells plus the fixed cell on serverless compute in the Databricks workspace.
- **Why:** Strings are fine as column names for single-argument functions like `F.radians`, but only for arithmetic done inside Spark columns; fixing at the call site keeps the helper usable with both strings and Columns.
- **Notes / follow-ups:** Verified on the first full run in the workspace: 10,088 bronze rows -> 10,077 unique facilities, 32 possible near-duplicate pairs written to `silver_possible_duplicates`. Section 7 (flags / final `silver_facilities`) and section 8 (SQL checks) were not run this time and still need a pass.

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

## 2026-11-21 — Authorized isolated Kayakalp persistence attempt

- Executed unchanged notebook 03 with explicit isolated catalog/schema and `write_output=true`; failed before creation because Spark Connect rejects `errorifexists`. Canceled the automatic retry; kept write behavior and transformation unchanged.
- Prepared separate read-only session checks and retained submission, traceback, source hashes and comparison evidence in ignored `shared/runs/kayakalp-validation/databricks/persistence/`.
- Updated validation handoff with the blocker, intended target, queries, review/access limitations and integration recommendations against Sophia `106316d2d81db70755e8e94aaaef2241e0d4f2fd` (district/state naming and reference-helper conflict). Claude review attempt failed because CLI is not logged in. No push, merge, credential or generated-data commit, shared modification, overwrite/drop/truncate, or new cluster/warehouse.
- Separate read-only run `694938706475969` completed: Bronze actual count 1,197; Silver absent; Spark 4.2.0. Parent persistence run canceled after first failed attempt. Final documentation whitespace check passed.
