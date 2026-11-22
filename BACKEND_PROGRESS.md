# Backend progress

## Checkpoint 1 — 2026-11-22 (attempt 1, non-interactive)

Blocked from running Python/pytest and reading `/private/tmp`. Added `recommend_facilities(...)`
(cached bundle), two wrapper tests, website and Elliot handoff notes in `docs/recommendation-pipeline.md`.
Nothing executed.

## Checkpoint 2 — 2026-11-22 (interactive session)

**Phase 1 (inspect):** worktree `/Users/jihyun/Desktop/cmu/F26/datathon/evidence-confidence`, branch
`alice-evidence-confidence`, all uncommitted work preserved. `recommend_facilities` (pipeline.py:241)
and the two wrapper tests exist and are correct; nothing rewritten.

**Phase 2 (Elliot, read-only):** `origin/Elliot_New_Branch` @ `385b0db`; 07 notebook sha256
`848f182e…` = the version validated locally; `notebooks/common/validation.py` identical. Committed HEAD
merges cleanly. Uncommitted edits: `run_pipeline.py` merges cleanly; `setup_pipeline.py` has 1 conflicting
hunk. Resolution prepared in the scratchpad (`mergesim2/setup_pipeline.py.resolved`), keeping
`step_06_matching → step_07_nearby → validate_silver` and the Kayakalp params. Not merged.
No hard-coded obsolete notebook path in active code (only `default_notebook()` fallback / test LEGACY).

**Phases 3–6, 8–9 (real data, `recommend_facilities`, Elliot's 07 notebook):**

| Query (50 km) | Geo cands | After join = ranked | Tiers | Rec / Alt | Dupes | Cited non-U |
|---|---|---|---|---|---|---|
| 110001 C-section | 749 | 749 | T1 1, T2 1, T3 46, R 2, U 699 | 5 / 5 | 0 | 10/10 |
| 110001 dialysis | 749 | 749 | T3 53, R 2, U 694 | 5 / 5 | 0 | 10/10 |
| 400001 dialysis | 700 | 700 | T1 1, T3 56, R 2, U 641 | 5 / 5 | 0 | 10/10 |
| 600001 C-section | 347 | 347 | T3 18, R 3, U 326 | 5 / 5 | 0 | 10/10 |

Deterministic (repeat call and shuffled `ready` order give identical JSON); JSON-safe; 400001 dialysis
identical to the saved reference (no differing keys). First call 4.5 s (bundle load), cached call 0.35 s.
Artifacts: `backend_logs/validation/recommend_*.json` (real Silver-derived; do not commit or publish).

**Phase 7 (website, read-only):** `origin/website` @ `35cb789` vendors commit `2368382` (no
`recommend_facilities`). Old radius rule confirmed; it drops 12/12/3/2 PIN-centroid candidates for the four
queries. Selection policy differs (`engine.shape`). Documented in `docs/recommendation-pipeline.md`.

**Tests:** before: 247 run, 246 pass, 1 error (`test_kayakalp` import: pdfplumber missing).
After the approved `python3 -m pip install pdfplumber`: `python3 -m unittest discover -s tests` → 249 run,
248 pass, 0 failures, 0 skips, 1 error = `test_kayakalp.SparkTests.setUpClass`: `No module named 'pyspark'`
(local Spark test of the Kayakalp notebook; needs pyspark + Java; unrelated to the backend). pytest not installed.
`compileall` and `git diff --check` pass.

**Files changed this session:** `docs/recommendation-pipeline.md` (merge facts, re-measured website
loss), `BACKEND_PROGRESS.md`, `DEVLOG.md`.

**Remaining / next action**
1. pdfplumber installed (approved). Optional: pyspark (+ Java) to run the Kayakalp Spark test.
2. Approval needed: commit this branch → merge `origin/Elliot_New_Branch` → apply the `setup_pipeline.py`
   resolution → rerun tests.
3. Website owner: uncertainty radius rule; re-vendor at the new commit; choose selection policy.
