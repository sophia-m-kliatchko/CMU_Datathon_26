# Dataset Notes: Virtue Foundation India Facilities

Lessons we've collected about the dataset. Anything not yet checked against our own copy of the data is marked **(unverified)**.

## Sources
- A previous team's write-up (DAIS 2026 hackathon, Peter Tadrous): https://github.com/petertadrous/2026-dbx-hackathon/blob/main/Virtue%20Foundation%20Dataset%20(DAIS%202026).md
- That team's issue log: https://github.com/petertadrous/2026-dbx-hackathon/blob/main/docs/data-quality-notes.md
- Our challenge brief (CMU Datathon Fall 2026), which gives field coverage numbers.

## Where the data lives
- Unity Catalog table **(unverified for our Marketplace listing)**: `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities`
- About 10,000 rows, one row per reported facility. It's roughly a 0.5% sample of a larger national dataset.
- Our brief says there are 51 attributes. The previous write-up only documents the 12 below, so run `DESCRIBE TABLE` to get the full list.

## Key columns (from the previous write-up)
| Column | Type | Notes |
|---|---|---|
| `unique_id` | string | **Not unique.** The same ID can appear on 2 or 3 rows (address variants or transliterations). |
| `name` | string | Some rows contain NUL bytes (`\x00`). |
| `address_zipOrPostcode` | string | 6-digit PIN, but not always valid. Keep it as a string. |
| `address_city` | string | Self-reported; spelling and casing aren't standardized. |
| `address_stateOrRegion` | string | Self-reported; doesn't always match the state the coordinates fall in. |
| `latitude`, `longitude` | float | Some are null; some land in the ocean or another country. |
| `capability` | array\<string\> | For example "Maternity", "NICU", "ICU". The main field for evidence of a service. |
| `procedure` | array\<string\> | Procedures offered. |
| `equipment` | array\<string\> | Equipment the facility lists. |
| `description` | string | Free text; about 16 tokens at the median, so it's short. May contain URLs. |
| `yearEstablished` | int/string | Can be in the future, before 1947, or missing. |

> **Coverage numbers disagree:** the previous write-up says capability, procedure and equipment are each 99.7% populated. Our brief says procedure is 92.5% and equipment is 77.0%. The difference is probably empty arrays (`[]`) being counted as populated. Check `size(col) > 0`, not just `IS NOT NULL`.

## Known data-quality problems
1. **Duplicate `unique_id`.** Deduplicate when loading. Merging the duplicate rows beats keeping just the first one: dropping a row can throw away the correct coordinates or services.
2. **Near-duplicates under different IDs.** These look like similar names in the same PIN code, within about 1 km of each other. The previous team used MinHash on capability, procedure and equipment combined to flag them as "contested".
3. **NUL bytes in strings.** Writes to Delta or Postgres fail with `CHARACTER_NOT_IN_REPERTOIRE`. Strip `\x00` from every string column before writing.
4. **Bad or missing coordinates.** Check that each point falls inside India, and ideally inside the state the record lists.
5. **One PIN code, several places.** A PIN can cover several post offices and districts, so aggregate to one centroid per PIN before joining.
6. **Inconsistent city and state names.** Locating a facility from its coordinates (a spatial join) is more reliable than matching place names.
7. **Implausible `yearEstablished` values.** Treat values in the future or before 1947 as unreliable.

## Optional extra datasets (Open Government Data License India, data.gov.in)
- **India Post PIN Code Directory:** about 165,000 rows covering 19,586 PINs, with latitude and longitude for most rows. Useful for turning a user's PIN into coordinates and for checking PINs in our records. Each row is one post office, not one PIN, so aggregate before joining.
- **NFHS-5 district health indicators:** 706 districts, 109 indicators. `*` means suppressed (treat it as NULL), and values in parentheses come from small samples. Useful as context, such as showing which districts are underserved.
- **District boundaries** (geoBoundaries or DataMeet India): for point-in-polygon joins (`ST_Contains`, or GeoPandas/Shapely).

## Outside datasets for checking care quality and reliability

These are free public sources that can **back up or contradict** a facility's claims. Links were found on 2026-11-21 and not all were opened, so check each one is live and note the snapshot date before using it. Many are searchable websites or PDFs rather than CSVs, so expect to scrape or convert them.

**Matching to our facilities:** these sources share no ID with the Virtue Foundation data. Match on normalized name plus PIN code or distance; the silver notebook's near-duplicate step already normalizes names this way. **A match is evidence for a facility; no match is NOT evidence against it.** Many lists only cover public hospitals or members of one scheme. Show a match as a badge ("✓ PM-JAY approved for dialysis"), not as a penalty.

**Getting files into Databricks:** Free Edition's serverless compute may not be able to download from the internet. The safe route is to download on your own computer, then upload to a Unity Catalog Volume or use **Create table → Upload file**.

