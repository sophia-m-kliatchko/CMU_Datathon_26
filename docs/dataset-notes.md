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

## How this applies to our challenge
- The previous team's question was whether each facility really exists. Ours is whether it offers *this service*, and whether it's the best choice from *here*. We can reuse their checks for existence and duplicates as one part of our trust score.
- Descriptions are short (median about 16 tokens), so most of the evidence for a service will come from the capability, procedure and equipment lists. The description text can back that up or contradict it.
- Every cleaning rule above is a decision to record in `DEVLOG.md`.
