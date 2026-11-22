# Service Registries at Silver: `registry_sites_silver` and `registry_services_silver`

Built by `notebooks/05_registries_bronze_to_silver.py` (sites and services) and `notebooks/06_registry_matching.py` (links to facilities). These tables hold **outside evidence about which services a place provides**, from six registries, in one shared shape, linked to `facilities_silver.facility_id`.

```
facilities_silver ──facility_id── facility_registry_links_silver (06) ──site_id── registry_sites_silver ──site_id── registry_services_silver
        └── facility_registry_summary_silver (06): one row per facility, quick view
```

## How to run it
1. In Databricks, create a Volume (e.g. `workspace.datathon.external`) and upload these CSVs from `datasets/external/*/`:
   - `laqshya_facilities_bronze.csv`, `laqshya_certifications_bronze.csv`
   - `trauma_care_facilities_bronze.csv`
   - `nmc_colleges_bronze.csv`, `nmc_college_courses_bronze.csv`
   - `dnb_hospitals_bronze.csv`, `dnb_hospital_specialties_bronze.csv`
   - `ncg_members_bronze.csv`
   - `nabh_organisations_bronze.csv`
2. Optional but recommended: run notebook 04 first. Sites with a PIN then get that PIN's location and a state cross-check.
3. Run notebook 05, setting widget 3 to the Volume folder. Each CSV becomes a raw table of the same name, plus the two silver tables. A source whose CSV is missing is skipped with a warning.

**Local test:** on 2026-11-21 the notebook ran end to end on local Spark 4.0 against these CSVs: 24,961 sites, 22,757 service rows, and all checks passed.

## Contents (2026-11-21)

| `source` | Registry | Sites | Service rows | Has PIN | Evidence type |
|---|---|---|---|---|---|
| `laqshya` | LaQshya labour room / maternity OT certification | 1,343 | 4,304 | — (district only) | `government_certification` |
| `nmc` | NMC medical colleges and courses | 911 | 10,015 | 611 | `government_training_approval` |
| `dnb` | NBEMS/DNB-accredited hospitals | 655 | 4,111 | — (city only) | `government_training_approval` |
| `ncg` | National Cancer Grid member cancer centres | 376 | 376 | 344 | `network_membership` |
| `trauma` | MoHFW Trauma Care Facilities (Level I–III) | 196 | 392 | — (place only) | `government_designation` |
| `nabh` | NABH accredited / certified / empanelled organisations | 21,480 | 3,559 | 17,051 (+ coordinates for most) | `independent_accreditation`, `government_scheme_empanelment` |

Sites with evidence for the main demo services:
- **Emergency C-section:** LaQshya 901 sites (200 currently valid), NMC 516, DNB 161.
- **Dialysis:** NMC 82, DNB 64, NABH dialysis centres 49.
- **NICU:** NMC 36, DNB 11.
- **Trauma / emergency:** trauma programme 196; NABH emergency departments 90; plus indirect evidence via orthopaedics/neurosurgery (NMC 508, DNB 219).
- **Blood bank:** NABH-accredited blood centres 127; NMC transfusion-medicine departments 69.
- **Stroke care:** NABH advanced stroke centres 15; NMC/DNB neurology departments 105/69.
- **Cancer care:** NCG 376, NMC 135, DNB 74.

## `registry_sites_silver`: one row per place listed by a registry

| Column | Meaning |
|---|---|
| `site_id` | `<source>:<source_record_id>`, unique across registries |
| `name`, `name_norm`, `name_core` | The name as published / normalized / with facility-type words removed. Normalized with the shared `common/reference_data` functions, the same as NQAS and Kayakalp. **Match on `name_core`.** |
| `facility_type_code`, `facility_level` | DH, SDH, CHC, MC, GH… (from the source, or guessed from the name) and primary/secondary/tertiary |
| `ownership` | `government` (LaQshya, trauma), from NMC's management type, or NULL (unknown) |
| `state` | Standardized state/UT, the same values as `facilities_silver.state`. For NABH, corrected from the PIN where the listed state disagreed (`STATE_CORRECTED_FROM_PIN`) |
| `state_listed` | The state as the source gave it (standardized) |
| `district`, `city`, `pincode`, `address`, `website` | Whatever the source gives. **Different sources give different fields**; see the table above. |
| `latitude`, `longitude` | The site's own coordinates, where the source gives them (NABH) |
| `listing_type`, `listing_category`, `listing_status`, `listing_current` | What being in this registry means (e.g. "Hospital accreditation" / `hospital_accreditation`, "Blood bank / blood centre accreditation" / `service_accreditation`), the source's status text, and whether it's still in force. **General-quality listings (NABH hospital accreditation, entry-level, empanelment) appear here, not as service rows.** |
| `pin_latitude`, `pin_longitude`, `pin_main_district` | From `pincode_centroids_silver`: the **PIN's** median location, not the site's exact location |
| `dq_flags` | See below |
| `row_citation` + `source_*`, `retrieved_on`, `produced_by` | Citation columns (team rule) |

