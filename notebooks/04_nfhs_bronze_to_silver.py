# Databricks notebook source
# /// script
# [tool.databricks.environment]
# base_environment = "databricks_ai_v6"
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # 04 · NFHS-5 district indicators: `nfhs_bronze` → `nfhs_silver`
# MAGIC
# MAGIC Written by elliotl-ops (originally `NFHS_Bronze_to_Silver.py`). Adapted to the pipeline conventions on 2026-11-21: widgets, `nfhs_*` table names, `882.0`-style counts, no `.cache()`, bronze validation and citations. The cleaning rules, quality report, quality gate, quarantine and quality view are Elliot's.
# MAGIC
# MAGIC **Input:** `nfhs_5_district_health_indicators.csv` (NFHS-5, 2019-21 district fact sheets; 706 rows). Read from a CSV in a Volume or from a table (widget 3). The silver table keeps the 8 indicators below; the full file stays in `nfhs_bronze`.
# MAGIC
# MAGIC | Output table | Grain | What it's for |
# MAGIC |---|---|---|
# MAGIC | `nfhs_bronze` | 1 row per source row | Raw copy of the whole file (all columns as text) |
# MAGIC | `nfhs_silver` | 1 row per (state, district) | Typed indicators, estimate/low-sample flags, standardized `state`, citations |
# MAGIC | `nfhs_quarantine` | 1 row per known-bad row | Rows kept out of silver, with the reason |
# MAGIC | `nfhs_quality_history` | 1 row per run | Elliot's quality metrics and gate result, appended each run |
# MAGIC | `nfhs_quality_current` (view) | 1 row per metric value | Current-state quality summary |
# MAGIC | `nfhs_validation` | 1 row per check | Silver-vs-bronze accuracy checks (all must pass) |
# MAGIC
# MAGIC **Order:** after `00_pincode_bronze_to_silver` (only used for the optional `district_in_pin_directory` check; the notebook still runs without it).

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

# MAGIC %run ./common/validation

# COMMAND ----------

from functools import reduce
from operator import or_

from pyspark.sql import Row, Window
from pyspark.sql import functions as F

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("source", "/Volumes/workspace/datathon/external/nfhs_5_district_health_indicators.csv",
                     "3. Source: CSV path or table name")
dbutils.widgets.text("retrieved_on", "2026-11-21", "4. Date the source file was obtained")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
SOURCE = dbutils.widgets.get("source").strip()
RETRIEVED_ON = dbutils.widgets.get("retrieved_on").strip()
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")
print(f"Source: {SOURCE}\nWriting to: {CATALOG}.{SCHEMA}")

BRONZE_TABLE = "nfhs_bronze"
SILVER_TABLE = "nfhs_silver"
QUARANTINE_TABLE = "nfhs_quarantine"
QUALITY_HISTORY_TABLE = "nfhs_quality_history"
QUALITY_VIEW = "nfhs_quality_current"

SURVEY_ROUND = "NFHS-5"
SURVEY_PERIOD = "2019-21"

SOURCE_NAME = "National Family Health Survey (NFHS-5), 2019-21: District Fact Sheets"
SOURCE_PUBLISHER = "International Institute for Population Sciences (IIPS) for the Ministry of Health and Family Welfare, Government of India"
SOURCE_URL = "https://rchiips.org/NFHS/factsheet_NFHS-5.shtml"
SOURCE_LICENSE = "Government Open Data License - India (GODL), if obtained from data.gov.in; cite IIPS/MoHFW"
PRODUCED_BY = "notebooks/04_nfhs_bronze_to_silver.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)"

KNOWN_BAD_ROWS = {
    ("Mizoram", "Chandel"): "Exact copy of Manipur's Chandel row; Mizoram's Saiha district is missing.",
}

STATE_FIXES = {"Maharastra": "Maharashtra"}
DISTRICT_FIXES = {"Sri Potti Sriramulu Nello": "Sri Potti Sriramulu Nellore"}

LOW_SAMPLE_HOUSEHOLDS = 600
LOW_SAMPLE_MEN = 50

PCT_RANGE = (0.0, 100.0)
SEX_RATIO_RANGE = (500, 1600)

