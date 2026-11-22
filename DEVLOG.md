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

### 2026-11-22 09:52: `aesthetics`: merged main; green palette, one font, no provisional banner, new subtitle
- **Who:** Claude (for Sophia)
- **What:**
  - Merged `origin/main` into `aesthetics`: PRs #20 (evidence key, references footer), #21 (Alice's evidence tiers v2, claim guards) and #22. The only conflict was `DEVLOG.md`, where I kept both sides' entries.
  - `app/static/styles.css`:
    - Off-white paper (`#f7f8f4`), white cards and green accents (`--accent #2f7a4b`, `--accent-2 #1f5a35`, plus new `--accent-soft` and `--accent-tint`). Former teal tints are now green, the orange background glow is now pale green, and the focus outline is green.
    - Tier colours are unchanged because they carry meaning.
    - `--display`, `--body` and `--mono` are all DM Sans; the section titles no longer use Newsreader.
  - `app/static/index.html`:
    - Loads only DM Sans (400–700, with italics).
    - Removed the "Provisional results" banner.
    - New subtitle: "Pick a service and enter your PIN code. We find facilities near you, rank them by how well independent records back the service, and link every piece of evidence to its source."
  - `app/static/app.js`: removed the code that filled and showed the banner.
  - Redeployed `find-the-right-care` from `aesthetics`.
- **How:** `git merge origin/main`, then edited the files, ran `databricks sync --full` and `databricks apps deploy`. The live page has no banner and shows the new subtitle. A dialysis search at PIN 800020 returns 3 cards.
- **Why:** Sophia asked for the final website to match `main` and for these visual changes.
- **Note:** with Alice's tiers v2 from `main`, accepted self-reports for dialysis count as T3. The Patna dialysis top 3 is now three nearby facilities that self-report it, not IGIMS.

### 2026-11-22 09:37: App fills empty slots only with facilities that self-report the service
- **Who:** Claude (for Sophia)
- **What:**
  - `app/backend/engine.py`:
    - New `self_reports(facility_ids, service)` finds facilities whose own listing (`silver_facility_claims`) mentions the service, using the synonyms in `backend/services.py`.
    - `shape(..., claims)`: when fewer than 3 facilities have documentary evidence (T1–T3), the remaining slots go to the **nearest** facilities that self-report the service. They keep the **U** label, and their claim text appears in the evidence list as "SELF … not verified".
    - The alternatives table also keeps only U facilities that self-report the service.
    - Unrelated facilities are no longer shown. Before, a dialysis search could show dental clinics.
  - `app/main.py`: passes the claims to `shape`.
  - `app/static/app.js`: shows "No additional facilities found." when there are fewer than 3 cards. The no-evidence notice now says the facilities below only claim the service themselves.
  - Redeployed `find-the-right-care`.
- **How:** edited the files, then ran `databricks sync --full` and `databricks apps deploy`. Checked through the live API:
  - dialysis 800020: 1 T3 + 2 self-reported U cards.
  - C-section 800020: 1 T3 + 2 U.
  - dialysis 110001 (5 km): 1 self-reported U card (an eye hospital whose listing describes a 20-bed dialysis unit) and no alternatives.
  - stroke 800020 (3 km): 1 U card.
- **Why:** Sophia asked that, without evidence, the app take the dataset's self-reports at their word (labelled U), fill the open slots with the nearest such facilities, and say "No additional facilities found" when there are none. Her first version capped this at 2; she then asked to fill all the open slots instead.
- **Tradeoff:** self-reports are unverified. The U stamp, the "SELF" ledger tag and the "not verified" status keep this visible. Where nothing nearby claims the service, fewer than 3 cards are shown, which is better than showing unrelated facilities.
- **Branch:** on `sophia-wip` at Sophia's request (new work normally goes to `aesthetics`).

