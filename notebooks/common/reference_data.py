# Databricks notebook source
# MAGIC %md
# MAGIC # common/reference_data
# MAGIC Shared lookups and cleaning helpers for the outside-dataset notebooks (02, 03, …).
# MAGIC Load it in another notebook with a cell that contains only:
# MAGIC ```
# MAGIC %run ./common/reference_data
# MAGIC ```
# MAGIC Defines: `STATES`, `state_from_text()`, `name_norm()`, `name_core()`, `facility_type_from_text()`,
# MAGIC `FACILITY_LEVEL`, `add_provenance()`, `write_table()` (which refuses to write any `*_clean` column), `assert_no_clean_columns()`.
# MAGIC
# MAGIC Note: `01_bronze_to_silver.py` still has its own copy of the state lookup. Keep the two in sync, or switch 01 to this notebook later.

# COMMAND ----------

import re
from pyspark.sql import functions as F

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]

def _norm_key_py(s):
    return re.sub(r"[^a-z]", "", s.lower().replace("&", " and "))

# Lookup key (lower case, letters only) -> official state or UT name
STATE_ALIASES = {
    "orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
    "newdelhi": "Delhi", "nctofdelhi": "Delhi", "delhinct": "Delhi",
    "jammukashmir": "Jammu and Kashmir", "jandk": "Jammu and Kashmir", "jk": "Jammu and Kashmir",
    "andamannicobarislands": "Andaman and Nicobar Islands", "andamanandnicobar": "Andaman and Nicobar Islands",
    "andamannicobar": "Andaman and Nicobar Islands",
    "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "dadranagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu",
    "dnhanddd": "Dadra and Nagar Haveli and Daman and Diu", "dnhdd": "Dadra and Nagar Haveli and Daman and Diu",
    "dadraandnagarhavelianddamananddiu": "Dadra and Nagar Haveli and Daman and Diu",
    "chattisgarh": "Chhattisgarh", "chhatisgarh": "Chhattisgarh", "telengana": "Telangana",
    "maharastra": "Maharashtra", "gujrat": "Gujarat", "tamilnadu": "Tamil Nadu",
}
STATE_LOOKUP = {_norm_key_py(s): s for s in STATES}
STATE_LOOKUP.update(STATE_ALIASES)
_STATE_MAP = F.create_map(*[x for k, v in STATE_LOOKUP.items() for x in (F.lit(k), F.lit(v))])


def _norm_key(col):
    return F.regexp_replace(F.lower(F.regexp_replace(col, "&", " and ")), "[^a-z]", "")


def state_from_text(col):
    """Standardize a state/UT name: exact lookup first, then the longest state name found inside the text."""
    key = _norm_key(col)
    fallback = F.lit(None).cast("string")
    for k in sorted([k for k in STATE_LOOKUP if len(k) >= 5], key=len):  # longest key ends up tested first
        fallback = F.when(key.contains(k), F.lit(STATE_LOOKUP[k])).otherwise(fallback)
    return F.coalesce(_STATE_MAP[key], fallback)


# COMMAND ----------

# ---- Facility names ----
_LEGAL_WORDS = r"\b(pvt|private|ltd|limited|the|govt|government)\b"
_TYPE_WORDS = (r"\b(phc|chc|uphc|uchc|sdh|dh|hwc|h and wc|sc|rh|bphc|mphc|sd|fhc|gh|thq|thqh|taluk|taluka|family|"
               r"primary|community|urban|health|healthcare|centre|center|wellness|and|sub|divisional|district|"
               r"hospital|area|rural|general|block|mini|additional|referral|unit)\b")


def name_norm(col):
    """Lower case, '&' -> 'and', punctuation removed, legal words removed, spaces collapsed. For display-free matching."""
    s = F.lower(F.regexp_replace(col, "&", " and "))
    s = F.regexp_replace(s, r"[^a-z0-9 ]", " ")
    s = F.regexp_replace(s, _LEGAL_WORDS, " ")
    return F.trim(F.regexp_replace(s, r"\s+", " "))


