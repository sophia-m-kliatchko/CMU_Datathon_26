# Find the Right Care: web app

A FastAPI app with one web page, built to run as a **Databricks App** on top of the team's pipeline tables in `workspace.datathon`.

```
 User: service + PIN + radius + urgency
        │
        ▼
 1. Geography (Elliot)      pincode_centroids_silver → facility_geo_ready → every facility in the radius   backend/geography.py
 2. Evidence rows           links + service rows for those facilities, filtered to the service            backend/evidence.py   (app queries)
 3. Tier + rank (Alice)     evidence_confidence.build_recommendation_response(): tiers, LEFT JOIN           ◀ PLUG-IN
                            (no evidence = tier U), ranks the full set; computed per request, no gold table
 4. Then select top 3–5 + nearby alternatives
 5. Optional AI explainer (Databricks Foundation Model, grounded in the evidence)                         backend/explain.py
```

**Status:** the geography step is real (it ports Elliot's `07_pin_nearby_facilities` search). **The evidence and ranking steps are placeholders** until Alice's `evidence_confidence` package is wired in (see "Planned integration" below), and the page shows a "Provisional results" banner while they are.

## For the team: how the app uses the pipeline, and what we need from you

**Request flow** (one `POST /api/recommend`): PIN lookup → every facility in the radius → evidence per facility (LEFT JOIN, missing = tier U) → rank the **whole** set → only then take the top 5 and the alternatives. This follows the end-to-end pipeline diagram. Each step is its own module in `backend/`, so a step can be replaced without touching the others.

### Tables the app reads today
| Step | Table | Made by | Used for |
|---|---|---|---|
| PIN lookup | `pincode_centroids_silver` | notebook 00 | Validate the PIN, find its centre |
| Candidate search | `facility_geo_ready` | Elliot, `07_pin_nearby_facilities` Part A | Facilities within the radius, with location certainty |
| Placeholder evidence (self-claims) | `silver_facility_claims` | notebook 01 | Facility's own claims |
| Placeholder evidence (registries) | `facility_registry_links_silver`, `registry_services_silver` | notebooks 06, 05 | Registry listings per service |

The team decided **not to use gold tables**: tiers and ranking are computed per request from these silver tables by Alice's package. Until it's wired in, the placeholders compute them, and the page shows a "Provisional results" banner.

### What we need from each owner
1. **Alice (evidence and ranking).** Answers to the open questions in "Planned integration" below: mainly the entry point, the claim-to-service matcher, urgent mode and where the package will live. Her tier definitions (`evidence_confidence/TIERS.md`) replace the placeholder's, and the page legend will follow them.
2. **Team (service vocabulary).** Confirm the service tags. `backend/services.py` currently has: dialysis, emergency C-section, NICU, trauma, emergency, ICU, cancer care, cardiac care, stroke care, blood bank, obstetrics, eye care. They must match `registry_services_silver.service` exactly.
3. **Elliot.** `facility_geo_ready` currently exists in the workspace only because it was created by hand from his notebook. Please add that notebook to the saved job so a fresh run creates it. Also, it lives in `notebooks/common/` but uses `%run ./common/...`, which only works from `notebooks/`.
4. **Whoever owns the job.** Keep `facility_registry_links_silver` and `registry_services_silver` in the job (notebooks 05 and 06), since the app reads them on every search.

### How the AI explainer fits
The optional "Explain in plain language" button sends only the facility's own cited evidence to a Databricks Foundation Model endpoint (Llama 3.3 70B) and shows 2–3 sentences. If the call fails, it falls back to a template. It never adds facts that aren't in the evidence.

## Planned integration with Alice's evidence engine (`alice-evidence-confidence`)

**Status:** planned, not built yet. Alice's `evidence_confidence/` package (pure Python, tested on synthetic data) replaces the placeholder evidence and ranking. The app imports it and doesn't modify it. Until then, the placeholders in `backend/evidence.py` and `backend/ranking.py` stay in use.

### Call sequence per search
1. **Candidates:** every facility within the radius of the PIN, from Elliot's `facility_geo_ready`. There's no service filter or top-k, so facilities with no evidence stay in as tier U. Each candidate carries `facility_id`, `name`, `distance_km`, `geo_confidence`, `location_basis` and `location_uncertainty_km`.
2. **Evidence:** query `facility_registry_links_silver` for those facility IDs, then `registry_services_silver` for the linked `site_id`s, **filtered to the requested service**.
3. **Conversion:** each link and service row goes through `registry_match(link)` and then `from_registry_service(row, match)`. The optional `site` argument isn't passed, because it raises an error for NABH sites in general accreditation categories.
4. **Her function:** `build_recommendation_response(request, records, candidates)` assigns tiers, LEFT JOINs them to every candidate and ranks the whole set.
5. **Display:** the app reshapes the `recommendation-response/1` JSON for the page, shows the top 5 plus alternatives after ranking, and offers the optional AI explainer.

### Rows her adapters need (checked against the live tables)
| Table | Adapter | Columns used | Affects tier? |
|---|---|---|---|
| `facility_registry_links_silver` (06) | `registry_match` | `facility_id`, `site_id`, `match_score`, `needs_review`, `match_method`, `dq_flags` (optional; not in the table) | yes: `needs_review` makes a link pending, and pending-only evidence gives **R** |
| `registry_services_silver` (05) | `from_registry_service` | `service_row_id`, `site_id`, `source`, `service`, `evidence_type`, `service_specific`, `status`, `evidence_date`, `valid_until`, `is_current`, `evidence_detail`, `dq_flags`, `retrieved_on`, `source_name`, `source_url`, `row_citation` (all present; optional `valid_from` absent) | yes |
| `silver_facility_claims` (01) | `from_facility_claim` | `facility_id`, `claim_field`, `claim_text`, `claim_position`, **plus a reviewed service and yes/no supplied by the caller** | yes, but nothing produces the service and yes/no yet |
| `nqas_silver` (02) | `from_nqas` | needs a `certification_id` → `facility_id` link that doesn't exist yet | no (separate quality signal) |
| `kayakalp_silver` (03) | `from_kayakalp` | not in the workspace (only `kayakalp_silver_validation` is) | no (separate cleanliness signal) |

Her tier rules differ from the placeholder's: T1 and T2 come only from LaQshya or service-specific NABH (current or expired); NMC, DNB, NCG, trauma and self-reports top out at T3; R means "evidence exists but every facility match needs review". The page's legend will change to match.

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
- **for the placeholder evidence:** `silver_facility_claims` (01), `facility_registry_links_silver` (06), `registry_services_silver` (05)

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

## Plugging in Alice's package (evidence and ranking)
There is no gold table to plug in. Wiring it in means:
1. **Make the package importable.** A Databricks App only uploads its own folder, so `evidence_confidence/` must be copied into `app/` (or merged to main and copied at deploy time; see open question 6).
2. **Load the evidence rows** in `backend/evidence.py`: links for the candidate facility IDs, and service rows for the linked sites, filtered to the requested service. Convert them with `registry_match()` and `from_registry_service()`.
3. **Call `build_recommendation_response()`** in place of the placeholder evidence and ranking, mapping the app's request (`pincode` → `pin`, `urgency` → `mode`).
4. **Reshape the response** (`recommendation-response/1`) into the fields the page uses: tier from `service_evidence.effective_tier`, evidence items from its citations, plus `source_urls`, `warnings` and `ranking_explanation`. Then select the top 5 and the alternatives.
5. **Update the page:** the tier legend (R = "evidence exists but the facility match needs review"), and remove the "Provisional results" banner once the placeholders aren't used.

The placeholder's tier rules (top of `backend/evidence.py`) and ranker (`backend/ranking.py`) stay as a fallback for demos until then. `EVIDENCE_PROVIDER=table` and `TableEvidence` were built for the gold-table plan and will be removed.

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
- **Honesty:** a "Provisional results" banner whenever a placeholder is in use; every card ends with "availability today is not confirmed"; distances are labelled straight-line; location certainty is shown per facility; choosing Emergency shows "call 112 / 108" first.
