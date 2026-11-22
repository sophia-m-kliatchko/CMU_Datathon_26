# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze → Silver: Virtue Foundation facilities
# MAGIC
# MAGIC Takes the raw Marketplace table and turns it into **clean, deduplicated, flagged** tables that the rest of the team can build on.
# MAGIC
# MAGIC | Output table | Grain | What it's for |
# MAGIC |---|---|---|
# MAGIC | `facilities_bronze` | 1 row per source row | Raw copy of the Marketplace table. The only changes: invisible control characters (NUL bytes) removed, plus load metadata. |
# MAGIC | `facilities_silver` | 1 row per `facility_id` | Cleaned, typed, merged facilities with data-quality flags. Columns in silver are clean by definition, so cleaned columns have plain names (`state`, `pincode`, `latitude`…) and the raw versions they replace are left out (they stay in bronze). |
# MAGIC | `silver_facility_claims` | 1 row per facility × field × claimed item | Every specialty, capability, procedure and equipment claim, one per row. Use this for service matching and for quoting evidence. |
# MAGIC | `silver_possible_duplicates` | 1 row per suspected duplicate pair | Facilities with different IDs that look like the same place. They are flagged, never deleted. |
# MAGIC | `silver_dq_summary` | 1 row per flag | How many facilities carry each data-quality flag. |
# MAGIC | `silver_rejected_facilities` | 1 row per removed record | Every row the rules below removed, with the reason, so nothing disappears silently. |
# MAGIC | `facilities_validation` | 1 row per check | Silver-vs-bronze accuracy checks (all must pass) |
# MAGIC
# MAGIC **Rows removed from silver** (logged in `silver_rejected_facilities`):
# MAGIC 1. `unique_id` is not a real ID (UUID). These rows are fragments of other records, created where a description contained line breaks (e.g. an "ID" of *oculoplasty*).
# MAGIC 2. Name is missing, or is a list of strings.
# MAGIC 3. No usable coordinates **and** no address at all.
# MAGIC 4. Fewer than 30% of the kept source columns are filled in.
# MAGIC
# MAGIC **Columns dropped from silver** (still in `facilities_bronze`): source_types, source_ids, source_content_id, organization_type, content_table_id, phone_numbers, websites, acceptsVolunteers, facebookLink, address_country, address_countryCode, countries, affiliationTypeIds, area, and every column to the right of `recency_of_page_update` except the coordinates.
# MAGIC
# MAGIC **Addresses** are reorganized into `address_street` (number + street/road/lane + building), `address_region` (locality/area), `address_landmark` ("near…/opp…"), `city`, `state`, `pincode`, plus a combined `address_full`. The raw `address_line1/2/3`, `address_city`, `address_stateOrRegion` and `address_zipOrPostcode` are **dropped** from silver. A value that can't be standardized is left NULL in the cleaned column (not copied over) and flagged; section 7 prints how many. Bronze always keeps the originals.
# MAGIC
# MAGIC **Coordinates must match the address.** Using the India Post directory (`pincode_*` tables from notebook 00), a facility's point must be within 25 km (+ the PIN's own spread) of its PIN's centre and inside its state's area. If not, `latitude`/`longitude` are set to NULL (`coord_status` = `nulled_pin_mismatch` / `nulled_state_mismatch`).
# MAGIC
# MAGIC **Validation:** before `facilities_silver` is written, it is checked against `facilities_bronze` (row counts, IDs, names, PINs, coordinates, state, numbers) and against the coordinate rules. Results go to `facilities_validation`; any failure stops the run and leaves the old `facilities_silver` in place.
# MAGIC
# MAGIC **Run order:** `00_pincode_bronze_to_silver` first, then this notebook.
# MAGIC
# MAGIC **How to run:** attach to serverless compute, check the widgets at the top, then **Run all**. It's safe to re-run, because every table is fully overwritten.
# MAGIC
# MAGIC See `docs/silver-tables.md` for column definitions and the **things to watch out for when filtering**.
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0 · Settings

# COMMAND ----------

dbutils.widgets.text(
    "source_table",
    "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities",
    "1. Source table (Marketplace)",
)
dbutils.widgets.text("target_catalog", "workspace", "2. Target catalog")
dbutils.widgets.text("target_schema", "datathon", "3. Target schema")

SOURCE_TABLE = dbutils.widgets.get("source_table").strip()
CATALOG = dbutils.widgets.get("target_catalog").strip()
SCHEMA = dbutils.widgets.get("target_schema").strip()

# Optional manual column mapping, used if auto-detection (section 2) picks the wrong column.
# Keys: id, name, pincode, city, state, lat, lon, description, year, doctors, capacity,
#       specialties, capability, procedure, equipment
COLUMN_OVERRIDES = {
    # "doctors": "numberDoctors",
}

# ---- Row and column rules (Sophia, 2026-11-21) ----
# Source columns not carried into silver (matched case-insensitively; they stay in facilities_bronze)
DROP_COLUMNS = [
    "source_types", "source_ids", "source_content_id", "organization_type", "content_table_id", "phone_numbers",
    "websites", "acceptsVolunteers", "facebookLink", "address_country", "address_countryCode", "countries",
    "affiliationTypeIds", "area",
]
# Every column to the right of this one is dropped too, except KEEP_AFTER_CUTOFF
DROP_AFTER_COLUMN = "recency_of_page_update"
KEEP_AFTER_CUTOFF = ["coordinates", "latitude", "longitude"]
# A facility needs at least this share of the kept source columns filled in
MIN_FILLED_SHARE = 0.30
# Coordinates must match the address (uses notebook 00's India Post tables): a facility's point must be within
# PIN_MATCH_KM of its PIN's centre point (plus that PIN's own spread) and inside its state's area (padded box).
# If not, latitude/longitude are set to NULL.
PIN_MATCH_KM = 25.0
STATE_BOX_PAD_DEG = 0.25
# A valid unique_id looks like 2b8d1c3e-9f4a-4c1d-8e2f-0a1b2c3d4e5f
ID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")
print(f"Source: {SOURCE_TABLE}\nWriting to: {CATALOG}.{SCHEMA}")

# COMMAND ----------

import re
from datetime import date

from pyspark.sql import functions as F
from pyspark.sql import Window
from pyspark.sql.types import ArrayType, StringType, NumericType

def assert_no_clean_columns(df, table):
    """Silver tables never have *_clean columns: being in silver already means clean."""
    bad = [c for c in df.columns if c.lower().endswith("_clean")]
    assert not bad, f"{table} would get *_clean columns {bad}; use the plain name instead"

def qc(name):
    """Reference a column safely, even if its name has dots or spaces."""
    return F.col(f"`{name}`")

# Control characters, including NUL (\x00), break Delta and Postgres writes. Tab, CR and LF are kept.
CTRL_CHARS = r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
# Values that mean "no data" (compared lower-case, after trimming).
NULL_TOKENS = ["", "null", "none", "nan", "n/a", "na", "-", "--", "[]", "{}", "not available", "unknown"]

# Rough bounding box for India (mainland plus islands)
LAT_MIN, LAT_MAX = 6.0, 37.5
LON_MIN, LON_MAX = 68.0, 97.5

THIS_YEAR = date.today().year
YEAR_MIN = 1800          # Some Indian mission and government hospitals date from the 1800s
DOCTORS_MAX = 10000      # Above this is treated as an extraction error
CAPACITY_MAX = 10000     # beds

# COMMAND ----------

# MAGIC %run ./common/address_parsing

# COMMAND ----------

# MAGIC %run ./common/validation

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Bronze: raw copy of the Marketplace table
# MAGIC Marketplace tables are read-only shares, so we make our own copy. The only change is removing control characters (NUL bytes), because Delta refuses to write them (`CHARACTER_NOT_IN_REPERTOIRE`).

# COMMAND ----------

def strip_ctrl(col, dtype):
    if isinstance(dtype, StringType):
        return F.regexp_replace(col, CTRL_CHARS, "")
    if isinstance(dtype, ArrayType) and isinstance(dtype.elementType, StringType):
        return F.transform(col, lambda x: F.regexp_replace(x, CTRL_CHARS, ""))
    return col

raw = spark.table(SOURCE_TABLE)
bronze = (
    raw.select([strip_ctrl(qc(f.name), f.dataType).alias(f.name) for f in raw.schema.fields])
    .withColumn("_bronze_row_id", F.monotonically_increasing_id())
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source_table", F.lit(SOURCE_TABLE))
)
bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("facilities_bronze")

bronze = spark.table("facilities_bronze")
META_COLS = ["_bronze_row_id", "_ingested_at", "_source_table"]
print(f"facilities_bronze: {bronze.count():,} rows, {len(bronze.columns) - len(META_COLS)} source columns")

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Every column the source table really has (the challenge brief says 51 attributes)
# MAGIC DESCRIBE TABLE facilities_bronze