EXPECTED_BRONZE_ROWS = (650, 800)
MIN_STATES = 30
MAX_QUARANTINED_ROWS = 5
MAX_DROPPED_PCT = 0.01
MAX_NULL_NUMERIC_PCT = 0.02
MAX_UNPARSEABLE_ROWS = 0
MAX_RANGE_VIOLATION_ROWS = 0

TEXT_COLS = ["district_name", "state_ut"]
INT_COLS = [
    "households_surveyed",
    "women_15_49_interviewed",
    "men_15_54_interviewed",
    "sex_ratio_total_f_per_1000_m",
    "sex_ratio_at_birth_5y_f_per_1000_m",
]
PCT_COLS = [
    "female_population_age_6_years_and_above_ever_schooled_pct",
    "population_below_age_15_years_pct",
    "child_u5_whose_birth_was_civil_reg_pct",
]
SEX_RATIO_COLS = ["sex_ratio_total_f_per_1000_m", "sex_ratio_at_birth_5y_f_per_1000_m"]
NUM_COLS = INT_COLS + PCT_COLS
SOURCE_COLS = TEXT_COLS + NUM_COLS
NULL_TOKENS = ["", "*", "NA", "na", "-"]
# Whole numbers may be written "882" or "882.0" in the source
INT_PATTERN = r"^\d+(\.0+)?$"
DEC_PATTERN = r"^\d+(\.\d+)?$"

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def clean_text(col_name):
    c = F.trim(F.regexp_replace(F.col(col_name), r"\s+", " "))
    return F.when(F.length(c) > 0, c)

def nullify(expr):
    return F.when(F.length(expr) > 0, expr)

def apply_mapping(col_name, mapping):
    expr = F.col(col_name)
    for bad, good in mapping.items():
        expr = F.when(F.col(col_name) == bad, F.lit(good)).otherwise(expr)
    return expr

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 1. Bronze: raw copy of the whole file, then select the indicators by NAME
# --------------------------------------------------------------------------- #
print("Reading bronze data...")
if "/" in SOURCE:
    raw = spark.read.option("header", "true").option("inferSchema", "false").option("encoding", "UTF-8").csv(SOURCE)
else:
    raw = spark.table(SOURCE)
# Strip a UTF-8 byte-order mark / spaces from column names; every column as text
raw = raw.select([F.col(f"`{c}`").cast("string").alias(c.replace("﻿", "").strip()) for c in raw.columns])
missing = [c for c in SOURCE_COLS if c not in raw.columns]
assert not missing, f"Source is missing columns {missing}"
(raw.withColumn("_bronze_row_id", F.monotonically_increasing_id())
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("source_file", F.lit(SOURCE))
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(BRONZE_TABLE))

# Select by header name (a user-supplied StructType maps columns by POSITION,
# which silently swapped the pct and sex-ratio columns in an earlier version).
bronze = spark.table(BRONZE_TABLE).select("_bronze_row_id", *SOURCE_COLS, "source_file")
bronze_count = bronze.count()
print(f"✓ Loaded {bronze_count:,} rows from bronze")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 2. Clean and parse
# --------------------------------------------------------------------------- #
print("Cleaning and parsing...")
df = bronze
for c in TEXT_COLS:
    df = df.withColumn(c, clean_text(c))
for c in NUM_COLS:
    df = df.withColumn(c, F.trim(F.col(c)))

df = df.dropDuplicates(SOURCE_COLS)

for c in NUM_COLS:
    raw_c = F.col(c)
    is_missing_token = raw_c.isNull() | raw_c.isin(*NULL_TOKENS)
    is_estimate = raw_c.rlike(r"^\(.*\)$")
    core = F.regexp_replace(raw_c, r"^\((.*)\)$", "$1")
    number_pattern = INT_PATTERN if c in INT_COLS else DEC_PATTERN
    parses_ok = core.rlike(number_pattern)
    df = df.withColumn(f"_est_{c}", F.when(is_estimate, F.lit(c)))
    df = df.withColumn(f"_bad_{c}", F.when(~is_missing_token & ~parses_ok, F.lit(c)))
    df = df.withColumn(c, F.when(parses_ok, core.cast("double").cast("int") if c in INT_COLS else core.cast("double")))

