"""
NFHS district indicators (NFR.csv): Bronze -> Silver (one row per district)
"""
from functools import reduce
from operator import or_

from pyspark.sql import Row, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BRONZE_PATH = "file:/Workspace/Users/elliotl@andrew.cmu.edu/.db_internal/genie/002ce5e3947e4a71be97e9c6ddff5e48/file_uploads/csv/07062480-b6db-4a25-a062-36d6adce15d0"
SILVER_TABLE = "labuser_elliotl.silver.nfhs_district_indicators_silver"
QUARANTINE_TABLE = f"{SILVER_TABLE}_quarantine"
QUALITY_HISTORY_TABLE = f"{SILVER_TABLE}_quality_history"
QUALITY_VIEW = f"{SILVER_TABLE}_quality_current"

SURVEY_ROUND = "NFHS-5"
SURVEY_PERIOD = "2019-21"

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

spark = SparkSession.builder.getOrCreate()

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

# --------------------------------------------------------------------------- #
# 1. Bronze
# --------------------------------------------------------------------------- #
print("Reading bronze data...")

# Read by header name (no forced schema): a user-supplied StructType maps columns
# by POSITION, which silently swapped the pct and sex-ratio columns.
bronze = (
    spark.read
    .option("header", "true")
    .option("encoding", "UTF-8")
    .csv(BRONZE_PATH)
    .select(*SOURCE_COLS, F.col("_metadata.file_path").alias("source_file"))
)
bronze_count = bronze.count()
print(f"✓ Loaded {bronze_count:,} rows from bronze")

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
    raw = F.col(c)
    is_missing_token = raw.isNull() | raw.isin(*NULL_TOKENS)
    is_estimate = raw.rlike(r"^\(.*\)$")
    core = F.regexp_replace(raw, r"^\((.*)\)$", "$1")
    number_pattern = r"^\d+$" if c in INT_COLS else r"^\d+(\.\d+)?$"
    parses_ok = core.rlike(number_pattern)
    df = df.withColumn(f"_est_{c}", F.when(is_estimate, F.lit(c)))
    df = df.withColumn(f"_bad_{c}", F.when(~is_missing_token & ~parses_ok, F.lit(c)))
    df = df.withColumn(c, F.when(parses_ok, core.cast("int" if c in INT_COLS else "double")))

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
)

print("✓ Cleaning complete")

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

df = df.cache()
print("✓ Flags applied")

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
    df.unpersist()
    raise RuntimeError(
        "Silver quality gate FAILED; tables were NOT written:\n  - " + "\n  - ".join(failures)
    )
print("✓ Quality gate passed")

# --------------------------------------------------------------------------- #
# 6. Write Silver and quarantine
# --------------------------------------------------------------------------- #
print("Writing tables...")
INTERNAL_COLS = ["_is_good", "_good_in_metric_group", "quarantine_reason"]

silver = df.filter(F.col("quarantine_reason").isNull()).drop(*INTERNAL_COLS)
quarantined = df.filter(F.col("quarantine_reason").isNotNull()).drop("_is_good", "_good_in_metric_group")

(
    silver.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(SILVER_TABLE)
)
(
    quarantined.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    .saveAsTable(QUARANTINE_TABLE)
)
df.unpersist()
print(f"✓ Silver table written:     {SILVER_TABLE}")
print(f"✓ Quarantine table written: {QUARANTINE_TABLE}")

# --------------------------------------------------------------------------- #
# 7. Optimize and document
# --------------------------------------------------------------------------- #
print("Optimizing tables...")
spark.sql(f"OPTIMIZE {SILVER_TABLE} ZORDER BY (state_norm, district_norm)")
spark.sql(f"ANALYZE TABLE {SILVER_TABLE} COMPUTE STATISTICS FOR ALL COLUMNS")
print("✓ Optimization complete")

print("Adding column documentation...")
COLUMN_COMMENTS = {
    "district_key": "Deterministic SHA-256 of state + district",
    "state_name": "State/UT with known spelling fixes applied",
    "district_std": "District name with known fixes applied",
    "estimate_columns": "Indicators written in parentheses (25-49 cases)",
    "has_estimate_values": "True when at least one indicator is a small-sample estimate",
    "low_sample": "True when households or men interviewed fall below thresholds",
}
for col_name, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE {SILVER_TABLE} ALTER COLUMN `{col_name}` COMMENT '{comment}'")
print("✓ Column comments applied")

# --------------------------------------------------------------------------- #
# 8. Quality view
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
