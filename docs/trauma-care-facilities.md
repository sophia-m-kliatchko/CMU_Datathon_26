# Trauma Care Facilities (MoHFW trauma programme)

Government hospitals designated as **Trauma Care Facilities (TCFs)** under MoHFW's National Programme for Prevention & Management of Trauma and Burn Injuries (NPPMT&BI). The aim of the programme is a trauma network along national highways. Being on this list is outside evidence that a hospital was set up and funded to handle **trauma and emergencies**.

- **Source:** Rajya Sabha Unstarred Question No. 2048, answered 10 March 2026, Annexure-I ([PDF](https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars)). A public Parliament answer.
- **Script:** `scrapers/mohfw_trauma_centres.py`. It downloads the PDF once and reads the table from the PDF text. Needs `requests` and `pypdf`.
- **Output:** `datasets/external/trauma_care_bronze/trauma_care_facilities_bronze.csv`
- **Size:** 196 facilities in 32 states/UTs. 6 are Level I, 76 Level II and 114 Level III.
- **Status:** bronze, not yet verified by the team.

```bash
python scrapers/mohfw_trauma_centres.py                 # download and build
python scrapers/mohfw_trauma_centres.py --pdf <file>    # build from a saved copy
```

## Columns
| Column | Meaning |
|---|---|
| `tcf_id` | `tcf_001`–`tcf_196`, from the serial number in the PDF |
| `facility_name_raw` | name exactly as printed, typos included (e.g. "Kishanjanj", "Allhabad"). **Quote this one.** |
| `name_norm` | lower-case, punctuation removed, for matching |
| `place` | the town or city, **added by hand from the name**, with spelling corrected and current names (Kishanganj, Prayagraj (Allahabad), Belagavi…). The PDF has no address column. |
| `state_listed` / `state_clean` | state as printed / official name matching `silver_facilities.state_clean` |
| `trauma_level`, `trauma_level_label` | 1/2/3 and "Level I/II/III". **Level I is the highest.** |
| `trauma_level_meaning` | a general description of the tier (ours, not from the PDF) |
| `facility_type` | medical_college / district_hospital / sub_district_or_taluk / chc_or_phc / other_government_hospital, a keyword guess from the name |
| `ownership` | always Government |
| `status_in_source` | always `sanctioned` (see watch-out 1) |
| `related_services` | `trauma;emergency`: the same tags as the DNB and NMC datasets |
| `source_doc`, `source_url`, `as_of_date` | provenance |

## How the PDF was parsed
- In the PDF, the state cell spans several rows and is printed once per group. The script carries the state forward, including across page breaks (Meghalaya, Sikkim and Uttarakhand continue onto the next page).
- A state name at the start of a row counts as a new state only if it differs from the current one. That keeps "Chhattisgarh Institute of Medical Sciences" as a facility name, not a state label.
- Level cells with stray characters are cleaned ("CuttackI" → Cuttack, Level I; "III." → III).
- The script stops with an error unless exactly 196 rows are found and every row has a state, a level and a place. That catches a changed PDF layout.

## ⚠️ Watch-outs
1. **"Sanctioned" doesn't mean "working today."** These facilities were sanctioned in 2007–2017. The question asked about functionality, beds and doctors, and the answer didn't give them. Show it as "designated a Level II trauma care facility under the national programme", not as "has a working trauma centre".
2. **Only government hospitals, and only this programme.** Not being on the list says nothing against a hospital. Private trauma centres and state-run programmes aren't included.
3. **The names are short and informal** ("DH Sagar", "Medical College, Guntur", "GMCH, Kolhapur"). Match on `state_clean` + `place` first, then on the type of facility. The Virtue Foundation name may be quite different (e.g. "District Hospital, Faizabad" may appear as "District Hospital Ayodhya").
4. **`place` and `facility_type` are our additions,** derived from the name and reviewed by hand. Check them before relying on them.
5. **Many Level I/II facilities are medical colleges** that also appear in the NMC dataset (`datasets/external/nmc_bronze/`). The two can be cross-linked for stronger combined evidence: trauma designation plus an emergency medicine or orthopaedics department.
