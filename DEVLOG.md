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

### 2026-11-21 12:50: First commit and push to GitHub
- **Who:** Claude (for Sophia)
- **What:** Committed `DEVLOG.md`, `CLAUDE.md` and `docs/dataset-notes.md`, then pushed them to `origin/main`. This creates the `main` branch on GitHub.
- **How:** `git add`, `git commit`, then `git push -u origin main`.
- **Why:** So all collaborators can see the log, the logging rule and the dataset notes, and build on them.
- **Notes / follow-ups:** Claude's push failed because Git wasn't signed in to GitHub yet. Sophia then ran `git push -u origin main` herself and signed in through the browser using Git Credential Manager. The push worked, and the login is now saved on this machine.

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
