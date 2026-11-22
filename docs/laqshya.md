# LaQshya-Certified Labour Rooms and Maternity Operating Theatres

**LaQshya** is the Health Ministry's quality certification for labour rooms and maternity operating theatres (OTs) in public health facilities, run by NHSRC. Assessors check each facility against national standards before certifying it.
- A certified **maternity OT** is direct government evidence that the facility performs **caesarean sections**.
- A certified **labour room** is evidence of facility-based delivery care.

This is the strongest obstetric evidence we have, and it stands in for the First Referral Unit list we couldn't get.

- **Source:** NHSRC Quality & Patient Safety portal, "LaQshya Master data" PDF dated **2026-04-08** ([PDF](https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf)). A public government document, downloaded once.
- **Script:** `scrapers/nhsrc_laqshya.py`. Needs `requests` and `pdfplumber`.
- **Output:** `datasets/external/laqshya_bronze/`
- **Size:** 2,173 certifications (1,229 labour room, 902 maternity OT, 42 with no department stated) at **1,343 facilities** in 32 states/UTs. 901 facilities have a maternity OT certification. Facility types: 608 district hospitals, 315 sub-district hospitals, 314 community health centres, 106 medical colleges.
- **Status:** bronze, not yet verified by the team.

```bash
python scrapers/nhsrc_laqshya.py                 # download and build
python scrapers/nhsrc_laqshya.py --pdf <file>    # build from a saved copy
```

## Files

| File | One row per | Key columns |
|---|---|---|
| `laqshya_certifications_bronze.csv` | certification (facility × department) | `cert_row_id`, `laqshya_facility_id`, `state_clean`, `district`, `facility_type_code` (DH / SDH / CHC / MC), `facility_name_raw`, `name_norm`, `department` (Labour Room / Maternity OT / Not stated), `certification_status` (certified / conditional), `result_date`, `validity_date`, `valid_on_list_date`, `valid_on_build_date`, `related_services`, plus `*_raw` columns and repair flags |
| `laqshya_facilities_bronze.csv` | facility | `has_maternity_ot_cert`, `maternity_ot_valid_until`, `maternity_ot_valid_now`, `has_labour_room_cert`, `labour_room_valid_until`, `labour_room_valid_now`, `any_conditional`, `n_certifications`, `related_services`, `cert_row_ids` |

`related_services` uses the same tags as the other datasets:
- maternity OT → `obstetrics;emergency_c_section`
- labour room → `obstetrics;normal_delivery`

## How the PDF was parsed
- **`pdfplumber` follows the table's grid lines.** This matters because "Certified" and "Conditionality" are two separate Yes/blank columns, and only the cell position tells them apart. Plain text extraction loses that.
- **Long text overflows into the next column**, and the letters of the two texts interleave. These rows are repaired and flagged:
  - **Type cell** (129 rows): it holds the real code mixed with the end of a truncated district, e.g. "PDUHRAM" = DH + "puram" → district Thiruvananthapuram, type DH. The script finds the longest known code (SDH, CHC, PHC, DH, MC) that can be read in order within the cell, matching as late as possible, and adds the leftover letters back to the district. Four districts get exact fixes on top (`DISTRICT_FIXES`). Flagged with `cells_repaired = 1`; the original values are in `district_raw` and `facility_type_raw`.
  - **State overflow** ("hEast Siang", the "h" of "Pradesh"): the stray lowercase letters at the start are removed.
  - **Department cell** (3 rows): if "Labour Room" or "Maternity OT" can be read in order within the cell, that's the department.
  - **Facility names** (9 rows): restored by hand in `NAME_REPAIRS`, after checking the letter counts. Flagged with `name_repaired = 1`.
- **Checks:** every serial number from 1 to 2,173 is present exactly once, every date parses, and every state maps to an official name.
- **Facility roll-up** groups certifications by state + normalized name + the first 5 letters of the district. The district is truncated differently in different rows, so a full-name match would split facilities.

## ⚠️ Watch-outs
1. **Many certifications have expired.** Only 200 of the 901 maternity OT facilities, and 307 facilities overall, have a certification still valid today. Certifications last 1–3 years (conditional ones less). An expired certification still shows the facility *had* a working maternity OT when assessed, so use two strengths:
   - valid now → strongest evidence;
   - expired → strong evidence that the facility had the capability; cite the date.
2. **"Conditional" certifications** (531 rows) passed with conditions. Count them as evidence, but slightly weaker.
3. **42 recent rows (serials 2132–2173) have no department.** They're kept as "Not stated", tagged only `obstetrics`, and never as C-section evidence.
4. **Public facilities only, and only those assessed.** Not being on the list says nothing against a facility.
5. **Names are informal and inconsistent** ("CHC Bobblli", "GH Aalo", "FRU HOSKOTE TALUK HOSPITAL"). Match on `state_clean` + `district` first, then fuzzy-match the name.
6. **Districts can still be truncated** where the overflow didn't land in the type cell. Compare by prefix.
