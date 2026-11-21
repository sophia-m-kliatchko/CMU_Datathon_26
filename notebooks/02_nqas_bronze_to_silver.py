# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · NQAS: `nqas_bronze` → `nqas_silver`
# MAGIC
# MAGIC **Input:** `nqas_bronze`, made by uploading `data/external/nqas_certified_facilities.csv` (from `scripts/scrape_nqas.py`) as a table.
# MAGIC **Output:** `nqas_silver`, with **one row per certification listing** (a facility can appear more than once: different departments or certification rounds).
# MAGIC
# MAGIC | What happens | Why |
# MAGIC |---|---|
# MAGIC | Text trimmed, blanks set to NULL | The CSV upload keeps stray spaces |
# MAGIC | `validity_from` / `validity_to` parsed from `dd-mm-yyyy` into real dates | So you can filter "certified in 2022" or "still valid" |
# MAGIC | `certification_status` = current / expired (as of the run date) | **Every certificate in the 2026-11 scrape has expired (2019–2023)**. Treat it as "was certified", not "is certified" |
# MAGIC | State standardized (`state`), district title-cased (`district`) | To join with `facilities_silver` |
# MAGIC | Facility type (PHC, CHC, DH, …) guessed from the name, with a level (primary/secondary) | For filtering and for matching like with like |
# MAGIC | `name_norm` and `name_core` (the name with type words such as "PHC" removed) | For fuzzy matching to Virtue Foundation facilities |
# MAGIC | Department scope parsed (`n_departments_assessed`, `covers_all_departments`) | A partial certification covers only some departments |
# MAGIC | Exact duplicate listings collapsed (`n_listings`) | The website repeats a few rows |
# MAGIC | `dq_flags` | Problems are flagged, never silently dropped |
# MAGIC | `district_in_state`: the district exists in that state in the India Post directory (`pincode_silver`) | Catches a district/state pair that don't belong together (flag `DISTRICT_NOT_IN_STATE`). Run notebook 04 first |
# MAGIC | **Validation** against bronze before publishing (results in `nqas_validation`) | Row counts, every listing, dates, state, district must match bronze, or `nqas_silver` is not overwritten |
# MAGIC | **Citation columns** (`source_*`, `row_citation`) | Every row can be cited back to the NHSRC website (see `docs/data-sources.md`) |
# MAGIC
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

# MAGIC %run ./common/validation

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("bronze_table", "nqas_bronze", "3. Bronze table")
dbutils.widgets.text("silver_table", "nqas_silver", "4. Silver table")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
SILVER = dbutils.widgets.get("silver_table").strip()
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

SOURCE_NAME = "NQAS Certified Facilities list (National Quality Assurance Standards)"
SOURCE_PUBLISHER = "National Health Systems Resource Centre (NHSRC), Ministry of Health and Family Welfare, Government of India"
SOURCE_LANDING_URL = "https://qps.nhsrcindia.org/nqas-facility-list"
SOURCE_LICENSE = "Public government web page. No explicit open-data licence found; cite NHSRC as the source."
PRODUCED_BY = "scripts/scrape_nqas.py -> notebooks/02_nqas_bronze_to_silver.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Read bronze and check the columns

# COMMAND ----------

bronze = spark.table(BRONZE)
cols = {c.lower().strip(): c for c in bronze.columns}
REQUIRED = ["state", "district", "facility_name", "department_assessed", "validity_from", "validity_to", "certification_type"]
missing = [c for c in REQUIRED if c not in cols]
assert not missing, f"{BRONZE} is missing columns {missing}. Found: {bronze.columns}"

def col(name, default=None):
    """Bronze column as trimmed text (NULL if blank), or a default literal if the column doesn't exist."""
    if name in cols:
        t = F.trim(F.col(f"`{cols[name]}`").cast("string"))
        return F.when(t == "", F.lit(None).cast("string")).otherwise(t)
    return F.lit(default).cast("string")

