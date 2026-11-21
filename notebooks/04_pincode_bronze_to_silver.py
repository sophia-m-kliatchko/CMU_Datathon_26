# Databricks notebook source
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
# MAGIC
# MAGIC **Main cleaning steps**
# MAGIC * `"NA"` text becomes NULL; text is trimmed. Exact duplicate rows are collapsed (`n_listings`).
# MAGIC * **Coordinates** (`common/coordinate_parsing`): degree signs and N/E letters removed, degree-minute-second values converted, stray spaces in decimals removed, swapped lat/lon fixed, values outside India set to NULL. `lat_how`/`lon_how` record how each value was read.
# MAGIC * Offices more than **50 km** from their PIN's median point are flagged `COORDS_FAR_FROM_PIN` and left out of the PIN centroid.
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

FAR_FROM_PIN_KM = 50.0   # office further than this from its PIN's median point -> flagged, left out of the centroid

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

df = (df
    .withColumn("_c", fix_pair_udf(F.col("latitude"), F.col("longitude")))
    .withColumn("latitude_clean", F.col("_c.latitude"))
    .withColumn("longitude_clean", F.col("_c.longitude"))
    .withColumn("coord_status", F.col("_c.coord_status"))
    .withColumn("lat_how", F.col("_c.lat_how"))
    .withColumn("lon_how", F.col("_c.lon_how"))
    .drop("_c")
    .withColumnRenamed("latitude", "latitude_raw")
    .withColumnRenamed("longitude", "longitude_raw")
    .withColumn("state_clean", state_from_text(F.col("statename")))
    .withColumn("district_clean", F.initcap(F.lower(F.col("district"))))
    .withColumn("district_key", F.regexp_replace(F.lower(F.col("district")), r"[^a-z0-9]", ""))
    .withColumn("office_type", F.upper(F.col("officetype")))
    .withColumn("office_type_label", F.when(F.col("office_type") == "HO", "Head Office")
                                      .when(F.col("office_type") == "PO", "Sub/Post Office")
                                      .when(F.col("office_type") == "BO", "Branch Office"))
    .withColumn("office_name_clean",
                F.trim(F.regexp_replace(F.col("officename"), r"(?i)\s*\b[BSH]\.?\s?O\.?$", "")))
    .withColumn("is_delivery_office", F.upper(F.col("delivery")) == "DELIVERY")
)

# PIN ambiguity: one PIN can serve several districts or states
w_pin = Window.partitionBy("pincode")
df = (df
    .withColumn("pin_n_offices", F.count(F.lit(1)).over(w_pin))
    .withColumn("pin_n_districts", F.size(F.collect_set("district_key").over(w_pin)))
    .withColumn("pin_n_states", F.size(F.collect_set("state_clean").over(w_pin)))
    .withColumn("pin_ambiguous", (F.col("pin_n_districts") > 1) | (F.col("pin_n_states") > 1))
)

# Distance from the PIN's median point (robust to a few bad coordinates)
df = (df
    .withColumn("_pin_med_lat", F.percentile_approx("latitude_clean", 0.5).over(w_pin))
    .withColumn("_pin_med_lon", F.percentile_approx("longitude_clean", 0.5).over(w_pin)))
p = 3.141592653589793 / 180
h = (F.pow(F.sin((F.col("latitude_clean") - F.col("_pin_med_lat")) * p / 2), 2) +
     F.cos(F.col("_pin_med_lat") * p) * F.cos(F.col("latitude_clean") * p) *
     F.pow(F.sin((F.col("longitude_clean") - F.col("_pin_med_lon")) * p / 2), 2))
df = (df
    .withColumn("km_from_pin_median", F.round(2 * 6371.0 * F.asin(F.least(F.lit(1.0), F.sqrt(h))), 2))
    .withColumn("coords_far_from_pin", F.col("km_from_pin_median") > FAR_FROM_PIN_KM)
    .drop("_pin_med_lat", "_pin_med_lon"))

