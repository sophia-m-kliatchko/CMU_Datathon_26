# DNB-Accredited Hospitals (ANBAI / NBEMS)

Outside evidence for **which specialties a hospital really practises**. NBEMS only accredits a hospital to train DNB / DrNB / FNB doctors in a specialty if the hospital has the patient volume, faculty and equipment for it. A hospital accredited for Nephrology training almost certainly runs a dialysis unit.

- **Source:** https://anbai.org/DNB_accredited_institutions.php (Association of National Board Accredited Institutions)
- **Scraper:** `scrapers/anbai_dnb.py` (one HTTP request; the page is static HTML)
- **Output:** `datasets/external/anbai_dnb_bronze/` (bronze: not yet verified by the team)
- **Snapshot:** 2026-11-21. 655 hospital listings, 2,596 hospital × specialty rows, 28 states, 71 specialties.

```bash
python scrapers/anbai_dnb.py                  # re-scrape (saves raw/anbai_dnb_<date>.html)
python scrapers/anbai_dnb.py --html <file>    # re-parse a saved copy
```
Needs `requests` and `beautifulsoup4`.

## Files

| File | One row per | Key columns |
|---|---|---|
| `dnb_hospitals_bronze.csv` | hospital listing | `hospital_id`, `hospital_name`, `name_norm` (for matching), `city_raw`, `state_listed`, `state_clean`, `state_note`, `n_specialties`, `specialties`, `specialties_raw`, `duplicate_name_city`, `source_url`, `scraped_at` |
| `dnb_hospital_specialties_bronze.csv` | hospital × accredited specialty | `hospital_id`, `specialty` (canonical), `course_note`, `category`, `related_services`, `specialty_raw` |
| `dnb_specialty_reference_bronze.csv` | canonical specialty | `category`, `related_services`, `n_hospitals` |
| `anbai_dnb_bronze.sqlite` | the 3 tables above (table names have no `_bronze` suffix), plus the view `v_service_evidence` (hospital × challenge service, with the specialties behind it) | |
| `raw/anbai_dnb_<date>.html` | the page that was parsed | provenance |

**Into Databricks:** upload the CSVs with **Create table → Upload file** (or copy them to a Volume), e.g. as `workspace.datathon.ext_dnb_hospitals` and `ext_dnb_hospital_specialties`.

## Cleaning done by the scraper
- **Specialty cells are split on commas and then repaired.** Stray commas inside names are rejoined ("Genito Urinary, Surgery (Urology)", "Critical Care, Medicine", "Dermatology, Venereology and Leprosy"). Missing commas are split ("…(Direct 6 Years Course) Cardiology"). A specialty repeated in one cell is kept once. Any name the scraper doesn't recognize is printed as a warning; none were found in the 2026-11-21 run.
- **Spelling variants are merged:** Anesthesia/Anaesthesia, Pediatrics/Paediatrics, "Critical Care" → Critical Care Medicine. "(Direct 6 Years Course)" moves to `course_note`. Some names keep the page's own spelling (e.g. "Pediatric Cardiology"), so match on these exact names.
- **States:** Orissa → Odisha, Uttaranchal → Uttarakhand, Jammu & Kashmir → Jammu and Kashmir, the same names as `silver_facilities.state_clean`. Three hospitals are listed under Andhra Pradesh but are in Telangana cities (Hyderabad, Secunderabad, Warangal). They're moved to Telangana and explained in `state_note`.
- **Repeated hospital name in the same city** (Max Super Specialty Hospital, New Delhi; Yashoda Super Speciality Hospital, Hyderabad): these have different specialty lists, so they're probably different branches. They're kept as separate rows with `duplicate_name_city = 1`, and the second gets an `_2` ID suffix.

## ⚠️ Watch-outs
1. **The page has no "last updated" date.** The leftover Andhra Pradesh / Telangana listings suggest parts of it are years old, and accreditation expires and gets renewed. Treat it as "was accredited at some point," and cite the snapshot date.
2. **A match is evidence for a facility; no match is not evidence against it.** This list only covers DNB teaching hospitals, about 650 nationally. Most good hospitals aren't on it.
3. **Specialty ≠ service.** `related_services` is a hint we wrote, not something the source says. Nephrology → `dialysis` is strong. Obstetrics and Gynaecology → `emergency_c_section` is reasonable, since DNB OBG training needs round-the-clock obstetric emergencies. Anaesthesiology → `icu` is weak. Show it as "accredited to train specialists in Nephrology," not as "does dialysis."
4. **`city_raw` is messy.** Sometimes it's a district ("West Godavari Dist"), a locality ("Saket", "Malkaganj") or a road ("Jawahar Lal Nehru Marg"). Match on `state_clean` + `name_norm` and check the city by hand. There are no coordinates or PIN codes.
5. **Hospital chains share names** ("Apollo Hospital" appears in several cities). Never match on name alone; always add the state, and the city where possible.
6. **`hospital_id` is a hash of state + name + city as listed.** It stays stable across re-scrapes unless the page edits those fields. The `_2` suffix depends on page order.
7. **Category `lab_basic_science` / `public_health_admin`** (Pathology, Physiology, Hospital Administration…) says little about patient services. Leave those out of service evidence.

## Next step: matching to `silver_facilities`
Block on `state_clean`, compare `name_norm` against the normalized silver name (fuzzy, ≥85%, the same rule as the near-duplicate step), then check the city against `city_clean`. Review borderline matches by hand: with about 650 rows, a manual check is feasible.