## `registry_services_silver`: one row per site × service × piece of evidence

| Column | Meaning |
|---|---|
| `service_row_id`, `site_id`, `source` | Keys; join to sites on `site_id` |
| `service`, `service_label` | A tag from the shared vocabulary (`SERVICES` in notebook 05) and its display label |
| `evidence_type` | `government_certification` · `government_designation` · `government_training_approval` · `government_scheme_empanelment` · `independent_accreditation` · `network_membership` |
| `service_specific` | **true** if the evidence is about this service itself (LaQshya maternity OT → C-section; trauma facility → trauma; NCG → cancer care). **false** if inferred from a specialty department or course (NMC, DNB) |
| `evidence_subtype` | e.g. "Super-specialty (DM) course", "Level II Trauma Care Facility", "LaQshya maternity ot certification" |
| `evidence_detail` | **The sentence to quote** in an explanation, e.g. "NMC-approved D.M. Nephrology, 5 approved seats (Super-specialty (DM))" |
| `approved_seats` | NMC only: seats for the course (bigger number, bigger department) |
| `status` | certified / conditional / sanctioned / approved / accredited / member |
| `evidence_date`, `valid_until`, `is_current` | `is_current` is true if still valid on the run date, false if expired, and NULL if the source gives no validity (DNB, trauma) |
| `dq_flags`, `row_citation`, `source_*` | As above |

A site can have several rows for one service. For example, a college with D.M. Nephrology and M.Ch. Urology has two `kidney_care` rows. Keep them all: the scoring step can take the strongest.

## Data-quality flags
**Sites:**
- `NO_PINCODE`: no PIN code.
- `NO_LOCALITY`: no city, district or PIN.
- `PIN_NOT_IN_DIRECTORY`: the PIN isn't in the India Post directory.
- `PIN_STATE_MISMATCH`: the PIN belongs to a different state. These are source errors, e.g. a Gujarat hospital listed with a Tamil Nadu PIN.
- `STATE_UNRECOGNIZED`: the state couldn't be standardized.
- `POSSIBLE_DUPLICATE_IN_SOURCE`: the same name and place appear twice in one source.
- `NAME_REPAIRED_FROM_PDF`, `CELLS_REPAIRED_FROM_PDF` (LaQshya): the value was repaired from PDF overflow.
- `PLACE_ADDED_BY_HAND` (trauma): `city` was added by hand from the facility name.
- `STATE_REASSIGNED`, `DUPLICATE_NAME_IN_CITY`, `LIST_UNDATED` (DNB).
- `NEW_COLLEGE_LOP_ONLY`, `NO_DETAIL_RECORD` (NMC).
- `MAY_BE_GROUP_OR_HEAD_OFFICE` (NCG).
- `STATE_CORRECTED_FROM_PIN`, `LISTING_NOT_CURRENT`, `NO_COORDINATES` (NABH).

**Services:**
- `CERTIFICATION_EXPIRED`, `CONDITIONAL_CERTIFICATION`, `DEPARTMENT_NOT_STATED` (LaQshya).
- `SANCTIONED_NOT_CONFIRMED_FUNCTIONAL` (trauma).
- `INDIRECT_VIA_SPECIALTY`, `RECENT_LOP_ONLY`, `NO_ACCREDITATION_DATE` (NMC/DNB).
- `MEMBERSHIP_NOT_INSPECTION` (NCG).
- `LISTING_NOT_CURRENT`, `DATE_IS_YEAR_ONLY` (NABH).
- `SERVICE_NOT_IN_VOCABULARY`.

## ⚠️ Watch-outs
1. **These are places in registries, not our facilities.** Join to `facilities_silver` only through `facility_registry_links_silver`. **Never join on name alone.**
2. **No scores here.** `evidence_type`, `service_specific` and `is_current` describe the evidence; points and levels belong in gold.
3. **A match is evidence for a facility; no match is not evidence against it.** Each registry covers only part of India's facilities.
4. **`pin_latitude`/`pin_longitude` are PIN-level** (often several km across). Use them to narrow down candidates, not as exact positions.
5. **Expired isn't worthless.** An expired LaQshya certification still shows the facility had a certified maternity OT when assessed. Use `is_current` to weight it, not to drop it.
6. **Some service tags are broad hints** (e.g. orthopaedics → `trauma`). They're `service_specific = false` and flagged `INDIRECT_VIA_SPECIALTY`.
7. **NABH general accreditation is a site-level quality signal** (`listing_category` = `hospital_accreditation` / `entry_level_certification` / `empanelment`). It isn't service evidence. See `docs/nabh.md`.

