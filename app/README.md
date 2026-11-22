# Find the Right Care: web app

A FastAPI app with one web page, built to run as a **Databricks App** on top of the team's pipeline tables in `workspace.datathon`.

```
 User: service + PIN + radius + urgency
        │
        ▼
 1. Geography (Elliot)      pincode_centroids_silver → facility_geo_ready → every facility in the radius   backend/geography.py
 2. Evidence rows           links, sites and service rows for those facilities (one service)             backend/engine.py
 3. Tier + rank (Alice)     evidence_confidence: adapt_registry_tables() + build_recommendation_response()   evidence_confidence/ (vendored)
                            tiers, LEFT JOIN (no evidence = tier U), ranks the full set; per request, no gold table
 4. Then select top 3–5 + nearby alternatives
 5. Optional AI explainer (Databricks Foundation Model, grounded in the evidence)                         backend/explain.py
```

**Status:** geography (Elliot's search) and evidence + ranking (Alice's `evidence_confidence` package, commit in `EVIDENCE_CONFIDENCE_VERSION`) are both real. Tiers use **registry records only** for now: facilities' own claims aren't counted until a reviewed claim-to-service matcher exists. Alice's ranking settings are provisional, so the page keeps a "Provisional results" banner. The old placeholder evidence and ranker remain as a fallback (`EVIDENCE_PROVIDER=placeholder`, and always in mock mode).

## For the team: how the app uses the pipeline, and what we need from you

**Request flow** (one `POST /api/recommend`): PIN lookup → every facility in the radius → evidence per facility (LEFT JOIN, missing = tier U) → rank the **whole** set → only then take the top 5 and the alternatives. This follows the end-to-end pipeline diagram. Each step is its own module in `backend/`, so a step can be replaced without touching the others.