### 2026-11-22 09:26: New work for Sophia goes on the `aesthetics` branch
- **Who:** Claude (for Sophia)
- **What:** `CLAUDE.md`, Branches section: new work for Sophia now goes on `aesthetics` (tracking `origin/aesthetics`) instead of `sophia-wip`. Earlier work stays on `sophia-wip`.
- **How:** edited the line, then committed and pushed to `aesthetics`.
- **Why:** Sophia asked for all new updates to go to the aesthetics branch.
### 2026-11-22 14:30: Tier framework evidence-tiers/2 (variant C) integrated in production (Alice)
- **Who:** Claude (for Alice). Uncommitted, for review.
- **What:** `tiers.py` applies the approved variant C upgrade (`_evidence_class`, `_tier_from_classes`, `PROCEDURE_OR_UNIT_SERVICES`, `BROAD_SPECIALTY_HINTS`); new assessment fields `t2_basis`, `evidence_nature`; framework `evidence-tiers/2`. `pipeline.py`: route-specific T2 explanation, `tier_label`, `t2_basis`, `evidence_nature`. `evidence_review_audit.py` mirrors the rule. `service_claims.py`: guard skipped (and reported) when callers pass no facility names, for the website's current call.
- **Result:** all 5,619 evidence pairs: T1 281 / T2 942 / T3 2,641 / R 1,754 / U 1 (was T2 77 / T3 3,506). Four validation queries: only 400001 dialysis changes (Lilavati T3→T2 corroborated, #9→#2).
- **Tests:** 269 run, 268 pass, 1 error (SparkTests: pyspark). Simulated merge with origin/main a93dd99: same result; website `shape()` consumes the response but labels every T2 "Expired certification" (website change documented).

### 2026-11-22 13:00: Tier policy revision: specialty training restored; revised framework proposed (Alice)
- **Who:** Claude (for Alice). Uncommitted, for review.
- **Production (`tiers.py`):** the 11:30 specialty-only exclusion is reverted at Alice's request; NMC/DNB training is again T3, now labelled as clinical expertise (`related_specialty`, explanation: not confirmation the service is offered). Kept: future/planned claim fix (`service-claims/2`), attribution guard (`service-claims/3`), `evidence_freshness`, `attribution` output. Snapshot re-baselines from 11:30 reverted. Ranking unchanged.
- **Proposal (`experimental_tiers.py`, analysis only):** T1 current direct; T2 expired direct, NCG membership, NMC training for specialty-level services, or self-report corroborated by independent registry evidence; T3 self-report, training for procedure/unit services, undated DNB training, sanctioned trauma designation; `evidence_nature` operational/expertise.
- **Result on all 5,619 evidence-bearing facility-service pairs (61 services):** production T1 281 / T2 77 / T3 3,506 / R 1,754 / U 1 → proposal T1 281 / T2 942 / T3 2,641 / R 1,754 / U 1 (865 T3→T2, no demotions).
- **Tests:** 260 run, 259 pass, 1 error (SparkTests: pyspark).

### 2026-11-22 09:00: Diagnosed suspicious Mumbai dialysis recommendations; fixed future-tense claim matching (Alice)
- **Who:** Claude (for Alice).
- **What:** `service_claims.py` → `service-claims/2`: claims stating a plan or future capability (`plans to`, `under construction`, `will be/open`, `being set up`, `to be set up/started…`) are skipped like negations (never counterevidence). Two regression tests in `tests/test_pipeline.py`.
- **Why:** Municipal Hospital (Mumbai) was T3 for dialysis only from "Plans to convert into a 17-floor multispeciality hospital … including dialysis". 5 dialysis claims across the dataset were future-tense; "dialysis planning, initiation and maintenance" (clinical) stays matched.
- **Result (local snapshot):** 400001 dialysis T3 56→55, U 641→642, Municipal Hospital leaves the top 5; 110001 dialysis/C-section and 600001 C-section unchanged. 251 tests: 250 pass, 1 error (SparkTests needs pyspark).
- **Not code bugs (data quality, reported):** J J Eye Hospital and Saifee Hospital VF records are conflated with other facilities (claims describe a JJDB dialysis centre in Santacruz; Saifee's website/description are Prince Aly Khan Hospital); 10 Mumbai-area dialysis registry sites (9 Apex Kidney Care branches, Grant Medical College) are not linked to any facility by notebook 06. Live Databricks links (4,226) not available locally to compare with 4,482.

### 2026-11-22 09:22: Website: evidence key stays visible next to the results
- **Who:** Claude (for William)
- **What:**
  - `app/static/index.html`: an "Evidence key" panel (`#key`, a `<details>`) in the sidebar under the search form, with the six tiers, a short definition each, and a count.
  - `app/static/app.js`: `updateKey()` shows the key after each search with the count per tier over all candidates (tiers with none are dimmed); `linkToKey()` highlights a card's or table row's tier in the key on hover or keyboard focus. Collapsed by default on narrow screens.
  - `app/static/styles.css`: `.key*` styles. The sidebar now stretches to the results' height and only the key is sticky (the form was sticky before and scrolls with the page now).
- **How:** edited the three files; checked with Playwright in live mode (Delhi C-section: counts T1 1, T2 0, T3 46, R 3, U 699, X 0; hovering a T3 table row highlights T3) at 1360 px and 390 px, no console errors.
- **Why:** William asked for a key that stays on screen; the tier definitions only appeared on the start screen and disappeared once results loaded.
- **Tradeoff:** the full form no longer follows you down the page; pinning both didn't fit a 900 px-tall window and cut off the key.
- **Deployed:** committed as 131c6ec, pushed to `origin/website_finalization`, redeployed William's app `find-the-right-care` (deployment 01f1e68050c21f028dc60446ca1b9703 SUCCEEDED); the live page serves the key.

### 2026-11-22 09:05: Website: "Data sources and references" section
- **Who:** Claude (for William)
- **What:** `app/static/index.html`: a numbered references list in the footer (`#references`, entries `#ref-1`…`#ref-12`) replaces the one-line source sentence; a "Data sources and references" link under the intro jumps to it. `app/static/styles.css`: `.refs*` and `.lede__refs` styles.
- **How:** William's 11 references (IEEE style) as given, each with a "Used for" line that says honestly how the app uses it. NQAS [3], Kayakalp [4] and NFHS-5 [5] are marked "the data pipeline only; not yet used in results". Added [12] Meta Llama 3.3 70B Instruct (the AI explainer, via Databricks Foundation Model APIs). Checked with Playwright at 1360 px and 390 px, no console errors.
- **Why:** William asked for a references window or footer listing every dataset used. All 11 match the sources in `docs/data-sources.md`; the explainer model was the only thing missing, since its text appears on the page.
- **Deployed:** committed as fae884c, pushed to `origin/website_finalization`, redeployed William's app `find-the-right-care` (deployment 01f1e67e313f1d3faae946b348aa332a SUCCEEDED); the live page serves all 12 references.

### 2026-11-22 08:41: Website brought up to date with Alice's `evidence_confidence` on main (claims, review decisions, radius rule)
- **Who:** Claude (for William)
- **What:** new branch `website_finalization` from `main` @ 8a2c8d3 (PR #19).
  - `app/evidence_confidence/`: re-copied unchanged from main's `evidence_confidence/` (last commit c5f1586). `app/EVIDENCE_CONFIDENCE_VERSION` now records `source_branch: main`, commit c5f1586e…, and how to update from main.
  - `app/backend/geography.py` `nearby_facilities()`: Alice's and notebook 07's radius rule. `distance_min_km = max(distance_km - location_uncertainty_km, 0) <= radius` (was `distance_km <= radius`); bounding box widened by the largest `location_uncertainty_km` (cached `max_uncertainty_km()`); `distance_min_km` returned.
  - `app/backend/engine.py`:
    - `load_claims()` reads `silver_facility_claims` (fields specialties / capability / procedure / equipment, coarse `claim_norm` prefilter that is a superset of her patterns) for services in her `CLAIM_PATTERNS`. `claim_evidence()` turns them into self-reported Evidence (T3 cap) added to the registry evidence.
    - `load_reviews()` reads `registry_match_review` rows with a `reviewer_decision`, passed to `adapt_registry_tables(reviews=)`.
    - `distance_min_km` passed to `build_recommendation_response`; the adapter report now includes `claim_mapping` and row counts for reviews and claims.
    - Display: claims shown as "Listed under procedures: “…”" with source "Facility's own listing (Virtue Foundation dataset)"; cards with only self-reported T3 say so and get `self_reported_only`; the C-section qualifier `CLAIM_DOES_NOT_STATE_EMERGENCY` becomes a warning; facilities kept by the uncertainty rule say why they're outside the radius; two new auditor strings from her package mapped; R cards no longer also say "no record was found".
  - `app/main.py`: provisional note says claims count for dialysis and C-section. `app/static/app.js`: T3 stamp reads "Self-reported" when only claims support it.
  - `app/README.md`, `CLAUDE.md`: tables read, call sequence, update steps from main, answered questions.
- **How:** `git archive HEAD evidence_confidence | tar -x -C app` (checked identical with `diff -rq`); ran her tests on main (228 pass, 18 skipped, 1 unrelated error: `scripts/kayakalp_pdf_to_csv.py` needs `pdfplumber`). Local app in live mode against warehouse 280169f53e6a2de0: 7 searches, adapter PASS on all; Playwright screenshots of 3 searches, no console errors.
- **Why:** Alice's PR #19 added the claim mapping, review-decision support and a handoff list for the website (`docs/recommendation-pipeline.md`): radius rule, `distance_min_km`, selection policy. William asked to bring the website up to date with it and to count C-section claims for now.
- **Result (live tables, 50 km unless noted):**

  | Search | Before | Now |
  |---|---|---|
  | Patna 800020 dialysis | T3 1 | T3 30 (claims) |
  | Chennai 600001 dialysis | | T3 34, R 2 |
  | Delhi 110001 C-section | T1 1, T3 0 | T1 1, T3 46, R 3 |
  | Patna C-section, emergency | 5 unconfirmed | 11 T3 unconfirmed |
  | Mumbai 400001 blood bank, 25 km | T1 Lilavati | unchanged (no claim mapping) |

  The radius rule adds 2–12 candidates per search (110001: 12, matching Alice's measurement).
- **Tradeoffs / decisions:**
  - C-section claims count for `emergency_c_section` (William's call; Alice flagged it for the team). Each such card warns that the claim doesn't state emergency availability.
  - Kept the app's own SQL loading instead of her `recommend_facilities()`, which reads a local CSV bundle that a Databricks App doesn't have.
  - Kept Sophia's selection policy (top 3, filled in her order) rather than her ranks 1..K; noted in `app/README.md` as a team decision.
- **Deployed:** committed as f7ecedf and pushed to `origin/website_finalization`, then redeployed William's app `find-the-right-care` (`databricks sync --full`, `apps start`, `apps deploy`; deployment 01f1e67bd62e1e628f474bb74d26086b SUCCEEDED). The live `/api/health` reports `evidence_confidence@c5f1586`; Patna dialysis returns 161 candidates, 30 T3 from claims, adapter PASS.
- **Notes / follow-ups:** `registry_match_review.reviewer_decision` is empty (0 of 1,197), and notebook 06 overwrites the table, so a separate decisions table is still needed.

### 2026-11-22 05:00: Backend final validation (Alice)
- **Who:** Claude (for Alice). Read-only on teammate branches; no commits or merges.
- **What:** ran `recommend_facilities` on 4 real queries with Elliot's 07 notebook; corrected merge notes (only `setup_pipeline.py` conflicts, 1 hunk; the rename deletes the legacy notebook); re-measured website radius-rule loss.
- **Validation:** 749/749/700/347 candidates kept, 5 recs + 5 distinct alternatives each, 0 duplicates, all non-U cited, deterministic, 400001 dialysis identical to the reference. 246/247 unittest (test_kayakalp: pdfplumber). Details in BACKEND_PROGRESS.md.

### 2026-11-22 (time not captured; shell blocked): Website entrypoint + handoff (Alice)
- **Who:** Claude (for Alice), non-interactive run.
- **What:** `evidence_confidence/pipeline.py`: added `recommend_facilities(service, pincode, radius_km, max_results=5, max_alternatives=5, *, silver_dir|bundle, **options)`, a thin wrapper over `recommend()` with a per-directory bundle cache. `tests/test_pipeline.py`: 2 new tests. `docs/recommendation-pipeline.md`: entrypoint, website handoff (radius rule, cap, selection-policy difference), Elliot merge plan. New `BACKEND_PROGRESS.md`.
- **How:** read `origin/website:app/backend/{geography,engine}.py` and `git diff origin/Elliot_New_Branch` (read only).
- **Why:** the website needs one call; ranking/tier logic untouched.
- **Validation:** NOT RUN. Python/pytest were blocked by the session's permission mode; the new code and tests are unexecuted.

### 2026-11-22 04:00: Compatibility check against origin/Elliot_New_Branch (Alice)
- **Who:** Claude (for Alice). Read-only inspection; no checkout/merge.
- **What:** 07 notebook on that branch is byte-identical to the version validated locally; `notebooks/common/validation.py` identical. Added `default_notebook()` so pipeline/validation/tests use the renamed `notebooks/07_pin_nearby_facilities.py` when present.
- **Validation:** post-merge layout simulated in a scratch copy: 245 tests, only test_kayakalp (pdfplumber) errors; 400001 dialysis response identical to the pre-merge run. Committed HEAD merges cleanly; the uncommitted `notebooks/setup_pipeline.py` edit conflicts with Elliot's step_07 task (one hunk).

### 2026-11-22 03:30: End-to-end recommendation pipeline + self-reported claim mapping (Alice)
- **Who:** Claude (for Alice).
- **What:** new `evidence_confidence/pipeline.py` (`load_bundle`, `recommend` → `recommendation-pipeline/1`: top-K + next-ranked alternatives, provenance, uncertainty, warnings, nearest-first comparison) and `evidence_confidence/service_claims.py` (`service-claims/1`, provisional: dialysis + C-section exact terms, negations skipped, self-report ≤ T3); `tests/test_pipeline.py` (13). Ranking semantics, `build_recommendation_response` and the website contract unchanged. Docs: `docs/recommendation-pipeline.md`.
- **Validation:** local only, downloaded Silver + ~/Downloads 07 notebook. 110001 C-section/dialysis 749 candidates, 400001 dialysis 700, 600001 C-section 347; all retained, deterministic, JSON round-trip, no duplicate IDs; website-shape call still PASS. 244/245 tests pass (test_kayakalp: pdfplumber missing). No Databricks, commits or pushes.
- **Open:** claim-mapping approval; LaQshya site linked to a 'Blood Bank, LBS Hospital' record (notebook 06); facility PIN/address mismatches (e.g. Hyderabad address with Delhi PIN); 07 notebook not yet committed by Elliot.

### 2026-11-22 02:00: Geographic producer integrated with Evidence Confidence (Alice)
- **Who:** Claude (for Alice).
- **What:** `geographic_candidates.py` supports the newer 07 notebook (uncertainty-adjusted radius, widened box) and adds `to_join_candidate`; `geographic_validation.py` takes `--geography-notebook`/`--pins` and checks the box against the producer's own rule; new `tests/test_geographic_integration.py` (8 tests). Teammate notebooks untouched; the downloaded 07 notebook was read from ~/Downloads, not copied.
- **Validation:** local run on downloaded Silver (no Databricks): 9,989 geo-ready rows, 2 unsearchable; PINs 110001/400001/600001 → 749/700/347 candidates, 0 box omissions, all retained through LEFT JOIN, uncertainty fields preserved. 231/232 tests pass (test_kayakalp needs pdfplumber). No commits/pushes.

### 2026-11-22 01:05: Audited real evidence review decisions and prepared geography handoff (Alice)
- **Who:** Codex (for Alice)
- **What:** Added read-only evidence review audit, per-R ledger generation, local snapshot regressions and component handoff documentation.
- **How:** Reclassified actual downloaded Silver records as of 2026-11-22; inspected all 1,771 R pairs and eight T3/pending-T1 pairs; exercised real evidence with explicitly controlled geographic fixtures.
- **Why:** Separate identity-review coverage from geographic readiness while teammate develops facility_geo_ready.
- **Notes / follow-ups:** 223 Evidence Confidence tests pass. Real geographic validation awaits teammate handoff; no geography/shared pipelines, source data, tier policy or ranking policy changed in this phase. See docs/evidence-confidence-review-audit.md.

### 2026-11-22 00:22: Audited downloaded Silver CSVs without regeneration or publication (Alice)
- **Who:** Codex (for Alice).
- **What:** Added `evidence_confidence/downloaded_silver_audit.py`, explicit CSV dialect support in the existing reader/CLI, six focused tests and `docs/evidence-confidence-downloaded-silver-audit.md`; linked the existing integration handoff. Preserved prior uncommitted pipeline and Evidence Confidence work.
- **How:** Read all 14 downloaded CSVs (322,321,092 bytes) using their verified backslash-escape convention; checked keys/rows/types, full-row duplicates, arrays, references, geography, provenance, snapshot differences and contact-field presence. Reused the existing adapters/tier/LEFT JOIN/ranker/JSON interfaces with real records; inventory probes explicitly used unknown distances and were not geographic searches.
- **Why:** Downloads are incomplete for full integration and publication eligibility must be separate from data quality. Missing Kayakalp/review/geographic exports, legacy schemas, unresolved source redistribution terms, a 136.3 MiB CSV and a public destination block publication.
- **Validation / result:** 214 Evidence Confidence tests passed; full suite has one pdfplumber import error and pytest is unavailable. Synthetic smoke retains 32/32. Actual inventory probes retain 9,989/9,989 per service and preserve eight real T3 + pending-T1 cases without promotion. Source hashes unchanged; no downloaded records changed, regenerated, staged, committed or uploaded. No Databricks job ran in this task.

### 2026-11-21 23:25: Silver generation/publication preflight blocked before execution (Alice)
- **Who:** Codex (for Alice).
- **What:** Added `docs/silver-generation-publication.md`; no preprocessing code, source data, tables, jobs or Evidence Confidence implementation changed.
- **How:** Inspected setup/runner and notebook 00–06 source, source-licence documentation, actual local input presence, runtime dependencies, existing output directories, Git size/ignore/LFS configuration and official GitHub limits. Setup is a Databricks notebook/job provisioner, not a local environment installer. Its step 03 omits the persistence flag.
- **Why:** The user's stop conditions prohibit publication with unclear redistribution rights. Virtue Foundation terms remain TODO, NCG records an all-rights-reserved restriction, and other source licences are unresolved; local PySpark/Delta/SDK runtime is also absent. No environment install, remote execution, dataset export, staging, commit, push, PR or merge was performed.
- **Validation / result:** No Silver was generated or newly validated; published size 0 bytes, no publication commit. The report inventories expected outputs/dependencies, exact blockers and remaining reproduction/validation gates; documentation whitespace checks passed.

### 2026-11-22 00:18: Added nearby-facility search to the pipeline
- **Who:** Copilot (for Elliot)
- **What:** Moved `notebooks/common/pin_nearby_facilities.py` to `notebooks/07_pin_nearby_facilities.py`; added step 07 to `setup_pipeline.py`, `run_pipeline.py`, and `scripts/local_spark/run_all.sh`; documented the 00 → 07 run order.
- **How:** Replaced the hand-run dependency on `facility_geo_ready` with a fresh rebuild, and changed radius matching to include facilities whose uncertainty-adjusted closest distance is within the requested radius while retaining measured distance and uncertainty columns.
- **Why:** A fresh pipeline could not build or run the nearby-facility app, and the previous radius filter ignored coordinate uncertainty.
- **Notes / follow-ups:** Rerun setup_pipeline and the 00–07 Job on Databricks to recreate `facility_geo_ready`; verify step 07 with a PIN and radius before merging.

### 2026-11-22 07:44: App title in DM Sans with a real italic "right"
- **Who:** Claude (for Sophia)
- **What:** `app/static/index.html` loads DM Sans 700 (roman and italic) from Google Fonts. In `app/static/styles.css`, the `h1` uses DM Sans and `h1 em` is italic again. Redeployed `find-the-right-care`.
- **How:** edited the font link and two CSS rules, then ran `databricks sync --full` and `databricks apps deploy`.
- **Why:** Sophia wants "right" in italics, but in a better-looking font. The previous Atkinson Hyperlegible title had no bold italic loaded, so the browser would have faked a slanted one. DM Sans ships a true bold italic.

### 2026-11-22 07:42: App shows the top 3 results, each with its own explanation; plainer title font
- **Who:** Claude (for Sophia)
- **What:**
  - Merged `main` (the app from PR #17) into `sophia-wip`. Conflicts in `.gitignore`, `README.md` and `DEVLOG.md` were resolved by keeping both sides.
  - `app/backend/config.py`: `TOP_N` defaults to 3 (was 5).
  - `app/backend/engine.py` `shape()`, routine mode: when fewer than 3 facilities have documentary evidence (T1–T3), the cards are filled with the next best in the engine's order. Facilities with some evidence come first, then the nearest with none. The cards used to fill are removed from the alternatives table.
  - `app/static/app.js`:
    - Every card's "Why is this recommended?" menu opens with its plain-language explanation already generated, so you no longer click a button.
    - Cards without documentary evidence say "Why is this listed?".
    - The "no documentary evidence" notice now checks the tiers instead of whether the list is empty.
  - `app/static/styles.css`: the title "Find the right care" uses the body font (Atkinson Hyperlegible, bold) instead of the italic Newsreader serif. "right" is no longer italic and keeps the accent colour.
  - Redeployed the Databricks App `find-the-right-care` from `sophia-wip`'s `app/`.
- **How:** edited the files, ran `databricks sync --full` to the app folder, then `databricks apps deploy`. Checked with authenticated calls to `/api/recommend` (dialysis, PIN 800020, 50 km), which returned 3 cards (T3, U, U), and to `/api/explain` on card 3, which returned text from the LLM.
- **Why:** Sophia asked for the top 3 results, each with the same explanation menu, and a less ornate title font: the italic "right" looked bad.
- **Tradeoff:** padding to 3 can show facilities with no evidence for the service. Their stamp reads "U / No evidence", the ledger says "No evidence found", and the menu says "listed", not "recommended", so they aren't presented as confirmed. Each search now makes up to 3 LLM calls instead of 0 until a click.

### 2026-11-22 07:33: App `find-the-right-care` deployed in Sophia's workspace; live tables refreshed
- **Who:** Claude (for Sophia)
- **What:**
  - Job "CMU Datathon pipeline 00-06" run on `main` (run 1088698257596279): all 7 steps SUCCESS.
  - Notebook `07_pin_nearby_facilities` (Part A) run to build `workspace.datathon.facility_geo_ready` (run 903388580739811).
  - New Databricks App `find-the-right-care` from `main`'s `app/` (commit 01e348c), with resources `sql-warehouse` (Serverless Starter Warehouse, CAN_USE) and `serving-endpoint` (`databricks-meta-llama-3-3-70b-instruct`, CAN_QUERY).
  - The app's service principal was granted `USE CATALOG` on `workspace` and `USE SCHEMA, SELECT` on `workspace.datathon`.
  - URL: https://find-the-right-care-7474649081384549.aws.databricksapps.com
- **How:** `git archive` of `origin/main:app` → `databricks apps create --json` (resources attached) → `databricks sync --full` to `/Users/<me>/apps/find-the-right-care` → GRANTs through the SQL Statements API → `databricks apps deploy`.
- **Why:** Sophia asked to deploy the app in her workspace for the demo.
- **Result:** deployment SUCCEEDED; app RUNNING; uvicorn started with no errors. The log's "Security scan failed: scanner run failed" is Databricks' optional scanner, not a deploy failure.
- **Notes / follow-ups:**
  - Not yet clicked through in a browser.
  - Stop the app between demos (`databricks apps stop find-the-right-care --profile datathon`).
  - `facility_geo_ready` isn't built by the job, so re-run notebook 07 after future job runs.

### 2026-11-21 23:31: `notebooks/export_silver_csv.py`: silver tables to CSV
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/export_silver_csv.py`: writes one CSV per silver table to the Volume `workspace.<schema>.exports`, plus `_export_manifest.csv`, then reads each file back and checks the row and column counts.
  - `.gitignore`: `silver_csv/`.
  - README: export section.
- **How:** list and struct columns (e.g. `dq_flags`) become JSON text, since CSV can't hold them. Each table is written with `coalesce(1)` and its part file moved to `<table>.csv`.
  - Tested on Databricks only (run 1098749705351954, schema `datathon_verify`): SUCCESS. 13 tables exported, about 340 MB, and the read-back check passed.
  - Downloaded to the local folder `silver_csv/` (not committed).
- **Why:** Sophia asked for all the silver datasets as CSV on her computer. From now on testing is on Databricks only, keeping checks to what's necessary (time pressure).
- **Notes / follow-ups:** the downloaded files come from `workspace.datathon_verify` (the verified code's output). Run the export with `schema=datathon` after the live job has re-run with the merged code to export the live tables.

### 2026-11-21 23:20: PR #16 merged: `main` has the Databricks-verified pipeline
- **Who:** Sophia (approved), Claude (merged)
- **What:**
  - PR #16 (`databricks-verified` → `main`) merged as `e11e2d9`: the full notebook 01, the `setup_pipeline` CSV fix, `README.md` and `scripts/databricks/`.
  - `main` merged back into `sophia-wip`.
  - Remote branch `databricks-verified` deleted.
- **How:** `gh pr merge 16 --merge --match-head-commit a5ed199` (merged only if the head was still the verified commit).
- **Why:** Sophia approved after the serverless verification (runs 69185514918504 and 330170087354586).
- **Notes / follow-ups:**
  - **Pull** in the Databricks Git folder `/Datathon Fall 26/CMU_Datathon_26`, then run the job "CMU Datathon pipeline 00-06".
  - `main` and `sophia-wip` now differ only by the two unverified Databricks files, plus this entry until the next sync.
### 2026-11-22 01:02: Merged `Will_branch` and `main` into `website`
- **Who:** Claude (for William)
- **What:** `website` now includes:
  - `Will_branch` (70c2e6f): the notebook 06 kind-of-place check and its docs;
  - `origin/main` (73facd8): Sophia's Databricks-verified pipeline, `setup_pipeline.py`, `run_pipeline.py`, NFHS notebook 04, the project README and the pre-processed silver CSVs.
- **How:** `git merge Will_branch`, then `git merge origin/main`. The only conflicts were in `DEVLOG.md`, where both sides had added entries at the top. I kept all 23 entries (no duplicates) and ordered them by timestamp, newest first. CLAUDE.md merged automatically and keeps the `app/` line and main's updated run order.
- **Why:** Keep the website branch current with the pipeline it reads. The app code is unchanged, so the deployed app still matches.

### 2026-11-22 00:52: End-to-end Databricks run (00 → 07) with main's notebooks + the 06 kind-of-place fix
- **Who:** Claude (for William)
- **What:**
  - New workspace folder `/Users/<William>/e2e/CMU_Datathon_26`: main @ 73facd8's notebooks and input CSVs, plus this branch's `06_registry_matching.py` and Elliot's `notebooks/common/pin_nearby_facilities.py` copied as `notebooks/07_pin_nearby_facilities`.
  - Helper notebook `/Users/<William>/e2e/00b_load_missing_bronze`: the bronze section of `setup_pipeline.py`, verbatim. It created the missing `facilities` and `nqas_certified_facilities` bronze tables; existing tables were kept.
  - New job 681912826573850, "E2E check: 00-07 from main + 06 kind fix": tasks bronze → 00 → 01 → 02 → 03 → 04 → 05 → 06 → 07 on serverless, using the same parameters as `setup_pipeline.py`.
  - The app `find-the-right-care` had stopped (the compute stops when idle on Free Edition), so I restarted and redeployed it from the same workspace code (`website` 71c20c1).
- **How:** `databricks workspace import-dir`, `jobs create`, `jobs run-now` (run 218502582054949). The outputs were then checked through the SQL warehouse.
- **Why:** Verify the whole pipeline end to end on the real datasets, including `facility_geo_ready` (07) and the website on fresh tables.
- **Results:**
  - Every task succeeded (about 8 minutes of compute).
  - Validations passed: facilities 13/13, pincode 12/12, nqas 8/8, nfhs 7/7, facility_geo_ready 7/7.
  - Row counts: `facilities` bronze 10,088; `facilities_silver` 9,989; `facility_geo_ready` 9,989 (8,350 high, 1,634 PIN centroid, 5 none), all IDs in `facilities_silver`; `registry_sites_silver` 24,961; `registry_services_silver` 22,757; `nqas_silver` 989; `nfhs_silver` 705.
  - `facility_registry_links_silver`: 4,226 links (4,241 before; 15 rejected by the kind check). 1,197 need review, 165 of them because of the kind check.
  - "Blood Bank, LBS Hospital" and Government Dental College Raipur are now review links. Kasturba Hospital ↔ Kasturba Hospital Blood Bank stays automatic.
  - Deployed website on the fresh tables, adapter PASS on each search:
    - Delhi C-section (100 km): T1 1, T3 3, R 3, U 854. The LBS blood bank moved from T2 to R.
    - Patna dialysis: IGIMS T3.
    - Mumbai blood bank (25 km): Lilavati T1.
- **Notes / follow-ups:** The job and the e2e folder are a one-off check, separate from Sophia's "CMU Datathon pipeline 00-06" job; delete them after Elliot adds 07 to the pipeline. The 06 fix is still uncommitted on `Will_branch`.

### 2026-11-22 00:15: Notebook 06: kind-of-place check for registry matches
- **Who:** Claude (for William)
- **What:** `notebooks/06_registry_matching.py` and `docs/registries-silver.md`. Added `KIND_PATTERNS` (dental, eye, blood bank, diagnostics/lab, dialysis, fertility, physiotherapy), `DEPARTMENT_KINDS`, `kinds()`, and the `kind_conflict` / `kind_mismatch` columns:
  - Both names name kinds and share none: candidate rejected.
  - The facility names a kind the registry name lacks, or the registry name adds a specialty (eye, dental, fertility, physiotherapy): score capped below the link threshold, so the link goes to review. The review reason names both kinds.
  - The registry name only adds a department (blood bank, dialysis, diagnostics/lab): unchanged.
- **How:**
  - Found by the web app: "Blood Bank, Lal Bahadur Shastri Hospital" was auto-linked (score 98.8) to LBS Hospital's LaQshya maternity OT certificate.
  - Queried the 4,241 live links. 248 had a kind word on one side only. Auto-accepted ones included Government Dental College Raipur → Pt. JNM Medical College (24 service rows) and Narayana Dental College → Narayana Medical College (27).
  - Simulated the final rule on those links: 61 auto links go to review and 15 pairs are rejected, all of them clearly different places.
  - Tested the Spark expressions on 8 sample pairs with local PySpark; `py_compile` passes.
- **Why:**
  - A department or specialist clinic was inheriting a whole hospital's registry evidence (and so its tiers in the app) with no review.
  - Matching hospital departments in the registry (e.g. "Kasturba Hospital Blood Bank") stay automatic, because the hospital runs them.
  - The rule is direction-aware, so true hospital ↔ blood-bank links aren't lost.
- **Notes / follow-ups:** Not yet run on Databricks. Rerun notebook 06 to update `facility_registry_links_silver`, `facility_registry_summary_silver` and `registry_match_review`. The app reads the links live, so it picks up the change without a redeploy.

### 2026-11-22 00:00: Redeployed the Databricks App with Alice's engine
- **Who:** Claude (for William)
- **What:** Databricks App `find-the-right-care` redeployed from `website` commit 71c20c1 (evidence and ranking by `evidence_confidence@2368382`).
- **How:** `databricks sync` to the app's workspace folder, then `databricks apps deploy`.
- **Why:** Make the deployed site match the integration. Checked on the deployed URL:
  - `/api/health` reports `evidence_confidence@2368382`;
  - Delhi C-section (100 km) gives 861 candidates, T1 1 / T2 1 / T3 3 / R 2 / U 854, with the adapter at PASS;
  - Patna C-section (emergency) gives urgent mode, 0 recommended and 5 unconfirmed cards. These match the local runs.

### 2026-11-21 23:51: Web app wired to Alice's evidence_confidence package
- **Who:** Claude (for William)
- **What:**
  - `app/evidence_confidence/` (new): Alice's package copied unchanged from `alice-evidence-confidence` at commit 2368382. `app/EVIDENCE_CONFIDENCE_VERSION` records the commit and how to update it.
  - `app/backend/engine.py` (new):
    - loads the links, sites and service rows (one service) for the candidate facilities;
    - drops service rows from empanelment or general-accreditation sites;
    - calls her `silver.adapt_registry_tables()` and `build_recommendation_response()`;
    - reshapes her response for the page: plain-language warnings, evidence items with "counted" / "match under review", per-facility ranking text, and urgent-mode grouping.
  - `app/main.py`: `EVIDENCE_PROVIDER=evidence_confidence` (new default) routes searches through `engine.py`; health reports the package commit and a provisional note.
  - `app/backend/config.py`, `app.yaml`: new default; `EVIDENCE_TABLE` and `RANKER` settings removed from `app.yaml`.
  - `app/backend/evidence.py`: removed `TableEvidence` (gold-table plan dropped); tier labels follow Alice's definitions; the placeholder stays as a fallback and for mock mode.
  - `app/backend/services.py`: `best_tier` per service (T1 possible for C-section, obstetrics, dialysis, blood bank, emergency, stroke and eye care; T3 at most for NICU, ICU, trauma, cancer and cardiac care).
  - `app/static/*`: new legend (Alice's tiers, her R wording), service hint and results note on the best possible tier, urgent section "Nearest facilities, emergency capability not confirmed", evidence status labels.
  - `app/README.md`, `CLAUDE.md`: describe the built integration.
- **How:**
  - Ran her tests at 2368382 in a separate worktree: 193 pass, 2 skipped.
  - Tested live against `workspace.datathon`:
    - Delhi C-section within 100 km: 861 candidates, T1 1 / T2 1 / T3 3 / R 2 / U 854;
    - Patna C-section, emergency: 0 recommended, 5 T3 cards;
    - Delhi ICU within 25 km: T3 2, R 2.
    - Her adapter report was PASS in each; about 1–1.6 s per search.
  - Checked the explainer, mock mode, and Playwright screenshots (no console errors).
- **Why:**
  - The team computes evidence and ranking per request in Alice's package instead of gold tables. A Databricks App only uploads `app/`, so the package is copied in at a fixed commit.
  - Following Alice's answers:
    - emergency maps to her urgent mode;
    - capability eligibility is never invented;
    - sites are passed so their flags count;
    - service rows from empanelment and general-accreditation sites are filtered out.
  - The display only filters her order, without re-scoring or re-sorting.
- **Notes / follow-ups:**
  - Self-reported claims aren't counted (no reviewed claim-to-service matcher yet), so most facilities are U.
  - Urgent searches recommend nothing until an emergency-capability source exists.
  - Notebook 06 linked "Blood Bank, Lal Bahadur Shastri Hospital" to LBS Hospital's LaQshya certificate (a name-match issue to review in 06).
  - Not yet redeployed to Databricks.

### 2026-11-21 23:28: Test deploy of the web app as a Databricks App
- **Who:** Claude (for William)
- **What:**
  - New Databricks App `find-the-right-care` (compute MEDIUM), with resources `sql-warehouse` (Serverless Starter Warehouse, CAN_USE) and `serving-endpoint` (`databricks-meta-llama-3-3-70b-instruct`, CAN_QUERY).
  - Code uploaded to `/Workspace/Users/<William>/apps/find-the-right-care` from the `website` branch (commit 7f5b751).
  - Granted the app's service principal `USE CATALOG` on `workspace` and `USE SCHEMA, SELECT` on `workspace.datathon`.
- **How:** `databricks apps create --json` (resources attached at creation, so no UI step), `databricks sync`, GRANTs through the SQL warehouse, `databricks apps deploy`.
- **Why:** Check that the app runs on Databricks before the evidence engine is ready. Verified on the deployed URL:
  - `/api/health` reports live data;
  - a PIN lookup for 800001 works;
  - a dialysis search within 100 km of Patna returns 204 candidates (IGIMS T2 first);
  - the Llama explainer answers.
- **Notes / follow-ups:**
  - It still uses the placeholder evidence and ranking.
  - Teammates need workspace access plus *Can use* on the app to open it.
  - An app's compute runs until stopped (`databricks apps stop find-the-right-care`).
  - Added `.databricks/` (the CLI's sync state) to `.gitignore`.

### 2026-11-21 23:22: README rewritten for the no-gold-table plan
- **Who:** Claude (for William)
- **What:** In `app/README.md`, rewrote:
  - the pipeline diagram and status line;
  - "Tables the app reads today" note;
  - "What we need from each owner" items 1, 2 and 4;
  - replaced the "Plugging in the real evidence engine" and "Plugging in the real ranker" sections with "Plugging in Alice's package".
- **How:** Edited the README. No code changed.
- **Why:** The team decided against gold tables. Evidence and ranking will be computed per request by Alice's `evidence_confidence` package, so the proposed `facility_service_evidence_gold` contract and the separate ranker contract were out of date.
- **Notes / follow-ups:** `TableEvidence` and `EVIDENCE_PROVIDER=table` in the code are now obsolete; remove them when wiring in Alice's package.

### 2026-11-21 23:17: Whole pipeline verified on Databricks serverless; `setup_pipeline` facilities.csv parsing fixed
- **Who:** Claude (for Sophia)
- **What:**
  - `notebooks/setup_pipeline.py`: `facilities.csv` is now read with `escape='\'`.
  - New `scripts/databricks/`: `watch_run.ps1`, `verify_outputs.py`, `check_facilities_csv.py`.
  - New `scripts/local_spark/check_csv_reads.py`; `run_all.sh` gets a `csvcheck` option, and 03 now runs with its default `write_output=false` (as in the job).
  - `README.md`: verification on Databricks and known issues.
- **How:**
  - Sophia installed the Databricks CLI (winget, v1.27.0) and signed in with OAuth (`databricks auth login --profile datathon`).
  - Uploaded `sophia-wip`'s notebooks to `/Users/<me>/datathon_verify/` and created a test schema `workspace.datathon_verify`, with the bronze inputs copied from `workspace.datathon`. The live Git folder (`/Datathon Fall 26/CMU_Datathon_26`, on `main`), the live job and the live tables were not touched.
  - Submitted one-time serverless runs (CPU environment v5) with the same inputs as the job (the Marketplace PIN, facilities and NFHS tables).
- **Results on Databricks:**
  - **Run 69185514918504:** prep, 00, 01, 02, 03, 04, 05 and 06 all SUCCESS.
  - **Output check (run 330170087354586):** `pincode_validation` 12/12, `facilities_validation` 13/13, `nqas_validation` 8/8, `nfhs_validation` 7/7.
    - **Facilities:** 9,989 (all UUIDs, 0 bad PINs, 0 coordinates outside India); 1,603 coordinates nulled for PIN/state mismatch; 88 rejected as `INVALID_ID`.
    - **PIN offices:** 12,070 nulled as far from their PIN versus 12,009 missing.
    - **NFHS:** 705 districts.
    - **Registry links:** 4,241; 0 accepted links more than 25 km apart.
    - **Hygiene:** no staging leftovers and no `_clean` columns in silver. Will's registry bronze tables contain `state_clean` / `pincode_clean` from the scraper CSVs, which is allowed in bronze.
    - The numbers match the local runs exactly.
  - **`setup_pipeline` bug proven on the platform (run 463510234196202):** reading `facilities.csv` with the old `escape='"'` gave 10,088 rows but **9,710 non-numeric latitudes** (columns shift inside rows); with `escape='\'`, 0. Sophia's job reads the Marketplace facilities table, so it was unaffected; teammates using `setup_pipeline` were affected.
- **Why:** Sophia pointed out that the code had not been running successfully on Databricks itself and asked to make absolutely sure it runs on the actual platform.
- **Notes / follow-ups:**
  - Test folder `/Users/<me>/datathon_verify` and schema `workspace.datathon_verify` are left in place for inspection; they can be dropped later.
  - `run_pipeline.py` still can't orchestrate on serverless notebook compute; the Lakeflow Job is the runner.
  - Teammates who already built `workspace.datathon.facilities` with the old `setup_pipeline` should drop it and re-run setup.

### 2026-11-21 23:15: README: planned integration with Alice's evidence engine
- **Who:** Claude (for William)
- **What:** Added "Planned integration with Alice's evidence engine" to `app/README.md`. It covers:
  - the call sequence per search;
  - the rows her adapters need, checked against the live table schemas (`DESCRIBE` on the workspace tables);
  - how her tier rules differ from the placeholder's;
  - 10 open questions for Alice.
- **How:** Read `origin/alice-evidence-confidence` (commit 9962ceb: `evidence_confidence/`, `docs/evidence-confidence-integration.md`, `TIERS.md`) read-only; described the workspace tables through the SQL warehouse. No code changed.
- **Why:** The team decided against gold tables. Evidence and ranking will run per request through Alice's Python package, so the app needs an agreed call sequence and answers to the open questions before wiring it in.
- **Notes / follow-ups:** `kayakalp_silver` isn't in the workspace (only `kayakalp_silver_validation`); no NQAS-to-facility link exists; nothing yet produces the reviewed service and yes/no for claims, or `capability_eligible`.

### 2026-11-21 22:58: Project README; merged `main` (PR #15) into `sophia-wip`, keeping the verified notebook 01
- **Who:** Claude (for Sophia)
- **What:**
  - New `README.md`: purpose, pipeline order and tables, Databricks setup (`setup_pipeline` → the "CMU Datathon pipeline 00-06" job), the data-honesty approach, sources, repo layout, local verification, contributing rules and known issues.
  - Merge of `main` (PR #15 "pipeline-fixes": `setup_pipeline.py`, notebook 02 ISO-date fix, notebook 03 validation-mode fix, GPU env headers removed) into `sophia-wip`.
- **How:**
  - Surveyed every tracked file, read the notebook headers, scrapers, docs and the new DEVLOG entries, then checked the README's table, branch and job names against the code.
  - **`DEVLOG.md` merge:** union of both sides' entries, newest first.
  - **Notebook 01 merge:** kept `sophia-wip`'s verified version and removed its `databricks_ai_v6` GPU environment header, which was PR #15's actual fix for 01. PR #15's "notebook 01 merge resolution" had replaced 01 with an older version: `_clean` column names, no bronze validation, no coordinate-vs-PIN/state check, and the pre-fix `least()` distance (the 20,015 km bug). Its `F.col` fix and spot-check cell were already in the verified version.
  - Also removed the same GPU header from `run_pipeline.py`.
- **Why:** Sophia asked for a project README based on the current state of the repo. Writing it surfaced the notebook 01 regression on `main`.
- **Notes / follow-ups (also in the README's Known issues):**
  - **Restore the verified notebook 01 on `main`.** Elliot's `pin_nearby_facilities` expects the plain column names and won't run against `main`'s version.
  - Move `notebooks/common/pin_nearby_facilities` to `notebooks/07_pin_nearby_facilities.py` (no `.py` extension, and the wrong relative `%run` path).
  - `docs/kayakalp-silver-audit.md` is referenced by the Kayakalp handoff doc but missing.
  - `run_pipeline.py` can't orchestrate on serverless notebook compute; the Lakeflow Job is the runner on Free Edition.

### 2026-11-21 22:55: setup_pipeline.py for teammates; notebook 03 validation-mode fix
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/setup_pipeline.py`: one-run Databricks setup for teammates. Auto-detects the repo Git folder, creates schema `workspace.datathon` and the bronze tables (`nqas_certified_facilities`, `kayakalp_bronze`, the 9 registry `*_bronze` tables, `facilities`) as all-text from the repo CSVs when missing, then creates or updates the "CMU Datathon pipeline 00-06" job (00 to 06 sequential, serverless, CPU environment v5; steps 00/04 read the repo CSVs, step 01 reads the created `facilities` table, step 05 runs with `reload_bronze=no`). Job operations go through raw REST (`w.api_client.do`) because this workspace's SDK rejects dict arguments for `environments`; validated with a create/list/update smoke test.
  - `notebooks/03_kayakalp_bronze_to_silver.py`: the check/display cells now query the temp view `kayakalp_validation_result` instead of `{SILVER}`. In validation mode (`write_output=false`, the job default) the silver table is never written, so `FROM {SILVER}` crashed step 03 of run 270846421127289 with TABLE_OR_VIEW_NOT_FOUND. The view exists in both modes and is identical to the table in write mode.
- **How:** exact-match patches verified with syntax checks; notebook 02's earlier fix proved out in the repair run (step 02 green).
- **Why:** Sophia asked how friends can pull the updates and set up the pipeline in Databricks.
- **Notes:** teammates run the job, not `run_pipeline.py`, on serverless. Leftover smoke-test job 207585649559027 should be deleted from the Jobs UI.

### 2026-11-21 22:50: Notebook 02 date validation accepts ISO text from the DATE-typed bronze
- **Who:** Claude (for Sophia)
- **What:** `date_differs` in `notebooks/02_nqas_bronze_to_silver.py` now accepts both d-m-yyyy text (the site's format, as in the repo CSV) and ISO yyyy-mm-dd (what the DATE-typed `nqas_certified_facilities` columns render as when cast to string); rows whose text matches neither layout are listed as validation failures instead of crashing on `''` → INT casts.
- **How:** job run 270846421127289 failed at step 02 with CAST_INVALID_INPUT. The bronze table was uploaded with type inference (dates became DATE columns), so the d-m-yyyy-only regexp no longer matched. Sophia chose to keep the DATE-typed table, so the notebook now handles both layouts. `parse_date` already handled ISO, so only `date_differs` needed the fix.
- **Why:** keep the bronze table as uploaded; the same notebook must run against the local harness's text CSVs and the workspace's typed table.
- **Notes / follow-ups:** fix committed on branch `pipeline-fixes`.

### 2026-11-21 22:40: Team section in app/README.md; new `website` branch
- **Who:** Claude (for William)
- **What:** Added "For the team" section to `app/README.md` (request flow, tables read today, what is needed from the evidence, ranking, geography and job owners). Created branch `website` from `Will_branch` (uncommitted work carried over).
- **How:** Edited the README; `git checkout -b website`.
- **Why:** Teammates need to know which tables the app reads, that no gold table is used yet, and which contracts (evidence table, ranker) are unagreed proposals.

### 2026-11-21 22:35: Pipeline as a Lakeflow Job; missing bronze inputs created; GPU env headers removed
- **Who:** Claude (for Sophia)
- **What:**
  - New job `CMU Datathon pipeline 00-06` (id 448999964395839): notebooks 00–06 as sequential tasks (00 → 01 → … → 06) on serverless job compute. This replaces `run_pipeline`'s `dbutils.notebook.run` calls, which cannot run from this workspace's serverless notebook compute ("NOT_FOUND: Cluster … does not exist").
  - Job parameters: 00 and 04 read the shared UC tables (`…dais_2026.virtue_foundation_dataset.india_post_pincode_directory` and `.nfhs_5_district_health_indicators`) because their volume widget defaults don't exist; 03 gets `bronze_table=kayakalp_bronze`; 05 runs with `reload_bronze=no` (uses existing bronze tables).
  - Created `workspace.datathon.kayakalp_bronze` (1,197 rows) from `data/external/kayakalp_2021_22.csv`.
  - Created the 9 registry bronze tables (laqshya ×2, trauma, nmc ×2, dnb ×2, ncg, nabh) from the `datasets/external/**` CSVs, all-string columns plus `_ingested_at`/`_source_file`, matching notebook 05's loader.
  - Removed the `# /// script` environment headers (`base_environment = "databricks_ai_v6"`, a GPU environment) from notebooks 00, 01, 02, 04; staged in git.
- **How:** job created and configured via the Jobs API (7 sequential tasks, 60-min timeout each); bronze tables loaded with Spark CSV reads (all-string, same read options as the notebooks' loaders); headers removed with an exact-match patch script; then a job-level `environment_key` ("default", CPU environment version 5) was added to all 7 tasks.
- **Why:** Sophia asked for a script that runs all pipeline code sequentially. The first two job runs failed instantly with "The selected GPU base environment is incompatible with the selected accelerator (CPU)": the notebooks' environment setting persists server-side (Environment panel), so removing the source headers alone wasn't enough — the job-level CPU environment on every task overrides it, and the third run is executing.
- **Notes / follow-ups:** step 03 runs in validation mode by default (`write_output=false`), so it does not create `kayakalp_silver`; create that separately if analysis needs it. `run_pipeline` stays for reference but can't orchestrate on serverless notebook compute.

### 2026-11-21 22:26: "Find the Right Care" web app with placeholder evidence and ranking
- **Who:** Claude (for William)
- **What:**
  - New `app/` folder:
    - FastAPI backend: `main.py`, `backend/{config,db,services,geography,evidence,ranking,explain,mock}.py`;
    - one web page: `static/index.html`, `styles.css`, `app.js`;
    - `app.yaml` (Databricks App config), `requirements.txt`, and `README.md` (how to run and deploy, plus the plug-in contracts).
  - `CLAUDE.md` layout line added.
  - In William's workspace: ran Elliot's `07_pin_nearby_facilities` (from main, `notebooks/common/pin_nearby_facilities`) once to build `facility_geo_ready`. The copy was placed at `pipeline_check/notebooks/07_pin_nearby_facilities`, because its `%run ./common/...` paths only resolve from `notebooks/`.
- **How:**
  - The request flow follows the team's end-to-end diagram: geography (Elliot's search, ported to SQL) → evidence (LEFT JOIN; no evidence = U) → rank the full set → only then pick the top 5 + alternatives → optional AI explainer.
  - **Evidence and ranking are plug-in points:**
    - `EVIDENCE_PROVIDER=placeholder|table` (the table contract is in the README);
    - the placeholder ranker scores evidence tier minus distance minus location uncertainty.
  - **AI explainer:** `databricks-meta-llama-3-3-70b-instruct`, grounded in the cited evidence only, with a template fallback.
  - **Tests:**
    - Mock mode with FastAPI's TestClient.
    - Live mode against `workspace.datathon` through the CLI profile: Delhi 110001 (737 candidates) and Patna 800001; about 1.5–3.5 s per search.
    - Screenshots of desktop and mobile with headless Chromium (Playwright, in a scratchpad virtualenv; browser cached in `~/Library/Caches/ms-playwright`). No console errors.
  - **Bugs fixed during testing:**
    - Array columns come back as JSON text without pyarrow, so they were being split into characters (`db.as_list`).
    - The candidate cap was raised from 500 to 5,000, so evidence is added before anything is cut.
    - On mobile, the emergency notice moved above the form, and the banner margins were fixed.
- **Why:** William asked for a website that uses the team's Databricks pipeline. The model and scoring belong to teammates, so the app defines their interfaces and runs on placeholders until their parts exist. The page shows "Provisional results" while any placeholder is active. Design aims: calm and trustworthy, accessible type, tiers shown as text as well as colour, honest uncertainty (straight-line distance, location certainty per facility, "call ahead" on every card, 112/108 for emergencies).
- **Notes / follow-ups:**
  - Needs from teammates: the evidence table (contract in `app/README.md`), the tier definitions, and a ranker.
  - Not yet deployed as a Databricks App (steps in the README; the app's service principal needs `SELECT` on `workspace.datathon` and use of the SQL warehouse and serving endpoint).
  - The placeholder's keyword matching over facility claims is loose (e.g. an eye centre matched "C-section"); it's only for the demo.
  - For Elliot: `notebooks/common/pin_nearby_facilities` should probably live at `notebooks/07_pin_nearby_facilities`, since its `%run ./common/...` lines fail from inside `common/`.

### 2026-11-21 22:18: PR #14 merged: pipeline runner and NFHS notebook 04 are on `main`
- **Who:** Sophia (approved), Claude (merged)
- **What:**
  - PR #14 (`nfhs-04` → `main`) merged as `c710c57`, adding `notebooks/run_pipeline.py`, `notebooks/04_nfhs_bronze_to_silver.py` and the local-harness updates.
  - `main` merged back into `sophia-wip`.
  - Remote branch `nfhs-04` deleted.
- **How:** `gh pr merge 14 --merge --match-head-commit 6297016` (only if the head was still the reviewed commit).
- **Why:** Sophia approved the merge.
- **Notes / follow-ups:**
  - `main` and `sophia-wip` now differ only by the two unverified Databricks files, plus this entry until the next sync.
  - **Next, on Databricks:**
    1. Pull `main`.
    2. Upload `nfhs_5_district_health_indicators.csv` to `/Volumes/workspace/datathon/external/`.
    3. Run `run_pipeline`.

### 2026-11-21 22:17: Pipeline runner added to PR #14; runner docs completed
- **Who:** Claude (for Sophia)
- **What:**
  - PR #14 (branch `nfhs-04`) now also carries `notebooks/run_pipeline.py` and the local-harness updates (`nbrun.py`, `run_all.sh`, `show_pipeline_log.sh`, `test_pipeline_failure.sh`, `README.md`), plus `CLAUDE.md` and `DEVLOG.md`.
  - `scripts/local_spark/README.md`: added the `pipeline` / failure-test / log commands, which were missing because an earlier scripted edit skipped this file.
- **How:** copied those files from `sophia-wip` onto `nfhs-04` (in a separate worktree) and pushed. The branch equals `sophia-wip` except for the two unverified Databricks files, which stay on `sophia-wip` only.
- **Why:** Sophia chose to ship the runner together with the NFHS notebook it calls (step 04), so `main` gets both at once.

### 2026-11-21 22:14: Pipeline runner `notebooks/run_pipeline.py` (00 → 06 with a run log)
- **Who:** Claude (for Sophia)
- **What:**
  - New `notebooks/run_pipeline.py`.
  - Local harness: `scripts/local_spark/nbrun.py` (adds `dbutils.notebook.run`; command-line widgets now flow to child notebooks), `run_all.sh` (`pipeline` option), and new `test_pipeline_failure.sh` and `show_pipeline_log.sh`.
  - Docs: `CLAUDE.md`, `scripts/local_spark/README.md`.
  - New table `pipeline_run_log`.
- **How:**
  - Runs 00, 01, 02, 03, 04, 05, 06 in order with `dbutils.notebook.run`, passing `catalog` / `schema` (plus `target_*` for 01).
  - **Dependencies:** 00 → 01, 02, 04, 05; 01 + 05 → 06; 03 is independent. A failed step marks the steps that depend on it `SKIPPED`; the other steps still run. Optional `stop_on_failure` stops everything after the first failure.
  - **Run log:** each step appends a row to `pipeline_run_log`: `run_id`, `step`, `notebook`, `status` (OK / FAILED / SKIPPED / MISSING), `seconds`, `error` (Databricks' message), and `failed_checks` from that step's `<dataset>_validation` table during the run.
  - **End of run:** prints a summary, then raises if any step failed, so a scheduled job turns red.
  - **Inputs:** optional widgets `pincode_source`, `facilities_source_table` and `nfhs_source`, because 00 and 04 both name their input widget `source`. Blank means each notebook's own default.
- **Why:** Sophia asked for a script that runs 00 → 06 in sequence and logs what breaks.
- **Local tests:**
  - **Clean run:** all 7 steps OK in ~4 min.
  - **Forced failure** (`test_pipeline_failure.sh`: missing input file for 00): 00 FAILED with `[PATH_NOT_FOUND] Path does not exist: …`; 01, 02, 04, 05 and 06 SKIPPED with the reason; 03 OK; the run ends red.
  - **Fixed during testing:** a missing data file was first mislabelled MISSING (that status now means only "notebook not found").
- **Notes / follow-ups:**
  - `03_kayakalp` runs in validation-only mode under the runner (`write_output` defaults to false), as it does when opened directly.
  - The runner needs `04_nfhs_bronze_to_silver.py`, which is on `main` only after PR #14 merges; until then step 04 shows MISSING on `main`.
  - Not yet run on Databricks.

### 2026-11-21 22:01: Pipeline check re-run on main's verified pipeline (00 → 01 + 05 → 06, plus 02 and 03)
- **Who:** Claude (for William)
- **What:**
  - Job 413468616877500 updated to "Pipeline check: 00 -> 01 + 05 -> 06, plus 02 and 03". It uses unchanged copies of `Will_branch` `427dc75` (main + 2 commits), with notebook 02 also depending on 00.
  - Dropped `kayakalp_silver_validation` beforehand (notebook 03 is create-only).
  - Run 253038959423039: 00, 02, 03 and 05 succeeded.
  - **Notebook 01 failed:** `InvalidRunConfiguration: The selected GPU base environment is incompatible with the selected accelerator (CPU)`. Its file starts with a `# /// script … base_environment = "databricks_ai_v6" … # ///` header, from commit `4297f3c`. That's a GPU environment, while serverless jobs run on CPU.
  - Fix, **in the workspace copy only:** deleted notebook 01 and re-imported it without those 5 lines. Overwriting in place wasn't enough: the environment recorded at first import stayed. Then repaired 01 and 06, which **succeeded**.
- **How:**
  - `workspace delete` + `workspace import` (new object, no environment metadata, checked by a Jupyter export).
  - `jobs repair-run` with `latest_repair_id`: a second repair is silently not created without it.
  - Counts checked with the SQL Statements API.
- **Results, with the previous run (patched old main) for comparison:**
  - `facilities_silver` 9,989 (=). **Facilities with coordinates: 8,350**. Main's notebook 01 now nulls coordinates that don't match the PIN: 1,598 `nulled_pin_mismatch`, 5 `nulled_state_mismatch`.
  - `pincode_*`, `registry_*`, `nqas_silver` (989) and `kayakalp_silver_validation` (1,197) all unchanged.
  - **Links:** 4,241 (was 4,482). Needing review: 1,154 (was 1,444). Confident: 3,087 (was 3,038).
  - Facilities in at least one registry: 2,639 (was 2,745).
  - Confident evidence: C-section 118 (114), trauma 130 (126), cancer 98 (90), dialysis 37 (36), blood bank 21 (19), NICU 4 (4).
  - Teammates' validation tables written and passed: `facilities_validation`, `pincode_validation`, `nqas_validation`.
- **Why:** Main now has Sophia's verified pipeline, with both reported bugs fixed and the PIN notebook renamed 04 → 00. William wanted the job verified on the current code. Reading the change: with bad facility coordinates removed, fewer pairs qualify on distance, so there are fewer links overall. But fewer links get flagged "more than 10 km apart", so more of them are confident.
- **Notes for Sophia:**
  - Remove the `# /// script … # ///` header (lines 2–6) from `notebooks/01_bronze_to_silver.py`. It makes notebook 01 fail in any serverless or CPU job.
  - Databricks adds this header when the notebook is exported or committed from a workspace where the AI/GPU environment was selected.

### 2026-11-21 21:31: Notebooks 02 (NQAS) and 03 (Kayakalp) added to the Databricks pipeline check
- **Who:** Claude (for William)
- **What:**
  - Uploaded `data/external/nqas_certified_facilities.csv` and `kayakalp_2021_22.csv` to the Volume, and created `workspace.datathon.nqas_bronze` (989 rows) and `kayakalp_bronze` (1,197 rows), all text columns, as `scripts/README.md` describes.
  - Added unchanged copies of notebooks 02 and 03 to `/Users/<William>/pipeline_check/notebooks/`.
  - Job 413468616877500 renamed "Pipeline check: 04 -> 01 + 05 -> 06, plus 02 and 03", with tasks `nb02_nqas` and `nb03_kayakalp` running in parallel with the main chain.
  - Run 183485095627632: **all 6 tasks succeeded** (about 5 minutes).
- **How:**
  - Bronze tables built with `read_files(…, format => 'csv', header => true, inferColumnTypes => false)` through the SQL Statements API.
  - Job updated with `databricks jobs reset`, then `jobs run-now`.
- **Results:**
  - `nqas_silver` 989 (all `expired`, as documented; 1 with an unrecognized state).
  - `kayakalp_silver_validation` 1,197 (equal to bronze, Alice's check).
  - Registry and link tables unchanged (4,482 links).
- **Why:** William wanted every notebook so far checked on Databricks.
- **Notes for teammates:**
  - **Notebook 03 (Alice):**
    - With `write_output = true` it creates `kayakalp_silver_validation` and refuses to run if that table already exists, so the job's next **Run now** will fail at `nb03` unless that table is dropped first. That's intended on her side; the job description says so.
    - With the default `write_output = false`, the first and last check cells query `FROM {SILVER}`, a table never created in that mode. They should probably read the temp view `kayakalp_validation_result`, as the middle check does.
  - **Naming:** the Kayakalp output is now `kayakalp_silver_validation`, not the `kayakalp_silver` that `docs/data-sources.md` and the scripts README mention.

### 2026-11-21 21:15: Full pipeline verified on Databricks (04 → 01 → 05 → 06)
- **Who:** Claude (for William)
- **What:**
  - Created the saved Databricks job **"Registry pipeline check (04 -> 01 -> 05 -> 06)"** (job ID 413468616877500) in William's workspace. It runs notebooks from `/Users/<William>/pipeline_check/notebooks/`, a copy of `Will_branch` (`f0c78e2`) plus `common/`.
  - **One change in that copy only:** `01_bronze_to_silver` line 753 calls `haversine_km(F.col("latitude_a"), …)` instead of passing strings. That's the same fix as on `sophia-wip`. The repo is unchanged; William is telling Sophia.
  - Run 1017643203247717: all 4 tasks succeeded in about 5 minutes on serverless.
- **How:**
  - `databricks workspace import-dir`, `jobs create` (04 first; 01 and 05 in parallel after it; 06 after both), `jobs run-now`.
  - Counts checked with the SQL Statements API.
- **Results** (identical to the local test):
  - `facilities_silver` 9,989; `silver_facility_claims` 549,841
  - `pincode_silver` 165,625; `pincode_centroids_silver` 19,586
  - `registry_sites_silver` 24,961; `registry_services_silver` 22,757
  - `facility_registry_links_silver` 4,482; `facility_registry_summary_silver` 9,989; `registry_match_review` 1,444
  - Facilities in at least one registry: 2,745. Confident evidence: C-section 114, trauma 126, cancer 90, dialysis 36, blood bank 19, NICU 4.
  - Registry sites now have PIN locations (e.g. 16,675 / 21,480 NABH sites).
- **Why:** William wanted to check that everything so far runs end to end on Databricks, not just locally. The job is kept so it can be re-run from **Jobs & Pipelines → Run now**.
- **Notes / follow-ups:**
  - Once Sophia's notebook 01 fix reaches main, re-upload or point the job at the Git folder, so it no longer uses the patched copy.
  - Notebooks 02 (NQAS) and 03 (Kayakalp) aren't in the job yet; they need `nqas_bronze` and `kayakalp_bronze` loaded first.

### 2026-11-21 21:05: NFHS notebook fixed and fitted into the pipeline as `04_nfhs_bronze_to_silver.py`
- **Who:** Claude (for Sophia; notebook written by elliotl-ops)
- **What:**
  - `notebooks/NFHS_Bronze_to_Silver.py` renamed with `git mv` to `notebooks/04_nfhs_bronze_to_silver.py` and edited.
  - `scripts/local_spark/run_all.sh` (runs it as `04`) and new `scripts/local_spark/audit_nfhs.py`.
  - `CLAUDE.md` (run order, layout) and `docs/data-sources.md` (NFHS entry).
- **How:** applied the four suggested fixes; Elliot's cleaning rules, quality report, gate, history, quarantine, copied-row detection and quality view are kept as written.
  1. **Locations:** widgets `catalog` / `schema` / `source` (defaults `workspace.datathon` and `/Volumes/workspace/datathon/external/nfhs_5_district_health_indicators.csv`) replace the candidate-path lists.
  2. **Numbers:** whole numbers may be written `882.0` (pattern `^\d+(\.0+)?$`, cast via double to int).
  3. **Caching:** `df.cache()` / `unpersist()` replaced by a staging table `_nfhs_stage`, dropped at the end.
  4. **Pipeline conventions:**
     - Notebook format with `%run` of the common helpers.
     - Tables `nfhs_bronze` (raw copy of the whole file), `nfhs_silver`, `nfhs_quarantine`, `nfhs_quality_history` and the view `nfhs_quality_current`.
     - `nfhs_validation` with 7 checks against bronze, run before writing.
     - Citation columns plus `row_citation`.
     - Writes go through `write_table()`, which blocks any `_clean` column.
     - New columns `state` (standardized, for joins), `district_join_key` and `district_in_pin_directory` (optional check against `pincode_silver`).
  - Also: `OPTIMIZE` / `ANALYZE` made best-effort. `ANALYZE … FOR ALL COLUMNS` isn't supported by open-source Delta, and it's housekeeping on a ~700-row table.
  - Correction to my earlier claim: Elliot's PR #11 version already read the columns by name, so the column-order bug was already fixed there.
- **Why:** Sophia asked to apply the fixes so the NFHS notebook works in the shared pipeline.
- **Local run** (`run_all.sh 04` on `data/raw/nfhs_5_district_health_indicators.csv`):
  - **Runs end to end.** Elliot's quality gate passes and all 7 validation checks pass.
  - **Rows:** 706 bronze rows → 705 silver plus 1 quarantined (Mizoram "Chandel").
  - **Values:** sex ratios 755–1,332 (at birth 658–1,485), percentages 16–100.
  - **Flags:** 8 districts are low-sample, 2 have estimates, and 36 state names were fixed (Maharastra).
  - **Directory match:** 613 of 705 districts match the India Post directory; the rest are mostly spelling variants (e.g. Koch Bihar / Cooch Behar), flagged only.
- **Notes / follow-ups:**
  - Upload the CSV to `/Volumes/workspace/datathon/external/` before running on Databricks.
  - `nfhs_silver` keeps Elliot's 8 indicators; the other ~99 indicators are only in `nfhs_bronze`.
  - Elliot should know his file was renamed and adapted.
  - Not on `main` yet.

### 2026-11-21 20:58: Re-checked Elliot's updated NFHS notebook (PR #11): still fails
- **Who:** Claude (for Sophia)
- **What:**
  - Merged `main` (PR #11, `a0033bc` "Update NFHS_Bronze_to_Silver.py") into `sophia-wip`.
  - `scripts/local_spark/run_all.sh`: two NFHS runs, `nfhs_asis` (unchanged notebook) and `nfhs` (repo data and local schema added to its candidate lists, as its own comment suggests).
- **How:** local Spark run (see the 20:44 entry).
- **Results:**
  - **`nfhs_asis`:** stops at once with `ValueError: No readable bronze source found`. Its inputs are `/Volumes/main/default/bronze_data/NFR.csv`, `dbfs:/FileStore/tables/NFR.csv` and Elliot's personal upload, and none exist outside his workspace. Its output targets (`main.default`, `labuser_elliotl.silver`) don't exist in a Free Edition workspace either, where the catalog is `workspace`, so it would then stop with "No usable (catalog, schema) target".
  - **`nfhs` (repo file `data/raw/nfhs_5_district_health_indicators.csv`):** its quality gate fails with 706/706 rows unparseable and 706/706 rows with a NULL indicator. The parsing logic didn't change: counts written like `882.0` fail its `^\d+$` pattern.
- **Why:** Sophia asked to check whether the newly pulled NFHS notebook works.
- **Suggested fixes for Elliot (not applied; it's his notebook):**
  1. Add `/Volumes/workspace/datathon/external/nfhs_5_district_health_indicators.csv` (or a `source` widget) to the inputs and `("workspace", "datathon")` to the targets.
  2. Accept whole numbers written as `882.0`: pattern `^\d+(\.0+)?$`, cast via double to int.
  3. Drop `df.cache()` (may not be supported on serverless).
  4. Follow the pipeline conventions: number it `04`, write `nfhs_*` tables, and add a `<dataset>_validation` check and citation columns.
- **Notes / follow-ups:** `main` and `sophia-wip` still differ only by the two unverified Databricks files and recent DEVLOG entries.

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

### 2026-11-21 19:51: Started modular Evidence Confidence baseline (Alice)
- **Who:** Codex (for Alice).
- **What:** new isolated `alice-evidence-confidence` worktree from `origin/main` b5aba4d; additive `evidence_confidence/`, `config/evidence-confidence.json`, focused unit tests/examples and integration documentation. No teammate notebooks, datasets or Silver contracts edited.
- **How:** inspected current main, William registry normalization/matching at ab113d7, Sophia NQAS/Kayakalp and Elliot PIN/location contracts, plus the local Kayakalp audit. Pure standard-library scoring with explicit source/match/recency weights, bounded lineage-aware agreement, contradictions, scoped service vs quality/cleanliness/identity outputs, citations and fail-closed adapters. No Databricks execution or writes.
- **Why:** provide a runnable, interpretable policy baseline while upstream schemas evolve; no calibrated-probability, current clinical-safety or missing-means-absent claims. Canonical matches and service assertions remain explicit upstream inputs. No commits, merges, pushes or shared-resource changes.
- **Validation:** 57 focused tests passed on Python 3.10.4; 10 synthetic scenarios serialized/executed with default and file-loaded policy; 5 existing address and 12 coordinate parser cases passed; compile and whitespace checks passed. No live scoring deployment, probability calibration or clinical validation claimed; integration needs are in `docs/evidence-confidence.md`.

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
