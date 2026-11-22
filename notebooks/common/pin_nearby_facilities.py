# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
# MAGIC %md
# MAGIC # 07 · PIN code → nearby facilities: `facility_geo_ready`, then a search
# MAGIC
# MAGIC **Part A (pre-processing, run once):** builds `facility_geo_ready`, one row per facility with a **verified, usable point** and a confidence label.
# MAGIC **Part B (the search):** the user types a PIN in a widget; the notebook checks it, turns it into a location and lists facilities by distance.
# MAGIC
# MAGIC | Step | What happens |
# MAGIC |---|---|
# MAGIC | B1 | **Is it an Indian PIN?** Exactly 6 digits, first digit 1-9, and present in `pincode_centroids_silver`. (Format alone is not enough: Singapore, Russia and China also use 6-digit codes, so the directory lookup is the real test.) |
# MAGIC | B2 | PIN → its centroid (median of the PIN's post offices). Warns if the PIN is ambiguous (spans districts or states) or its offices are spread out. |
# MAGIC | B3 | Bounding-box prefilter, then **haversine** distance to each facility's point. Straight-line, not road distance. |
# MAGIC
# MAGIC **Why haversine, not Euclidean:** a degree of longitude shrinks with latitude (about 110 km at the equator, about 85 km at Delhi), so plain Euclidean distance on lat/lon is wrong east-west. Haversine is already in `common/validation` and costs the same.
# MAGIC
# MAGIC **Facility points (Part A)**
# MAGIC * `facility_coordinates`: the facility's own coordinates, re-verified (inside India, not 0,0, within range of its PIN's centroid).
# MAGIC * `pin_centroid`: the facility has no usable coordinates, so its own PIN's centroid is used. **Approximate**; `location_uncertainty_km` says by how much.
# MAGIC * Facilities with neither get no point and never appear in search results.
# MAGIC
# MAGIC **Run order:** 00 → 01 → this notebook. Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

# MAGIC %run ./common/validation

# COMMAND ----------

