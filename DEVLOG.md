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

### 2026-11-21 14:10: Listed outside datasets for checking care quality, with links
- **Who:** Claude (for Sophia)
- **What:** Added the section "Outside datasets for checking care quality and reliability" to `docs/dataset-notes.md`, with about 25 sources in four groups (priority 1, specific services, existence and location, context) and links.
- **How:** Web searches on 2026-11-21 for each source's official portal or data.gov.in / AIKosh page. Portals were mostly not opened, so availability and formats still need checking.
- **Why:** Sophia asked for free datasets to judge the quality and reliability of care at each facility, so the team can corroborate claims instead of trusting the Virtue Foundation fields. Decision recorded: **a match is evidence for a facility; no match is not evidence against it**, because most of these lists only cover public hospitals or members of one scheme.
- **Notes / follow-ups:**
  - Team to choose which sources to bring in.
  - The top candidates are PM-JAY (specialty approvals), NABH, PMNDP dialysis centres, LaQshya, and the blood bank directory.
  - No links found yet for SNCU, trauma centres, NOTTO or Kayakalp.
  - PM-JAY, NABH and HFR appear to be search-only portals, so they'd need scraping. Check each site's terms of use first.

### 2026-11-21 13:30: Added the bronze → silver ETL notebook and silver-table docs
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

### 2026-11-21 13:25: Started using the `sophia-wip` branch
- **Who:** Sophia (created the branch), Claude (switched to it)
- **What:** Sophia created `sophia-wip` on GitHub. The local repo now tracks `origin/sophia-wip`, and `CLAUDE.md` records that Claude's work goes there.
- **How:** `git fetch origin` then `git switch sophia-wip`.
- **Why:** Sophia wants `sophia-wip` to be the main place Claude's work goes, keeping `main` clean for the team.

### 2026-11-21 12:50: First commit and push to GitHub
- **Who:** Claude (for Sophia)
- **What:** Committed `DEVLOG.md`, `CLAUDE.md` and `docs/dataset-notes.md`, then pushed them to `origin/main`. This creates the `main` branch on GitHub.
- **How:** `git add`, `git commit`, then `git push -u origin main`.
- **Why:** So all collaborators can see the log, the logging rule and the dataset notes, and build on them.
- **Notes / follow-ups:** Claude's push failed because Git wasn't signed in to GitHub yet. Sophia then ran `git push -u origin main` in their own terminal and signed in through the browser using Git Credential Manager. The push worked, and the login is now saved on this machine.

### 2026-11-21 12:45: Set Git identity on Sophia's machine
- **Who:** Sophia
- **What:** Set the global Git `user.name` (`sophia-m-kliatchko`) and `user.email`.
- **How:** `git config --global user.name ...` and `git config --global user.email ...`
- **Why:** Git needs an author identity before it will make commits.

### 2026-11-21 12:40: Added dataset notes from a previous team's write-up
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