def name_core(col):
    """name_norm with facility-type words removed (e.g. 'PHC Majri, Ambala' -> 'majri ambala'). Mostly the place name; use for fuzzy matching."""
    s = F.regexp_replace(name_norm(col), _TYPE_WORDS, " ")
    return F.trim(F.regexp_replace(s, r"\s+", " "))


# Order matters: more specific patterns first
FACILITY_TYPE_PATTERNS = [
    (r"\buchc\b|urban community health", "UCHC"),
    (r"\buphc\b|urban primary health", "UPHC"),
    (r"\bchc\b|community health cent", "CHC"),
    (r"\b(b|m)?phc\b|primary health cent", "PHC"),
    (r"\bfhc\b|family health cent", "FHC"),                 # Kerala: upgraded PHCs
    (r"\bgh\b|general hospital", "GH"),
    (r"taluk(a)? (head ?quarters? )?hospital|\bthq?h\b", "SDH"),
    (r"\bsdh\b|sub[- ]?divisional hosp|sub[- ]?district hosp", "SDH"),
    (r"\bdh\b|district hospital|district headquarters? hospital|civil hospital", "DH"),
    (r"area hospital", "AH"),
    (r"\bhwc\b|h\s*&\s*wc|health (and|&) wellness", "HWC"),
    (r"\bsc\b|sub[- ]?cent", "SC"),
    (r"\brh\b|rural hospital", "RH"),
    (r"medical college", "MC"),
]
FACILITY_LEVEL = {"UCHC": "secondary", "UPHC": "primary", "CHC": "secondary", "PHC": "primary", "SDH": "secondary",
                  "FHC": "primary", "GH": "secondary",
                  "SDH/CHC": "secondary", "DH": "secondary", "AH": "secondary", "HWC": "primary", "SC": "primary",
                  "RH": "secondary", "MC": "tertiary"}
_LEVEL_MAP = F.create_map(*[x for k, v in FACILITY_LEVEL.items() for x in (F.lit(k), F.lit(v))])


def facility_type_from_text(col):
    """Guess the public-facility type code (PHC, CHC, DH, …) from a facility name. NULL if no pattern matches."""
    s = F.lower(col)
    out = F.lit(None).cast("string")
    for pattern, code in reversed(FACILITY_TYPE_PATTERNS):  # first pattern in the list ends up tested first
        out = F.when(s.rlike(pattern), F.lit(code)).otherwise(out)
    return out


def facility_level(type_col):
    return _LEVEL_MAP[type_col]


# COMMAND ----------

# ---- Provenance and writing ----
def add_provenance(df, source_name, publisher, source_url, retrieved_on, license_note, produced_by):
    """Add the same citation columns to every row, so any downstream answer can cite where the row came from."""
    return (df
            .withColumn("source_name", F.lit(source_name))
            .withColumn("source_publisher", F.lit(publisher))
            .withColumn("source_url", source_url if not isinstance(source_url, str) else F.lit(source_url))
            .withColumn("retrieved_on", retrieved_on if not isinstance(retrieved_on, str) else F.lit(retrieved_on))
            .withColumn("source_license", F.lit(license_note))
            .withColumn("produced_by", F.lit(produced_by)))


def assert_no_clean_columns(df, table):
    """Silver tables never have *_clean columns: being in silver already means clean."""
    bad = [c for c in df.columns if c.lower().endswith("_clean")]
    assert not bad, f"{table} would get *_clean columns {bad}; use the plain name instead"


def write_table(df, name, comment):
    assert_no_clean_columns(df, name)
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(name)
    spark.sql(f"COMMENT ON TABLE {name} IS '{comment.replace(chr(39), '')}'")
    print(f"Wrote {name}: {spark.table(name).count():,} rows")