import re

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("pincode", "110001", "3. PIN code")
dbutils.widgets.text("radius_km", "50", "4. Radius (km)")
dbutils.widgets.text("max_results", "25", "5. Max results")
dbutils.widgets.text("service_keyword", "", "6. Optional service word (e.g. dialysis)")
dbutils.widgets.dropdown("rebuild_geo_ready", "yes", ["yes", "no"], "7. Rebuild facility_geo_ready (Part A)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

LAT_MIN, LAT_MAX = 6.0, 37.5      # same India box as common/coordinate_parsing
LON_MIN, LON_MAX = 68.0, 97.5
PIN_MATCH_KM = 25.0               # same rule as notebook 01
KM_PER_DEG_LAT = 111.0

for t_ in ["facilities_silver", "pincode_centroids_silver"]:
    assert spark.catalog.tableExists(t_), f"{t_} not found: run notebooks 00 and 01 first."

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part A · Pre-processing: `facility_geo_ready`
# MAGIC Notebook 01 already nulls coordinates that don't match the PIN or state. This step **re-verifies independently** (so a change in 01 can't silently break search), adds the PIN-centroid fallback, and labels how much to trust each point.

# COMMAND ----------

if dbutils.widgets.get("rebuild_geo_ready") == "yes" or not spark.catalog.tableExists("facility_geo_ready"):
    fac = spark.table("facilities_silver")
    need = ["facility_id", "name", "pincode", "latitude", "longitude", "coords_low_precision", "coord_status"]
    miss = [c for c in need if c not in fac.columns]
    assert not miss, f"facilities_silver is missing {miss}"

    cent = spark.table("pincode_centroids_silver").select(
        "pincode", F.col("latitude").alias("pin_lat"), F.col("longitude").alias("pin_lon"),
        F.coalesce("max_office_distance_km", F.lit(0.0)).alias("pin_spread_km"), "centroid_quality")

    g = fac.join(F.broadcast(cent), "pincode", "left")

    in_box = (F.col("latitude").between(LAT_MIN, LAT_MAX) & F.col("longitude").between(LON_MIN, LON_MAX) &
              ~((F.col("latitude") == 0) & (F.col("longitude") == 0)))
    d_pin = haversine_km_col(F.col("latitude"), F.col("longitude"), F.col("pin_lat"), F.col("pin_lon"))
    # Facility's own point is usable only if inside India AND (no PIN centroid to compare, or close enough to it)
    own_ok = F.coalesce(in_box, F.lit(False)) & ~F.coalesce(d_pin > F.lit(PIN_MATCH_KM) + F.col("pin_spread_km"), F.lit(False))
    pin_ok = F.col("pin_lat").isNotNull() & F.col("pin_lon").isNotNull()

    geo = (g
        .withColumn("location_basis", F.when(own_ok, "facility_coordinates").when(pin_ok, "pin_centroid"))
        .withColumn("geo_latitude", F.when(own_ok, F.col("latitude")).when(pin_ok, F.col("pin_lat")))
        .withColumn("geo_longitude", F.when(own_ok, F.col("longitude")).when(pin_ok, F.col("pin_lon")))
        .withColumn("location_uncertainty_km",
                    F.when(own_ok & F.coalesce(F.col("coords_low_precision"), F.lit(False)), F.lit(1.0))
                     .when(own_ok, F.lit(0.1))
                     .when(pin_ok, F.greatest(F.col("pin_spread_km"), F.lit(2.0))))
        .withColumn("geo_confidence",
                    F.when(own_ok & ~F.coalesce(F.col("coords_low_precision"), F.lit(False)), "high")
                     .when(own_ok, "medium_low_precision")
                     .when(pin_ok, "approximate_pin_centroid")))

    GEO_COLS = ["facility_id", "name", "city", "state", "pincode", "address_full",
                "geo_latitude", "geo_longitude", "location_basis", "location_uncertainty_km", "geo_confidence",
                "coord_status", "dq_flags"]
    geo_out = geo.select(*[c for c in GEO_COLS if c in geo.columns])

    # ---- Validation before writing (same pattern as notebooks 00-02) ----
    checks = [
        ("ROW_COUNT", "facility_geo_ready has exactly one row per facilities_silver row",
         mismatch_rows("facilities", fac.count(), geo_out.count())),
        ("FACILITY_ID_UNIQUE", "facility_id is unique",
         geo_out.groupBy("facility_id").count().where("count > 1")),
        ("POINT_IN_INDIA", "Every geo point is inside India's bounding box",
         geo_out.where(F.col("geo_latitude").isNotNull() &
                       ~(F.col("geo_latitude").between(LAT_MIN, LAT_MAX) & F.col("geo_longitude").between(LON_MIN, LON_MAX)))),
        ("POINT_NOT_ZERO", "No geo point is (0, 0)",
         geo_out.where((F.col("geo_latitude") == 0) & (F.col("geo_longitude") == 0))),
        ("LAT_LON_TOGETHER", "latitude and longitude are both set or both NULL",
         geo_out.where(F.col("geo_latitude").isNull() != F.col("geo_longitude").isNull())),
        ("OWN_POINT_FROM_SILVER", "facility_coordinates points equal the facilities_silver point",
         geo.where((F.col("location_basis") == "facility_coordinates") &
                   ~(same_number(F.col("geo_latitude"), F.col("latitude")) & same_number(F.col("geo_longitude"), F.col("longitude"))))
            .select("facility_id", "geo_latitude", "latitude", "geo_longitude", "longitude")),
        ("OWN_POINT_MATCHES_PIN", f"No facility_coordinates point is more than {PIN_MATCH_KM:.0f} km (+ PIN spread) from its PIN centroid",
         geo.where((F.col("location_basis") == "facility_coordinates") &
                   (haversine_km_col(F.col("geo_latitude"), F.col("geo_longitude"), F.col("pin_lat"), F.col("pin_lon"))
                    > F.lit(PIN_MATCH_KM) + F.col("pin_spread_km")))
            .select("facility_id", "pincode", "geo_latitude", "geo_longitude")),
    ]
    run_validations(checks, "facility_geo_ready_validation")

    write_table(geo_out, "facility_geo_ready",
                "One row per facility with a verified point for distance search: own coordinates (re-verified) or its PIN centroid "
                "(approximate). geo_confidence and location_uncertainty_km say how far to trust it. Built by notebooks/07_pin_nearby_facilities.")

    display(spark.sql("""SELECT geo_confidence, count(*) AS facilities,
                                round(100 * count(*) / sum(count(*)) OVER (), 1) AS pct
                         FROM facility_geo_ready GROUP BY geo_confidence ORDER BY facilities DESC"""))
else:
    print("Using existing facility_geo_ready (rebuild_geo_ready = no)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Part B · Search

# COMMAND ----------

def stop(msg):
    print(msg)
    dbutils.notebook.exit(msg)


# ---- B1 · Is it an Indian PIN? ----
raw = dbutils.widgets.get("pincode")
pin = re.sub(r"[\s-]", "", raw or "")            # "110 001" and "110-001" -> "110001"

if not pin.isdigit() or len(pin) != 6:
    stop(f"'{raw}' is not an Indian PIN code: India Post PINs are exactly 6 digits "
         f"(a 5-digit US ZIP, for example, can't be one).")
if pin[0] == "0":
    stop(f"'{pin}' is not an Indian PIN code: the first digit is 1-9.")

c = spark.table("pincode_centroids_silver").where(F.col("pincode") == pin).first()
if c is None:
    stop(f"'{pin}' has the right shape but is not in the India Post directory. It may be mistyped, new, or from another "
         f"country (Singapore, Russia and China also use 6-digit codes).")

# ---- B2 · PIN -> location ----
print(f"PIN {pin}: {c['main_district']}, {c['main_state']} | {c['n_offices']} post office(s) | centroid quality: {c['centroid_quality']}")
if c["latitude"] is None:
    stop(f"PIN {pin} is valid but none of its post offices has usable coordinates, so there is no centre point to measure from.")
if c["pin_ambiguous"]:
    print(f"WARNING: this PIN spans several districts or states: {c['districts']} / {c['states']}. The centre is a median across them.")
if c["centroid_quality"] == "spread_out":
    print(f"WARNING: its post offices are spread up to {c['max_office_distance_km']} km apart; the centre point is rough.")
if c["centroid_quality"] == "single_office":
    print("NOTE: centre comes from a single post office.")

lat0, lon0 = float(c["latitude"]), float(c["longitude"])

# ---- B3 · Nearby facilities ----
radius = float(dbutils.widgets.get("radius_km"))
limit_n = int(dbutils.widgets.get("max_results"))
keyword = dbutils.widgets.get("service_keyword").strip().lower()

import math
dlat = radius / KM_PER_DEG_LAT
dlon = radius / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 0.01))

