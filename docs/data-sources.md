# Data Sources and Citations

**Rule (see `CLAUDE.md`):** every table we scrape, download, convert or assemble gets an entry here **in the same commit that adds it**. Each entry says where the data came from, who published it, when we got it, the licence or terms, how we turned it into a table, and how to cite it. Silver tables built from outside sources also carry **per-row citation columns** (`source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by`, `row_citation`), so any recommendation can cite its evidence.

Items marked **⚠ TODO** still need information from the person who added the data.

## Summary

| Table(s) | Source | Publisher | Retrieved | Built by |
|---|---|---|---|---|
| `facilities_bronze`, `facilities_silver`, `silver_facility_claims`, `silver_possible_duplicates`, `silver_dq_summary`; file `data/raw/facilities.csv` | Virtue Foundation India healthcare facilities dataset (Databricks Marketplace) | Virtue Foundation | 2026-11-21 | `notebooks/01_bronze_to_silver.py` |
| `nqas_bronze`, `nqas_silver`; file `data/external/nqas_certified_facilities.csv` | NQAS Certified Facilities list | NHSRC, MoHFW | 2026-11-21 | `scripts/scrape_nqas.py` → `notebooks/02_nqas_bronze_to_silver.py` |
| `kayakalp_bronze`, `kayakalp_silver`; file `data/external/kayakalp_2021_22.csv` | Kayakalp Winner Facilities of FY 2021-22 (PDF) | NHSRC, MoHFW (Kayakalp scheme) | 2026-11-21 | `scripts/kayakalp_pdf_to_csv.py` → `notebooks/03_kayakalp_bronze_to_silver.py` |
| `pincode_bronze`, `pincode_silver`, `pincode_centroids_silver`, `pincode_rejected`, `pincode_dq_summary`; file `data/raw/india_post_pincode_directory.csv` | All India Pincode Directory | Department of Posts, via data.gov.in | ⚠ TODO (file received 2026-11-21) | `notebooks/04_pincode_bronze_to_silver.py` (builds on elliotl-ops's `notebooks/india_pincode_bronze_to_silver.py`) |
| file `data/raw/nfhs_5_district_health_indicators.csv` | NFHS-5 (2019-21) district factsheets | IIPS / MoHFW, via data.gov.in | ⚠ TODO | not yet processed |
| files `datasets/external/anbai_dnb_bronze/*_bronze.csv` (+ `.sqlite`) | List of DNB accredited institutions | Association of National Board Accredited Institutions (ANBAI), mirroring NBEMS accreditation | 2026-11-21 | `scrapers/anbai_dnb.py` (no silver table yet) |
| files `datasets/external/nmc_bronze/*_bronze.csv` (+ `.sqlite`) | Lists of colleges teaching MBBS and PG courses | National Medical Commission (NMC) | 2026-11-21 | `scrapers/nmc_colleges.py` (no silver table yet) |
| file `datasets/external/trauma_care_bronze/trauma_care_facilities_bronze.csv` | Rajya Sabha Unstarred Q. 2048 (10 Mar 2026), Annexure-I | Ministry of Health and Family Welfare, via Rajya Sabha | 2026-11-21 | `scrapers/mohfw_trauma_centres.py` (no silver table yet) |
| files `datasets/external/laqshya_bronze/laqshya_*_bronze.csv` | LaQshya Master data (8 Apr 2026) | NHSRC, MoHFW | 2026-11-21 | `scrapers/nhsrc_laqshya.py` (no silver table yet) |
| file `datasets/external/ncg_bronze/ncg_members_bronze.csv` | National Cancer Grid member list | National Cancer Grid (Tata Memorial Centre, DAE) | 2026-11-21 | `scrapers/ncg_members.py` (no silver table yet) |

---

## 1. Virtue Foundation facilities dataset
- **What:** about 10,000 Indian healthcare facility records with 51 attributes, extracted from web sources.
- **Publisher:** Virtue Foundation (virtuefoundation.org), distributed for the CMU Datathon Fall 2026 through the Databricks Marketplace.
- **Where:** Databricks Marketplace listing `19326b3d-db63-4627-abc0-cf4e8131a305`. The default table is `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities`; the catalog name depends on what each person chose when adding the listing. A CSV copy is at `data/raw/facilities.csv`, added by JhK830 on 2026-11-21 as "original Datathon raw datasets".
- **Licence / terms:** as set by the Marketplace listing and the datathon rules. ⚠ TODO: copy the licence line from the listing.
- **Processing:** `notebooks/01_bronze_to_silver.py`. Data problems are documented in `docs/dataset-notes.md` and `docs/silver-tables.md`.
- **Background:** a previous team's dataset write-up, used for our data-quality notes: Peter Tadrous, *Virtue Foundation Dataset (DAIS 2026)*, https://github.com/petertadrous/2026-dbx-hackathon (accessed 2026-11-21).
- **Cite as:** Virtue Foundation. *Virtue Foundation India Healthcare Facilities Dataset (DAIS 2026).* Databricks Marketplace, 2026. Accessed 2026-11-21.

## 2. NQAS Certified Facilities
- **What:** public health facilities certified under India's National Quality Assurance Standards, with state, district, departments assessed and validity dates. There are two lists, "full" and "partial" certification.
- **Publisher:** National Health Systems Resource Centre (NHSRC), Ministry of Health and Family Welfare, Government of India.
- **Where:** https://qps.nhsrcindia.org/nqas-facility-list. The scraped pages are https://qps.nhsrcindia.org/nqas-certification-full and https://qps.nhsrcindia.org/nqas-certification-partial.
- **Retrieved:** 2026-11-21. Run twice that day with identical results.
- **Licence / terms:** a public government web page; no explicit open-data licence was found. We cite NHSRC and scrape politely (0.5 s between requests).
- **Processing:** `scripts/scrape_nqas.py` → CSV (989 rows) → upload as `nqas_bronze` → `notebooks/02_nqas_bronze_to_silver.py` → `nqas_silver`.
- **Known limitations:**
  - **Historical:** every certificate in the list expired between 2019 and 2023, and the list has about 1k rows versus about 21k certified facilities on the NHSRC dashboard. Use it as "was certified", not "is certified now".
  - The site reports 994 rows and we recovered 989. The other 5 are probably duplicate listings on the site itself.
  - Public facilities only.
- **Cite as:** National Health Systems Resource Centre. *NQAS Certified Facilities.* Ministry of Health and Family Welfare, Government of India. https://qps.nhsrcindia.org/nqas-facility-list. Accessed 2026-11-21.
- **Per-row citation:** the `row_citation` column in `nqas_silver`.

## 3. Kayakalp Winner Facilities, FY 2021-22
- **What:** 1,197 public facilities that won Kayakalp awards (cleanliness, hygiene and infection control) in FY 2021-22, including Eco-friendly awards.
- **Publisher:** National Health Systems Resource Centre (NHSRC), Ministry of Health and Family Welfare, Government of India (Kayakalp Award Scheme).
- **Where:**
  - Landing page: [List of Kayakalp winner facilities (NHSRC)](https://qps.nhsrcindia.org/kayakalp-swachh-swasth-sarvatra/quality-LOKWF)
  - PDF: https://qps.nhsrcindia.org/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf (uploaded to the NHSRC site in 2024-09, according to its path)
  - Background on the scheme: [Kayakalp Guidelines 2021 (NHSRC)](https://qps.nhsrcindia.org/sites/default/files/2022-03/Kayakalp%20Guidelines%202021%20%28with%20eco%20friendly%29.pdf)
- **File check:** the copy Sophia downloaded matches the online PDF byte for byte (788,186 bytes, SHA-256 `6af952e2caa017f6f9ad92f916848caffa357f08db7556309805a44977607680`, checked 2026-11-21).
- **Retrieved / converted:** 2026-11-21. A copy of the PDF is in the repo at `data/KAYAKALP WINNER FACILITIES 21-22.pdf` (uploaded by Sophia; same SHA-256 as the online file).
- **Licence / terms:** a government publication; no explicit open-data licence was found. We cite NHSRC/MoHFW.
- **Processing:** `scripts/kayakalp_pdf_to_csv.py` (pdfplumber) → CSV → upload as `kayakalp_bronze` → `notebooks/03_kayakalp_bronze_to_silver.py` → `kayakalp_silver`.
- **Known limitations:**
  - In 17 rows, district text had spilled into the State column; this was repaired and flagged `DISTRICT_REPAIRED_FROM_PDF`.
  - Some states wrote "village, block, district" in the district field; it's split into `locality` and `district`.
  - Public facilities only, and FY 2021-22 only.
- **Cite as:** National Health Systems Resource Centre. *List of Kayakalp Winner Facilities FY 2021-22.* Ministry of Health and Family Welfare, Government of India. https://qps.nhsrcindia.org/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf. Accessed 2026-11-21.
- **Per-row citation:** the `row_citation` column in `kayakalp_silver`, which gives the PDF page and S.No.

## 4. India Post Pincode Directory
- **What:** about 165k post offices with PIN, district, state and latitude/longitude.
- **Publisher:** Department of Posts, Government of India, via the Open Government Data Platform: https://data.gov.in/resource/all-india-pincode-directory-till-last-month.
- **Where:** `data/raw/india_post_pincode_directory.csv`, added by JhK830 on 2026-11-21 as "original Datathon raw datasets". **⚠ TODO (JhK830): confirm the exact source** (data.gov.in or supplied by the datathon) **and the download date.** The official data.gov.in file may not include coordinates, so the coordinates may come from elsewhere.
- **Processing:** `notebooks/04_pincode_bronze_to_silver.py` → `pincode_bronze` (raw), `pincode_silver` (one row per post office), `pincode_centroids_silver` (one row per PIN: median office location), `pincode_rejected`, `pincode_dq_summary`. Coordinates are parsed by `notebooks/common/coordinate_parsing.py`. This builds on elliotl-ops's `notebooks/india_pincode_bronze_to_silver.py` (added 2026-11-21), which first documented the "NA" values, junk latitudes and multi-district PINs.
- **Per-row citation:** the `row_citation` column in `pincode_silver` and `pincode_centroids_silver`.
- **Known limitations:**
  - About 7% of offices have no coordinates.
  - About 7% sit more than 50 km from their PIN's median point; these are flagged and left out of the centroid.
  - 1,478 PINs span several districts and 290 span several states (`pin_ambiguous`).
- **Licence:** Government Open Data License – India (GODL), if it came from data.gov.in.
- **Cite as:** Department of Posts. *All India Pincode Directory.* Open Government Data Platform India. ⚠ TODO: date.

## 5. NFHS-5 district health indicators
- **What:** National Family Health Survey 5 (2019-21) indicators for 706 districts. `*` means suppressed; values in parentheses are based on small samples.
- **Publisher:** International Institute for Population Sciences (IIPS) for the Ministry of Health and Family Welfare: https://rchiips.org/NFHS/factsheet_NFHS-5.shtml. Also on data.gov.in: https://data.gov.in/catalog/national-family-health-survey-5-nfhs-5-india-districts-factsheet-data.
- **Where:** `data/raw/nfhs_5_district_health_indicators.csv`, added by JhK830 on 2026-11-21. Column names are already snake_case, so it was probably pre-processed by the datathon or a teammate. **⚠ TODO (JhK830): confirm the exact source and date.**
- **Licence:** GODL (data.gov.in), if it came from there.
- **Cite as:** International Institute for Population Sciences (IIPS) and ICF. *National Family Health Survey (NFHS-5), 2019-21: District Fact Sheets.* Mumbai: IIPS, 2021.

## 6. DNB-accredited hospitals and specialties (ANBAI / NBEMS)
- **What:** hospitals accredited by the National Board of Examinations in Medical Sciences (NBEMS) to train DNB/DrNB/FNB specialists, with the specialties each is accredited for. 655 hospital listings and 2,596 hospital × specialty rows, in 28 states and 71 specialties.
- **Publisher:** Association of National Board Accredited Institutions (ANBAI). The accreditation itself is granted by NBEMS, Ministry of Health and Family Welfare.
- **Where:** https://anbai.org/DNB_accredited_institutions.php (one static HTML page). Files: `datasets/external/anbai_dnb_bronze/` — `dnb_hospitals_bronze.csv`, `dnb_hospital_specialties_bronze.csv`, `dnb_specialty_reference_bronze.csv`, `anbai_dnb_bronze.sqlite`. The page snapshot is in `raw/`, which is git-ignored.
- **Retrieved:** 2026-11-21. The site has no robots.txt; the page was fetched with one request.
- **Licence / terms:** none found; the website of a professional association. Cite ANBAI and NBEMS.
- **Processing:** `scrapers/anbai_dnb.py`:
  - specialty cells split on commas, with broken and missing commas repaired, then mapped to 71 canonical names;
  - old state names updated, and Andhra Pradesh listings in Telangana cities moved to Telangana;
  - a hand-written `related_services` tag added per specialty.

  Details are in `docs/anbai-dnb.md`.
- **Known limitations:**
  - The page has **no "last updated" date**, and its Andhra Pradesh/Telangana listings suggest parts of it are out of date.
  - No addresses or PIN codes. The city field is sometimes a district, locality or road.
  - Covers DNB teaching hospitals only (about 650).
  - `related_services` is our hint, not the source's.
- **Cite as:** Association of National Board Accredited Institutions. *DNB Accredited Institutions.* https://anbai.org/DNB_accredited_institutions.php. Accessed 2026-11-21.
- **Per-row citation:** `source_url` and `scraped_at` in `dnb_hospitals_bronze.csv`. A silver table should add `row_citation`.

## 7. NMC medical colleges and courses
- **What:** every medical college recognized by the National Medical Commission (911 colleges), with its MBBS and postgraduate courses (11,583 college × course rows: MD/MS, diploma, DM, M.Ch.) and approved seats. Address, city, PIN and website come from each college's detail record.
- **Publisher:** National Medical Commission (NMC), Government of India.
- **Where:**
  - [List of colleges teaching MBBS](https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs) and [List of colleges teaching PG courses](https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-pg-courses).
  - Data comes from the pages' own JSON endpoints: `/college-courses/list`, `/college-courses/pg-list`, `/college-courses/detail/<id>`.
  - Files: `datasets/external/nmc_bronze/` — `nmc_colleges_bronze.csv`, `nmc_college_courses_bronze.csv`, `nmc_specialty_reference_bronze.csv`, `nmc_colleges_bronze.sqlite`. API responses are in `raw/`, which is git-ignored.
- **Retrieved:** 2026-11-21. NMC's records show they were last updated 2026-11-04. robots.txt allows all paths; detail requests were spaced 0.5 s apart.
- **Licence / terms:** a public government website; no explicit open-data licence found. Cite NMC.
- **Personal data:** the detail endpoint also returns named staff contacts, mobile numbers and email addresses. **These were dropped before saving.** Only institutional fields are kept.
- **Processing:** `scrapers/nmc_colleges.py`:
  - degree prefixes and diploma suffixes removed to get specialty names;
  - course level (MBBS / PG degree / PG diploma / DM / M.Ch.) recorded;
  - service tags from regex rules;
  - states mapped to the silver names.

  Details are in `docs/nmc-colleges.md`.
- **Known limitations:**
  - 300 of 911 colleges have no valid PIN. `city` is sometimes a locality.
  - A college and its teaching hospital may have different names.
  - New colleges with only a recent Letter of Permission may not have a fully working hospital yet.
  - `related_services` is our hint.
- **Cite as:** National Medical Commission. *List of Colleges Teaching MBBS* and *List of Colleges Teaching PG Courses.* https://nmc.org.in/. Accessed 2026-11-21.
- **Per-row citation:** `source_pages` and `snapshot_date` in `nmc_colleges_bronze.csv`.

## 8. Trauma Care Facilities (MoHFW NPPMT&BI)
- **What:** the 196 Trauma Care Facilities sanctioned in government hospitals and medical colleges under the National Programme for Prevention & Management of Trauma and Burn Injuries (11th and 12th Five Year Plans, 2007–2017), with trauma level I/II/III. 32 states/UTs.
- **Publisher:** Ministry of Health and Family Welfare, in a written answer to the Rajya Sabha.
- **Where:** Rajya Sabha Unstarred Question No. 2048, answered 10 March 2026, Annexure-I: https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars. File: `datasets/external/trauma_care_bronze/trauma_care_facilities_bronze.csv`. The PDF is in `raw/`, which is git-ignored.
- **Retrieved:** 2026-11-21 (one download).
- **Licence / terms:** a public parliamentary record; no explicit licence. Cite the Rajya Sabha answer.
- **Processing:** `scrapers/mohfw_trauma_centres.py`:
  - Annexure-I read with `pypdf`, with state cells carried across page breaks;
  - the trauma level taken from the end of each row;
  - a hand-checked `place` column (corrected spellings, current names) and a keyword-based `facility_type` added;
  - the script refuses to write unless it finds 196 rows, each with a state, level and place.

  Details are in `docs/trauma-care-facilities.md`.
- **Known limitations:**
  - **"Sanctioned" doesn't mean "functional today"**: the answer doesn't confirm functionality, beds or staff.
  - Government hospitals only.
  - Names are informal. `place` and `facility_type` are our additions.
- **Cite as:** Ministry of Health and Family Welfare. *Rajya Sabha Unstarred Question No. 2048: Establishment of Trauma Centres near National Highways*, Annexure-I. Answered 10 March 2026. https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars. Accessed 2026-11-21.
- **Per-row citation:** `source_doc`, `source_url`, `as_of_date` (and `sno_in_source`) in the CSV.

## 9. LaQshya-certified labour rooms and maternity OTs
- **What:** 2,173 LaQshya certifications (1,229 labour room, 902 maternity operating theatre, 42 department not stated) at 1,343 public facilities in 32 states/UTs. A certified maternity OT is government evidence of caesarean-section capability.
- **Publisher:** National Health Systems Resource Centre (NHSRC), Ministry of Health and Family Welfare (LaQshya programme).
- **Where:** "LaQshya Master data" PDF dated 08-04-2026: https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf (linked from https://qps.nhsrcindia.org/laqshya/quality-Certification-Status). Files: `datasets/external/laqshya_bronze/` — `laqshya_certifications_bronze.csv` (one row per certification) and `laqshya_facilities_bronze.csv` (one row per facility). The PDF is in `raw/`, which is git-ignored.
- **Retrieved:** 2026-11-21 (one download). The site's robots.txt returns "forbidden", so it sets no rules.
- **Licence / terms:** a government publication; no explicit open-data licence found. Cite NHSRC/MoHFW.
- **Processing:** `scrapers/nhsrc_laqshya.py`:
  - the table read with `pdfplumber`, following its grid lines (needed to tell the Certified and Conditional columns apart);
  - cells where text overflowed into the next column repaired: 129 type/district cells, state overflow, 3 department cells, and 9 facility names fixed by hand, all flagged `cells_repaired` / `name_repaired`;
  - certifications rolled up to facilities, with validity checked against the build date;
  - validation: serials 1–2,173 complete and unique.

  Details are in `docs/laqshya.md`.
- **Known limitations:**
  - **Many certifications have expired.** Only 200 of the 901 maternity-OT facilities were valid on 2026-11-21.
  - 531 certifications are conditional.
  - 42 recent rows don't name a department.
  - Public facilities only. Some districts are still truncated.
- **Cite as:** National Health Systems Resource Centre. *LaQshya Master Data (certified labour rooms and maternity OTs), 08-04-2026.* Ministry of Health and Family Welfare, Government of India. https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf. Accessed 2026-11-21.
- **Per-row citation:** `source_url`, `list_date`, `source_page` and `sno_in_source` in `laqshya_certifications_bronze.csv`.

## 10. National Cancer Grid members
- **What:** 421 Indian member institutions of the National Cancer Grid: 376 cancer centres/units, 31 NGOs/charities, 8 professional societies and 6 research institutions. Each has an address (386 with a PIN), state and website.
- **Publisher:** National Cancer Grid (NCG), set up by the Department of Atomic Energy, Government of India, and run from Tata Memorial Centre, Mumbai.
- **Where:** https://www.ncgindia.org/hospitals-and-institutions/members. Data comes from the page's fragment endpoint `/hospitalsandinstitutions/_index`. File: `datasets/external/ncg_bronze/ncg_members_bronze.csv`. HTML fragments are in `raw/`, which is git-ignored.
- **Retrieved:** 2026-11-21, with 5 requests 1 s apart. robots.txt allows all paths. (The older address, tmc.gov.in/ncg, rejects scripted requests and wasn't used.)
- **Licence / terms:** the site footer says "© 2026 The National Cancer Grid (NCG). All rights reserved." We use only the factual member list (name, address, type), for non-commercial research, and cite NCG. Check with organizers before redistributing it outside the datathon.
- **Processing:** `scrapers/ncg_members.py`: one request per member type to label each member; PIN taken from the address; states mapped to the silver names; only `cancer_centre` members tagged `cancer_care`. Details are in `docs/ncg-members.md`.
- **Known limitations:**
  - Membership is not a licence or an inspection.
  - It doesn't say which cancer treatments a member offers.
  - Some entries are hospital groups or head offices.
  - Some addresses are cut short by the site.
- **Cite as:** National Cancer Grid. *Member List: Hospitals & Institutions.* Tata Memorial Centre, Mumbai. https://www.ncgindia.org/hospitals-and-institutions/members. Accessed 2026-11-21.
- **Per-row citation:** `source_url` and `snapshot_date` in the CSV.

---

## Template for a new source
```markdown
## N. <Dataset name>
- **What:** <one line: what each row is, how many rows>
- **Publisher:** <organization>
- **Where:** <URL(s); file path in repo>
- **Retrieved:** <YYYY-MM-DD>
- **Licence / terms:** <licence or "none found">
- **Processing:** <script/notebook chain → table names>
- **Known limitations:** <coverage, age, quirks>
- **Cite as:** <Publisher. *Title.* Where. URL. Accessed YYYY-MM-DD.>
- **Per-row citation:** <column name, if the silver table has one>
```
