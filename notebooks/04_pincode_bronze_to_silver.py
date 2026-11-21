# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # 04 · PIN directory: `pincode_bronze` → `pincode_silver`, `pincode_centroids_silver`
# MAGIC
# MAGIC **Input:** India Post *All India Pincode Directory* (`data/raw/india_post_pincode_directory.csv`, about 165k post offices), as a CSV in a Volume or an uploaded table.
# MAGIC
# MAGIC | Output table | Grain | What it's for |
# MAGIC |---|---|---|
# MAGIC | `pincode_bronze` | 1 row per source row | Raw copy (all text), plus load metadata |
# MAGIC | `pincode_silver` | 1 row per post office | Cleaned offices: standardized state/district, parsed coordinates, PIN ambiguity, flags, citations |
# MAGIC | `pincode_centroids_silver` | 1 row per PIN code | **Turns a user's PIN into a location**: median point of the PIN's offices, spread, main district/state |
# MAGIC | `pincode_rejected` | 1 row per removed row | Rows removed (invalid PIN), with the reason |
# MAGIC | `pincode_dq_summary` | 1 row per flag | How many offices carry each flag |
# MAGIC | `pincode_validation` | 1 row per check | Silver-vs-bronze accuracy checks (all must pass) |
# MAGIC
# MAGIC **Main cleaning steps**
# MAGIC * `"NA"` text becomes NULL; text is trimmed. Exact duplicate rows are collapsed (`n_listings`).
# MAGIC * **Coordinates** (`common/coordinate_parsing`): degree signs and N/E letters removed, degree-minute-second values converted, stray spaces in decimals removed, swapped lat/lon fixed, values outside India set to NULL. `lat_how`/`lon_how` record how each value was read.
# MAGIC * Offices more than **50 km** from their PIN's median point **don't match their PIN: their coordinates are set to NULL** (`coord_status = nulled_far_from_pin`, flag `COORDS_NULLED_FAR_FROM_PIN`).
# MAGIC * **Validation:** before publishing, `pincode_silver` and `pincode_centroids_silver` are checked against `pincode_bronze` (row counts, PINs, names, coordinates, state, district); results in `pincode_validation`. Any failure stops the run before the silver tables are overwritten.
# MAGIC * **PIN ambiguity:** a PIN can span several districts or states. This is exposed (`pin_n_districts`, `pin_n_states`, `pin_ambiguous`), not "fixed".
# MAGIC * State standardized with `common/reference_data`; district title-cased plus a join key.
# MAGIC * In `pincode_silver`, cleaned columns have plain names (`latitude`, `longitude`, `state`, `district`, `office_name`); the raw text is in `latitude_raw`, `longitude_raw`, `statename`, `district_raw`, `officename`.
# MAGIC
# MAGIC Builds on elliotl-ops's `notebooks/india_pincode_bronze_to_silver.py`: the "NA" handling, junk-latitude findings, PIN ambiguity, office-name suffix cleaning and deterministic `office_id` come from there.
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`; the source is cited in `docs/data-sources.md`.

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

# MAGIC %run ./common/coordinate_parsing

# COMMAND ----------

# MAGIC %run ./common/validation

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("source", "/Volumes/workspace/datathon/external/india_post_pincode_directory.csv",
                     "3. Source: CSV path or table name")
dbutils.widgets.text("retrieved_on", "2026-11-21", "4. Date the source file was obtained")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
SOURCE = dbutils.widgets.get("source").strip()
RETRIEVED_ON = dbutils.widgets.get("retrieved_on").strip()
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

FAR_FROM_PIN_KM = 50.0   # office further than this from its PIN's median point -> coordinates don't match the PIN -> set to NULL

SOURCE_NAME = "All India Pincode Directory"
SOURCE_PUBLISHER = "Department of Posts, Ministry of Communications, Government of India (via Open Government Data Platform India)"
SOURCE_URL = "https://data.gov.in/resource/all-india-pincode-directory-till-last-month"
SOURCE_LICENSE = "Government Open Data License - India (GODL), if obtained from data.gov.in"
PRODUCED_BY = "notebooks/04_pincode_bronze_to_silver.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)"

from pyspark.sql import Window
EXPECTED = ["circlename", "regionname", "divisionname", "officename", "pincode", "officetype",
            "delivery", "district", "statename", "latitude", "longitude"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Bronze: raw copy (every column as text)

# COMMAND ----------

if "/" in SOURCE:
    raw = (spark.read.option("header", True).option("inferSchema", False).option("encoding", "UTF-8")
           .csv(SOURCE))
else:
    raw = spark.table(SOURCE)
raw = raw.select([F.col(f"`{c}`").cast("string").alias(c.strip().lower()) for c in raw.columns])
missing = [c for c in EXPECTED if c not in raw.columns]
assert not missing, f"Source is missing columns {missing}. Found: {raw.columns}"

(raw.withColumn("_bronze_row_id", F.monotonically_increasing_id())
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source", F.lit(SOURCE))
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pincode_bronze"))
bronze = spark.table("pincode_bronze")
n_bronze = bronze.count()
print(f"pincode_bronze: {n_bronze:,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Clean each office

# COMMAND ----------

def txt(c):
    """Trim, collapse spaces, and turn NA/blank into NULL."""
    t = F.trim(F.regexp_replace(F.col(c), r"\s+", " "))
    return F.when(~F.upper(t).isin("", "NA", "N/A", "NULL", "NONE"), t)

df = bronze.select("_bronze_row_id", *[txt(c).alias(c) for c in EXPECTED])

# Invalid PINs are removed (logged in pincode_rejected); everything else stays, flagged
PIN_OK = F.coalesce(F.col("pincode").rlike(r"^[1-9][0-9]{5}$"), F.lit(False))
rejected = df.where(~PIN_OK).select(
    F.array("_bronze_row_id").alias("source_row_ids"), "pincode", "officename",
    F.lit("INVALID_PINCODE").alias("reject_reason"))
df = df.where(PIN_OK)

# Collapse exact duplicates (same text in every column)
df = df.groupBy(*EXPECTED).agg(F.count(F.lit(1)).alias("n_listings"),
                               F.sort_array(F.collect_list("_bronze_row_id")).alias("source_row_ids"))
# Raw columns whose plain name a cleaned column will use are kept as *_raw (for citations).
# Silver never has *_clean columns: being in silver already means clean.
df = (df.withColumnRenamed("latitude", "latitude_raw")
        .withColumnRenamed("longitude", "longitude_raw")
        .withColumnRenamed("district", "district_raw"))

df = (df
    .withColumn("_c", fix_pair_udf(F.col("latitude_raw"), F.col("longitude_raw")))
    .withColumn("latitude", F.col("_c.latitude"))
    .withColumn("longitude", F.col("_c.longitude"))
    .withColumn("coord_status", F.col("_c.coord_status"))
    .withColumn("lat_how", F.col("_c.lat_how"))
    .withColumn("lon_how", F.col("_c.lon_how"))
    .drop("_c")
    .withColumn("state", state_from_text(F.col("statename")))
    .withColumn("district", F.initcap(F.lower(F.col("district_raw"))))
    .withColumn("district_key", F.regexp_replace(F.lower(F.col("district_raw")), r"[^a-z0-9]", ""))
    .withColumn("office_type", F.upper(F.col("officetype")))
    .withColumn("office_type_label", F.when(F.col("office_type") == "HO", "Head Office")
                                      .when(F.col("office_type") == "PO", "Sub/Post Office")
                                      .when(F.col("office_type") == "BO", "Branch Office"))
    .withColumn("office_name",
                F.trim(F.regexp_replace(F.col("officename"), r"(?i)\s*\b[BSH]\.?\s?O\.?$", "")))
    .withColumn("is_delivery_office", F.upper(F.col("delivery")) == "DELIVERY")
)

# PIN ambiguity: one PIN can serve several districts or states
w_pin = Window.partitionBy("pincode")
df = (df
    .withColumn("pin_n_offices", F.count(F.lit(1)).over(w_pin))
    .withColumn("pin_n_districts", F.size(F.collect_set("district_key").over(w_pin)))
    .withColumn("pin_n_states", F.size(F.collect_set("state").over(w_pin)))
    .withColumn("pin_ambiguous", (F.col("pin_n_districts") > 1) | (F.col("pin_n_states") > 1))
)

# Distance from the PIN's median point (robust to a few bad coordinates)
df = (df
    .withColumn("_pin_med_lat", F.percentile_approx("latitude", 0.5).over(w_pin))
    .withColumn("_pin_med_lon", F.percentile_approx("longitude", 0.5).over(w_pin)))
p = 3.141592653589793 / 180
h = (F.pow(F.sin((F.col("latitude") - F.col("_pin_med_lat")) * p / 2), 2) +
     F.cos(F.col("_pin_med_lat") * p) * F.cos(F.col("latitude") * p) *
     F.pow(F.sin((F.col("longitude") - F.col("_pin_med_lon")) * p / 2), 2))
df = (df
    .withColumn("km_from_pin_median", F.round(2 * 6371.0 * F.asin(F.least(F.lit(1.0), F.sqrt(h))), 2))
    .withColumn("coords_far_from_pin", F.col("km_from_pin_median") > FAR_FROM_PIN_KM)
    .drop("_pin_med_lat", "_pin_med_lon"))

# Coordinates that don't match their PIN (over FAR_FROM_PIN_KM from the PIN's median point) are set to NULL.
# km_from_pin_median keeps the distance of the original point, so the reason stays visible.
far = F.coalesce(F.col("coords_far_from_pin"), F.lit(False))
df = (df
    .withColumn("coord_status", F.when(far, F.lit("nulled_far_from_pin")).otherwise(F.col("coord_status")))
    .withColumn("latitude", F.when(far, F.lit(None).cast("double")).otherwise(F.col("latitude")))
    .withColumn("longitude", F.when(far, F.lit(None).cast("double")).otherwise(F.col("longitude"))))

# Deterministic office_id (stable across reloads; tie-breaker for offices sharing the natural key)
key_cols = ["pincode", "office_name", "office_type", "district_key", "divisionname"]
df = df.withColumn("_k", F.sha2(F.concat_ws("|", *[F.coalesce(F.col(c), F.lit("")) for c in key_cols]), 256))
w_k = Window.partitionBy("_k").orderBy("circlename", "regionname", "delivery", "latitude_raw", "longitude_raw")
df = (df.withColumn("office_id", F.substring(F.sha2(F.concat_ws("|", "_k", F.row_number().over(w_k)), 256), 1, 16))
        .drop("_k"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Flags, citations, stage `pincode_silver`
# MAGIC Written to a staging table first; it only becomes `pincode_silver` after the bronze checks in section 5 pass.

# COMMAND ----------

FLAGS = [
    ("COORDS_MISSING",              F.col("coord_status") == "missing"),
    ("COORDS_UNPARSEABLE",          F.col("coord_status") == "unparseable"),
    ("COORDS_ZERO",                 F.col("coord_status") == "zero"),
    ("COORDS_OUTSIDE_INDIA",        F.col("coord_status") == "out_of_range"),
    ("COORDS_SWAPPED_FIXED",        F.col("coord_status") == "swapped_fixed"),
    ("COORDS_TEXT_REPAIRED",        F.col("lat_how").isin("symbols_removed", "dms_converted", "space_removed") |
                                    F.col("lon_how").isin("symbols_removed", "dms_converted", "space_removed")),
    ("COORDS_NULLED_FAR_FROM_PIN",  F.col("coords_far_from_pin")),
    ("PIN_SPANS_DISTRICTS",         F.col("pin_n_districts") > 1),
    ("PIN_SPANS_STATES",            F.col("pin_n_states") > 1),
    ("MISSING_DISTRICT",            F.col("district_raw").isNull()),
    ("STATE_UNRECOGNIZED",          F.col("state").isNull()),
    ("DUPLICATE_ROW_COLLAPSED",     F.col("n_listings") > 1),
]
silver = df.withColumn(
    "dq_flags",
    F.filter(F.array(*[F.when(F.coalesce(c, F.lit(False)), F.lit(code)) for code, c in FLAGS]), lambda x: x.isNotNull()))
silver = add_provenance(silver, SOURCE_NAME, SOURCE_PUBLISHER, SOURCE_URL,
                        F.lit(RETRIEVED_ON).cast("date"), SOURCE_LICENSE, PRODUCED_BY)
silver = silver.withColumn("row_citation", F.concat(
    F.lit("India Post, All India Pincode Directory: "), F.coalesce(F.col("officename"), F.lit("?")),
    F.lit(", PIN "), F.col("pincode"), F.lit(", "), F.coalesce(F.col("district_raw"), F.lit("?")), F.lit(", "),
    F.coalesce(F.col("statename"), F.lit("?")), F.lit(". "), F.lit(SOURCE_URL), F.lit(", obtained "), F.lit(RETRIEVED_ON), F.lit(".")))

ORDER = ["office_id", "pincode", "officename", "office_name", "office_type", "office_type_label", "is_delivery_office",
         "district", "state", "latitude", "longitude", "coord_status", "km_from_pin_median",
         "coords_far_from_pin", "pin_n_offices", "pin_n_districts", "pin_n_states", "pin_ambiguous", "dq_flags",
         "row_citation", "circlename", "regionname", "divisionname", "district_raw", "district_key", "statename",
         "officetype", "delivery", "latitude_raw", "longitude_raw", "lat_how", "lon_how", "n_listings", "source_row_ids",
         "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
silver_out = silver.select(*ORDER)
assert_no_clean_columns(silver_out, "_pincode_silver_stage")
silver_out.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_pincode_silver_stage")
silver = spark.table("_pincode_silver_stage")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · `pincode_centroids_silver`: one row per PIN
# MAGIC The centroid is the **median** latitude/longitude of the PIN's offices with usable coordinates (offices whose coordinates didn't match their PIN were already set to NULL). `main_district`/`main_state` are the ones with the most offices; all of them are listed in `districts`/`states`.

# COMMAND ----------

good = F.col("latitude").isNotNull() & ~F.coalesce(F.col("coords_far_from_pin"), F.lit(False))
by_district = (silver.groupBy("pincode", "district", "state").count()
               .withColumn("_r", F.row_number().over(Window.partitionBy("pincode").orderBy(F.desc("count"), "district")))
               .where("_r = 1").select("pincode", F.col("district").alias("main_district"),
                                       F.col("state").alias("main_state")))
cent = (silver.groupBy("pincode").agg(
            F.count(F.lit(1)).alias("n_offices"),
            F.sum(F.when(good, 1).otherwise(0)).alias("n_offices_used_for_centroid"),
            F.percentile_approx(F.when(good, F.col("latitude")), 0.5).alias("latitude"),
            F.percentile_approx(F.when(good, F.col("longitude")), 0.5).alias("longitude"),
            F.max(F.when(good, F.col("km_from_pin_median"))).alias("max_office_distance_km"),
            F.sort_array(F.collect_set("district")).alias("districts"),
            F.sort_array(F.collect_set("state")).alias("states"),
            F.first(F.when(F.col("office_type") == "HO", F.col("office_name")), ignorenulls=True).alias("head_office"),
            F.max("pin_ambiguous").alias("pin_ambiguous"))
        .join(by_district, "pincode", "left")
        .withColumn("centroid_quality",
                    F.when(F.col("latitude").isNull(), "none")
                     .when(F.col("n_offices_used_for_centroid") == 1, "single_office")
                     .when(F.col("max_office_distance_km") > 25, "spread_out")
                     .otherwise("good")))
cent = add_provenance(cent, SOURCE_NAME, SOURCE_PUBLISHER, SOURCE_URL,
                      F.lit(RETRIEVED_ON).cast("date"), SOURCE_LICENSE, PRODUCED_BY)
cent = cent.withColumn("row_citation", F.concat(
    F.lit("Median location of "), F.col("n_offices_used_for_centroid").cast("string"),
    F.lit(" post offices with PIN "), F.col("pincode"),
    F.lit(", India Post All India Pincode Directory, "), F.lit(SOURCE_URL), F.lit(", obtained "), F.lit(RETRIEVED_ON), F.lit(".")))
assert_no_clean_columns(cent, "_pincode_centroids_stage")
cent.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("_pincode_centroids_stage")
cent = spark.table("_pincode_centroids_stage")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Validation: silver must be accurate to `pincode_bronze`
# MAGIC Every check lists the rows that break a rule; all must be empty. Results go to `pincode_validation`.
# MAGIC If any check fails, the notebook stops here and `pincode_silver` / `pincode_centroids_silver` are **not** overwritten.

# COMMAND ----------

b = spark.table("pincode_bronze").select("_bronze_row_id", *[txt(c).alias(f"b_{c}") for c in EXPECTED])
s_rows = silver.select("office_id", "pincode", "officename", "state", "district", "latitude", "longitude",
                       "latitude_raw", "longitude_raw", "coord_status", F.explode("source_row_ids").alias("_bronze_row_id"))
j = s_rows.join(b, "_bronze_row_id", "inner")
reparsed = silver.withColumn("_p", fix_pair_udf(F.col("latitude_raw"), F.col("longitude_raw")))
office_box = (silver.where("latitude IS NOT NULL").groupBy("pincode")
              .agg(F.min("latitude").alias("_min_lat"), F.max("latitude").alias("_max_lat"),
                   F.min("longitude").alias("_min_lon"), F.max("longitude").alias("_max_lon")))
n_rejected = rejected.count()
n_listed = silver.agg(F.sum("n_listings")).first()[0] or 0

checks = [
    ("ROW_RECONCILIATION", "Bronze rows = rows collapsed into silver offices + rejected rows",
     mismatch_rows("bronze_rows", n_bronze, n_listed + n_rejected)),
    ("ROWS_FROM_BRONZE", "Every silver office points to bronze rows that exist",
     s_rows.join(b, "_bronze_row_id", "left_anti")),
    ("PINCODE_FROM_BRONZE", "Silver PIN equals the bronze PIN of every source row",
     j.where(~F.col("pincode").eqNullSafe(F.col("b_pincode")))),
    ("OFFICE_NAME_FROM_BRONZE", "Silver office name equals the bronze office name",
     j.where(~F.col("officename").eqNullSafe(F.col("b_officename")))),
    ("COORD_TEXT_FROM_BRONZE", "latitude_raw / longitude_raw equal the bronze text",
     j.where(~F.col("latitude_raw").eqNullSafe(F.col("b_latitude")) | ~F.col("longitude_raw").eqNullSafe(F.col("b_longitude")))),
    ("COORDS_FROM_BRONZE", "Silver latitude/longitude are NULL or exactly the parsed bronze values",
     reparsed.where(F.col("latitude").isNotNull() &
                    ~(same_number(F.col("latitude"), F.col("_p.latitude")) & same_number(F.col("longitude"), F.col("_p.longitude"))))
             .drop("_p")),
    ("COORDS_MATCH_PIN", f"No kept coordinate is more than {FAR_FROM_PIN_KM:.0f} km from its PIN's median point",
     silver.where(F.col("latitude").isNotNull() & (F.col("km_from_pin_median") > FAR_FROM_PIN_KM))),
    ("STATE_FROM_BRONZE", "Silver state is NULL or the standardized bronze state",
     j.where(~F.col("state").eqNullSafe(state_from_text(F.col("b_statename"))))),
    ("DISTRICT_FROM_BRONZE", "Silver district is the bronze district, title-cased",
     j.where(~F.col("district").eqNullSafe(F.initcap(F.lower(F.col("b_district")))))),
    ("OFFICE_ID_UNIQUE", "office_id is unique",
     silver.groupBy("office_id").count().where("count > 1")),
    ("CENTROID_PIN_EXISTS", "Every centroid PIN exists in the office table",
     cent.select("pincode").join(silver.select("pincode").distinct(), "pincode", "left_anti")),
    ("CENTROID_INSIDE_OFFICES", "Each PIN centroid lies within the box around that PIN's kept office coordinates",
     cent.where("latitude IS NOT NULL").join(office_box, "pincode", "left")
         .where(~F.col("latitude").between(F.col("_min_lat"), F.col("_max_lat")) |
                ~F.col("longitude").between(F.col("_min_lon"), F.col("_max_lon")) | F.col("_min_lat").isNull())),
]
run_validations(checks, "pincode_validation")

# All checks passed: publish
write_table(silver, "pincode_silver",
            "India Post offices (All India Pincode Directory), one row per office. Coordinates that don't match their PIN are NULL. "
            "Validated against pincode_bronze (see pincode_validation). Built by notebooks/04_pincode_bronze_to_silver.")
write_table(cent, "pincode_centroids_silver",
            "One row per PIN code: median location of its post offices, main district/state, ambiguity. "
            "Use to turn a user PIN into coordinates. Built by notebooks/04_pincode_bronze_to_silver.")
silver = spark.table("pincode_silver")
spark.sql("DROP TABLE IF EXISTS _pincode_silver_stage")
spark.sql("DROP TABLE IF EXISTS _pincode_centroids_stage")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Rejected rows, data-quality summary

# COMMAND ----------

assert_no_clean_columns(rejected, "pincode_rejected")
rejected.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pincode_rejected")
n_silver = silver.count()
dq = (silver.select(F.explode("dq_flags").alias("flag")).groupBy("flag").count()
      .withColumn("pct_of_offices", F.round(100.0 * F.col("count") / n_silver, 1))
      .withColumnRenamed("count", "n_offices").orderBy(F.desc("n_offices")))
assert_no_clean_columns(dq, "pincode_dq_summary")
dq.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pincode_dq_summary")

COLUMN_COMMENTS = {
    "office_id": "Deterministic key (hash of PIN, office name, type, district, division), stable across reloads.",
    "latitude": "Parsed, validated latitude (inside India, swaps fixed). NULL if unusable.",
    "coord_status": "ok | swapped_fixed | missing | unparseable | zero | out_of_range | nulled_far_from_pin",
    "km_from_pin_median": "Distance of the original point from the median point of offices sharing this PIN. Over 50 km -> coordinates set to NULL.",
    "pin_ambiguous": "True if this PIN spans more than one district or state. Join on PIN with care.",
}
for c, comment in COLUMN_COMMENTS.items():
    spark.sql(f"ALTER TABLE pincode_silver ALTER COLUMN `{c}` COMMENT '{comment}'")
print(f"Done. bronze rows: {n_bronze:,} | offices: {n_silver:,} | rejected: {spark.table('pincode_rejected').count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Checks

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM pincode_dq_summary ORDER BY n_offices DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- How usable are the PIN centroids?
# MAGIC SELECT centroid_quality, count(*) AS pins, count_if(pin_ambiguous) AS ambiguous_pins
# MAGIC FROM pincode_centroids_silver GROUP BY ALL ORDER BY pins DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Example: turn a user's PIN into a location
# MAGIC SELECT pincode, latitude, longitude, main_district, main_state, centroid_quality, districts, row_citation
# MAGIC FROM pincode_centroids_silver WHERE pincode = '110001'