# Silver Tables: What They Contain and How to Use Them Safely

> **Naming rule:** a column being in a silver table means it is clean, so cleaned columns have plain names (`state`, `pincode`, `latitude`…) with no `_clean` suffix. Raw versions they replace are kept only in the bronze table.

Built by `notebooks/01_bronze_to_silver.py`. All tables are written to `<target_catalog>.<target_schema>`, which defaults to `workspace.datathon`.

## Tables

| Table | One row per | Use it for |
|---|---|---|
| `facilities_bronze` | source row | Raw copy of the Marketplace table. Control characters such as NUL bytes are removed, nothing else is changed. |
| `facilities_silver` | facility (`facility_id`) | Everything: filtering, distance, scoring, display. |
| `silver_facility_claims` | facility × field × claimed item | Matching a service (e.g. dialysis) and **quoting the evidence**. |
| `silver_possible_duplicates` | suspected duplicate pair | Avoiding recommending the same place twice. |
| `silver_dq_summary` | data-quality flag | How common each problem is (good for the presentation). |
| `facilities_validation` | check | Silver-vs-bronze accuracy checks; all must pass or `facilities_silver` isn't overwritten. |
| `silver_rejected_facilities` | removed record | Every record removed from silver and why (`INVALID_ID`, `NAME_MISSING`, `NAME_IS_LIST`, `NO_COORDS_OR_ADDRESS`, `UNDER_MIN_FILLED_SHARE`). |