df = (
    df
    .withColumn("estimate_columns", nullify(F.concat_ws(",", *[F.col(f"_est_{c}") for c in NUM_COLS])))
    .withColumn("unparseable_columns", nullify(F.concat_ws(",", *[F.col(f"_bad_{c}") for c in NUM_COLS])))
    .drop(*[f"_est_{c}" for c in NUM_COLS], *[f"_bad_{c}" for c in NUM_COLS])
    .withColumn("has_estimate_values", F.col("estimate_columns").isNotNull())
)

df = (
    df
    .withColumn("state_name", apply_mapping("state_ut", STATE_FIXES))
    .withColumn("district_std", apply_mapping("district_name", DISTRICT_FIXES))
    .withColumn("state_norm", F.upper(F.col("state_name")))
    .withColumn("district_norm", F.upper(F.col("district_std")))
    .withColumn(
        "district_key",
        F.sha2(F.concat_ws("|", F.coalesce("state_norm", F.lit("")),
                           F.coalesce("district_norm", F.lit(""))), 256),
    )
    # Pipeline conventions: the same standardized state as the other silver tables, and a district join key
    # matching pincode_silver.district_key (lower case, letters and digits only)
    .withColumn("state", state_from_text(F.col("state_name")))
    .withColumn("district_join_key", F.regexp_replace(F.lower(F.col("district_std")), r"[^a-z0-9]", ""))
)

PIN_OFFICES = f"{CATALOG}.{SCHEMA}.pincode_silver"
if spark.catalog.tableExists(PIN_OFFICES):
    district_ref = (spark.table(PIN_OFFICES).where("state IS NOT NULL AND district_key IS NOT NULL")
                    .select(F.col("state").alias("_ref_state"), F.col("district_key").alias("_ref_key")).distinct())
    df = (df.join(F.broadcast(district_ref),
                  (F.col("state") == F.col("_ref_state")) & (F.col("district_join_key") == F.col("_ref_key")), "left")
            .withColumn("district_in_pin_directory", F.col("_ref_state").isNotNull())
            .drop("_ref_state", "_ref_key"))
else:
    print("pincode_silver not found (run notebook 00 first): district_in_pin_directory left NULL")
    df = df.withColumn("district_in_pin_directory", F.lit(None).cast("boolean"))

print("✓ Cleaning complete")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 3. Flags
# --------------------------------------------------------------------------- #
print("Applying quality flags...")
range_hits = (
    [F.when(F.col(c).isNotNull() & ~F.col(c).between(*PCT_RANGE), F.lit(c)) for c in PCT_COLS]
    + [F.when(F.col(c).isNotNull() & ~F.col(c).between(*SEX_RATIO_RANGE), F.lit(c)) for c in SEX_RATIO_COLS]
)
df = (
    df
    .withColumn("range_violations", nullify(F.concat_ws(",", *range_hits)))
    .withColumn(
        "low_sample",
        F.coalesce(
            (F.col("households_surveyed") < LOW_SAMPLE_HOUSEHOLDS)
            | (F.col("men_15_54_interviewed") < LOW_SAMPLE_MEN),
            F.lit(False),
        ),
    )
    .withColumn("has_null_numeric", reduce(or_, [F.col(c).isNull() for c in NUM_COLS]))
)

reason = F.lit(None).cast("string")
for (state, district), why in KNOWN_BAD_ROWS.items():
    reason = F.when(
        (F.col("state_norm") == state.upper()) & (F.col("district_norm") == district.upper()),
        F.lit(why),
    ).otherwise(reason)
df = df.withColumn("quarantine_reason", reason).withColumn(
    "_is_good", F.col("quarantine_reason").isNull().cast("int")
)

