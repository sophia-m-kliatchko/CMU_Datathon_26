"""
NFHS district indicators (NFR.csv): Bronze -> Silver (one row per district)

The file looks like a 10-column extract of the NFHS-5 (2019-21) district fact
sheets: 706 rows, 36 states/UTs. Findings this script is built around:

  * 704 of 706 district names, 704 sex-ratio-at-birth values and one state name
    carry trailing whitespace.
  * Two sex-ratio-at-birth values are written "(1261)" / "(1111)". NFHS uses
    parentheses for estimates based on only 25-49 cases, so they are valid but
    less reliable. They also turn the column into text unless parsed.
  * "Maharastra" is a misspelling of Maharashtra (36 rows).
  * District names are NOT unique (Aurangabad, Balrampur, Bijapur, Bilaspur,
    Hamirpur ... occur in several states): the key is state + district.
  * Mizoram's "Chandel" row is an exact copy of Manipur's Chandel row and
    Mizoram's Saiha district is missing. It is quarantined, not silently kept.
  * Some districts have very small samples (e.g. 213 households, 17 men).
  * The file starts with a UTF-8 byte-order mark. Reading with an explicit
    schema skips the header line, so the BOM cannot leak into a column name.

Run order: read -> clean/parse -> flags -> metrics -> quality gate -> history
           -> write Silver (+ quarantine). If the gate fails, nothing is written
           except the history row.
"""
from functools import reduce
from operator import or_

from pyspark.sql import Row, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BRONZE_PATH = "path/to/bronze/NFR.csv"
SILVER_TABLE = "catalog.schema.nfhs_district_indicators_silver"
QUARANTINE_TABLE = f"{SILVER_TABLE}_quarantine"
QUALITY_HISTORY_TABLE = f"{SILVER_TABLE}_quality_history"   # one row appended per run
QUALITY_VIEW = f"{SILVER_TABLE}_quality_current"            # current-state summary

# The file does not say what it is. Confirm against your source before relying on these.
SURVEY_ROUND = "NFHS-5"
SURVEY_PERIOD = "2019-21"

# Known-bad rows: (state, district) -> reason. They go to the quarantine table.
KNOWN_BAD_ROWS = {
    ("Mizoram", "Chandel"): "Exact copy of Manipur's Chandel row; Mizoram's Saiha district is missing. "
                            "Replace with Saiha's values from the original NFHS-5 fact sheet.",
}

# Spelling / naming fixes (extend as you find more; keep a crosswalk to other
# sources such as the PIN directory separately, e.g. "NCT of Delhi" vs "Delhi").
STATE_FIXES = {"Maharastra": "Maharashtra"}
DISTRICT_FIXES = {"Sri Potti Sriramulu Nello": "Sri Potti Sriramulu Nellore"}   # truncated in source

# Low-sample flag (suggested cut-offs; adjust to taste)
LOW_SAMPLE_HOUSEHOLDS = 600
LOW_SAMPLE_MEN = 50

# Plausibility ranges (flag violations; the gate decides whether they are fatal)
PCT_RANGE = (0.0, 100.0)
SEX_RATIO_RANGE = (500, 1600)

# Quality-gate thresholds. Ranges, not exact counts, so refreshes pass.
EXPECTED_BRONZE_ROWS = (650, 800)
MIN_STATES = 30
MAX_QUARANTINED_ROWS = 5            # known bad rows only; growth means something new broke
MAX_DROPPED_PCT = 0.01
MAX_NULL_NUMERIC_PCT = 0.02
MAX_UNPARSEABLE_ROWS = 0
MAX_RANGE_VIOLATION_ROWS = 0

spark = SparkSession.builder.getOrCreate()   # already defined in Databricks notebooks

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
NULL_TOKENS = ["", "*", "NA", "na", "-"]      # NFHS uses "*" for suppressed values


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def clean_text(col_name):
    """Trim, collapse repeated whitespace, turn empty strings into NULL."""
    c = F.trim(F.regexp_replace(F.col(col_name), r"\s+", " "))
    return F.when(F.length(c) > 0, c)


def nullify(expr):
    """Turn an empty string (e.g. from concat_ws with no hits) into NULL."""
    return F.when(F.length(expr) > 0, expr)


def apply_mapping(col_name, mapping):
    """Replace exact values using a dict, leaving everything else unchanged."""
    expr = F.col(col_name)
    for bad, good in mapping.items():
        expr = F.when(F.col(col_name) == bad, F.lit(good)).otherwise(expr)
    return expr


# --------------------------------------------------------------------------- #
# 1. Bronze: read as-is (all strings, explicit schema)
# --------------------------------------------------------------------------- #
schema = StructType([StructField(c, StringType(), True) for c in SOURCE_COLS])

bronze = (
    spark.read
    .option("header", "true")          # header line is skipped; names come from `schema`
    .option("encoding", "UTF-8")
    .schema(schema)
    .csv(BRONZE_PATH)
    .select("*", F.col("_metadata.file_path").alias("source_file"))
)
bronze_count = bronze.count()          # for the Bronze -> Silver reconciliation

# --------------------------------------------------------------------------- #
# 2. Clean and parse
# --------------------------------------------------------------------------- #
df = bronze
for c in TEXT_COLS:
    df = df.withColumn(c, clean_text(c))
