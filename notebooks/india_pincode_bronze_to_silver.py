"""
India Post PIN directory: Bronze -> Silver (one row per post office)

Written against the data.gov.in "All India Pincode Directory" CSV.

Findings this script is built around (observed on the raw file; counts will
drift as the source is refreshed, so nothing below is hard-coded):
  * Missing values are the literal text "NA", not empty cells.
  * `latitude` contains junk: "18.856818°", "28.430354° N", DMS strings like
    "17°57'17.7", and values like "28.4 32628". It also has 0s and values in the
    hundreds of millions, so a plain cast is not enough.
  * Some copies of the file have NO longitude column. Set HAS_LONGITUDE below.
  * A PIN is not a place: some PINs span more than one district (and a few more
    than one state), so joins on `pincode` alone fan out. See `pin_ambiguous`.
  * Office-name suffixes are inconsistent ("B.O", "BO", "B.O.", "S.O", "SO"...).
  * A small share of rows has no district/state/region.

Column naming (team rule, 2026-11-21): silver columns never get a "_clean" suffix; being in
silver already means clean. Parsed coordinates are `latitude`/`longitude`; the raw text is in
`latitude_raw`/`longitude_raw`.

Run order: read -> clean -> metrics -> quality gate -> history -> write Silver.
If the gate fails, the Silver table is NOT overwritten.
"""
from pyspark.sql import Row, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
BRONZE_PATH = "path/to/bronze/india_post_pincode_directory.csv"
SILVER_TABLE = "catalog.schema.india_post_offices_silver"
QUALITY_HISTORY_TABLE = f"{SILVER_TABLE}_quality_history"   # one row appended per run
QUALITY_VIEW = f"{SILVER_TABLE}_quality_current"            # current-state summary

HAS_LONGITUDE = False          # set True if your file has a `longitude` column
LAT_RANGE = (6.0, 38.0)        # generous bounds for India (incl. islands)
LON_RANGE = (68.0, 98.0)

# Quality-gate thresholds. Ranges, not exact counts, so monthly refreshes pass.
# Defaults are set with headroom around what the raw file looked like
# (~165k rows, ~19.6k PINs, <1% missing state, ~90% usable latitude).
MIN_RECORDS = 100_000
MIN_UNIQUE_PINS = 19_000
MAX_MISSING_STATE_PCT = 0.01
MAX_INVALID_PIN_PCT = 0.001
MAX_DROPPED_PCT = 0.01         # share of Bronze rows removed as duplicates
MIN_VALID_LATITUDE_PCT = 0.80

spark = SparkSession.builder.getOrCreate()   # already defined in Databricks notebooks

SOURCE_COLS = [
    "circlename", "regionname", "divisionname", "officename", "pincode",
    "officetype", "delivery", "district", "statename", "latitude",
] + (["longitude"] if HAS_LONGITUDE else [])

TEXT_COLS = [c for c in SOURCE_COLS if c not in ("latitude", "longitude")]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def clean_text(col_name):
    """Trim, collapse repeated whitespace, turn empty strings into NULL."""
    c = F.trim(F.regexp_replace(F.col(col_name), r"\s+", " "))
    return F.when(F.length(c) > 0, c)


def parse_coord(raw_col):
    """
    Accept only plain decimals, optionally with a degree sign and N/E suffix
    ("18.85", "18.85°", "28.43° N"). Anything else (DMS such as 17°57'17.7,
    or "28.4 32628") is deliberately NOT guessed at -> NULL, flagged
    'unparseable'. Guessing the first number would silently produce
    plausible-looking but wrong coordinates.
    """
    pattern = r"^\s*(\d+(?:\.\d+)?)\s*°?\s*[NnEe]?\s*$"
    num = F.regexp_extract(raw_col, pattern, 1)
    return F.when(num != "", num.cast("double"))


def coord_status(raw_col, parsed_col, lo, hi):
    return (
        F.when(raw_col.isNull(), "missing")
        .when(parsed_col.isNull(), "unparseable")
        .when(parsed_col.between(lo, hi), "ok")
        .otherwise("out_of_range")
    )


# --------------------------------------------------------------------------- #
# 1. Bronze: read as-is (all strings, explicit schema, "NA" -> NULL)
# --------------------------------------------------------------------------- #
schema = StructType([StructField(c, StringType(), True) for c in SOURCE_COLS])