w_metrics = Window.partitionBy(*NUM_COLS)
w_key = Window.partitionBy("district_key")
df = (
    df
    .withColumn("identical_metrics_rows", F.count(F.lit(1)).over(w_metrics))
    .withColumn("_good_in_metric_group", F.sum("_is_good").over(w_metrics))
    .withColumn("suspected_duplicate_content", F.col("identical_metrics_rows") > 1)
    .withColumn(
        "unexplained_identical_metrics",
        (F.col("_is_good") == 1) & (F.col("_good_in_metric_group") > 1),
    )
    .withColumn(
        "duplicate_key",
        (F.col("_is_good") == 1) & (F.sum("_is_good").over(w_key) > 1),
    )
    .withColumn("survey_round", F.lit(SURVEY_ROUND))
    .withColumn("survey_period", F.lit(SURVEY_PERIOD))
    .withColumn("ingestion_timestamp", F.current_timestamp())
)
df = add_provenance(df, SOURCE_NAME, SOURCE_PUBLISHER, SOURCE_URL, F.lit(RETRIEVED_ON).cast("date"),
                    SOURCE_LICENSE, PRODUCED_BY)
df = df.withColumn("row_citation", F.concat(
    F.lit("IIPS/MoHFW, NFHS-5 (2019-21) District Fact Sheet: "), F.coalesce("district_name", F.lit("?")), F.lit(", "),
    F.coalesce("state_ut", F.lit("?")), F.lit(". "), F.lit(SOURCE_URL), F.lit(", file obtained "), F.lit(RETRIEVED_ON), F.lit(".")))

# Staging table instead of df.cache() (not supported on serverless compute): later steps read it once.
assert_no_clean_columns(df, "_nfhs_stage")
df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_nfhs_stage")
df = spark.table("_nfhs_stage")
print("✓ Flags applied")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 4. Quality metrics
# --------------------------------------------------------------------------- #
print("Calculating quality metrics...")
raw_metrics = df.agg(
    F.count(F.lit(1)).alias("rows_after_dedupe"),
    F.sum(F.when(F.col("quarantine_reason").isNotNull(), 1).otherwise(0)).alias("quarantined_rows"),
    F.countDistinct("state_norm").alias("states"),
    F.sum(F.when(F.col("has_estimate_values"), 1).otherwise(0)).alias("rows_with_estimate_values"),
    F.sum(F.when(F.col("unparseable_columns").isNotNull(), 1).otherwise(0)).alias("unparseable_rows"),
    F.sum(F.when(F.col("range_violations").isNotNull(), 1).otherwise(0)).alias("range_violation_rows"),
    F.sum(F.when(F.col("low_sample"), 1).otherwise(0)).alias("low_sample_rows"),
    F.sum(F.when(F.col("has_null_numeric"), 1).otherwise(0)).alias("rows_with_null_numeric"),
    F.sum(F.when(F.col("duplicate_key"), 1).otherwise(0)).alias("duplicate_key_rows"),
    F.sum(F.when(F.col("unexplained_identical_metrics"), 1).otherwise(0)).alias("unexplained_identical_metric_rows"),
).collect()[0].asDict()

m = {k: int(v or 0) for k, v in raw_metrics.items()}
m["bronze_rows"] = int(bronze_count)
m["rows_dropped_as_duplicates"] = m["bronze_rows"] - m["rows_after_dedupe"]
m["silver_rows"] = m["rows_after_dedupe"] - m["quarantined_rows"]
total = max(m["rows_after_dedupe"], 1)

source_files = sorted(
    r["source_file"] for r in df.select("source_file").distinct().collect() if r["source_file"]
)

print("\n" + "=" * 70)
print("SILVER LAYER QUALITY REPORT")
print("=" * 70)
print(f"Bronze rows read:               {m['bronze_rows']:,}")
print(f"Dropped as exact duplicates:    {m['rows_dropped_as_duplicates']:,}")
print(f"Quarantined (known bad):        {m['quarantined_rows']:,}")
print(f"Silver rows:                    {m['silver_rows']:,}")
print(f"States / UTs:                   {m['states']:,}")
print("\nValue quality:")
print(f"  Rows with estimate values:    {m['rows_with_estimate_values']:,}")
print(f"  Rows with unparseable values: {m['unparseable_rows']:,}")
print(f"  Rows with out-of-range values:{m['range_violation_rows']:,}")
print(f"  Rows with a null indicator:   {m['rows_with_null_numeric']:,}")
print("\nReliability and integrity:")
print(f"  Low-sample districts:         {m['low_sample_rows']:,}")
print(f"  Duplicate (state, district):  {m['duplicate_key_rows']:,}")
print(f"  Unexplained identical rows:   {m['unexplained_identical_metric_rows']:,}")
print("=" * 70 + "\n")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 5. Quality gate
# --------------------------------------------------------------------------- #
print("Running quality gate...")
failures = []

