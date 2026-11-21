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