### Tables the app reads today
| Step | Table | Made by | Used for |
|---|---|---|---|
| PIN lookup | `pincode_centroids_silver` | notebook 00 | Validate the PIN, find its centre |
| Candidate search | `facility_geo_ready` | Elliot, `07_pin_nearby_facilities` Part A | Facilities within the radius, with location certainty |
| Evidence (Alice's package) | `facility_registry_links_silver`, `registry_sites_silver`, `registry_services_silver` | notebooks 06, 05 | Registry links, sites and service listings |
| Placeholder fallback only | `silver_facility_claims` | notebook 01 | Facility's own claims |

The team decided **not to use gold tables**: tiers and ranking are computed per request from these silver tables by Alice's package.

### What we need from each owner
1. **Alice / team (evidence and ranking).** An owner for the reviewed claim-to-service matcher, and a source for emergency capability (see "Updating Alice's package" below). Her tier definitions (`evidence_confidence/TIERS.md`) are what the page legend shows.
2. **Team (service vocabulary).** Confirm the service tags. `backend/services.py` currently has: dialysis, emergency C-section, NICU, trauma, emergency, ICU, cancer care, cardiac care, stroke care, blood bank, obstetrics, eye care. They must match `registry_services_silver.service` exactly.
3. **Elliot.** `facility_geo_ready` currently exists in the workspace only because it was created by hand from his notebook. Please add that notebook to the saved job so a fresh run creates it. Also, it lives in `notebooks/common/` but uses `%run ./common/...`, which only works from `notebooks/`.
4. **Whoever owns the job.** Keep `facility_registry_links_silver` and `registry_services_silver` in the job (notebooks 05 and 06), since the app reads them on every search.

### How the AI explainer fits
The optional "Explain in plain language" button sends only the facility's own cited evidence to a Databricks Foundation Model endpoint (Llama 3.3 70B) and shows 2–3 sentences. If the call fails, it falls back to a template. It never adds facts that aren't in the evidence.

## Integration with Alice's evidence engine (`alice-evidence-confidence`)

**Status:** built (`backend/engine.py`). Alice's package is copied unchanged into `app/evidence_confidence/` at the commit recorded in `app/EVIDENCE_CONFIDENCE_VERSION` (a Databricks App only uploads its own folder). The app imports it and never edits it. Her answers to the questions below are reflected in the code; the questions stay listed for the record.

### Call sequence per search
1. **Candidates:** every facility within the radius of the PIN, from Elliot's `facility_geo_ready`. There's no service filter or top-k, so facilities with no evidence stay in as tier U. Each candidate carries `facility_id`, `name`, `distance_km`, `geo_confidence`, `location_basis` and `location_uncertainty_km`.
2. **Evidence:** query `facility_registry_links_silver` for those facility IDs, then `registry_services_silver` for the linked `site_id`s, **filtered to the requested service**.
3. **Conversion:** Alice's `silver.adapt_registry_tables()` turns the links, sites and service rows into Evidence records, keeping pending and rejected links. Following her advice, service rows from sites in empanelment or general-accreditation categories (`NON_SERVICE_CATEGORIES`) are dropped first: they can't support a tier, and her adapter rejects them when the site is passed. Passing the site keeps site-level flags (possible duplicates, head offices), some of which correctly push a facility to R.
4. **Her function:** `build_recommendation_response(request, records, candidates)` assigns tiers, LEFT JOINs them to every candidate and ranks the whole set.
5. **Display** (`engine.shape()`): the app reshapes the `recommendation-response/1` JSON for the page without re-scoring or re-sorting:
   - **Routine:** the first 5 facilities in her order with T1–T3 are recommended. The alternatives table lists the rest in her order, facilities with some evidence (R, X) first, then the nearest unknowns.
   - **Urgent and emergency** (both map to her `urgent` mode): she recommends only T1 facilities with a confirmed emergency-capability record, which no source supplies yet, so nothing is recommended. Her alternatives (distance order) with T1–T3 evidence are shown as cards under "Nearest facilities, emergency capability not confirmed". Emergency also shows the 112/108 notice.
   - Her auditor-style explanations are translated into plain-language warnings (`EXPLANATION_TEXT` and `FLAG_TEXT` in `backend/engine.py`).
   - The page notes the strongest tier possible for each service (`best_tier` in `backend/services.py`): T1 for C-section, obstetrics, dialysis, blood bank, emergency, stroke and eye care; T3 for NICU, ICU, trauma, cancer and cardiac care.

### Rows her adapters need (checked against the live tables)
| Table | Adapter | Columns used | Affects tier? |
|---|---|---|---|
| `facility_registry_links_silver` (06) | `registry_match` | `facility_id`, `site_id`, `match_score`, `needs_review`, `match_method`, `dq_flags` (optional; not in the table) | yes: `needs_review` makes a link pending, and pending-only evidence gives **R** |
| `registry_services_silver` (05) | `from_registry_service` | `service_row_id`, `site_id`, `source`, `service`, `evidence_type`, `service_specific`, `status`, `evidence_date`, `valid_until`, `is_current`, `evidence_detail`, `dq_flags`, `retrieved_on`, `source_name`, `source_url`, `row_citation` (all present; optional `valid_from` absent) | yes |
| `silver_facility_claims` (01) | `from_facility_claim` | `facility_id`, `claim_field`, `claim_text`, `claim_position`, **plus a reviewed service and yes/no supplied by the caller** | yes, but nothing produces the service and yes/no yet |
| `nqas_silver` (02) | `from_nqas` | needs a `certification_id` → `facility_id` link that doesn't exist yet | no (separate quality signal) |
| `kayakalp_silver` (03) | `from_kayakalp` | not in the workspace (only `kayakalp_silver_validation` is) | no (separate cleanliness signal) |

Her tier rules differ from the placeholder's: T1 and T2 come only from LaQshya or service-specific NABH (current or expired); NMC, DNB, NCG, trauma and self-reports top out at T3; R means "evidence exists but every facility match needs review". The page's legend uses these definitions.

### Open questions for Alice
1. **Entry point.** Is `build_recommendation_response()` the function the website should call? Will its signature and `recommendation-response/1` schema stay stable?
2. **Claims.** `from_facility_claim()` needs the service and yes/no already decided for each claim. Who builds that matcher? Without it, self-reported claims count for nothing and most facilities are U.
3. **Urgent mode.** Urgent only recommends T1 facilities with `capability_eligible = true`, and nothing supplies that yet. Should urgent fall back to something until it exists, or is "everything goes to alternatives" intended?
4. **Urgency levels.** The site has routine, urgent and emergency; the package accepts `routine` and `urgent`. Should emergency map to urgent (with the "call 112/108" notice), or be dropped?
5. **Links that need review.** 1,154 of the 4,241 links have `needs_review = true`, so those facilities become R. Should the app pass `reviewer_decision` from somewhere, or leave them pending?
6. **Package location.** A Databricks App only uploads its own folder. Should `evidence_confidence/` be merged to main and copied into `app/` at deploy time, or is there another plan?
7. **Service tags.** The dropdown uses `dialysis`, `emergency_c_section`, `nicu`, `trauma`, `emergency`, `icu`, `cancer_care`, `cardiac_care`, `stroke_care`, `blood_bank`, `obstetrics` and `eye_care`. These must match `registry_services_silver.service` exactly. Is that the agreed vocabulary?
8. **Streamlit.** Her doc mentions a "Streamlit consumer". Is a second front end planned?
9. **R wording.** Is "evidence exists but the facility match needs review" the right legend text for R?
10. **NQAS and Kayakalp.** Is it fine to leave them out of the website for now, since they don't change the tier?

## Run it locally
```bash
cd app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# a) Demo data, no Databricks needed (made-up facilities, PIN 110001 only)
DATA_MODE=mock .venv/bin/uvicorn main:app --port 8000

# b) Live, against your Databricks tables, using your CLI login (`databricks auth login --profile datathon`)
DATABRICKS_CONFIG_PROFILE=datathon DATABRICKS_WAREHOUSE_ID=<your SQL warehouse id> .venv/bin/uvicorn main:app --port 8000
```
Then open http://localhost:8000. `databricks warehouses list` shows your warehouse ID.

**Tables needed for live mode** (in `APP_CATALOG`.`APP_SCHEMA`, default `workspace.datathon`):
- `pincode_centroids_silver` (notebook 00)
- `facility_geo_ready` (Elliot's `07_pin_nearby_facilities`, Part A)
- **for evidence:** `facility_registry_links_silver` (06), `registry_sites_silver` and `registry_services_silver` (05)
- **for the placeholder fallback only:** `silver_facility_claims` (01)

## API
| Endpoint | What it does |
|---|---|
| `GET /api/health` | Data mode, evidence provider, ranker, explainer |
| `GET /api/services` | Services for the dropdown (`backend/services.py`) |
| `GET /api/pin/{pin}` | Checks a PIN and returns its centre, district, state and warnings |
| `POST /api/recommend` | `{service, pincode, radius_km, urgency}` → `recommendations` (top 5), `alternatives`, `tier_counts` over **all** candidates, `origin`, `provenance` |
| `POST /api/explain` | `{service, recommendation}` → a 2–3 sentence explanation (AI, or a template fallback) |

Each recommendation follows the team's output schema:
`facility_id`, `facility_name`, `location`, `distance_km`, `requested_service`, `service_match`, `evidence_level`, `evidence_text`, `source_urls`, `warnings`, `ranking_explanation`.
It also has `tier`, `evidence` (items with source and link), `geo_confidence`, `geo_label`, `location_uncertainty_km` and `rank_score`.

## Updating Alice's package
1. Fetch her branch and copy the package at the new commit (from the repo root):
   ```bash
   git fetch origin
   rm -rf app/evidence_confidence && git archive <commit> evidence_confidence | tar -x -C app
   ```
2. Put the new commit in `app/EVIDENCE_CONFIDENCE_VERSION`.
3. Run a search locally (live mode) and check `provenance.adapter.status` in the `/api/recommend` response is `PASS`.
4. Redeploy (see below).

Still to come from the team: a reviewed claim-to-service matcher (so self-reports count, up to T3), an emergency-capability source (`capability_eligible` / `capability_basis`) for urgent searches, and NQAS / Kayakalp facility links (these don't change the tier).

## Deploy as a Databricks App
```bash
databricks apps create find-the-right-care
databricks sync app /Users/<you>/apps/find-the-right-care            # upload this folder
databricks apps deploy find-the-right-care --source-code-path /Workspace/Users/<you>/apps/find-the-right-care
```
Then, in the app's settings:
1. Add the **SQL warehouse** as a resource named `sql-warehouse` (CAN USE).
2. Add the **serving endpoint** `databricks-meta-llama-3-3-70b-instruct` (CAN QUERY) for the explainer.
3. Give the app's **service principal** read access to the data:
   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<app service principal>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.datathon TO `<app service principal>`;
   ```

## Design notes
- **Typefaces:** Newsreader (headings), Atkinson Hyperlegible (body; designed for low-vision readers) and IBM Plex Mono (citations).
- **Accessibility:** keyboard focus rings, `aria-live` results, tier text alongside colour, and reduced-motion support.
- **Honesty:** a "Provisional results" banner while the evidence or ranking is provisional; every card ends with "availability today is not confirmed"; distances are labelled straight-line; location certainty is shown per facility; choosing Emergency shows "call 112 / 108" first.