def check(condition, message):
    if not condition:
        failures.append(message)

lo, hi = EXPECTED_BRONZE_ROWS
check(lo <= m["bronze_rows"] <= hi, f"Bronze has {m['bronze_rows']:,} rows (expected {lo:,}-{hi:,})")
check(m["states"] >= MIN_STATES, f"Only {m['states']} states/UTs (< {MIN_STATES})")
check(m["rows_dropped_as_duplicates"] / max(m["bronze_rows"], 1) <= MAX_DROPPED_PCT,
      f"{m['rows_dropped_as_duplicates']:,} exact duplicates dropped (> {MAX_DROPPED_PCT:.1%})")
check(m["quarantined_rows"] <= MAX_QUARANTINED_ROWS,
      f"{m['quarantined_rows']} rows quarantined (> {MAX_QUARANTINED_ROWS})")
check(m["duplicate_key_rows"] == 0,
      f"{m['duplicate_key_rows']} rows share a (state, district) key")
check(m["unexplained_identical_metric_rows"] == 0,
      f"{m['unexplained_identical_metric_rows']} rows have identical indicator values")
check(m["unparseable_rows"] <= MAX_UNPARSEABLE_ROWS,
      f"{m['unparseable_rows']} rows have unparseable numeric values")
check(m["range_violation_rows"] <= MAX_RANGE_VIOLATION_ROWS,
      f"{m['range_violation_rows']} rows have out-of-range values")
check(m["rows_with_null_numeric"] / total <= MAX_NULL_NUMERIC_PCT,
      f"{m['rows_with_null_numeric'] / total:.2%} of rows have a null indicator")

history_row = Row(
    **m,
    source_files=", ".join(source_files),
    gate_passed=not failures,
    gate_failures="; ".join(failures),
)
(
    spark.createDataFrame([history_row])
    .withColumn("run_timestamp", F.current_timestamp())
    .write.format("delta").mode("append").option("mergeSchema", "true")
    .saveAsTable(QUALITY_HISTORY_TABLE)
)

if failures:
    raise RuntimeError(
        "Silver quality gate FAILED; tables were NOT written:\n  - " + "\n  - ".join(failures)
    )
print("✓ Quality gate passed")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 6. Validation against bronze (pipeline convention; results in nfhs_validation)
# --------------------------------------------------------------------------- #
INTERNAL_COLS = ["_is_good", "_good_in_metric_group", "quarantine_reason"]
silver = df.filter(F.col("quarantine_reason").isNull()).drop(*INTERNAL_COLS)
quarantined = df.filter(F.col("quarantine_reason").isNotNull()).drop("_is_good", "_good_in_metric_group")

b = spark.table(BRONZE_TABLE).select("_bronze_row_id", *[F.col(c).alias(f"b_{c}") for c in SOURCE_COLS])
j = df.join(b, "_bronze_row_id", "inner")

def expected_value(c):
    t = F.trim(F.col(f"b_{c}"))
    core = F.regexp_replace(t, r"^\((.*)\)$", "$1")
    if c in INT_COLS:
        return F.when(core.rlike(INT_PATTERN), core.cast("double").cast("int"))
    return F.when(core.rlike(DEC_PATTERN), core.cast("double"))