bronze = (
    spark.read
    .option("header", "true")
    .option("nullValue", "NA")
    .option("ignoreLeadingWhiteSpace", "true")
    .option("ignoreTrailingWhiteSpace", "true")
    .schema(schema)
    .csv(BRONZE_PATH)
    .select("*", F.col("_metadata.file_path").alias("source_file"))
)
bronze_count = bronze.count()    # for the Bronze -> Silver reconciliation

# --------------------------------------------------------------------------- #
# 2. Silver transformations
# --------------------------------------------------------------------------- #
df = bronze.dropDuplicates(SOURCE_COLS)          # exact duplicates, before adding metadata

# Standardise text but KEEP original casing for display
for c in TEXT_COLS:
    df = df.withColumn(c, clean_text(c))

df = (
    df
    .withColumnRenamed("latitude", "latitude_raw")
    # normalised join keys (original columns stay untouched)
    .withColumn("district_norm", F.upper(F.col("district")))
    .withColumn("state_norm", F.upper(F.col("statename")))
    .withColumn("officetype", F.upper(F.col("officetype")))
    # office name without the B.O / BO / S.O / SO / H.O / HO suffix variants
    .withColumn(
        "office_name",
        F.trim(F.regexp_replace(F.col("officename"), r"(?i)\s+[BSH]\.?\s?O\.?$", "")),
    )
    .withColumn("is_delivery_office", F.upper(F.col("delivery")) == F.lit("DELIVERY"))
    # PIN stays a string; validity flag instead of dropping rows
    .withColumn("pincode_valid", F.col("pincode").rlike(r"^[1-9][0-9]{5}$"))
)

# Latitude (and longitude if present): parse, validate range, keep a status
df = df.withColumn("latitude", parse_coord(F.col("latitude_raw")))
df = df.withColumn(
    "latitude_status",
    coord_status(F.col("latitude_raw"), F.col("latitude"), *LAT_RANGE),
)
df = df.withColumn(
    "latitude",
    F.when(F.col("latitude_status") == "ok", F.col("latitude")),
)

if HAS_LONGITUDE:
    df = df.withColumnRenamed("longitude", "longitude_raw")
    df = df.withColumn("longitude", parse_coord(F.col("longitude_raw")))
    df = df.withColumn(
        "longitude_status",
        coord_status(F.col("longitude_raw"), F.col("longitude"), *LON_RANGE),
    )
    df = df.withColumn(
        "longitude",
        F.when(F.col("longitude_status") == "ok", F.col("longitude")),
    )
    df = df.withColumn(
        "has_valid_coordinates",
        (F.col("latitude_status") == "ok") & (F.col("longitude_status") == "ok"),
    )
else:
    # Without longitude there are no usable coordinates, so say "latitude" only.
    df = df.withColumn("has_valid_latitude", F.col("latitude_status") == "ok")

# Completeness flags (filterable, instead of one made-up score)
df = (
    df
    .withColumn("missing_district", F.col("district").isNull())
    .withColumn("missing_state", F.col("statename").isNull())
    .withColumn("missing_region", F.col("regionname").isNull())
)

# Second de-dupe: whitespace/casing differences can create new exact duplicates
cleaned_identity = [
    "circlename", "regionname", "divisionname", "officename", "pincode",
    "officetype", "delivery", "district", "statename", "latitude_raw",
] + (["longitude_raw"] if HAS_LONGITUDE else [])
df = df.dropDuplicates(cleaned_identity)

# PIN ambiguity: expose it, don't try to "fix" it in Silver
w_pin = Window.partitionBy("pincode")
df = (
    df
    .withColumn("pin_n_offices", F.count(F.lit(1)).over(w_pin))
    .withColumn("pin_n_districts", F.size(F.collect_set("district_norm").over(w_pin)))
    .withColumn("pin_n_states", F.size(F.collect_set("state_norm").over(w_pin)))
    .withColumn(
        "pin_ambiguous",
        (F.col("pin_n_districts") > 1) | (F.col("pin_n_states") > 1),
    )
)