## Coordinates must match the address
Using the India Post directory (`pincode_silver` / `pincode_centroids_silver`, built by notebook 04, **which must run first**):
- A facility's coordinates must be within **25 km plus the PIN's own spread** of its PIN's centre point, and inside its state's area (the box around that state's post offices, padded 0.25°).
- **If not, `latitude`/`longitude` are set to NULL.** `coord_status` becomes `nulled_pin_mismatch` or `nulled_state_mismatch`, with the matching `dq_flags`. `km_from_pin_centre` keeps the distance of the original point.
- Also flagged (coordinates kept): `PIN_NOT_IN_DIRECTORY` (the PIN doesn't exist in the directory) and `STATE_NOT_SERVED_BY_PIN` (the PIN doesn't serve that state).
- Local dry run (`scripts/dryrun_coordinate_checks.py`): about 1,490 facilities (~15%) lose their coordinates this way, many of them merged records (e.g. a Delhi PIN with a Puducherry point).

## Validation against bronze
Before writing, the notebook checks the new silver table against `facilities_bronze`, and stops without overwriting `facilities_silver` if anything fails (results in `facilities_validation`):
- **Rows:** bronze rows = merged + rejected rows.
- **Values:** every ID exists in bronze and is a UUID; IDs are unique; names, PINs, coordinates, state and numbers all come from that facility's bronze rows.
- **Coordinate rule:** no kept coordinate breaks the PIN or state rule.

## What is removed from silver
**Rows** (each logged in `silver_rejected_facilities`):
1. `unique_id` is not a UUID. In the raw file these are fragments of other records, created where a description had line breaks and the rest of the row spilled into new rows with shifted columns. There are 88 in `data/raw/facilities.csv`, and they include every blank or list-shaped name.
2. Name is missing, or is a list of strings.
3. No usable coordinates and no address at all.
4. Fewer than 30% of the kept source columns are filled in (`source_fill_share < 0.30`).

**Columns** (still in `facilities_bronze` if you need them): source_types, source_ids, source_content_id, organization_type, content_table_id, phone_numbers, websites, acceptsVolunteers, facebookLink, address_country, address_countryCode, countries, affiliationTypeIds, area, distinct_social_media_presence_count, affiliated_staff_presence, custom_logo_presence, number_of_facts_about_the_organization, post_metrics_*, engagement_metrics_*, source, cluster_id, source_urls. The `coordinates`, `latitude` and `longitude` columns are kept.

**Raw address columns, replaced by cleaned ones:** `address_line1/2/3` → `address_full`/`address_street`/`address_region`/`address_landmark`, `address_city` → `city`, `address_stateOrRegion` → `state`, `address_zipOrPostcode` → `pincode`. The raw columns are dropped from silver. **If a value can't be standardized, the cleaned column is left NULL**: e.g. "Mumbai" typed in the state field gives `state = NULL` with the `STATE_UNRECOGNIZED` flag, and a broken PIN like "56" gives `pincode = NULL` with `PINCODE_MISSING_OR_INVALID`. The originals stay in `facilities_bronze`.

## Key columns in `facilities_silver`

| Column | Meaning |
|---|---|
| `facility_id` | Source `unique_id` (always a UUID, lower case), after merging rows that shared it. |
| `address_full` | Formatted address: street, region, city, state PIN. Use this for display. |
| `address_street` | House/plot/building number plus street, road or lane ("#422, 1st Floor, 27th Main Road"). |
| `address_region` | Locality, neighbourhood, sector or area ("Hsr Layout, Sector-1"). |
| `address_landmark` | Directions ("Next To Icici Bank; Near Byculla Station"). |
| `pincode_from_address_text` | True if the PIN field was invalid and `pincode` was found inside the address lines. |
| `source_fill_share` | Share of kept source columns that are filled in (0–1). Always ≥ 0.30 in silver. |
| original columns (`name`, `description`, `capability`…) | The source text with whitespace trimmed and "null"-like values set to NULL. **Quote these as evidence.** |
| `latitude`, `longitude` | Coordinates checked to be inside India, with swapped lat/lon fixed (from `latitude`/`longitude`, falling back to the `coordinates` GeoJSON). NULL if the location can't be used. The raw columns are only in bronze. |
| `coord_status` | `ok`, `swapped_fixed`, `missing`, `zero`, `outside_india`, `nulled_pin_mismatch`, `nulled_state_mismatch` |
| `coords_low_precision` | Both coordinates have 2 or fewer decimal places (about ±1 km or worse, often a city-centre point). |
| `pincode` | A valid 6-digit PIN code, or NULL. |
| `state` | The standardized state or union territory. Taken from the reported state; if that's missing, inferred from the PIN code (`state_from_pin`). |
| `pin_state_consistent` | Whether the reported state fits the PIN prefix. NULL if either is missing. |
| `city` | Title-cased city name, with old names replaced by current ones (Bombay → Mumbai, Bangalore → Bengaluru…). |
| `year_established`, `num_doctors`, `capacity` | Numbers; implausible values are set to NULL. (The raw `yearEstablished`, `numberDoctors` and `capacity` text are only in bronze.) |
| `n_specialties`, `n_capability`, `n_procedure`, `n_equipment`, `n_service_claims` | How many items each list contains. |
| `completeness_score` | 0–1: the share of 13 key fields that are filled in. |
| `dq_flags`, `dq_flag_count` | Data-quality issue codes (see below). |
| `n_source_rows`, `source_row_ids`, `name_variants`, `description_all`, `state_variants`, `pincode_variants`, `dup_coord_spread_km` | How the duplicate-ID merge went. |
| `possible_duplicate_ids` | Other facility IDs that look like the same place. |
| `states_mentioned_in_text` | State names found in the name or description. |

## Data-quality flags (`dq_flags`)

| Flag | Meaning |
|---|---|
| `MISSING_COORDS` / `COORDS_ZERO` / `COORDS_OUTSIDE_INDIA` | The location can't be used for distance. |
| `COORDS_NULLED_PIN_MISMATCH` / `COORDS_NULLED_STATE_MISMATCH` | The coordinates didn't match the PIN or state, so they were set to NULL. |
| `PIN_NOT_IN_DIRECTORY` | The PIN isn't in the India Post directory. |
| `STATE_NOT_SERVED_BY_PIN` | The facility's state isn't one the PIN serves. |
| `COORDS_SWAPPED_FIXED` | Latitude and longitude were swapped in the source; we swapped them back. |
| `COORDS_LOW_PRECISION` | Coordinates are probably approximate (city-centre point). |
| `PINCODE_MISSING_OR_INVALID` | No valid 6-digit PIN code. |
| `PINCODE_FROM_ADDRESS_TEXT` | The PIN code came from the address text, not the PIN field. |
| `ADDRESS_NO_STREET` | No street-level address could be parsed, only locality or city. |
| `STATE_UNRECOGNIZED` | We couldn't work out the state (it was missing or unreadable, and the PIN didn't settle it). |
| `STATE_INFERRED_FROM_PIN` | The state came from the PIN code, not from the record. |
| `PIN_STATE_MISMATCH` | The reported state and the PIN prefix disagree, so one of them is wrong. |
| `YEAR_IMPLAUSIBLE` / `DOCTORS_IMPLAUSIBLE` / `CAPACITY_IMPLAUSIBLE` | The source had a value, but it was impossible, so it was set to NULL. |
| `NO_SERVICE_CLAIMS` | Specialties, capability, procedure and equipment are all empty. |
| `DUPLICATE_ID_MERGED` | Several source rows shared this ID and were merged. |
| `DUP_ROWS_COORD_CONFLICT` / `DUP_ROWS_STATE_CONFLICT` / `DUP_ROWS_PINCODE_CONFLICT` | The merged rows disagreed on location, so this may be two different places. |
| `TEXT_MENTIONS_MULTIPLE_STATES` | The name or description mentions 2 or more states. Possibly a merged record or a chain. |
| `TEXT_STATE_DIFFERS` | The text mentions a state that isn't `state`. |
| `POSSIBLE_NEAR_DUPLICATE` | Another facility ID looks like the same place. |