# COMMAND ----------

# MAGIC %md
# MAGIC ### Profile: how filled-in is each column?
# MAGIC `pct_filled` counts empty strings, "null"-like text and empty lists (`[]`) as **missing**. A plain `IS NOT NULL` check overstates coverage.

# COMMAND ----------

def filled_expr(name, dtype):
    c = qc(name)
    if isinstance(dtype, ArrayType):
        return F.when(F.size(c) > 0, 1).otherwise(0)
    if isinstance(dtype, StringType):
        return F.when(c.isNotNull() & ~F.lower(F.trim(c)).isin(NULL_TOKENS), 1).otherwise(0)
    return F.when(c.isNotNull(), 1).otherwise(0)

src_fields = [f for f in bronze.schema.fields if f.name not in META_COLS]
profile_row = bronze.select(
    F.count(F.lit(1)).alias("__n"),
    *[F.sum(filled_expr(f.name, f.dataType)).alias(f.name) for f in src_fields],
).first().asDict()
n_bronze = profile_row.pop("__n")
profile = spark.createDataFrame(
    [(f.name, f.dataType.simpleString(), int(profile_row[f.name] or 0),
      round(100.0 * (profile_row[f.name] or 0) / max(n_bronze, 1), 1)) for f in src_fields],
    "column string, type string, n_filled long, pct_filled double",
).orderBy("pct_filled")
display(profile)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Work out which column is which
# MAGIC Known names come from a previous team's write-up of this dataset. When a name isn't found, we fall back to a pattern match. **Check the printed mapping.** If something is wrong, fix it in `COLUMN_OVERRIDES` in section 0.

# COMMAND ----------

lower_map = {c.lower(): c for c in bronze.columns if c not in META_COLS}

def resolve(*candidates, pattern=None):
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    if pattern:
        for c in bronze.columns:
            if c not in META_COLS and re.search(pattern, c, re.I):
                return c
    return None

COL = {
    "id":          resolve("unique_id", "facility_id", "id"),
    "name":        resolve("name", "facility_name"),
    "pincode":     resolve("address_zipOrPostcode", "pincode", "postcode", "zipcode", pattern=r"zip|postcode|postal|pin_?code"),
    "city":        resolve("address_city", "city", pattern=r"city"),
    "state":       resolve("address_stateOrRegion", "state", pattern=r"state"),
    "lat":         resolve("latitude", "lat"),
    "lon":         resolve("longitude", "lon", "lng"),
    "description": resolve("description"),
    "year":        resolve("yearEstablished", "year_established", pattern=r"year.*establish|establish.*year"),
    "doctors":     resolve("numberDoctors", "number_of_doctors", "num_doctors", pattern=r"doctor"),
    "capacity":    resolve("capacity", "bed_capacity", "beds", pattern=r"capacity|beds?$"),
    "specialties": resolve("specialties", "specialty", pattern=r"specialt"),
    "capability":  resolve("capability", "capabilities", pattern=r"capabilit"),
    "procedure":   resolve("procedure", "procedures", pattern=r"procedure"),
    "equipment":   resolve("equipment", pattern=r"equipment"),
    "line1":       resolve("address_line1", "address1", "street"),
    "line2":       resolve("address_line2", "address2"),
    "line3":       resolve("address_line3", "address3"),
    "coords_json": resolve("coordinates", "geometry", "location"),
}
COL.update(COLUMN_OVERRIDES)
COL_BRONZE = dict(COL)   # original bronze column names, for the validation checks in section 7

for k, v in COL.items():
    print(f"  {k:<12} -> {v if v else '!! NOT FOUND'}")
assert COL["name"], "Could not find the facility name column; set COLUMN_OVERRIDES['name']."

