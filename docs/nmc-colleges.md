# NMC Medical Colleges and Their Courses

Outside evidence from the **National Medical Commission (NMC)**, India's regulator for medical education. Every medical college runs a teaching hospital. NMC only permits a postgraduate course in a specialty when the hospital has that department with enough patients, faculty and equipment. A college with approved **D.M. Nephrology** seats almost certainly runs dialysis, and one with **D.M. Neonatology** seats runs a NICU.

- **Source pages:** [MBBS colleges](https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs) · [PG courses](https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-pg-courses)
- **Scraper:** `scrapers/nmc_colleges.py`
- **Output:** `datasets/external/nmc/`
- **Snapshot:** 2026-11-21. NMC's own records were last updated on 2026-11-04.
- **Size:** 911 colleges (839 with MBBS, 645 with PG courses, 219 with super-specialty courses) and 11,583 college × course rows (839 MBBS, 9,079 MD/MS, 299 diploma, 722 DM, 644 M.Ch.) across 103 PG specialties. Detail coverage: 819 colleges with a city, 611 with a valid PIN, 831 with a website.

## How the website works
Both pages are empty shells: JavaScript fills the tables from JSON endpoints, and the scraper calls those endpoints directly. robots.txt allows all paths.

| Endpoint | Returns | Requests needed |
|---|---|---|
| `/college-courses/list?page=1&per_page=1000` | MBBS: one row per college (839) | 1 |
| `/college-courses/pg-list?page=N&per_page=1000` | PG: one row per college × course (10,744) | 11 |
| `/college-courses/detail/<college_id>` | address, city, **PIN**, website for one college | 1 per college (~900), 0.5 s apart |

**Personal data:** the detail endpoint also returns named staff contacts, mobile numbers and email addresses. These are dropped before anything is saved; only institutional fields are kept.

```bash
python scrapers/nmc_colleges.py                 # everything (~15-20 min; details are cached, so re-runs resume)
python scrapers/nmc_colleges.py --skip-details  # the lists only, ~1 min (no address / PIN)
python scrapers/nmc_colleges.py --offline       # rebuild the CSVs and SQLite from raw/ without fetching
```

## Files

| File | One row per | Key columns |
|---|---|---|
| `nmc_colleges.csv` | college | `college_id`, `college_code`, `college_name`, `name_norm`, `state_clean`, `city`, `pincode_clean`, `address`, `website`, `management_type` (Government / Private / Trust), `inception_year`, `mbbs_seats`, `n_pg_courses`, `n_pg_seats`, `n_super_specialty_courses`, `super_specialties` |
| `nmc_college_courses.csv` | college × course | `course_level` (MBBS / PG degree / PG diploma / Super-specialty (DM) / Super-specialty (M.Ch.)), `course_name` (as published), `specialty` (degree prefix removed), `is_clinical`, `related_services`, `approved_seats`, `recognition_status`, `lop_date` |
| `nmc_specialty_reference.csv` | PG specialty | `course_levels`, `is_clinical`, `related_services`, `n_colleges`, `total_seats` |
| `nmc_colleges.sqlite` | the 3 tables, plus the view `v_service_evidence` (college × service, with the courses behind it, whether any is super-specialty, and seats) | |
| `raw/` | API responses as fetched (details with contacts removed) | provenance and offline rebuilds |

**Into Databricks:** upload the CSVs with **Create table → Upload file**, e.g. as `workspace.datathon.ext_nmc_colleges` and `ext_nmc_college_courses`.

## How strong is each kind of evidence?
| Course level | What it means | Strength as service evidence |
|---|---|---|
| **Super-specialty (DM / M.Ch.)** | 3-year training after MD/MS in one narrow field (D.M. Nephrology, M.Ch. Neurosurgery). Needs a dedicated department. | **Strong** |
| **PG degree (MD / MS)** | Broad specialty training (M.S. Obstetrics and Gynaecology, M.D. Emergency Medicine). | Good for broad services; e.g. M.S. OBG implies 24×7 obstetric emergencies, including C-sections. |
| **PG diploma** | 2-year diploma, an older and smaller programme. | Moderate |
| **MBBS only** | The college runs a general teaching hospital with all basic departments. | Weak for any specific service, but confirms a large hospital exists. |

More seats (`approved_seats`) means a bigger department.

## ⚠️ Watch-outs
1. **A match is evidence for a facility; no match is not evidence against it.** About 900 colleges are listed, against about 10,000 facilities in our data, and most good private hospitals aren't medical colleges.
2. **`related_services` is a hint we wrote, not something NMC says.** Present it as "has approved D.M. Nephrology training (4 seats)", not as "does dialysis". The rules are in `SERVICE_RULES` in the script, and they use the same tags as the ANBAI/DNB dataset so the two can be combined.
3. **The college and its teaching hospital often have different names** ("X Medical College" vs "X Hospital", or a government medical college attached to a district hospital). Name matching will miss some. Match on PIN code or city plus state first, then on name, and check by hand.
4. **New colleges (recent `lop_date`, "LoP granted… for AY 2026-27") may not have a working hospital at full scale yet.** A Letter of Permission is the first step, not full recognition. Look at `recognition_status`.
5. **`recognition_status` is free text** ("Recognized…", "Permitted…", "Annual renewal…"). It's kept as published rather than parsed.
6. **`specialty` names come from NMC** and differ from the DNB names ("Otorhinolaryngology/ENT" vs "Otorhinolaryngology (ENT)"). Use `related_services` to combine the two sources, not the specialty text.
7. **Non-clinical departments** (Anatomy, Physiology, Community Medicine, Forensic Medicine…) have `is_clinical = 0` and no service tags. Every medical college has them.
8. **PIN codes are missing or invalid for 300 of 911 colleges** (the API sometimes gives only the city). `pincode_clean` is NULL there.
9. **`city` is sometimes a locality** ("Maharanipeta" for Visakhapatnam). Use the college name, PIN and address as well.
10. **`raw/` is about 23 MB**, mostly the PG list pages. Consider `.gitignore`-ing `raw/` and keeping only the CSVs in git; you can rebuild with `--offline` only if you have `raw/`.

## Next step: matching to `silver_facilities`
1. Block on `state_clean`, then on `pincode_clean` = silver `pincode_clean`, or the same city.
2. Compare names fuzzily (≥85%, the same rule as the silver near-duplicate step). Strip words like "medical college", "institute of medical sciences", "and hospital" before comparing.
3. Review borderline matches by hand.