value_mismatch = reduce(or_, [~F.col(c).eqNullSafe(expected_value(c)) for c in NUM_COLS])
checks = [
    ("ROW_RECONCILIATION", "Bronze rows = silver + quarantined + exact duplicates dropped",
     mismatch_rows("bronze_rows", m["bronze_rows"],
                   silver.count() + quarantined.count() + m["rows_dropped_as_duplicates"])),
    ("ROWS_FROM_BRONZE", "Every silver/quarantine row points to an existing bronze row",
     df.join(b, "_bronze_row_id", "left_anti").select("district_name", "state_ut")),
    ("NAMES_FROM_BRONZE", "district_name / state_ut equal the bronze text (spaces collapsed)",
     j.where(~F.col("district_name").eqNullSafe(F.trim(F.regexp_replace("b_district_name", r"\s+", " "))) |
             ~F.col("state_ut").eqNullSafe(F.trim(F.regexp_replace("b_state_ut", r"\s+", " "))))
      .select("district_name", "state_ut")),
    ("VALUES_FROM_BRONZE", "Every indicator equals the bronze text read as a number (parentheses removed)",
     j.where(value_mismatch).select("district_name", "state_ut")),
    ("STATE_STANDARDIZED", "Every silver district has a standardized state",
     silver.where("state IS NULL").select("district_name", "state_ut")),
    ("STATE_DISTRICT_UNIQUE", "(state, district) is unique in silver",
     silver.groupBy("state", "district_std").count().where("count > 1")),
    ("NO_UNPARSEABLE_VALUES", "No indicator text that is neither a number, (number), '*' nor blank",
     silver.where("unparseable_columns IS NOT NULL").select("district_name", "state_ut", "unparseable_columns")),
]
run_validations(checks, "nfhs_validation")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 7. Write Silver and quarantine
# --------------------------------------------------------------------------- #
print("Writing tables...")
write_table(silver.drop("_bronze_row_id"), SILVER_TABLE,
            "NFHS-5 (2019-21) district indicators, one row per (state, district). Validated against nfhs_bronze "
            "(see nfhs_validation). Built by notebooks/04_nfhs_bronze_to_silver.")
write_table(quarantined, QUARANTINE_TABLE, "NFHS rows kept out of nfhs_silver, with quarantine_reason.")
spark.sql("DROP TABLE IF EXISTS _nfhs_stage")
print(f"✓ Silver table written:     {SILVER_TABLE}")
print(f"✓ Quarantine table written: {QUARANTINE_TABLE}")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 8. Optimize and document
# --------------------------------------------------------------------------- #
print("Optimizing tables...")
# Best effort: housekeeping only (the table is ~700 rows), so an unsupported command must not fail the run.
for _stmt in [f"OPTIMIZE {SILVER_TABLE} ZORDER BY (state_norm, district_norm)",
              f"ANALYZE TABLE {SILVER_TABLE} COMPUTE STATISTICS FOR ALL COLUMNS"]:
    try:
        spark.sql(_stmt)
    except Exception as e:
        print(f"  skipped ({type(e).__name__}): {_stmt.split(' ')[0]} not supported here")
print("✓ Optimization complete")

print("Adding column documentation...")
COLUMN_COMMENTS = {
    "district_key": "Deterministic SHA-256 of state + district",
    "state_name": "State/UT with known spelling fixes applied",
    "district_std": "District name with known fixes applied",
    "estimate_columns": "Indicators written in parentheses (25-49 cases)",
    "has_estimate_values": "True when at least one indicator is a small-sample estimate",
    "low_sample": "True when households or men interviewed fall below thresholds",
    "state": "Standardized state/UT, same values as the other silver tables (use for joins)",
    "district_join_key": "District name, lower case, letters and digits only; matches pincode_silver.district_key",
    "district_in_pin_directory": "True if the district exists in that state in the India Post directory (pincode_silver)",
}
for col_name, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE {SILVER_TABLE} ALTER COLUMN `{col_name}` COMMENT '{comment}'")
print("✓ Column comments applied")

# COMMAND ----------

# --------------------------------------------------------------------------- #
# 9. Quality view
# --------------------------------------------------------------------------- #
spark.sql(f"""
CREATE OR REPLACE VIEW {QUALITY_VIEW} AS
SELECT 'Estimate Values' AS metric_category,
       CASE WHEN has_estimate_values THEN 'Has estimate' ELSE 'None' END AS metric_value,
       COUNT(*) AS record_count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
FROM {SILVER_TABLE}
GROUP BY has_estimate_values

UNION ALL

SELECT 'Sample Size',
       CASE WHEN low_sample THEN 'Low sample' ELSE 'Adequate' END,
       COUNT(*),
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)
FROM {SILVER_TABLE}
GROUP BY low_sample

ORDER BY metric_category, metric_value
""")
print(f"✓ Quality view created: {QUALITY_VIEW}")

print("\n" + "=" * 70)
print("SILVER LAYER TRANSFORMATION COMPLETE")
print("=" * 70)