---

## ⚠️ Watch-outs when using and filtering silver

### Lists and missing values
1. **Lists are never NULL; they're empty.** Use `size(capability) > 0` or `n_capability > 0`, never `capability IS NOT NULL`, which is always true.
2. **Missing doesn't mean zero.** Year established, number of doctors and beds are missing for 50–75% of facilities. Don't treat a missing value as 0 in a score, and don't filter on `capacity > 50` unless you're happy to drop three-quarters of the data. Treat missing values as "unknown" and say so.
3. **Don't treat `completeness_score` as quality.** A well-documented facility isn't necessarily a better one. Use it to express *confidence*, not *rank*.

### Service matching
4. **Every service in the data is a claim the facility made, not a verified fact.** Silver only cleans the data; it doesn't verify anything. A facility with "Dialysis" in `capability` *says* it does dialysis.
5. **Match on `silver_facility_claims.claim_norm`, quote `claim_text`.** Use synonyms and spelling variants: dialysis / haemodialysis / hemodialysis / renal replacement; NICU / neonatal intensive care; C-section / caesarean / cesarean / LSCS.
6. **Be careful with substring matching.** `LIKE '%ent%'` matches "equipm*ent*" and "pati*ent*". Use word boundaries (`RLIKE '\\bent\\b'`) or exact items.
7. **Searching descriptions can catch negatives:** "referred out for dialysis", "no ICU". Treat the description as weaker evidence than the structured lists.
8. **A specialty isn't the service.** "Nephrology" ≠ dialysis, and "Obstetrics" ≠ emergency C-section capability. Score indirect evidence lower than a direct claim.
9. **The equipment list backs up claims.** A dialysis claim plus "dialysis machine" in `equipment` is stronger than the claim alone.

### Location and distance
10. **`latitude`/`longitude` in silver are already validated.** The raw values (which may be swapped, zero or outside India) are only in `facilities_bronze`.
11. **When `latitude` is NULL, don't silently drop the facility.** Decide deliberately: fall back to a PIN-code centroid, or show it as "location unknown".
12. **Low-precision coordinates (`coords_low_precision`) can be ±1 km or more.** Many facilities may share one city-centre point, so treat small distance differences as ties.
13. **Prefer filtering on `state`, distance or PIN code over `city`.** City spellings vary even after cleaning (the alias list only covers common renames), and the city field is self-reported.
14. **`STATE_INFERRED_FROM_PIN` and `PIN_STATE_MISMATCH` mean the location is uncertain.** Say so to the user.

