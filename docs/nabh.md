# NABH Accredited, Certified and Empanelled Organisations

**NABH** (National Accreditation Board for Hospitals & Healthcare Providers, part of the Quality Council of India) assesses healthcare organisations on site against published standards. Its public directory lists every organisation it currently accredits, certifies or empanels.

- **Source:** https://nabh.co/find-a-healthcare-organisation/
- **Scraper:** `scrapers/nabh_organisations.py`. Needs `requests` and `beautifulsoup4`.
- **Output:** `datasets/external/nabh_bronze/nabh_organisations_bronze.csv` (one row per listing). The API pages are in `raw/pages/` (82 MB, git-ignored).
- **Snapshot:** 2026-11-21: 865 pages, **21,582 listings** (the site reports 21,615; repeated cards are skipped).
- **Status:** bronze, not yet verified by the team. Brought to silver by notebook 05 as source `nabh`.

## How it was scraped
- The directory page posts its search form to WordPress `admin-ajax.php` (`action=get_hospitals`). robots.txt explicitly allows that path.
- Each request returns 25 results with an HTML list, pagination and map coordinates.
- The scraper made 865 requests, **1.5 s apart**, caching each page so a re-run resumes where it stopped. The server dropped two connections near the end; both succeeded on retry.
- **Personal data:** the site shows a contact phone number per organisation. It isn't saved.

```bash
python scrapers/nabh_organisations.py            # fetch (resumes from raw/pages) and build
python scrapers/nabh_organisations.py --offline  # rebuild the CSV from raw/pages
```

## Programmes (from the accreditation-number prefix)
| Category | Prefixes → programme | Listings | Service evidence? |
|---|---|---|---|
| `service_accreditation` | `BB` blood bank (127) · `CD` dialysis centre (49) · `E` emergency department (90) · `ST` advanced stroke centre (15) · `MANYATA` maternity care (15) · `MIS` medical imaging (421) · `MLP` medical lab (83) · `ECO` eye care (691) · `D`/`ELDC` dental (621) · `DE` dermatology clinic (13) · `CH` care home (17) | 2,142 | **Yes**: blood_bank, dialysis, emergency, stroke_care, obstetrics, imaging, lab_services, eye_care, dental, dermatology, geriatrics |
| `hospital_accreditation` | `H` hospital (1,843) · `SHCO` small hospital (1,254) | 3,097 | No: general quality |
| `entry_level_certification` | `PESHCO` (6,109) · `PEH` (1,671) · `ELCP` (176) | 7,956 | No: general quality, lighter standard |
| `empanelment` | `HOS` hospital · `EYE` · `DEN` · `LAB` · `CGHS` · `ECHS` · no prefix (3,586) | 6,780 | eye_care / dental / lab only. CGHS/ECHS empanelment is NABH-assessed. |
| `quality_certification` | `N` nursing excellence · `DH`/`DHC` digital health · `C` allopathic clinic | 614 | No |
| `ayush` | `AH`, `EAH`, `EAC`, `PC` | 891 | No (traditional medicine) |
| `non_facility` | `MT` medical-travel facilitators · `EC` ethics committees | 102 | **Excluded** from silver (not care sites) |

## Columns
`nabh_row_id` (hash of number + name + address; stable), `organisation_name`, `name_norm`, `address`, `state_clean`, `pincode_clean`, `latitude`, `longitude`, `website`, `accreditation_no`, `acc_prefix`, `cert_folder`, `programme`, `programme_category`, `status_text`, `listing_current`, `standards_edition`, `related_services`, `certificate_url` ("Certificate and Scope" PDF), `source_page`, `source_url`, `snapshot_date`.

## Cleaning done by the scraper
- **State:** taken from the address's last "…, State" part. If the address has no commas there ("… Meerut Uttar Pradesh"), the state name that appears **last** in the text is used. 99.4% of listings get a state.
- **PIN:** the last valid 6-digit PIN in the address (79%).
- **Coordinates:** from the site's map data. Points outside India are set to NULL. 20,098 listings have coordinates.
- **`listing_current`:** set to 0 when the status says withdrawn, suspended, expired or closed (194 listings).
- **Empanelment track:** numbers like `HOS/2025/E2674` vs `HOS/2025/C2655`. The **E/C letter is taken to mean ECHS/CGHS**; this is our inference, not something the site states. It separates two empanelments of the same hospital.

## ⚠️ Watch-outs
1. **NABH's "City, State" pair at the end of an address is often wrong.** Examples: an Agra hospital under "South Delhi, Delhi", and Hyderabad still under Andhra Pradesh. The PIN is usually right. Notebook 05 therefore replaces the state with the PIN's state when they disagree (389 listings, flagged `STATE_CORRECTED_FROM_PIN`; the original is in `state_listed`).
2. **Hospital accreditation is general quality, not a service.** A NABH-accredited hospital isn't evidence that it offers dialysis. Only the `service_accreditation` (and eye/dental/lab empanelment) rows become service evidence.
3. **Entry-level certification is a lighter standard** than full accreditation. Keep `programme_category` so the two can be weighted differently.
4. **One organisation can appear several times**, under different programmes (hospital + blood bank + nursing excellence). These are separate listings, not duplicates.
5. **Validity dates aren't shown.** `listing_current` only reflects explicit withdrawal or suspension text. The accreditation number's year is the closest thing to a date.
6. **Mostly private hospitals.** This complements the government sources (LaQshya, trauma, NQAS, Kayakalp).