### Priority 1: strongest evidence for this challenge
| Dataset | What it proves | Link(s) | Notes |
|---|---|---|---|
| **PM-JAY (Ayushman Bharat) approved hospitals** | The hospital passed an inspection to join the national insurance scheme. The list shows **which specialties** each hospital is approved for. | [hospitals.pmjay.gov.in/Search](https://hospitals.pmjay.gov.in/Search) · [Approval guidelines (NHA PDF)](https://nha.gov.in/img/resources/Hospital-Empanelment-Guidelines-21-12-22.pdf) | Search portal, filterable by state, district and specialty; no bulk download found. All public hospitals in participating states count as approved automatically. About 30k hospitals (Oct 2024). |
| **NABH accredited hospitals** | Third-party quality accreditation, the main hospital quality standard in India. | [nabh.co](https://nabh.co/), under Patient → Find an Accredited Healthcare Organisation | Includes both full and entry-level accreditation. |
| **National Dialysis Programme (PMNDP) centres** | Government-supported dialysis centres, by district. | [pmndp.mohfw.gov.in](https://pmndp.mohfw.gov.in/en/about-us) · [NHSRC PMNDP state table](https://qps.nhsrcindia.org/pmndp-map-table) · [State lists (Vikaspedia)](https://en.vikaspedia.in/health/nrhm/national-health-programmes-1/pradhan-mantri-national-dialysis-programme) | About 1,400+ centres in 36 states and UTs (count date unclear). |
| **LaQshya certified labour rooms and maternity operating theatres** | Quality-certified obstetric care, which bears directly on **emergency C-section** and high-risk delivery. | [LaQshya master list PDF (Apr 2026)](https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf) · [NHSRC Quality dashboard](https://qps.nhsrcindia.org/) | Gives state, district, facility, department and validity dates. About 1,250 labour-room and 920 maternity-OT certifications. Public facilities only. |
| **NQAS certified facilities** | Government quality certification for public facilities. | [NQAS map and report](https://qps.nhsrcindia.org/nqas-map-report) · [NHSRC quality map](https://nhsrcindia.org/quality-map-home) | About 21k certified facilities. |
| **Blood bank directory** | Blood supply nearby, needed for C-section, trauma and burns. | [e-RaktKosh nearby blood banks](https://eraktkosh.mohfw.gov.in/BLDAHIMS/bloodbank/nearbyBBRed.cnt) · [Blood Bank Directory (AIKosh)](https://aikosh.indiaai.gov.in/home/datasets/details/blood_bank_directory_updated_till_last_month.html) | Check whether there are latitude/longitude columns. Older copies had missing and wrong coordinates. |

### Evidence for specific services
| Dataset | What it proves | Link(s) | Notes |
|---|---|---|---|
| **NBEMS / DNB accredited hospital departments** | The hospital is approved to train specialists in a **named specialty** (e.g. nephrology, neonatology), so that specialty is really practised there. | [NBEMS accreditation portal](https://accr.natboard.edu.in/) · [DNB seats by state and specialty (PDF)](https://natboard.edu.in/notice_for_dnb_candidates/Status%20of%20DNB%20Seats%20-%20Bulletin_StatewiseSpecialitywise_WU26022009.pdf) · [Renewal list Jan 2026 (PDF)](https://accr.natboard.edu.in/online_user/DOCUMENTS/misc/information_bulletin_chapter/Jan-feb/RENEWAL_JAN_2026.pdf) | Published as PDFs, so they need table extraction. |
| **Medical colleges (NMC)** | Teaching hospitals, usually higher-capability and full-service. | [nmc.org.in](https://nmc.org.in/) (List of College Teaching MBBS / PG) · [State-wise MBBS colleges, 2024-25 seat list (PDF)](https://nmc.org.in/wp-content/uploads/2025/04/Revised%20UG%20Seat%20Matrix%202024-25%20on%2031-03-2025.pdf) | |
| **CGHS approved hospitals** | Approved for the central government employees' health scheme; the list includes NABH status. | [cghs.nic.in hospital list](https://cghs.nic.in/reports/view_hospital.jsp) · [CGHS hospital list (AIKosh)](https://aikosh.indiaai.gov.in/home/datasets/details/list_of_hospitals_empaneled_under_cghs_all_over_india.html) | Covers about 80 cities only. |
| **SNCU (Special Newborn Care Units)** | Newborn intensive care in public facilities (roughly a public-sector NICU). | No link found yet; search NHSRC or the NHM child-health pages. | |
| **First Referral Units (FRUs)** | Public facilities designated for emergency obstetric care, including C-section. | In Rural Health Statistics / Health Dynamics of India (below) and state NHM sites | |
| **Trauma centres (MoHFW trauma programme)** | Level I–III trauma care along highways. | No link found yet. | Pair with the highway black-spot data below. |
| **NOTTO registered hospitals** | Licensed for organ transplants. | No link found yet (notto.mohfw.gov.in). | |
| **Kayakalp awards** | Cleanliness and infection-control scores for public hospitals. | No link found yet; search NHSRC / qps.nhsrcindia.org. | |

### Checking that facilities exist and where they are
| Dataset | Use | Link(s) | Notes |
|---|---|---|---|
| **ABDM Health Facility Registry (HFR)** | The official national registry, giving each facility a 12-digit ID. Searchable by name, location, specialty and type. | [facility.abdm.gov.in](https://facility.abdm.gov.in) | 3.5 lakh+ facilities registered. Search only; no bulk download found. |
| **National Hospital Directory with geo-code** | Government hospital list with coordinates, specialties, PIN and website. | [data.gov.in catalog](https://data.gov.in/catalog/hospital-directory-national-health-portal) · [AIKosh copy](https://aikosh.indiaai.gov.in/home/datasets/details/national_hospital_directory_with_geo_code_and_additional_parameters_updated_till_last_month.html) · [NIN health facilities with geo-code](https://data.gov.in/resource/nin-health-faclities-geo-code-and-additional-parameters-updated-till-last-month) | Some copies are old (2015–2017). Check the date. |
| **All India Health Centres Directory** | Public PHCs, CHCs, sub-centres and district hospitals with coordinates. | [data.gov.in catalog](https://data.gov.in/catalog/all-india-health-centres-directory) | |
| **OpenStreetMap health facilities** | Facilities people have mapped, independent of government lists. | [Geofabrik India extract](https://download.geofabrik.de/asia/india.html) · [Global Healthsites Mapping Project](https://wiki.openstreetmap.org/wiki/Global_Healthsites_Mapping_Project) | Filter on `amenity=hospital/clinic` and `healthcare=*`. |
| **India Post PIN directory** | Turn a user's PIN into coordinates; validate PINs. | [data.gov.in: All India Pincode Directory](https://data.gov.in/resource/all-india-pincode-directory-till-last-month) · [PIN boundary GeoJSON](https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json) · [IndiaPIN, with coordinates (GitHub, Dec 2021)](https://github.com/harshvardhaniimi/IndiaPIN) | The official CSV may lack coordinates. The PIN boundary GeoJSON allows a point-in-polygon check. |

### Context: travel time, population and need
| Dataset | Use | Link(s) | Notes |
|---|---|---|---|
| **Travel time to healthcare, 2020 (Malaria Atlas Project)** | Rank by **travel time**, not straight-line distance. Motorized and walking-only maps on a 1 km grid. | [Malaria Atlas Project accessibility layers](https://malariaatlas.org/?p=458) · [Earth Engine catalog (2019)](https://developers.google.com/earth-engine/datasets/catalog/projects_malariaatlasproject_assets_accessibility_accessibility_to_healthcare_2019) | GeoTIFF raster files. Weiss et al., *Nature Medicine* 2020. |
| **WorldPop** | Where people live, to estimate demand. | [worldpop.org](https://www.worldpop.org/) | Raster files. |
| **Highway accident black spots (MoRTH)** | Accident hotspots for the trauma use case. | [data.gov.in: top-10 black spots per state, 2016–18](https://data.gov.in/resource/states-wise-list-top-ten-black-spots-2016-2018) | 13,795 black spots identified for 2016–22. A newer release (iRAD/e-DAR) has been announced but isn't confirmed. |
| **Rural Health Statistics / Health Dynamics of India** | Public facility infrastructure and specialist staffing by state and district, including FRUs. | [MoHFW statistics archive](https://www.mohfw.gov.in/documents/staistics/archives) · [MoHFW reports](https://main.mohfw.gov.in/documents/reports) | Renamed "Health Dynamics of India" from 2022-23 onward. Published as PDFs. |
| **HMIS** | Service volumes (deliveries, C-sections…) by district. | [hmis.mohfw.gov.in](https://hmis.mohfw.gov.in) | Some HMIS data is also on data.gov.in. |
| **NFHS-5 district factsheets** | District health indicators, e.g. C-section rate and institutional births. | [data.gov.in NFHS-5 district factsheets](https://data.gov.in/catalog/national-family-health-survey-5-nfhs-5-india-districts-factsheet-data) · [IIPS NFHS-5 factsheets](https://rchiips.org/NFHS/factsheet_NFHS-5.shtml) | `*` means suppressed (treat it as NULL); values in parentheses come from small samples. NFHS-6 (2023-24) is now listed too. |
| **District boundaries** | Point-in-polygon state and district checks. | [geoBoundaries](https://www.geoboundaries.org/) · [DataMeet maps](https://github.com/datameet/maps) | |

## How this applies to our challenge
- The previous team's question was whether each facility really exists. Ours is whether it offers *this service*, and whether it's the best choice from *here*. We can reuse their checks for existence and duplicates as one part of our trust score.
- Descriptions are short (median about 16 tokens), so most of the evidence for a service will come from the capability, procedure and equipment lists. The description text can back that up or contradict it.
- Every cleaning rule above is a decision to record in `DEVLOG.md`.