### Duplicates
15. **Facilities merged from several rows (`n_source_rows > 1`) have their lists combined.** If `DUP_ROWS_*_CONFLICT` is also set, those may be two different facilities, and the services may come from either one.
16. **Near-duplicates are flagged, not removed.** When showing a top-N list, collapse results that appear in each other's `possible_duplicate_ids`. Otherwise the same hospital can appear twice.
17. **The near-duplicate rules are heuristics:** names ≥85% similar or one contains the other, within 2 km. Expect some misses and some false alarms. Facilities on the edge of a ~1 km grid square can be missed.

### Flags and the text checks
18. **Flags are information, not filters.** `WHERE dq_flag_count = 0` throws away a large share of the data. Choose per use: for distance, care about the coordinate flags; for service claims, care about `NO_SERVICE_CLAIMS` and the duplicate conflicts.
19. **The text-based state flags are soft.** A Gurugram hospital "near Delhi" gets `TEXT_STATE_DIFFERS`. Use them as a nudge to check, not as proof.

### Running it as a team
20. **Re-run the notebook; don't edit silver tables by hand.** Every run overwrites all tables.
21. **Each teammate has their own workspace and tables.** Results only match if everyone runs the same notebook version from the same branch.
22. **Address parsing is rule-based.** `address_street`, `address_region` and `address_landmark` are a best effort (e.g. an unlabelled place name on line 1 is treated as part of the street). The raw address columns are not in silver; when exact wording matters, join to `facilities_bronze` on `lower(trim(unique_id)) = facility_id`.
24. **`source_urls` is not in silver** (it was dropped on request). To show the web pages a record came from, join back to `facilities_bronze` on `unique_id`.
23. **The source table name depends on what each person named the catalog** when they added the Marketplace listing. Set it in the `source_table` box at the top of the notebook.


### Kayakalp validation handoff (2026-11-21)

See the [Kayakalp validation and integration handoff](kayakalp-validation-handoff.md) for verified metrics, unchanged schema, reproducibility and Databricks instructions.

Kayakalp flag additions (all retain award records):

- `INVALID_SERIAL`: null/unparseable/nonpositive serial. Blocks notebook output before writing.
- `FINANCIAL_YEAR_UNEXPECTED`: missing or non-2021-22 year. Blocks output; the notebook's PDF metadata only supports 2021-22.
- `INVALID_SOURCE_PAGE`: null/unparseable/nonpositive PDF page; citation needs review.
- `AWARD_CATEGORY_UNRECOGNIZED`: missing or unsupported category; inspect `award_raw`.
- `MISSING_SOURCE_FILE`, `MISSING_SOURCE_URL`: incomplete provenance; inspect the Bronze import or URL widget.
- `DISTRICT_HEALTH_JURISDICTION`: health district, HD abbreviation or municipal corporation in the source district field; not automatically a civil district.
- `DISTRICT_SPACING_VERIFIED`: exact source-verified Meghalaya spacing repair for North Garo Hills / East Khasi Hills; original retained.
- `AWARD_ORDINAL_IN_RAW`: first/second rank distinction in `award_raw`; simplified rank is insufficient for detailed comparison.
- `FACILITY_TYPE_CONFLICT`: a single reported type differs from the inferred name type; neither automatically establishes the correct type.

`POSSIBLE_DUPLICATE_AWARD` remains a name/geography/category candidate flag, including cross-type awards. All 20 flagged rows in this PDF form ten UPHC/HWC pairs; preserve them until reviewed. Flags are review evidence, not identity or quality conclusions. The notebook's default output is now `kayakalp_silver_validation`, with `write_output=false`; it no longer refreshes a shared Silver table automatically.