---

# Matching to facilities: `facility_registry_links_silver` (notebook 06)

## Output tables
| Table | One row per | Use it for |
|---|---|---|
| `facility_registry_links_silver` | facility ↔ registry site link | **The join table.** `facility_id`, `site_id`, `match_score`, `needs_review`, `review_reason`, `match_method` (which evidence agreed: name, coordinates, pin, pin_area, place_name, type), `name_score`, `distinct_overlap`, `distance_km` + `distance_basis`, both names and places side by side |
| `facility_registry_summary_silver` | facility (all 9,989) | Quick view: `registry_sources`, `listing_categories`, `services_evidenced` (from confident links), `services_evidenced_pending_review`, `n_links_needing_review` |
| `registry_match_review` | link needing review | Side-by-side for a person; fill `reviewer_decision` with confirm/reject |

**Typical join:** `facility_registry_links_silver` → `registry_services_silver` on `site_id`, filtered to `NOT needs_review` (or with review links weighted lower).

## How matching works
1. **Candidates:** a facility and a registry site are compared only if all of these hold:
   - same `state`;
   - they share a **distinctive name word** (words in more than 250 names, such as "sri", "care" or "medical", don't count here);
   - they're **close by**: site coordinates within 3 km, the same PIN, the site's PIN area within 5 km, or the site's town or district named in the facility's address.
2. **Distinctive-word check:** remove common or generic words (medical, college, cardiac, eye, district…) and place names from both names.
   - Both have words left and **none match** (typo-tolerant) → rejected. This stops "ESIC Medical College" matching "Osmania Medical College".
   - Only one has words left → **review**.
3. **Score (0–100):**
   - name similarity (`rapidfuzz` token-set and token-sort average);
   - location bonus up to +20;
   - facility-type agreement +5 / −10;
   - ownership: a government registry against a private facility −10, against a public one +5;
   - −10 if a clinic or dentist is matched to a teaching-hospital, trauma, LaQshya or NCG listing.

   A registry name that's only a type plus a place ("DH Faridabad") needs the type to agree.
4. **Decide:**
   - Per site, the best candidate with score ≥ 85 is **linked**.
   - It's linked but marked **`needs_review`** if: the score is 70–84; there's a near-tie (within 5 points) with another facility; it's more than 10 km away; or the distinctive words appear on one side only.
   - A near-tie with a facility listed in the best one's `possible_duplicate_ids` is linked too, as two records of the same place.

All thresholds are widgets.

## Results (local test, 2026-11-21)
| Source | Sites | Linked | Confident | Needs review | Facilities reached |
|---|---|---|---|---|---|
| nabh | 21,480 | 3,878 (18%) | 2,696 | 1,182 | 2,546 |
| dnb | 655 | 212 (32%) | 140 | 72 | 204 |
| nmc | 911 | 167 (18%) | 77 | 90 | 145 |
| ncg | 376 | 110 (29%) | 61 | 49 | 109 |
| laqshya | 1,343 | 70 (5%) | 39 | 31 | 64 |
| trauma | 196 | 37 (19%) | 19 | 18 | 37 |

- **2,745 of 9,989 facilities (27%) are linked to at least one registry.**
- Facilities with **confident** outside evidence: C-section 114, trauma 126, cancer care 90, dialysis 36, blood bank 19, NICU 4.
- **Precision check:** random samples of confident links were checked by hand. NABH: 15/15 correct. Other sources: 29/30 (one branch mix-up of the same chain, "Jupiter Hospital, Thane" vs NCG "Jupiter Hospital Pune").
- **Low match rates for LaQshya and trauma are expected.** They list public facilities, while 88% of Virtue Foundation facilities are private.

## ⚠️ Watch-outs for links
1. **`needs_review` links are probably right, but not certain.** Count them as weaker evidence, or ask someone to review `registry_match_review`.
2. **Chains and branches** (Apollo, Jupiter, Max…) are the main risk: same name, different city. Links more than 10 km apart are sent to review, but a branch in the same metro area can still slip through.
3. **A teaching hospital and its medical college often have different names**, so some true matches are missed (e.g. a district hospital that's the teaching hospital of a government medical college).
4. **No link ≠ no service.** Most facilities are in no registry at all.
5. Facilities with no state (157) and sites with no state (80) aren't matched.
