# Data Sources and Citations

**Rule (see `CLAUDE.md`):** every table we scrape, download, convert or assemble gets an entry here **in the same commit that adds it**. Each entry says where the data came from, who published it, when we got it, the licence or terms, how we turned it into a table, and how to cite it. Silver tables built from outside sources also carry **per-row citation columns** (`source_name`, `source_publisher`, `source_url`, `retrieved_on`, `source_license`, `produced_by`, `row_citation`), so any recommendation can cite its evidence.

Items marked **⚠ TODO** still need information from the person who added the data.

## Summary

| Table(s) | Source | Publisher | Retrieved | Built by |
|---|---|---|---|---|
| `bronze_facilities`, `silver_facilities`, `silver_facility_claims`, `silver_possible_duplicates`, `silver_dq_summary`; file `data/raw/facilities.csv` | Virtue Foundation India healthcare facilities dataset (Databricks Marketplace) | Virtue Foundation | 2026-11-21 | `notebooks/01_bronze_to_silver.py` |
| `nqas_bronze`, `nqas_silver`; file `data/external/nqas_certified_facilities.csv` | NQAS Certified Facilities list | NHSRC, MoHFW | 2026-11-21 | `scripts/scrape_nqas.py` → `notebooks/02_nqas_bronze_to_silver.py` |
| `kayakalp_bronze`, `kayakalp_silver`; file `data/external/kayakalp_2021_22.csv` | Kayakalp Winner Facilities of FY 2021-22 (PDF) | NHSRC, MoHFW (Kayakalp scheme) | 2026-11-21 | `scripts/kayakalp_pdf_to_csv.py` → `notebooks/03_kayakalp_bronze_to_silver.py` |
| file `data/raw/india_post_pincode_directory.csv` | All India Pincode Directory | Department of Posts, via data.gov.in | ⚠ TODO | not yet processed |
| file `data/raw/nfhs_5_district_health_indicators.csv` | NFHS-5 (2019-21) district factsheets | IIPS / MoHFW, via data.gov.in | ⚠ TODO | not yet processed |

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
- **Retrieved / converted:** 2026-11-21. The PDF itself is not committed to the repo; re-download it from the link above.
- **Licence / terms:** a government publication; no explicit open-data licence was found. We cite NHSRC/MoHFW.
- **Processing:** `scripts/kayakalp_pdf_to_csv.py` (pdfplumber) → CSV → upload as `kayakalp_bronze` → `notebooks/03_kayakalp_bronze_to_silver.py` → `kayakalp_silver`.
- **Known limitations:**
  - In 17 rows, district text had spilled into the State column; this was repaired and flagged `DISTRICT_REPAIRED_FROM_PDF`.
  - Some states wrote "village, block, district" in the district field; it's split into `locality` and `district_clean`.
  - Public facilities only, and FY 2021-22 only.
- **Cite as:** National Health Systems Resource Centre. *List of Kayakalp Winner Facilities FY 2021-22.* Ministry of Health and Family Welfare, Government of India. https://qps.nhsrcindia.org/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf. Accessed 2026-11-21.
- **Per-row citation:** the `row_citation` column in `kayakalp_silver`, which gives the PDF page and S.No.

## 4. India Post Pincode Directory
- **What:** about 165k post offices with PIN, district, state and latitude/longitude.
- **Publisher:** Department of Posts, Government of India, via the Open Government Data Platform: https://data.gov.in/resource/all-india-pincode-directory-till-last-month.
- **Where:** `data/raw/india_post_pincode_directory.csv`, added by JhK830 on 2026-11-21 as "original Datathon raw datasets". **⚠ TODO (JhK830): confirm the exact source** (data.gov.in or supplied by the datathon) **and the download date.** The official data.gov.in file may not include coordinates, so the coordinates may come from elsewhere.
- **Licence:** Government Open Data License – India (GODL), if it came from data.gov.in.
- **Cite as:** Department of Posts. *All India Pincode Directory.* Open Government Data Platform India. ⚠ TODO: date.

## 5. NFHS-5 district health indicators
- **What:** National Family Health Survey 5 (2019-21) indicators for 706 districts. `*` means suppressed; values in parentheses are based on small samples.
- **Publisher:** International Institute for Population Sciences (IIPS) for the Ministry of Health and Family Welfare: https://rchiips.org/NFHS/factsheet_NFHS-5.shtml. Also on data.gov.in: https://data.gov.in/catalog/national-family-health-survey-5-nfhs-5-india-districts-factsheet-data.
- **Where:** `data/raw/nfhs_5_district_health_indicators.csv`, added by JhK830 on 2026-11-21. Column names are already snake_case, so it was probably pre-processed by the datathon or a teammate. **⚠ TODO (JhK830): confirm the exact source and date.**
- **Licence:** GODL (data.gov.in), if it came from there.
- **Cite as:** International Institute for Population Sciences (IIPS) and ICF. *National Family Health Survey (NFHS-5), 2019-21: District Fact Sheets.* Mumbai: IIPS, 2021.

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