SERVICE_KEYS = ["specialties", "capability", "procedure", "equipment"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Row-level cleaning
# MAGIC * **Text:** control characters removed, whitespace trimmed, "null"-like values (`""`, `"N/A"`, `"none"`…) set to real NULL.
# MAGIC * **Lists:** list-like text such as `'["ICU","NICU"]'` is parsed into a real `array<string>`, with items trimmed, de-duplicated and blanks removed. **A missing list becomes an empty array, never NULL.**
# MAGIC * **New `*_clean` columns** for PIN code, state, city, coordinates, year, doctors and beds. **The original columns are kept unchanged so they can be quoted as evidence.**

# COMMAND ----------

# Rename any source column whose name collides with a column we're about to create
DERIVED_NAMES = {
    "facility_id", "pincode", "state", "state_from_pin", "pin_state_consistent", "city",
    "latitude", "longitude", "coord_status", "coords_low_precision", "year_established",
    "num_doctors", "capacity", "n_source_rows", "source_row_ids", "name_variants",
    "description_all", "state_variants", "pincode_variants", "dup_coord_spread_km", "possible_duplicate_ids",
    "dq_flags", "dq_flag_count", "completeness_score", "states_mentioned_in_text",
    "n_specialties", "n_capability", "n_procedure", "n_equipment", "n_service_claims",
    "address_street", "address_region", "address_landmark", "address_full", "pincode_from_address_text",
    "source_fill_share", "km_from_pin_centre", "pin_in_directory", "state_matches_pin",
    # Cleaned columns use plain names, so raw source columns with these names are renamed src_<name>
    # (e.g. raw latitude -> src_latitude) and later left out of silver. Silver never has *_clean columns.
    "city", "state", "pincode", "latitude", "longitude", "year_established", "num_doctors", "capacity",
}

# ---- Drop the columns we don't carry into silver ----
src_order = [c for c in bronze.columns if c not in META_COLS]
drop_lower = {d.lower() for d in DROP_COLUMNS}
keep_after = {k.lower() for k in KEEP_AFTER_CUTOFF}
cut = next((i for i, c in enumerate(src_order) if c.lower() == DROP_AFTER_COLUMN.lower()), None)
if cut is None:
    print(f"!! {DROP_AFTER_COLUMN} not found: no columns dropped by position")
TO_DROP = [c for i, c in enumerate(src_order)
           if c.lower() in drop_lower or (cut is not None and i > cut and c.lower() not in keep_after)]
TO_DROP = [c for c in TO_DROP if c not in {COL.get("lat"), COL.get("lon")}]  # never drop the coordinates
print(f"Dropping {len(TO_DROP)} columns from silver: {TO_DROP}")

df = bronze.drop(*TO_DROP)
for c in list(df.columns):
    if c in DERIVED_NAMES:
        df = df.withColumnRenamed(c, f"src_{c}")
        COL = {k: (f"src_{c}" if v == c else v) for k, v in COL.items()}
        print(f"Renamed source column {c} -> src_{c} (name collision)")
print(f"Keeping {len([c for c in df.columns if c not in META_COLS])} source columns: "
      f"{[c for c in df.columns if c not in META_COLS]}")

schema = {f.name: f.dataType for f in df.schema.fields}
src_cols = [c for c in df.columns if c not in META_COLS]

# --- Which text columns actually hold lists? ---
string_cols = [c for c in src_cols if isinstance(schema[c], StringType)]
list_ratio = df.select([
    F.avg(F.when(F.trim(qc(c)).startswith("["), 1.0)
           .when(qc(c).isNotNull() & (F.trim(qc(c)) != ""), 0.0)).alias(c)
    for c in string_cols
]).first().asDict() if string_cols else {}

forced_lists = {COL[k] for k in SERVICE_KEYS if COL.get(k)}
text_never_list = {COL["name"], COL.get("description")}
LIST_FROM_STRING = sorted(
    c for c in string_cols
    if c not in text_never_list and (c in forced_lists or (list_ratio.get(c) or 0) >= 0.5)
)
NATIVE_STR_ARRAYS = [c for c in src_cols
                     if isinstance(schema[c], ArrayType) and isinstance(schema[c].elementType, StringType)]
LIST_COLS = set(LIST_FROM_STRING) | set(NATIVE_STR_ARRAYS)
print("Text columns parsed into lists:", LIST_FROM_STRING)
print("Columns that were already lists:", NATIVE_STR_ARRAYS)

# COMMAND ----------

EMPTY_STR_ARRAY = F.array().cast("array<string>")

def clean_str(col):
    t = F.trim(F.regexp_replace(col, CTRL_CHARS, ""))
    return F.when(F.lower(t).isin(NULL_TOKENS), F.lit(None).cast("string")).otherwise(t)

def parse_list(col):
    """Turn '["a","b"]', "['a', 'b']" or plain 'a' into array<string>."""
    s = F.trim(F.regexp_replace(col, CTRL_CHARS, ""))
    as_json = F.from_json(s, "array<string>")
    # Fallback for Python-style lists with single quotes, which aren't valid JSON
    inner = F.regexp_replace(s, r"^\[|\]$", "")
    parts = F.split(inner, r"""['"]\s*,\s*['"]""")
    fallback = F.transform(parts, lambda x: F.regexp_replace(x, r"""^\s*['"]?|['"]?\s*$""", ""))
    return (F.when(s.isNull() | (s == ""), EMPTY_STR_ARRAY)
             .when(s.startswith("["), F.coalesce(as_json, fallback))
             .otherwise(F.array(s)))

def clean_list(arr):
    t = F.transform(arr, lambda x: F.trim(F.regexp_replace(x, CTRL_CHARS, "")))
    t = F.filter(t, lambda x: x.isNotNull() & ~F.lower(x).isin(NULL_TOKENS))
    return F.coalesce(F.array_distinct(t), EMPTY_STR_ARRAY)

select_exprs = []
for c in df.columns:
    if c in META_COLS:
        select_exprs.append(qc(c))
    elif c in LIST_FROM_STRING:
        select_exprs.append(clean_list(parse_list(qc(c))).alias(c))
    elif c in NATIVE_STR_ARRAYS:
        select_exprs.append(clean_list(qc(c)).alias(c))
    elif isinstance(schema[c], StringType):
        select_exprs.append(clean_str(qc(c)).alias(c))
    else:
        select_exprs.append(qc(c))
df = df.select(select_exprs)

# Any service field that's missing from the source becomes an empty list, so later code stays simple
for k in SERVICE_KEYS:
    if not COL.get(k):
        COL[k] = f"_missing_{k}"
        df = df.withColumn(COL[k], EMPTY_STR_ARRAY)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Reference data: states, aliases, PIN prefixes, renamed cities

# COMMAND ----------

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

def norm_key_py(s):
    return re.sub(r"[^a-z]", "", s.lower().replace("&", " and "))

# Lookup key (lower case, letters only) -> official state or UT name
STATE_ALIASES = {
    "orissa": "Odisha", "od": "Odisha", "or": "Odisha",
    "pondicherry": "Puducherry", "pondy": "Puducherry", "py": "Puducherry",
    "uttaranchal": "Uttarakhand", "uk": "Uttarakhand", "ut": "Uttarakhand",
    "newdelhi": "Delhi", "nctofdelhi": "Delhi", "delhinct": "Delhi", "dl": "Delhi",
    "nationalcapitalterritoryofdelhi": "Delhi",
    "jammukashmir": "Jammu and Kashmir", "jandk": "Jammu and Kashmir", "jk": "Jammu and Kashmir",
    "andamannicobarislands": "Andaman and Nicobar Islands", "andamanandnicobar": "Andaman and Nicobar Islands",
    "andamannicobar": "Andaman and Nicobar Islands", "an": "Andaman and Nicobar Islands",
    "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadranagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu", "damandiu": "Dadra and Nagar Haveli and Daman and Diu",
    "dn": "Dadra and Nagar Haveli and Daman and Diu", "dd": "Dadra and Nagar Haveli and Daman and Diu",
    "chattisgarh": "Chhattisgarh", "chhatisgarh": "Chhattisgarh", "cg": "Chhattisgarh", "ct": "Chhattisgarh",
    "telengana": "Telangana", "ts": "Telangana", "tg": "Telangana",
    "maharastra": "Maharashtra", "mh": "Maharashtra", "gujrat": "Gujarat", "gj": "Gujarat",
    "karnatka": "Karnataka", "ka": "Karnataka", "tamilnad": "Tamil Nadu", "tn": "Tamil Nadu",
    "bengal": "West Bengal", "wb": "West Bengal", "hp": "Himachal Pradesh", "mp": "Madhya Pradesh",
    "up": "Uttar Pradesh", "ap": "Andhra Pradesh", "andhra": "Andhra Pradesh",
    "arunachal": "Arunachal Pradesh", "ar": "Arunachal Pradesh", "as": "Assam", "br": "Bihar", "ga": "Goa",
    "hr": "Haryana", "jh": "Jharkhand", "kl": "Kerala", "mn": "Manipur", "ml": "Meghalaya", "mz": "Mizoram",
    "nl": "Nagaland", "pb": "Punjab", "rj": "Rajasthan", "sk": "Sikkim", "tr": "Tripura", "ch": "Chandigarh",
    "la": "Ladakh", "ld": "Lakshadweep",
}
STATE_LOOKUP = {norm_key_py(s): s for s in STATES}
STATE_LOOKUP.update(STATE_ALIASES)

# Phrases used to spot state names inside free text (official names plus common old names)
STATE_TEXT_PATTERNS = [(s, s) for s in STATES] + [
    ("Orissa", "Odisha"), ("Pondicherry", "Puducherry"), ("Uttaranchal", "Uttarakhand"), ("New Delhi", "Delhi"),
]

# First two digits of a PIN code -> states that prefix can belong to (deliberately generous)
PIN_PREFIX_STATES = {
    "11": ["Delhi"], "12": ["Haryana"], "13": ["Haryana", "Punjab"], "14": ["Punjab"], "15": ["Punjab"],
    "16": ["Punjab", "Chandigarh", "Haryana"], "17": ["Himachal Pradesh"], "18": ["Jammu and Kashmir"],
    "19": ["Jammu and Kashmir", "Ladakh"],
    **{p: ["Uttar Pradesh"] for p in ["20", "21", "22", "23", "27", "28"]},
    **{p: ["Uttar Pradesh", "Uttarakhand"] for p in ["24", "25", "26"]},
    **{p: ["Rajasthan"] for p in ["30", "31", "32", "33", "34"]},
    **{p: ["Gujarat", "Dadra and Nagar Haveli and Daman and Diu"] for p in ["36", "37", "38", "39"]},
    "40": ["Maharashtra", "Goa"], **{p: ["Maharashtra"] for p in ["41", "42", "43", "44"]},
    **{p: ["Madhya Pradesh"] for p in ["45", "46", "47", "48"]}, "49": ["Chhattisgarh", "Madhya Pradesh"],
    "50": ["Telangana"], **{p: ["Andhra Pradesh", "Telangana", "Puducherry"] for p in ["51", "52", "53"]},
    **{p: ["Karnataka"] for p in ["56", "57", "58", "59"]},
    **{p: ["Tamil Nadu", "Puducherry"] for p in ["60", "61", "62", "63", "64"]},
    **{p: ["Kerala", "Lakshadweep", "Puducherry"] for p in ["67", "68", "69"]},
    **{p: ["West Bengal", "Sikkim", "Andaman and Nicobar Islands"] for p in ["70", "71", "72", "73", "74"]},
    **{p: ["Odisha"] for p in ["75", "76", "77"]}, "78": ["Assam"],
    "79": ["Arunachal Pradesh", "Assam", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Tripura"],
    **{p: ["Bihar", "Jharkhand"] for p in ["80", "81", "82", "83", "84", "85"]},
}

# Old or alternate city names -> current official name (lookup keys are lower case)
CITY_ALIASES = {
    "bombay": "Mumbai", "bangalore": "Bengaluru", "calcutta": "Kolkata", "madras": "Chennai",
    "gurgaon": "Gurugram", "poona": "Pune", "baroda": "Vadodara", "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi", "mysore": "Mysuru", "mangalore": "Mangaluru",
    "pondicherry": "Puducherry", "allahabad": "Prayagraj", "benares": "Varanasi", "banaras": "Varanasi",
    "calicut": "Kozhikode", "vizag": "Visakhapatnam", "belgaum": "Belagavi", "hubli": "Hubballi",
    "simla": "Shimla", "trichy": "Tiruchirappalli", "tiruchi": "Tiruchirappalli",
    "gauhati": "Guwahati", "bhubaneshwar": "Bhubaneswar",
}

def map_lit(d, value_fn=F.lit):
    items = []
    for k, v in d.items():
        items += [F.lit(k), value_fn(v)]
    return F.create_map(*items)

STATE_MAP = map_lit(STATE_LOOKUP)
PIN_MAP = map_lit(PIN_PREFIX_STATES, lambda v: F.array(*[F.lit(s) for s in v]))
CITY_MAP = map_lit(CITY_ALIASES)

# COMMAND ----------

def norm_key(col):
    return F.regexp_replace(F.lower(F.regexp_replace(col, "&", " and ")), "[^a-z]", "")

def state_from_text(col):
    """Exact lookup first; otherwise look for a full state name inside the text, longest name first."""
    key = norm_key(col)
    expr = STATE_MAP[key]
    long_keys = sorted([k for k in STATE_LOOKUP if len(k) >= 5], key=len, reverse=True)
    fallback = F.lit(None).cast("string")
    for k in reversed(long_keys):  # build the CASE so the longest key is tested first
        fallback = F.when(key.contains(k), F.lit(STATE_LOOKUP[k])).otherwise(fallback)
    return F.coalesce(expr, fallback)

def first_number(col):
    s = F.regexp_replace(col.cast("string"), r"(?<=\d),(?=\d)", "")  # "1,200" -> "1200"
    x = F.regexp_extract(s, r"(\d+(?:\.\d+)?)", 1)
    return F.when(x != "", x.cast("double"))

def try_double(name):
    return F.expr(f"try_cast(`{name}` AS DOUBLE)")

# ---- facility_id: must be a real ID (UUID). Anything else is a fragment of another record -> removed ----
assert COL.get("id"), "No ID column found; set COLUMN_OVERRIDES['id']."
id_src = F.trim(qc(COL["id"]).cast("string"))
df = df.withColumn("facility_id", F.when(id_src.rlike(ID_PATTERN), F.lower(id_src)))

def _short(c, n=200):
    return F.substring(c.cast("string"), 1, n)

# Rejected rows are kept (with the reason) in silver_rejected_facilities
REJECT_COLS = ["facility_id", "source_row_ids", "id_raw", "name_raw", "reject_reason", "reject_detail"]
rejected_invalid_id = df.where(F.col("facility_id").isNull()).select(
    F.lit(None).cast("string").alias("facility_id"),
    F.array(F.col("_bronze_row_id")).alias("source_row_ids"),
    _short(qc(COL["id"])).alias("id_raw"),
    _short(qc(COL["name"])).alias("name_raw"),
    F.lit("INVALID_ID").alias("reject_reason"),
    F.lit("unique_id is not a UUID; the row is a fragment of another record (columns shifted)").alias("reject_detail"),
)
df = df.where(F.col("facility_id").isNotNull())

# ---- PIN code: the first valid 6-digit code (first digit 1-9) ----
if COL.get("pincode"):
    pin_txt = F.regexp_replace(qc(COL["pincode"]).cast("string"), r"(?<=\d)[\s-](?=\d)", "")
    pin = F.regexp_extract(pin_txt, r"(?<!\d)([1-9]\d{5})(?!\d)", 1)
    df = df.withColumn("pincode", F.when(pin != "", pin))
else:
    df = df.withColumn("pincode", F.lit(None).cast("string"))

df = df.withColumn("_pin_states", PIN_MAP[F.substring("pincode", 1, 2)])

# ---- State: as reported, standardized; inferred from the PIN only when the reported state is missing or unrecognized ----
state_rep = state_from_text(qc(COL["state"])) if COL.get("state") else F.lit(None).cast("string")
df = (
    df.withColumn("_state_reported", state_rep)
      .withColumn("state_from_pin",
                  F.when(F.col("_state_reported").isNull() & (F.size("_pin_states") == 1), F.col("_pin_states")[0]))
      .withColumn("state", F.coalesce("_state_reported", "state_from_pin"))
      .withColumn("pin_state_consistent",
                  F.when(F.col("_state_reported").isNotNull() & F.col("_pin_states").isNotNull(),
                         F.array_contains("_pin_states", F.col("_state_reported"))))
)

# ---- City: collapse spaces, title case, map old names to current ones ----
if COL.get("city"):
    city = F.regexp_replace(qc(COL["city"]), r"\s+", " ")
    city_l = F.lower(city)
    df = df.withColumn(
        "city",
        F.when(city.isNull() | city.rlike(r"^[\d\W_]+$"), F.lit(None).cast("string"))
         .otherwise(F.coalesce(CITY_MAP[city_l], F.initcap(city))),
    )
else:
    df = df.withColumn("city", F.lit(None).cast("string"))

# ---- Coordinates: must fall inside India; swapped lat/lon gets fixed ----
lat0 = try_double(COL["lat"]) if COL.get("lat") else F.lit(None).cast("double")
lon0 = try_double(COL["lon"]) if COL.get("lon") else F.lit(None).cast("double")
if COL.get("coords_json"):
    # Fallback: GeoJSON point {"coordinates":[lon, lat], "type":"Point"} when latitude/longitude are empty
    lat0 = F.coalesce(lat0, F.expr(f"try_cast(get_json_object(`{COL['coords_json']}`, '$.coordinates[1]') AS DOUBLE)"))
    lon0 = F.coalesce(lon0, F.expr(f"try_cast(get_json_object(`{COL['coords_json']}`, '$.coordinates[0]') AS DOUBLE)"))
df = df.withColumn("_lat0", lat0).withColumn("_lon0", lon0)
in_lat = lambda c: c.between(LAT_MIN, LAT_MAX)
in_lon = lambda c: c.between(LON_MIN, LON_MAX)
ok = in_lat(F.col("_lat0")) & in_lon(F.col("_lon0"))
swapped = in_lat(F.col("_lon0")) & in_lon(F.col("_lat0"))
df = (
    df.withColumn("coord_status",
                  F.when(F.col("_lat0").isNull() | F.col("_lon0").isNull(), "missing")
                   .when((F.col("_lat0") == 0) & (F.col("_lon0") == 0), "zero")
                   .when(ok, "ok")
                   .when(swapped, "swapped_fixed")
                   .otherwise("outside_india"))
      .withColumn("latitude", F.when(ok, F.col("_lat0")).when(swapped, F.col("_lon0")))
      .withColumn("longitude", F.when(ok, F.col("_lon0")).when(swapped, F.col("_lat0")))
      # Two or fewer decimal places on both values means roughly ±1 km precision; often a city-centre point
      .withColumn("coords_low_precision",
                  F.when(F.col("latitude").isNotNull(),
                         (F.abs(F.col("latitude") * 100 - F.round(F.col("latitude") * 100)) < 1e-6) &
                         (F.abs(F.col("longitude") * 100 - F.round(F.col("longitude") * 100)) < 1e-6)))
)

# ---- Year established / doctors / beds: numbers only, implausible values set to NULL ----
if COL.get("year"):
    y = F.regexp_extract(qc(COL["year"]).cast("string"), r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", 1)
    y = F.when(y != "", y.cast("int"))
    df = df.withColumn("year_established", F.when(y.between(YEAR_MIN, THIS_YEAR), y))
else:
    df = df.withColumn("year_established", F.lit(None).cast("int"))

for key, out, mx in [("doctors", "num_doctors", DOCTORS_MAX), ("capacity", "capacity", CAPACITY_MAX)]:
    if COL.get(key):
        v = first_number(qc(COL[key]))
        df = df.withColumn(out, F.when((v >= 1) & (v <= mx), v.cast("int")))
    else:
        df = df.withColumn(out, F.lit(None).cast("int"))

# ---- How complete each source row is (used to choose the best row when merging duplicates) ----
row_fields = [c for c in src_cols if c in df.columns]
df = df.withColumn(
    "_row_completeness",
    sum((F.when(F.size(qc(c)) > 0, 1).otherwise(0) if c in LIST_COLS
         else F.when(qc(c).isNotNull(), 1).otherwise(0)) for c in row_fields),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Merge rows that share a `unique_id`
# MAGIC Some IDs appear on 2–3 rows. Rather than keeping one row and dropping the rest (which can throw away the correct coordinates or services), we **merge**:
# MAGIC * **Single values:** taken from the most complete row, with gaps filled from the other rows.
# MAGIC * **Coordinates:** latitude and longitude always come from the **same** row, choosing the best row that has valid coordinates.
# MAGIC * **Lists** (services, equipment…): the union of all rows.
# MAGIC * The other versions are kept in `name_variants`, `description_all`, `state_variants` and `pincode_variants`. Conflicts between rows become flags.

# COMMAND ----------

w_grp = Window.partitionBy("facility_id")
w_best = Window.partitionBy("facility_id").orderBy(F.desc("_row_completeness"), F.asc("_bronze_row_id"))
w_best_all = w_best.rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing)
w_coord = (Window.partitionBy("facility_id")
           .orderBy(F.col("latitude").isNull().asc(), F.desc("_row_completeness"), F.asc("_bronze_row_id"))
           .rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing))

COORD_COLS = [c for c in [COL.get("lat"), COL.get("lon")] if c] + \
             ["_lat0", "_lon0", "coord_status", "latitude", "longitude", "coords_low_precision"]
SKIP = set(COORD_COLS) | {"facility_id", "_bronze_row_id", "_row_completeness"}

merged_exprs = [F.col("facility_id")]
for c in df.columns:
    if c in SKIP:
        continue
    if c in LIST_COLS or c.startswith("_missing_"):
        merged_exprs.append(F.array_distinct(F.flatten(F.collect_list(qc(c)).over(w_grp))).alias(c))
    else:
        merged_exprs.append(F.first(qc(c), ignorenulls=True).over(w_best_all).alias(c))

coord_struct = F.first(F.struct(*[qc(c).alias(c) for c in COORD_COLS])).over(w_coord)
desc_col = qc(COL["description"]) if COL.get("description") else F.lit(None).cast("string")

merged = (
    df.select(
        *merged_exprs,
        coord_struct.alias("_coords"),
        F.count(F.lit(1)).over(w_grp).alias("n_source_rows"),
        F.collect_list("_bronze_row_id").over(w_grp).alias("source_row_ids"),
        F.array_distinct(F.collect_list(qc(COL["name"])).over(w_grp)).alias("name_variants"),
        F.array_distinct(F.collect_list(desc_col).over(w_grp)).alias("description_all"),
        F.array_distinct(F.collect_list("state").over(w_grp)).alias("state_variants"),
        F.array_distinct(F.collect_list("pincode").over(w_grp)).alias("pincode_variants"),
        (F.max("latitude").over(w_grp) - F.min("latitude").over(w_grp)).alias("_dlat"),
        (F.max("longitude").over(w_grp) - F.min("longitude").over(w_grp)).alias("_dlon"),
        F.row_number().over(w_best).alias("_rn"),
    )
    .where("_rn = 1")
    .select("*", "_coords.*")
    .drop("_coords", "_rn")
    .withColumn("dup_coord_spread_km",
                F.round(F.sqrt(F.pow(F.col("_dlat") * 111.0, 2) +
                               F.pow(F.col("_dlon") * 111.0 * F.cos(F.radians("latitude")), 2)), 2))
    .drop("_dlat", "_dlon")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Service counts, state mentions in the text, completeness
# MAGIC These are written to a staging table first, so the duplicate search in section 6 doesn't recompute everything above.

# COMMAND ----------

all_text = F.lower(F.concat_ws(" ", F.col("name_variants"), F.col("description_all")))
mentions = F.array(*[F.when(all_text.rlike(r"\b" + re.escape(p.lower()) + r"\b"), F.lit(canon))
                     for p, canon in STATE_TEXT_PATTERNS])

stage = (
    merged
    .withColumn("states_mentioned_in_text", F.array_distinct(F.filter(mentions, lambda x: x.isNotNull())))
    .withColumn("n_specialties", F.size(qc(COL["specialties"])))
    .withColumn("n_capability", F.size(qc(COL["capability"])))
    .withColumn("n_procedure", F.size(qc(COL["procedure"])))
    .withColumn("n_equipment", F.size(qc(COL["equipment"])))
    .withColumn("n_service_claims", F.col("n_specialties") + F.col("n_capability") + F.col("n_procedure") + F.col("n_equipment"))
)

key_fields = [
    qc(COL["name"]).isNotNull(),
    F.col("latitude").isNotNull(),
    F.col("pincode").isNotNull(),
    F.col("state").isNotNull(),
    F.col("city").isNotNull(),
    desc_col.isNotNull() if COL.get("description") else F.lit(False),
    F.col("n_specialties") > 0, F.col("n_capability") > 0, F.col("n_procedure") > 0, F.col("n_equipment") > 0,
    F.col("year_established").isNotNull(),
    F.col("num_doctors").isNotNull(),
    F.col("capacity").isNotNull(),
]
stage = stage.withColumn(
    "completeness_score",
    F.round(sum(F.when(k, 1).otherwise(0) for k in key_fields) / F.lit(len(key_fields)), 3),
)

# ---- Addresses: split line1/2/3 into street / region / landmark (common/address_parsing) ----
def raw_or_null(key):
    return qc(COL[key]).cast("string") if COL.get(key) else F.lit(None).cast("string")

stage = (stage
    .withColumn("_addr", parse_address_udf(raw_or_null("line1"), raw_or_null("line2"), raw_or_null("line3"),
                                           raw_or_null("city"), raw_or_null("state"), raw_or_null("pincode")))
    .withColumn("address_street", F.col("_addr.street"))
    .withColumn("address_region", F.col("_addr.region"))
    .withColumn("address_landmark", F.col("_addr.landmark"))
    # If the PIN field was unusable but a valid PIN appears inside the address text, use that
    .withColumn("pincode_from_address_text",
                F.col("pincode").isNull() & F.coalesce(F.col("_addr.pin_from_text").rlike(r"^[1-9]\d{5}$"), F.lit(False)))
    .withColumn("pincode", F.when(F.col("pincode_from_address_text"), F.col("_addr.pin_from_text"))
                                  .otherwise(F.col("pincode")))
    .withColumn("_state_pin", F.concat_ws(" ", "state", "pincode"))
    .withColumn("address_full", F.concat_ws(", ", "address_street", "address_region", "city",
                                            F.when(F.col("_state_pin") != "", F.col("_state_pin"))))
    .drop("_state_pin")
    .drop("_addr")
)

# ---- Coordinates must match the PIN and state (India Post directory, built by notebook 00) ----
PIN_CENTROIDS = f"{CATALOG}.{SCHEMA}.pincode_centroids_silver"
PIN_OFFICES = f"{CATALOG}.{SCHEMA}.pincode_silver"
assert spark.catalog.tableExists(PIN_CENTROIDS) and spark.catalog.tableExists(PIN_OFFICES), (
    "Run notebooks/00_pincode_bronze_to_silver first: checking coordinates against PIN and state "
    "needs pincode_centroids_silver and pincode_silver.")
pin_ref = spark.table(PIN_CENTROIDS).select(
    F.col("pincode").alias("_ref_pin"), F.col("latitude").alias("_ref_lat"), F.col("longitude").alias("_ref_lon"),
    F.coalesce(F.col("max_office_distance_km"), F.lit(0.0)).alias("_ref_spread"), F.col("states").alias("_ref_states"))
state_box = (spark.table(PIN_OFFICES).where("latitude IS NOT NULL AND state IS NOT NULL")
             .groupBy(F.col("state").alias("_box_state"))
             .agg((F.min("latitude") - STATE_BOX_PAD_DEG).alias("_box_lat_min"),
                  (F.max("latitude") + STATE_BOX_PAD_DEG).alias("_box_lat_max"),
                  (F.min("longitude") - STATE_BOX_PAD_DEG).alias("_box_lon_min"),
                  (F.max("longitude") + STATE_BOX_PAD_DEG).alias("_box_lon_max")))

def outside_state_box(lat, lon):
    return ~(lat.between(F.col("_box_lat_min"), F.col("_box_lat_max")) &
             lon.between(F.col("_box_lon_min"), F.col("_box_lon_max")))

stage = (stage
    .join(F.broadcast(pin_ref), F.col("pincode") == F.col("_ref_pin"), "left")
    .join(F.broadcast(state_box), F.col("state") == F.col("_box_state"), "left")
    .withColumn("km_from_pin_centre",
                F.round(haversine_km_col(F.col("latitude"), F.col("longitude"), F.col("_ref_lat"), F.col("_ref_lon")), 2))
    .withColumn("_pin_mismatch", F.col("latitude").isNotNull() & F.col("_ref_lat").isNotNull() &
                                 (F.col("km_from_pin_centre") > F.lit(PIN_MATCH_KM) + F.col("_ref_spread")))
    .withColumn("_state_mismatch", F.col("latitude").isNotNull() & F.col("_box_state").isNotNull() &
                                   outside_state_box(F.col("latitude"), F.col("longitude")))
    .withColumn("pin_in_directory", F.when(F.col("pincode").isNotNull(), F.col("_ref_pin").isNotNull()))
    .withColumn("state_matches_pin", F.when(F.col("state").isNotNull() & F.col("_ref_states").isNotNull(),
                                            F.array_contains(F.col("_ref_states"), F.col("state"))))
    .withColumn("coord_status", F.when(F.coalesce(F.col("_pin_mismatch"), F.lit(False)), F.lit("nulled_pin_mismatch"))
                                 .when(F.coalesce(F.col("_state_mismatch"), F.lit(False)), F.lit("nulled_state_mismatch"))
                                 .otherwise(F.col("coord_status")))
    .withColumn("_bad", F.col("coord_status").isin("nulled_pin_mismatch", "nulled_state_mismatch"))
    .withColumn("latitude", F.when(F.col("_bad"), F.lit(None).cast("double")).otherwise(F.col("latitude")))
    .withColumn("longitude", F.when(F.col("_bad"), F.lit(None).cast("double")).otherwise(F.col("longitude")))
    .withColumn("coords_low_precision", F.when(F.col("_bad"), F.lit(None).cast("boolean")).otherwise(F.col("coords_low_precision")))
    .drop("_ref_pin", "_ref_lat", "_ref_lon", "_ref_spread", "_ref_states",
          "_box_state", "_box_lat_min", "_box_lat_max", "_box_lon_min", "_box_lon_max", "_pin_mismatch", "_state_mismatch", "_bad")
)

# ---- Row rules: name, location, completeness ----
kept_src_cols = [c for c in src_cols if c in stage.columns]
def is_filled(c):
    return (F.size(qc(c)) > 0) if c in LIST_COLS else qc(c).isNotNull()
stage = stage.withColumn(
    "source_fill_share",
    F.round(sum(F.when(is_filled(c), 1).otherwise(0) for c in kept_src_cols) / F.lit(len(kept_src_cols)), 3),
)
name_c = qc(COL["name"])
has_address = F.lit(False)
for key in ["line1", "line2", "line3", "city", "state", "pincode"]:
    if COL.get(key):
        has_address = has_address | qc(COL[key]).isNotNull()
stage = stage.withColumn(
    "_reject_reason",
    F.when(name_c.isNull(), "NAME_MISSING")
     .when(F.trim(name_c).startswith("["), "NAME_IS_LIST")
     .when(F.col("latitude").isNull() & ~has_address, "NO_COORDS_OR_ADDRESS")
     .when(F.col("source_fill_share") < MIN_FILLED_SHARE, "UNDER_MIN_FILLED_SHARE"),
)
rejected_rules = stage.where(F.col("_reject_reason").isNotNull()).select(
    "facility_id", "source_row_ids", _short(qc(COL["id"])).alias("id_raw"), _short(name_c).alias("name_raw"),
    F.col("_reject_reason").alias("reject_reason"),
    F.concat(F.lit("source_fill_share="), F.col("source_fill_share").cast("string"),
             F.lit(f" (minimum {MIN_FILLED_SHARE}); coord_status="), F.col("coord_status")).alias("reject_detail"),
)
stage = stage.where(F.col("_reject_reason").isNull()).drop("_reject_reason")

assert_no_clean_columns(rejected_invalid_id.unionByName(rejected_rules), "silver_rejected_facilities")
rejected_invalid_id.unionByName(rejected_rules).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable("silver_rejected_facilities")
display(spark.sql("SELECT reject_reason, count(*) AS records FROM silver_rejected_facilities GROUP BY 1 ORDER BY 2 DESC"))

assert_no_clean_columns(stage, "_facilities_silver_stage")
stage.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_facilities_silver_stage")
stage = spark.table("_facilities_silver_stage")
n_stage = stage.count()
print(f"{n_bronze:,} bronze rows -> {n_stage:,} unique facilities")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Possible near-duplicates (different IDs, probably the same place)
# MAGIC Candidates are facility pairs **in the same PIN code** or **in the same ~1 km grid square**. A pair is flagged when:
# MAGIC * the names are **≥ 85% similar** (based on edit distance) **and** the facilities are within 2 km of each other (or one has no coordinates), **or**
# MAGIC * one name **contains** the other (shorter name at least 10 characters) **and** they are within 2 km.
# MAGIC
# MAGIC Pairs are **flagged, never deleted**. Grid squares with more than 500 facilities are skipped, because those are usually city-centre placeholder points.

# COMMAND ----------

# DBTITLE 1,Possible near-duplicates
def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two points given as Columns; NULL if either point is missing.
    Uses haversine_km_col from common/validation (F.least() skips NULLs, so the helper guards against
    least(1.0, NULL) = 1.0, which would otherwise give 20,015 km for a missing point)."""
    return haversine_km_col(lat1, lon1, lat2, lon2)

name_norm = F.trim(F.regexp_replace(
    F.regexp_replace(F.lower(qc(COL["name"])), r"[^a-z0-9 ]", " "),
    r"\b(pvt|private|ltd|limited|the|and)\b|\s+", " "))
base = (stage
        .select("facility_id", qc(COL["name"]).alias("name"), F.regexp_replace(name_norm, r"\s+", " ").alias("name_norm"),
                "pincode", "latitude", "longitude")
        .where(F.col("name_norm").isNotNull() & (F.length("name_norm") > 0))
        .withColumn("cell", F.when(F.col("latitude").isNotNull(),
                                   F.concat_ws(",", F.round("latitude", 2), F.round("longitude", 2)))))

cell_sizes = base.groupBy("cell").count().where("cell IS NOT NULL AND count <= 500").select("cell")
base_cell = base.join(cell_sizes, "cell")

def pairs_on(left, right, key):
    a, b = left.alias("a"), right.alias("b")
    return a.join(b, (F.col(f"a.{key}") == F.col(f"b.{key}")) & (F.col("a.facility_id") < F.col("b.facility_id"))) \
            .select(*[F.col(f"a.{c}").alias(f"{c}_a") for c in ["facility_id", "name", "name_norm", "pincode", "latitude", "longitude"]],
                    *[F.col(f"b.{c}").alias(f"{c}_b") for c in ["facility_id", "name", "name_norm", "pincode", "latitude", "longitude"]])

pairs = (pairs_on(base.where("pincode IS NOT NULL"), base.where("pincode IS NOT NULL"), "pincode")
         .unionByName(pairs_on(base_cell, base_cell, "cell"))
         .dropDuplicates(["facility_id_a", "facility_id_b"]))

maxlen = F.greatest(F.length("name_norm_a"), F.length("name_norm_b"))
minlen = F.least(F.length("name_norm_a"), F.length("name_norm_b"))
pairs = (pairs
    .withColumn("name_similarity", F.round(1 - F.levenshtein("name_norm_a", "name_norm_b") / maxlen, 3))
    .withColumn("distance_km", F.round(haversine_km(F.col("latitude_a"), F.col("longitude_a"), F.col("latitude_b"), F.col("longitude_b")), 3))
    .withColumn("_near", F.col("distance_km").isNull() | (F.col("distance_km") <= 2.0))
    .withColumn("_contains", (minlen >= 10) & (F.instr("name_norm_a", F.col("name_norm_b")) > 0) | (minlen >= 10) & (F.instr("name_norm_b", F.col("name_norm_a")) > 0))
    .withColumn("match_reason",
                F.when((F.col("name_similarity") >= 0.85) & F.col("_near"), "similar_name_nearby")
                 .when(F.col("_contains") & F.col("_near"), "name_contains_other_nearby"))
    .where("match_reason IS NOT NULL")
    .withColumn("same_pincode", F.col("pincode_a") == F.col("pincode_b"))
    .select("facility_id_a", "name_a", "facility_id_b", "name_b", "name_similarity", "distance_km",
            "same_pincode", "pincode_a", "pincode_b", "match_reason")
)
assert_no_clean_columns(pairs, "silver_possible_duplicates")
pairs.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("silver_possible_duplicates")
pairs = spark.table("silver_possible_duplicates")
print(f"Possible near-duplicate pairs: {pairs.count():,}")

dup_ids = (pairs.select(F.col("facility_id_a").alias("facility_id"), F.col("facility_id_b").alias("other"))
           .unionByName(pairs.select(F.col("facility_id_b").alias("facility_id"), F.col("facility_id_a").alias("other")))
           .groupBy("facility_id").agg(F.sort_array(F.collect_set("other")).alias("possible_duplicate_ids")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7 · Data-quality flags and the final `facilities_silver` table
# MAGIC `dq_flags` is an array of short codes; see `docs/silver-tables.md` for what each means. **Flags are information, not filters.** Decide per use case which ones matter.

# COMMAND ----------

def raw_present_but_clean_null(key, clean_col):
    if not COL.get(key):
        return F.lit(False)
    return qc(COL[key]).isNotNull() & F.col(clean_col).isNull()

FLAGS = [
    ("MISSING_COORDS",                F.col("coord_status") == "missing"),
    ("COORDS_NULLED_PIN_MISMATCH",    F.col("coord_status") == "nulled_pin_mismatch"),
    ("COORDS_NULLED_STATE_MISMATCH",  F.col("coord_status") == "nulled_state_mismatch"),
    ("PIN_NOT_IN_DIRECTORY",          F.col("pin_in_directory") == False),
    ("STATE_NOT_SERVED_BY_PIN",       F.col("state_matches_pin") == False),
    ("COORDS_ZERO",                   F.col("coord_status") == "zero"),
    ("COORDS_OUTSIDE_INDIA",          F.col("coord_status") == "outside_india"),
    ("COORDS_SWAPPED_FIXED",          F.col("coord_status") == "swapped_fixed"),
    ("COORDS_LOW_PRECISION",          F.col("coords_low_precision") == True),
    ("PINCODE_MISSING_OR_INVALID",    F.col("pincode").isNull()),
    ("PINCODE_FROM_ADDRESS_TEXT",     F.col("pincode_from_address_text")),
    ("ADDRESS_NO_STREET",             F.col("address_street").isNull()),
    ("STATE_UNRECOGNIZED",            F.col("state").isNull()),
    ("STATE_INFERRED_FROM_PIN",       F.col("state_from_pin").isNotNull()),
    ("PIN_STATE_MISMATCH",            F.col("pin_state_consistent") == False),
    ("YEAR_IMPLAUSIBLE",              raw_present_but_clean_null("year", "year_established")),
    ("DOCTORS_IMPLAUSIBLE",           raw_present_but_clean_null("doctors", "num_doctors")),
    ("CAPACITY_IMPLAUSIBLE",          raw_present_but_clean_null("capacity", "capacity")),
    ("NO_SERVICE_CLAIMS",             F.col("n_service_claims") == 0),
    ("DUPLICATE_ID_MERGED",           F.col("n_source_rows") > 1),
    ("DUP_ROWS_COORD_CONFLICT",       F.col("dup_coord_spread_km") > 1.0),
    ("DUP_ROWS_STATE_CONFLICT",       F.size("state_variants") > 1),
    ("DUP_ROWS_PINCODE_CONFLICT",     F.size("pincode_variants") > 1),
    ("TEXT_MENTIONS_MULTIPLE_STATES", F.size("states_mentioned_in_text") >= 2),
    ("TEXT_STATE_DIFFERS",            (F.size("states_mentioned_in_text") >= 1) & F.col("state").isNotNull() &
                                      ~F.array_contains("states_mentioned_in_text", F.col("state"))),
    ("POSSIBLE_NEAR_DUPLICATE",       F.size(F.coalesce("possible_duplicate_ids", EMPTY_STR_ARRAY)) > 0),
]

silver = stage.join(dup_ids, "facility_id", "left").withColumn(
    "possible_duplicate_ids", F.coalesce("possible_duplicate_ids", EMPTY_STR_ARRAY))
flag_arr = F.array(*[F.when(F.coalesce(cond, F.lit(False)), F.lit(code)) for code, cond in FLAGS])
silver = (silver
          .withColumn("dq_flags", F.filter(flag_arr, lambda x: x.isNotNull()))
          .withColumn("dq_flag_count", F.size("dq_flags")))

FRONT = ["facility_id", COL["name"], "address_full", "address_street", "address_region", "address_landmark",
         "city", "state", "pincode", "pincode_from_address_text", "latitude", "longitude",
         "coord_status", "coords_low_precision", "year_established", "num_doctors", "capacity",
         "n_specialties", "n_capability", "n_procedure", "n_equipment", "n_service_claims",
         "completeness_score", "source_fill_share", "dq_flag_count", "dq_flags", "possible_duplicate_ids",
         "n_source_rows", "name_variants", "state_from_pin", "pin_state_consistent", "state_variants",
         "pincode_variants", "dup_coord_spread_km", "states_mentioned_in_text", "description_all"]
FRONT = list(dict.fromkeys(FRONT))  # keep order, drop repeats
internal = [c for c in silver.columns if c.startswith("_") and c not in META_COLS]
# Raw address columns are replaced by their cleaned columns and dropped from silver:
#   address_line1/2/3      -> address_full / address_street / address_region / address_landmark
#   address_city           -> city
#   address_stateOrRegion  -> state
#   address_zipOrPostcode  -> pincode
# A value that can't be standardized stays NULL in the cleaned column (it is NOT copied over);
# dq_flags records it (STATE_UNRECOGNIZED, PINCODE_MISSING_OR_INVALID). The originals stay in facilities_bronze.
lost = silver.select(*[
    F.sum(F.when(qc(COL[k]).isNotNull() & F.col(clean).isNull(), 1).otherwise(0)).alias(clean)
    for k, clean in [("city", "city"), ("state", "state"), ("pincode", "pincode")]
    if COL.get(k) and COL[k] in silver.columns
]).first().asDict()
for clean, n in lost.items():
    print(f"{clean}: {int(n or 0):,} rows had a raw value that could not be standardized -> left NULL")

# Raw columns whose cleaned version replaces them (coordinates and numbers too). The originals stay in facilities_bronze.
REPLACED_BY_PARSED = [COL[k] for k in ["line1", "line2", "line3", "city", "state", "pincode",
                                       "lat", "lon", "coords_json", "year", "doctors", "capacity"]
                      if COL.get(k) and COL[k] in silver.columns]
print(f"Dropping from silver (replaced by cleaned columns): {REPLACED_BY_PARSED}")
rest = [c for c in silver.columns if c not in FRONT and c not in internal and c not in REPLACED_BY_PARSED]

silver = silver.select(*[qc(c) for c in FRONT + rest])

assert_no_clean_columns(silver, "_facilities_silver_check")
silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_facilities_silver_check")
silver = spark.table("_facilities_silver_check")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Validation: `facilities_silver` must be accurate to `facilities_bronze`
# MAGIC Each check lists the facilities that break a rule; all must be empty. Results go to `facilities_validation`.
# MAGIC If any check fails, the notebook stops and `facilities_silver` is **not** overwritten.

# COMMAND ----------

CB = COL_BRONZE
def braw(key):
    return F.col(f"`{CB[key]}`").cast("string") if CB.get(key) else F.lit(None).cast("string")

b_lat = F.expr(f"try_cast(`{CB['lat']}` AS DOUBLE)") if CB.get("lat") else F.lit(None).cast("double")
b_lon = F.expr(f"try_cast(`{CB['lon']}` AS DOUBLE)") if CB.get("lon") else F.lit(None).cast("double")
if CB.get("coords_json"):
    b_lat = F.coalesce(b_lat, F.expr(f"try_cast(get_json_object(`{CB['coords_json']}`, '$.coordinates[1]') AS DOUBLE)"))
    b_lon = F.coalesce(b_lon, F.expr(f"try_cast(get_json_object(`{CB['coords_json']}`, '$.coordinates[0]') AS DOUBLE)"))

bsrc = spark.table("facilities_bronze").select(
    F.lower(F.trim(braw("id"))).alias("facility_id"),
    clean_str(braw("name")).alias("b_name"),
    F.regexp_replace(F.concat_ws(" ", braw("pincode"), braw("line1"), braw("line2"), braw("line3")),
                     r"(?<=\d)[\s-](?=\d)", "").alias("b_address_text"),
    F.struct(b_lat.alias("lat"), b_lon.alias("lon")).alias("b_point"),
    state_from_text(clean_str(braw("state"))).alias("b_state"),
    F.regexp_replace(F.concat_ws(" ", braw("year"), braw("doctors"), braw("capacity")), r"(?<=\d),(?=\d)", "").alias("b_numbers"),
)
bagg = bsrc.groupBy("facility_id").agg(
    F.collect_set("b_name").alias("b_names"),
    F.concat_ws(" | ", F.collect_list("b_address_text")).alias("b_address_text"),
    F.collect_list("b_point").alias("b_points"),
    F.collect_set("b_state").alias("b_states"),
    F.concat_ws(" | ", F.collect_list("b_numbers")).alias("b_numbers"),
)
chk = silver.join(bagg, "facility_id", "left")

def matches_a_bronze_point(lat, lon):
    return F.exists("b_points", lambda pt: (same_number(pt["lat"], lat) & same_number(pt["lon"], lon)) |
                                           (same_number(pt["lat"], lon) & same_number(pt["lon"], lat)))

n_rejected_rows = spark.table("silver_rejected_facilities").agg(F.sum(F.size("source_row_ids"))).first()[0] or 0
n_merged_rows = silver.agg(F.sum("n_source_rows")).first()[0] or 0
num_cols = [c for c in ["year_established", "num_doctors", "capacity"] if c in silver.columns]

checks = [
    ("ROW_RECONCILIATION", "Bronze rows = rows merged into silver facilities + rows in silver_rejected_facilities",
     mismatch_rows("bronze_rows", n_bronze, n_merged_rows + n_rejected_rows)),
    ("ID_FROM_BRONZE", "Every facility_id exists as a unique_id in bronze",
     silver.select("facility_id").join(bagg, "facility_id", "left_anti")),
    ("ID_IS_UUID", "Every facility_id is a real ID (UUID)",
     silver.where(~F.col("facility_id").rlike(ID_PATTERN))),
    ("FACILITY_ID_UNIQUE", "facility_id is unique",
     silver.groupBy("facility_id").count().where("count > 1")),
    ("NAME_FROM_BRONZE", "Name is not NULL and equals the (trimmed) bronze name of one of its source rows",
     chk.where(qc(COL["name"]).isNull() | ~F.array_contains("b_names", qc(COL["name"])))
        .select("facility_id", qc(COL["name"]), "b_names")),
    ("PINCODE_FROM_BRONZE", "PIN is NULL or appears in the bronze PIN field or address lines",
     chk.where(F.col("pincode").isNotNull() & (F.instr("b_address_text", F.col("pincode")) == 0))
        .select("facility_id", "pincode", "b_address_text")),
    ("COORDS_FROM_BRONZE", "Coordinates are NULL or exactly a bronze point (or that point with lat/lon swapped back)",
     chk.where(F.col("latitude").isNotNull() & ~matches_a_bronze_point(F.col("latitude"), F.col("longitude")))
        .select("facility_id", "latitude", "longitude", "b_points")),
    ("COORDS_MATCH_PIN", f"No kept coordinate is more than {PIN_MATCH_KM:.0f} km (+ the PIN's spread) from its PIN's centre",
     silver.join(F.broadcast(pin_ref), F.col("pincode") == F.col("_ref_pin"))
           .where(F.col("latitude").isNotNull() &
                  (haversine_km_col(F.col("latitude"), F.col("longitude"), F.col("_ref_lat"), F.col("_ref_lon"))
                   > F.lit(PIN_MATCH_KM) + F.col("_ref_spread")))
           .select("facility_id", "pincode", "latitude", "longitude")),
    ("COORDS_IN_STATE", "No kept coordinate lies outside its state's area (from the India Post directory)",
     silver.join(F.broadcast(state_box), F.col("state") == F.col("_box_state"))
           .where(F.col("latitude").isNotNull() & outside_state_box(F.col("latitude"), F.col("longitude")))
           .select("facility_id", "state", "latitude", "longitude")),
    ("STATE_FROM_BRONZE", "State is NULL, the standardized bronze state, or inferred from the PIN (state_from_pin)",
     chk.where(F.col("state").isNotNull() & ~F.array_contains("b_states", F.col("state")) &
               ~F.col("state").eqNullSafe(F.col("state_from_pin")))
        .select("facility_id", "state", "state_from_pin", "b_states")),
] + [
    (f"{c.upper()}_FROM_BRONZE", f"{c} is NULL or its number appears in the bronze text",
     chk.where(F.col(c).isNotNull() & (F.instr("b_numbers", F.col(c).cast("string")) == 0))
        .select("facility_id", c, "b_numbers"))
    for c in num_cols
]
run_validations(checks, "facilities_validation")

# All checks passed: publish
silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("facilities_silver")
silver = spark.table("facilities_silver")
spark.sql("DROP TABLE IF EXISTS _facilities_silver_check")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8 · `silver_facility_claims`: one row per claimed service or equipment item
# MAGIC `claim_text` is exactly what the record says (quote it as evidence). `claim_norm` is lower case with punctuation removed (match on it).

# COMMAND ----------

claim_parts = []
for key in SERVICE_KEYS:
    c = COL[key]
    if c.startswith("_missing_"):
        continue
    claim_parts.append(
        silver.select("facility_id", F.lit(key).alias("claim_field"), F.posexplode(qc(c)).alias("claim_position", "claim_text"))
    )
if claim_parts:
    claims = claim_parts[0]
    for p in claim_parts[1:]:
        claims = claims.unionByName(p)
    claims = claims.withColumn(
        "claim_norm",
        F.trim(F.regexp_replace(F.regexp_replace(F.lower("claim_text"), r"[^a-z0-9+/ ]", " "), r"\s+", " ")),
    )
    assert_no_clean_columns(claims, "silver_facility_claims")
    claims.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("silver_facility_claims")
    print(f"silver_facility_claims: {spark.table('silver_facility_claims').count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9 · Data-quality summary, table comments, clean-up

# COMMAND ----------

n_silver = silver.count()
dq = (silver.select(F.explode("dq_flags").alias("flag")).groupBy("flag").count()
      .withColumn("pct_of_facilities", F.round(100.0 * F.col("count") / n_silver, 1))
      .withColumnRenamed("count", "n_facilities")
      .orderBy(F.desc("n_facilities")))
assert_no_clean_columns(dq, "silver_dq_summary")
dq.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("silver_dq_summary")

spark.sql("DROP TABLE IF EXISTS _facilities_silver_stage")

TABLE_COMMENTS = {
    "facilities_bronze": f"Raw copy of {SOURCE_TABLE}. Only control characters removed. Built by notebooks/01_bronze_to_silver.",
    "facilities_silver": "One row per facility_id. Cleaned and merged, with dq_flags. Original text columns kept for citation. Built by notebooks/01_bronze_to_silver.",
    "silver_facility_claims": "One row per facility x field x claimed item (specialties, capability, procedure, equipment). claim_text is verbatim.",
    "silver_possible_duplicates": "Facility pairs with different IDs that look like the same place. Flagged, not removed.",
    "silver_dq_summary": "Count of facilities per data-quality flag in facilities_silver.",
    "silver_rejected_facilities": "Records removed from facilities_silver, with the reason (INVALID_ID, NAME_MISSING, NAME_IS_LIST, NO_COORDS_OR_ADDRESS, UNDER_MIN_FILLED_SHARE).",
}
for t, comment in TABLE_COMMENTS.items():
    if spark.catalog.tableExists(f"{CATALOG}.{SCHEMA}.{t}"):
        spark.sql(f"COMMENT ON TABLE {t} IS '{comment.replace(chr(39), '')}'")

COLUMN_COMMENTS = {
    "facility_id": "Source unique_id (a UUID, lower case), merged across duplicate rows. Rows without a valid UUID are removed (see silver_rejected_facilities).",
    "address_full": "Formatted address: street, region, city, state PIN.",
    "address_street": "House/plot/building number and street, road or lane, parsed from address_line1-3.",
    "address_region": "Locality, neighbourhood, sector or area, parsed from address_line1-3.",
    "address_landmark": "Directions such as near/opposite/behind, parsed from address_line1-3.",
    "pincode_from_address_text": "True if pincode was recovered from the address text because the PIN field was invalid.",
    "source_fill_share": "Share (0 to 1) of the kept source columns that are filled in. Facilities under 0.30 are removed.",
    "latitude": "Validated latitude (inside India, swapped values fixed). NULL if unusable. Use for distance.",
    "longitude": "Validated longitude. NULL if unusable.",
    "coords_low_precision": "True if both coordinates have 2 or fewer decimals (about 1 km or worse; possibly a city-centre point).",
    "state": "Standardized state or UT. From the reported state, else inferred from the PIN prefix (see state_from_pin).",
    "pincode": "Valid 6-digit PIN code or NULL.",
    "dq_flags": "Data-quality issue codes. See docs/silver-tables.md.",
    "completeness_score": "Share (0 to 1) of 13 key fields that are filled in. A measure of how much we know, not of quality.",
    "possible_duplicate_ids": "Other facility_ids that look like the same place (see silver_possible_duplicates).",
}
for c, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE facilities_silver ALTER COLUMN `{c}` COMMENT '{comment.replace(chr(39), '')}'")

assert n_silver == silver.select("facility_id").distinct().count(), "facility_id is not unique in facilities_silver!"
print(f"Done. bronze rows: {n_bronze:,} | silver facilities: {n_silver:,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10 · Checks (SQL)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- How often does each data-quality issue occur?
# MAGIC SELECT * FROM silver_dq_summary ORDER BY n_facilities DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Overall shape of the silver table
# MAGIC SELECT
# MAGIC   count(*)                                            AS facilities,
# MAGIC   count_if(n_source_rows > 1)                         AS merged_from_duplicate_ids,
# MAGIC   count_if(latitude IS NOT NULL)                AS with_usable_coords,
# MAGIC   count_if(coords_low_precision)                       AS low_precision_coords,
# MAGIC   count_if(state IS NOT NULL)                   AS with_state,
# MAGIC   count_if(pincode IS NOT NULL)                 AS with_valid_pin,
# MAGIC   count_if(n_service_claims = 0)                      AS no_service_claims,
# MAGIC   count_if(size(possible_duplicate_ids) > 0)          AS possible_near_duplicates,
# MAGIC   round(avg(completeness_score), 3)                   AS avg_completeness
# MAGIC FROM facilities_silver

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Facilities per state (check for odd spellings that slipped through as NULL)
# MAGIC SELECT state, count(*) AS facilities
# MAGIC FROM facilities_silver GROUP BY state ORDER BY facilities DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Example: which facilities claim anything dialysis-related? (match on claim_norm, quote claim_text)
# MAGIC SELECT f.facility_id, f.name, f.city, f.state, c.claim_field, c.claim_text, f.dq_flags
# MAGIC FROM silver_facility_claims c
# MAGIC JOIN facilities_silver f USING (facility_id)
# MAGIC WHERE c.claim_norm RLIKE 'dialys|haemodialys|hemodialys'
# MAGIC ORDER BY f.state, f.city
# MAGIC LIMIT 50

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Which records were removed, and why? (examples per reason)
# MAGIC SELECT reject_reason, count(*) AS records, slice(collect_list(coalesce(name_raw, id_raw)), 1, 5) AS examples
# MAGIC FROM silver_rejected_facilities GROUP BY reject_reason ORDER BY records DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Spot-check the reorganized addresses against the original lines (which only bronze still has)
# MAGIC SELECT s.name, b.address_line1, b.address_line2, b.address_line3,
# MAGIC        s.address_street, s.address_region, s.address_landmark, s.city, s.state, s.pincode
# MAGIC FROM (SELECT * FROM facilities_silver TABLESAMPLE (30 ROWS)) s
# MAGIC JOIN facilities_bronze b ON lower(trim(b.unique_id)) = s.facility_id