for c in NUM_COLS:
    df = df.withColumn(c, F.trim(F.col(c)))

df = df.dropDuplicates(SOURCE_COLS)    # exact duplicates

# Numeric parsing: strip "(...)" and remember it was an estimate; anything that is
# neither a suppressed token nor a clean number is reported, never guessed at.
for c in NUM_COLS:
    raw = F.col(c)
    is_missing_token = raw.isNull() | raw.isin(*NULL_TOKENS)
    is_estimate = raw.rlike(r"^\(.*\)$")
    core = F.regexp_replace(raw, r"^\((.*)\)$", "$1")
    number_pattern = r"^\d+$" if c in INT_COLS else r"^\d+(\.\d+)?$"
    parses_ok = core.rlike(number_pattern)
    # helper columns first (they read the raw text), then overwrite the column
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

# Names: keep the trimmed original, add standardised and normalised versions
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

# --------------------------------------------------------------------------- #
# 3. Flags
# --------------------------------------------------------------------------- #
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

# Known-bad rows -> quarantine reason
reason = F.lit(None).cast("string")
for (state, district), why in KNOWN_BAD_ROWS.items():
    reason = F.when(
        (F.col("state_norm") == state.upper()) & (F.col("district_norm") == district.upper()),
        F.lit(why),
    ).otherwise(reason)
df = df.withColumn("quarantine_reason", reason).withColumn(
    "_is_good", F.col("quarantine_reason").isNull().cast("int")
)

# Rows with identical values on every indicator but different districts: this is
# what a copied row looks like, and a key-uniqueness check alone cannot see it.
w_metrics = Window.partitionBy(*NUM_COLS)
w_key = Window.partitionBy("district_key")
df = (
    df
    .withColumn("identical_metrics_rows", F.count(F.lit(1)).over(w_metrics))
    .withColumn("_good_in_metric_group", F.sum("_is_good").over(w_metrics))
    .withColumn("suspected_duplicate_content", F.col("identical_metrics_rows") > 1)
    # unexplained = a good row still sharing identical values with another good row
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

# Cache: metrics, quarantine and Silver writes would otherwise each re-run the plan.
df = df.cache()

# --------------------------------------------------------------------------- #
# 4. Quality metrics + Bronze -> Silver reconciliation
# --------------------------------------------------------------------------- #
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

m = {k: int(v or 0) for k, v in raw_metrics.items()}      # SUM over empty data is NULL
m["bronze_rows"] = int(bronze_count)
m["rows_dropped_as_duplicates"] = m["bronze_rows"] - m["rows_after_dedupe"]
m["silver_rows"] = m["rows_after_dedupe"] - m["quarantined_rows"]
total = max(m["rows_after_dedupe"], 1)                     # avoid divide-by-zero

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
# 5. Quality gate: collect ALL failures, record the run, then decide
# --------------------------------------------------------------------------- #
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
      f"{m['unexplained_identical_metric_rows']} rows have identical indicator values to another district "
      "and are not in KNOWN_BAD_ROWS (possible copied row)")
check(m["unparseable_rows"] <= MAX_UNPARSEABLE_ROWS,
      f"{m['unparseable_rows']} rows have unparseable numeric values")
check(m["range_violation_rows"] <= MAX_RANGE_VIOLATION_ROWS,
      f"{m['range_violation_rows']} rows have out-of-range values")
check(m["rows_with_null_numeric"] / total <= MAX_NULL_NUMERIC_PCT,
      f"{m['rows_with_null_numeric'] / total:.2%} of rows have a null indicator (> {MAX_NULL_NUMERIC_PCT:.0%})")

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
# 6. Write Silver (clean rows) and quarantine (known-bad rows)
# --------------------------------------------------------------------------- #
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
# 7. Column documentation (overwrite + overwriteSchema wipes comments, so re-apply)
# --------------------------------------------------------------------------- #
COLUMN_COMMENTS = {
    "district_key": "Deterministic SHA-256 of state + district (district names repeat across states)",
    "state_name": "State/UT with known spelling fixes applied (original in state_ut)",
    "district_std": "District name with known fixes applied (original in district_name)",
    "estimate_columns": "Comma-separated indicators that were written in parentheses in the source, "
                        "meaning an estimate based on 25-49 cases",
    "has_estimate_values": "True when at least one indicator is a small-sample estimate",
    "low_sample": "True when households or men interviewed fall below the configured thresholds",
    "suspected_duplicate_content": "True when another row, possibly quarantined, has identical values "
                                   "on every indicator",
    "sex_ratio_at_birth_5y_f_per_1000_m": "Females per 1,000 males born in the last 5 years "
                                          "(parentheses removed; see estimate_columns)",
}
for col_name, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE {SILVER_TABLE} ALTER COLUMN {col_name} COMMENT '{comment}'")
print("✓ Column comments applied")

# --------------------------------------------------------------------------- #
# 8. Current-state quality view (history over time is in QUALITY_HISTORY_TABLE)
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

UNION ALL

SELECT 'Districts per State',
       state_name,
       COUNT(*),
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)
FROM {SILVER_TABLE}
GROUP BY state_name

ORDER BY metric_category, metric_value
""")
print(f"✓ Quality view created: {QUALITY_VIEW}")

print("\n" + "=" * 70)
print("SILVER LAYER TRANSFORMATION COMPLETE")
print("=" * 70)