n_bronze = bronze.count()
print(f"{BRONZE}: {n_bronze:,} rows; columns: {bronze.columns}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Clean and parse

# COMMAND ----------

def parse_date(c):
    """dd-mm-yyyy (the site's format), with a few fallbacks. NULL if unparseable (and flagged)."""
    return F.coalesce(*[F.to_date(F.expr(f"try_to_timestamp({c}, '{fmt}')"))
                        for fmt in ["dd-MM-yyyy", "d-M-yyyy", "dd/MM/yyyy", "yyyy-MM-dd"]])

df = bronze.select(
    col("state").alias("state_raw"),
    col("district").alias("district_raw"),
    col("facility_name").alias("facility_name"),
    col("department_assessed").alias("department_assessed"),
    col("validity_from").alias("validity_from_raw"),
    col("validity_to").alias("validity_to_raw"),
    F.lower(col("certification_type")).alias("certification_type"),
    col("source_url", SOURCE_LANDING_URL).alias("_source_url"),
    col("scraped_on").alias("_scraped_on"),
)

# Collapse exact duplicate listings (the website repeats a few rows)
key_cols = ["state_raw", "district_raw", "facility_name", "department_assessed",
            "validity_from_raw", "validity_to_raw", "certification_type"]
df = (df.groupBy(*key_cols)
        .agg(F.count(F.lit(1)).alias("n_listings"),
             F.first("_source_url", ignorenulls=True).alias("_source_url"),
             F.max("_scraped_on").alias("_scraped_on")))

dept_l = F.lower(F.coalesce(F.col("department_assessed"), F.lit("")))
n_dept = F.coalesce(F.regexp_extract(dept_l, r"all\s*(\d+)", 1), F.lit(""))
n_dept = F.when(n_dept != "", n_dept).otherwise(F.regexp_extract(dept_l, r"(\d+)\s*dep", 1))

silver = (df
    .withColumn("certification_id", F.substring(F.sha2(F.concat_ws("|", *[F.coalesce(F.col(c), F.lit("")) for c in key_cols]), 256), 1, 16))
    .withColumn("state", state_from_text(F.col("state_raw")))
    .withColumn("district", F.initcap(F.regexp_replace(F.col("district_raw"), r"\s+", " ")))
    .withColumn("facility_type", facility_type_from_text(F.col("facility_name")))
    .withColumn("facility_level", facility_level(F.col("facility_type")))
    .withColumn("name_norm", name_norm(F.col("facility_name")))
    .withColumn("name_core", name_core(F.col("facility_name")))
    .withColumn("validity_from", parse_date("validity_from_raw"))
    .withColumn("validity_to", parse_date("validity_to_raw"))
    .withColumn("certification_status",
                F.when(F.col("validity_to").isNull(), "unknown")
                 .when(F.col("validity_to") >= F.current_date(), "current")
                 .otherwise("expired"))
    .withColumn("n_departments_assessed", F.when(n_dept != "", n_dept.cast("int")))
    .withColumn("covers_all_departments", dept_l.rlike(r"^\s*all\b") & ~dept_l.contains("exclud"))
    .withColumn("certification_year", F.year("validity_from"))
)

# ---- District must belong to the state (India Post directory, built by notebook 04) ----
PIN_OFFICES = f"{CATALOG}.{SCHEMA}.pincode_silver"
assert spark.catalog.tableExists(PIN_OFFICES), (
    "Run notebooks/04_pincode_bronze_to_silver first: the district/state check needs pincode_silver.")
district_ref = (spark.table(PIN_OFFICES).where("state IS NOT NULL AND district_key IS NOT NULL")
                .select(F.col("state").alias("_ref_state"), F.col("district_key").alias("_ref_district_key")).distinct())
silver = (silver
    .withColumn("_district_key", F.regexp_replace(F.lower(F.col("district")), r"[^a-z0-9]", ""))
    .join(F.broadcast(district_ref),
          (F.col("state") == F.col("_ref_state")) & (F.col("_district_key") == F.col("_ref_district_key")), "left")
    .withColumn("district_in_state",
                F.when(F.col("state").isNotNull() & F.col("district").isNotNull(), F.col("_ref_state").isNotNull()))
    .drop("_district_key", "_ref_state", "_ref_district_key"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Data-quality flags and citations

# COMMAND ----------

FLAGS = [
    ("STATE_UNRECOGNIZED",          F.col("state").isNull()),
    ("MISSING_DISTRICT",            F.col("district").isNull()),
    ("DISTRICT_NOT_IN_STATE",       F.col("district_in_state") == False),
    ("MISSING_FACILITY_NAME",       F.col("facility_name").isNull()),
    ("DATE_UNPARSEABLE",            (F.col("validity_from_raw").isNotNull() & F.col("validity_from").isNull()) |
                                    (F.col("validity_to_raw").isNotNull() & F.col("validity_to").isNull())),
    ("VALIDITY_END_BEFORE_START",   F.col("validity_to") < F.col("validity_from")),
    ("CERTIFICATION_EXPIRED",       F.col("certification_status") == "expired"),
    ("FACILITY_TYPE_UNKNOWN",       F.col("facility_type").isNull()),
    ("DUPLICATE_LISTING_COLLAPSED", F.col("n_listings") > 1),
]
silver = silver.withColumn(
    "dq_flags",
    F.filter(F.array(*[F.when(F.coalesce(c, F.lit(False)), F.lit(code)) for code, c in FLAGS]), lambda x: x.isNotNull()),
)

silver = add_provenance(silver, SOURCE_NAME, SOURCE_PUBLISHER, F.col("_source_url"),
                        F.to_date("_scraped_on"), SOURCE_LICENSE, PRODUCED_BY)
silver = silver.withColumn(
    "row_citation",
    F.concat(F.lit("NHSRC, NQAS Certified Facilities list ("), F.col("certification_type"), F.lit(" certification): "),
             F.coalesce(F.col("facility_name"), F.lit("?")), F.lit(", "), F.coalesce(F.col("district_raw"), F.lit("?")),
             F.lit(", "), F.coalesce(F.col("state_raw"), F.lit("?")), F.lit("; valid "),
             F.coalesce(F.col("validity_from_raw"), F.lit("?")), F.lit(" to "), F.coalesce(F.col("validity_to_raw"), F.lit("?")),
             F.lit(". "), F.lit(SOURCE_LANDING_URL), F.lit(", retrieved "), F.coalesce(F.col("_scraped_on"), F.lit("?")), F.lit(".")),
).drop("_source_url", "_scraped_on")

ORDER = ["certification_id", "facility_name", "facility_type", "facility_level", "district", "state",
         "district_in_state", "certification_type", "department_assessed", "n_departments_assessed", "covers_all_departments",
         "validity_from", "validity_to", "certification_year", "certification_status", "name_norm", "name_core",
         "n_listings", "dq_flags", "row_citation", "state_raw", "district_raw", "validity_from_raw", "validity_to_raw",
         "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
silver = silver.select(*ORDER)
assert_no_clean_columns(silver, "_nqas_silver_check")
silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_nqas_silver_check")
silver = spark.table("_nqas_silver_check")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validation: `nqas_silver` must be accurate to the bronze table
# MAGIC Each check lists listings that break a rule; all must be empty. Results go to `nqas_validation`.
# MAGIC If any check fails, the notebook stops and `nqas_silver` is **not** overwritten.

# COMMAND ----------

b_keys = bronze.select(
    col("state").alias("state_raw"), col("district").alias("district_raw"), col("facility_name").alias("facility_name"),
    col("department_assessed").alias("department_assessed"), col("validity_from").alias("validity_from_raw"),
    col("validity_to").alias("validity_to_raw"), F.lower(col("certification_type")).alias("certification_type"))
DATE_PARTS = r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$"

def date_differs(date_col, raw_col):
    d, m, y = [F.regexp_extract(F.col(raw_col), DATE_PARTS, i) for i in (1, 2, 3)]
    return F.col(date_col).isNotNull() & ((F.dayofmonth(date_col) != d.cast("int")) |
                                          (F.month(date_col) != m.cast("int")) | (F.year(date_col) != y.cast("int")))

n_listed = silver.agg(F.sum("n_listings")).first()[0] or 0
checks = [
    ("ROW_RECONCILIATION", "Bronze rows = listings collapsed into silver",
     mismatch_rows("bronze_rows", n_bronze, n_listed)),
    ("LISTING_FROM_BRONZE", "Every silver listing (state, district, name, departments, dates, type) exists in bronze",
     silver.alias("s").join(b_keys.alias("b"),
                            [F.col(f"s.{c}").eqNullSafe(F.col(f"b.{c}")) for c in key_cols], "left_anti")),
    ("VALIDITY_FROM_MATCHES_BRONZE", "validity_from has the same day, month and year as the bronze text",
     silver.where(date_differs("validity_from", "validity_from_raw"))),
    ("VALIDITY_TO_MATCHES_BRONZE", "validity_to has the same day, month and year as the bronze text",
     silver.where(date_differs("validity_to", "validity_to_raw"))),
    ("STATE_FROM_BRONZE", "state is NULL or the standardized bronze state",
     silver.where(~F.col("state").eqNullSafe(state_from_text(F.col("state_raw"))))),
    ("DISTRICT_FROM_BRONZE", "district is the bronze district, title-cased",
     silver.where(~F.col("district").eqNullSafe(F.initcap(F.regexp_replace(F.col("district_raw"), r"\s+", " "))))),
    ("STATUS_MATCHES_DATES", "certification_status is 'expired' exactly when validity_to is before today",
     silver.where(F.col("validity_to").isNotNull() &
                  ((F.col("certification_status") == "expired") != (F.col("validity_to") < F.current_date())))),
    ("CERTIFICATION_ID_UNIQUE", "certification_id is unique",
     silver.groupBy("certification_id").count().where("count > 1")),
]
run_validations(checks, "nqas_validation")

# All checks passed: publish
write_table(silver, SILVER,
            f"NQAS certified facility listings from NHSRC ({SOURCE_LANDING_URL}), one row per listing. "
            "Historical: all certificates in the 2026-11 scrape had expired. Validated against bronze (see nqas_validation). "
            "Built by notebooks/02_nqas_bronze_to_silver.")
spark.sql("DROP TABLE IF EXISTS _nqas_silver_check")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Checks

# COMMAND ----------

silver = spark.table(SILVER)
assert silver.count() == silver.select("certification_id").distinct().count(), "certification_id is not unique"
display(spark.sql(f"""
  SELECT certification_type, certification_status, count(*) AS listings,
         min(validity_from) AS earliest_from, max(validity_to) AS latest_to,
         count_if(state IS NULL) AS state_unrecognized
  FROM {SILVER} GROUP BY ALL ORDER BY ALL"""))

# COMMAND ----------

display(spark.sql(f"""
  SELECT flag, count(*) AS listings
  FROM (SELECT explode(dq_flags) AS flag FROM {SILVER}) GROUP BY flag ORDER BY listings DESC"""))

# COMMAND ----------

display(spark.sql(f"""
  SELECT state, facility_type, count(*) AS listings
  FROM {SILVER} GROUP BY ALL ORDER BY state, listings DESC"""))