near = (spark.table("facility_geo_ready")
        .where(F.col("geo_latitude").isNotNull())
        # cheap box first, exact distance second
        .where(F.col("geo_latitude").between(lat0 - dlat, lat0 + dlat) &
               F.col("geo_longitude").between(lon0 - dlon, lon0 + dlon))
        .withColumn("distance_km", F.round(haversine_km_col(F.lit(lat0), F.lit(lon0), F.col("geo_latitude"), F.col("geo_longitude")), 2))
        .where(F.col("distance_km") <= radius))

if keyword:
    claims = (spark.table("silver_facility_claims")
              .where(F.col("claim_norm").contains(keyword)).select("facility_id").distinct())
    near = near.join(claims, "facility_id", "left_semi")

result = (near.orderBy("distance_km", "facility_id").limit(limit_n)
          .select("distance_km", "name", "city", "state", "pincode", "geo_confidence", "location_basis",
                  "location_uncertainty_km", "dq_flags", "facility_id"))

print(f"Centre of PIN {pin}: ({lat0:.5f}, {lon0:.5f}) | radius {radius:g} km"
      + (f" | service contains '{keyword}'" if keyword else ""))
print("Distances are straight-line from the PIN's centre, not road distance. "
      "Rows with location_basis = pin_centroid are only accurate to location_uncertainty_km.")
display(result)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Checks

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Coverage: how many facilities can be searched at all, and how precisely?
# MAGIC SELECT location_basis, geo_confidence, count(*) AS facilities
# MAGIC FROM facility_geo_ready GROUP BY ALL ORDER BY facilities DESC
