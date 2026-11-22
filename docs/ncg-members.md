# National Cancer Grid (NCG) Members

The **National Cancer Grid** is a network of cancer hospitals, research institutions, patient groups and professional societies. It was set up by the Government of India's Department of Atomic Energy and is run from Tata Memorial Centre, Mumbai. Members in the **"Cancer Centres / Units"** category are hospitals that treat cancer and have joined NCG's shared standards (treatment guidelines, virtual tumour boards, quality programmes). Membership is outside evidence that a hospital runs a **cancer service**. It partly stands in for the AERB radiotherapy list, which we couldn't get.

- **Source:** https://www.ncgindia.org/hospitals-and-institutions/members
- **Script:** `scrapers/ncg_members.py`. Needs `requests` and `beautifulsoup4`.
- **Output:** `datasets/external/ncg_bronze/ncg_members_bronze.csv`
- **Snapshot:** 2026-11-21. **421 Indian members:** 376 cancer centres/units, 31 NGOs/charities, 8 professional societies and 6 research institutions. 386 have a PIN code, and they cover 32 states/UTs.
- **Status:** bronze, not yet verified by the team.

## How the website works
The member page fills its table from an HTML fragment endpoint, `/hospitalsandinstitutions/_index?type_id=&country_id=&state_id=`. The script makes **5 requests, 1 s apart**: one for all Indian members (grouped by state), and one per member type to label each member. robots.txt allows all paths. (The older address, tmc.gov.in/ncg, rejects scripted requests through a firewall, so it isn't used.)

```bash
python scrapers/ncg_members.py              # fetch and build (saves raw/ fragments)
python scrapers/ncg_members.py --offline    # rebuild from raw/
```

## Columns
| Column | Meaning |
|---|---|
| `ncg_member_id` | hash of state + name + address |
| `member_name`, `name_norm` | the name as published / normalized for matching |
| `member_type` | `cancer_centre`, `research_institution`, `ngo_charity` or `professional_society` |
| `address` | as published; sometimes cut short by the site |
| `pincode_clean` | the last valid 6-digit PIN in the address (it accepts "400 012"). NULL for 35 members. |
| `state_group`, `state_clean` | the state heading on the site / the official name matching `silver_facilities.state_clean` |
| `is_national_member` | 1 for members listed under "National" (mostly professional societies) |
| `website` | the member's website, if listed |
| `related_services` | `cancer_care` for cancer centres/units only; empty for the other types |

## ⚠️ Watch-outs
1. **Membership isn't a licence or an inspection.** Hospitals apply to join and commit to NCG's standards, but NCG doesn't certify their equipment. Treat it as medium-strength evidence: stronger than a facility's own claim, weaker than AERB radiotherapy licensing or a DM/M.Ch. oncology course (NMC).
2. **Only `cancer_centre` members count as service evidence.** NGOs, societies and research institutes aren't treatment facilities.
3. **"Cancer care" is broad.** Membership doesn't say which treatments a hospital offers (surgery, chemotherapy, radiotherapy). Cross-check with the NMC oncology courses or the DNB Radio Therapy / Medical Oncology accreditations for specifics.
4. **Some members are hospital groups or head offices** ("Apollo Hospitals Enterprise Limited", "Regd Office – …"). Match on PIN and city as well as the name, and check by hand.
5. **No match is not evidence against a facility.** About 380 cancer centres is a fraction of the hospitals that treat cancer.