# Deterministic surrogate key (survives reloads, unlike monotonically_increasing_id).
# A few offices share the natural key, so add a deterministic tie-breaker.
natural_key_cols = ["pincode", "office_name", "officetype", "district_norm", "divisionname"]
key_hash = F.sha2(
    F.concat_ws("|", *[F.coalesce(F.col(c), F.lit("")) for c in natural_key_cols]), 256
)
df = df.withColumn("_key_hash", key_hash)
w_dup = Window.partitionBy("_key_hash").orderBy(
    "circlename", "regionname", "delivery", "latitude_raw"
)
df = (
    df
    .withColumn("_dup_seq", F.row_number().over(w_dup))
    .withColumn("office_id", F.sha2(F.concat_ws("|", F.col("_key_hash"), F.col("_dup_seq")), 256))
    .drop("_key_hash", "_dup_seq")
    .withColumn("ingestion_timestamp", F.current_timestamp())
)

# Cache: the metrics below and the write further down would otherwise each
# re-run the whole plan (both de-dupes and all window functions).
silver = df.cache()

# --------------------------------------------------------------------------- #
# 3. Quality metrics + Bronze -> Silver reconciliation
# --------------------------------------------------------------------------- #
raw_metrics = silver.agg(
    F.count(F.lit(1)).alias("total_records"),
    F.countDistinct("pincode").alias("unique_pins"),
    F.sum(F.when(F.col("latitude_status") == "ok", 1).otherwise(0)).alias("valid_latitude"),
    F.sum(F.when(F.col("latitude_status") == "unparseable", 1).otherwise(0)).alias("unparseable_latitude"),
    F.sum(F.when(F.col("latitude_status") == "out_of_range", 1).otherwise(0)).alias("out_of_range_latitude"),
    F.sum(F.when(F.col("latitude_status") == "missing", 1).otherwise(0)).alias("missing_latitude"),
    F.sum(F.when(F.col("pin_ambiguous"), 1).otherwise(0)).alias("ambiguous_pin_records"),
    F.countDistinct(F.when(F.col("pin_ambiguous"), F.col("pincode"))).alias("ambiguous_pin_count"),
    F.sum(F.when(F.col("missing_district"), 1).otherwise(0)).alias("missing_district_count"),
    F.sum(F.when(F.col("missing_state"), 1).otherwise(0)).alias("missing_state_count"),
    F.sum(F.when(~F.col("pincode_valid"), 1).otherwise(0)).alias("invalid_pincode_count"),
).collect()[0].asDict()

m = {k: int(v or 0) for k, v in raw_metrics.items()}     # SUM over empty data is NULL
m["bronze_rows"] = int(bronze_count)
m["rows_dropped_as_duplicates"] = m["bronze_rows"] - m["total_records"]
total = max(m["total_records"], 1)                         # avoid divide-by-zero

source_files = sorted(
    r["source_file"] for r in silver.select("source_file").distinct().collect()
    if r["source_file"]
)

print("\n" + "=" * 70)
print("SILVER LAYER QUALITY REPORT")
print("=" * 70)
print(f"Bronze rows read:           {m['bronze_rows']:,}")
print(f"Silver rows:                {m['total_records']:,}")
print(f"Dropped as duplicates:      {m['rows_dropped_as_duplicates']:,}")
print(f"Unique PIN codes:           {m['unique_pins']:,}")
print("\nLatitude quality:")
print(f"  Valid:                    {m['valid_latitude']:,}")
print(f"  Missing:                  {m['missing_latitude']:,}")
print(f"  Unparseable:              {m['unparseable_latitude']:,}")
print(f"  Out of range:             {m['out_of_range_latitude']:,}")
print("\nPIN code ambiguity:")
print(f"  Records in ambiguous PINs:{m['ambiguous_pin_records']:,}")
print(f"  Ambiguous PINs:           {m['ambiguous_pin_count']:,}")
print("\nCompleteness:")
print(f"  Missing district:         {m['missing_district_count']:,}")
print(f"  Missing state:            {m['missing_state_count']:,}")
print(f"  Invalid PIN format:       {m['invalid_pincode_count']:,}")
print("=" * 70 + "\n")

# --------------------------------------------------------------------------- #
# 4. Quality gate: collect ALL failures, record the run, then decide
# --------------------------------------------------------------------------- #
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


check(m["total_records"] >= MIN_RECORDS,
      f"Silver has {m['total_records']:,} rows (< {MIN_RECORDS:,})")
check(m["unique_pins"] >= MIN_UNIQUE_PINS,
      f"Only {m['unique_pins']:,} distinct PINs (< {MIN_UNIQUE_PINS:,})")