# Deterministic office_id (stable across reloads; tie-breaker for offices sharing the natural key)
key_cols = ["pincode", "office_name_clean", "office_type", "district_key", "divisionname"]
df = df.withColumn("_k", F.sha2(F.concat_ws("|", *[F.coalesce(F.col(c), F.lit("")) for c in key_cols]), 256))
w_k = Window.partitionBy("_k").orderBy("circlename", "regionname", "delivery", "latitude_raw", "longitude_raw")
df = (df.withColumn("office_id", F.substring(F.sha2(F.concat_ws("|", "_k", F.row_number().over(w_k)), 256), 1, 16))
        .drop("_k"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Flags, citations, write `pincode_silver`

# COMMAND ----------

FLAGS = [
    ("COORDS_MISSING",              F.col("coord_status") == "missing"),
    ("COORDS_UNPARSEABLE",          F.col("coord_status") == "unparseable"),
    ("COORDS_ZERO",                 F.col("coord_status") == "zero"),
    ("COORDS_OUTSIDE_INDIA",        F.col("coord_status") == "out_of_range"),
    ("COORDS_SWAPPED_FIXED",        F.col("coord_status") == "swapped_fixed"),
    ("COORDS_TEXT_REPAIRED",        F.col("lat_how").isin("symbols_removed", "dms_converted", "space_removed") |
                                    F.col("lon_how").isin("symbols_removed", "dms_converted", "space_removed")),
    ("COORDS_FAR_FROM_PIN",         F.col("coords_far_from_pin")),
    ("PIN_SPANS_DISTRICTS",         F.col("pin_n_districts") > 1),
    ("PIN_SPANS_STATES",            F.col("pin_n_states") > 1),
    ("MISSING_DISTRICT",            F.col("district").isNull()),
    ("STATE_UNRECOGNIZED",          F.col("state_clean").isNull()),
    ("DUPLICATE_ROW_COLLAPSED",     F.col("n_listings") > 1),
]
silver = df.withColumn(
    "dq_flags",
    F.filter(F.array(*[F.when(F.coalesce(c, F.lit(False)), F.lit(code)) for code, c in FLAGS]), lambda x: x.isNotNull()))
silver = add_provenance(silver, SOURCE_NAME, SOURCE_PUBLISHER, SOURCE_URL,
                        F.lit(RETRIEVED_ON).cast("date"), SOURCE_LICENSE, PRODUCED_BY)
silver = silver.withColumn("row_citation", F.concat(
    F.lit("India Post, All India Pincode Directory: "), F.coalesce(F.col("officename"), F.lit("?")),
    F.lit(", PIN "), F.col("pincode"), F.lit(", "), F.coalesce(F.col("district"), F.lit("?")), F.lit(", "),
    F.coalesce(F.col("statename"), F.lit("?")), F.lit(". "), F.lit(SOURCE_URL), F.lit(", obtained "), F.lit(RETRIEVED_ON), F.lit(".")))

ORDER = ["office_id", "pincode", "officename", "office_name_clean", "office_type", "office_type_label", "is_delivery_office",
         "district_clean", "state_clean", "latitude_clean", "longitude_clean", "coord_status", "km_from_pin_median",
         "coords_far_from_pin", "pin_n_offices", "pin_n_districts", "pin_n_states", "pin_ambiguous", "dq_flags",
         "row_citation", "circlename", "regionname", "divisionname", "district", "district_key", "statename",
         "officetype", "delivery", "latitude_raw", "longitude_raw", "lat_how", "lon_how", "n_listings", "source_row_ids",
         "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
# Being in silver means a column is clean: cleaned columns get the plain name, and the raw column they would
# collide with is renamed *_raw (district) so the original text stays available for citations.
SILVER_RENAME = {"district": "district_raw", "district_clean": "district", "state_clean": "state",
                 "latitude_clean": "latitude", "longitude_clean": "longitude", "office_name_clean": "office_name"}
silver_out = silver.select(*[F.col(c).alias(SILVER_RENAME.get(c, c)) for c in ORDER])
assert len(set(silver_out.columns)) == len(silver_out.columns), f"duplicate column names: {silver_out.columns}"
write_table(silver_out, "pincode_silver",
            "India Post offices (All India Pincode Directory), one row per office, cleaned coordinates and PIN ambiguity. "
            "Built by notebooks/04_pincode_bronze_to_silver.")
silver = spark.table("pincode_silver")
assert silver.count() == silver.select("office_id").distinct().count(), "office_id is not unique"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · `pincode_centroids_silver`: one row per PIN
# MAGIC The centroid is the **median** latitude/longitude of the PIN's offices with usable coordinates, leaving out offices flagged `COORDS_FAR_FROM_PIN`. `main_district`/`main_state` are the ones with the most offices; all of them are listed in `districts`/`states`.

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
write_table(cent, "pincode_centroids_silver",
            "One row per PIN code: median location of its post offices (outliers over 50 km excluded), main district/state, ambiguity. "
            "Use to turn a user PIN into coordinates. Built by notebooks/04_pincode_bronze_to_silver.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Rejected rows, data-quality summary

# COMMAND ----------

rejected.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pincode_rejected")
n_silver = silver.count()
dq = (silver.select(F.explode("dq_flags").alias("flag")).groupBy("flag").count()
      .withColumn("pct_of_offices", F.round(100.0 * F.col("count") / n_silver, 1))
      .withColumnRenamed("count", "n_offices").orderBy(F.desc("n_offices")))
dq.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("pincode_dq_summary")

COLUMN_COMMENTS = {
    "office_id": "Deterministic key (hash of PIN, office name, type, district, division), stable across reloads.",
    "latitude": "Parsed, validated latitude (inside India, swaps fixed). NULL if unusable.",
    "coord_status": "ok | swapped_fixed | missing | unparseable | zero | out_of_range",
    "km_from_pin_median": "Distance from the median point of offices sharing this PIN.",
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