check(m["bronze_rows"] > 0 and m["rows_dropped_as_duplicates"] / max(m["bronze_rows"], 1) <= MAX_DROPPED_PCT,
      f"{m['rows_dropped_as_duplicates']:,} of {m['bronze_rows']:,} Bronze rows dropped as duplicates "
      f"(> {MAX_DROPPED_PCT:.1%})")
check(m["missing_state_count"] / total <= MAX_MISSING_STATE_PCT,
      f"Missing state is {m['missing_state_count'] / total:.2%} (> {MAX_MISSING_STATE_PCT:.1%})")
check(m["invalid_pincode_count"] / total <= MAX_INVALID_PIN_PCT,
      f"Invalid PIN format is {m['invalid_pincode_count'] / total:.3%} (> {MAX_INVALID_PIN_PCT:.1%})")
check(m["valid_latitude"] / total >= MIN_VALID_LATITUDE_PCT,
      f"Valid latitude is {m['valid_latitude'] / total:.1%} (< {MIN_VALID_LATITUDE_PCT:.0%})")

# Append one row per run so quality can be tracked over time (also on failure)
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
    silver.unpersist()
    raise RuntimeError(
        "Silver quality gate FAILED; table was NOT written:\n  - " + "\n  - ".join(failures)
    )
print("✓ Quality gate passed")

# --------------------------------------------------------------------------- #
# 5. Write Silver table
# --------------------------------------------------------------------------- #
(
    silver.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(SILVER_TABLE)
)
silver.unpersist()
print(f"✓ Silver table written: {SILVER_TABLE}")

# No OPTIMIZE / ZORDER / ANALYZE: ~165k rows (~20 MB) is roughly one small file,
# so there is nothing to compact or skip, and predictive optimization covers
# managed Unity Catalog tables anyway.

# --------------------------------------------------------------------------- #
# 6. Column documentation (overwrite + overwriteSchema wipes comments, so re-apply)
# --------------------------------------------------------------------------- #
COLUMN_COMMENTS = {
    "latitude_status": "Coordinate quality: missing | unparseable | out_of_range | ok",
    "latitude": "Parsed latitude; NULL unless latitude_status = ok",
    "pin_ambiguous": "True when offices sharing this PIN map to more than one district or state "
                     "(district compared case-insensitively). Join on PIN with care.",
    "office_id": "Deterministic SHA-256 surrogate key (stable across reloads)",
    "office_name": "Office name with suffix variants (B.O/BO/S.O/SO/H.O/HO) removed",
    "district_norm": "Upper-cased district, for joins. Original casing is in district",
    "state_norm": "Upper-cased state, for joins. Original casing is in statename",
}
for col_name, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE {SILVER_TABLE} ALTER COLUMN {col_name} COMMENT '{comment}'")
print("✓ Column comments applied")

# --------------------------------------------------------------------------- #
# 7. Current-state quality view (history over time is in QUALITY_HISTORY_TABLE)
# --------------------------------------------------------------------------- #
spark.sql(f"""
CREATE OR REPLACE VIEW {QUALITY_VIEW} AS
SELECT 'Latitude Status' AS metric_category,
       latitude_status AS metric_value,
       COUNT(*) AS record_count,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS percentage
FROM {SILVER_TABLE}
GROUP BY latitude_status

UNION ALL

SELECT 'PIN Ambiguity',
       CASE WHEN pin_ambiguous THEN 'Ambiguous' ELSE 'Unique' END,
       COUNT(*),
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)
FROM {SILVER_TABLE}
GROUP BY pin_ambiguous

UNION ALL

SELECT 'District Completeness',
       CASE WHEN missing_district THEN 'Missing' ELSE 'Present' END,
       COUNT(*),
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)
FROM {SILVER_TABLE}
GROUP BY missing_district

UNION ALL

SELECT 'State Completeness',
       CASE WHEN missing_state THEN 'Missing' ELSE 'Present' END,
       COUNT(*),
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)
FROM {SILVER_TABLE}
GROUP BY missing_state

ORDER BY metric_category, metric_value
""")
print(f"✓ Quality view created: {QUALITY_VIEW}")

print("\n" + "=" * 70)
print("SILVER LAYER TRANSFORMATION COMPLETE")
print("=" * 70)
