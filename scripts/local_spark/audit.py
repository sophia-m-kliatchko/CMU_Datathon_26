"""
Audit the silver tables produced by a local run (scripts/local_spark/run_all.sh): row counts, key uniqueness,
NULL rates of key columns, impossible values, and samples of the riskiest outputs (registry matches).
Prints PROBLEM lines for anything suspicious.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nbrun import get_spark
from pyspark.sql import functions as F

s = get_spark()
s.sql("SET CATALOG spark_catalog")
s.sql("USE datathon")
problems = []


def problem(msg):
    problems.append(msg)
    print("PROBLEM:", msg)


tables = sorted(r.tableName for r in s.sql("SHOW TABLES IN datathon").collect())
print("tables:", tables)
leftover = [t for t in tables if t.startswith("_")]
if leftover:
    problem(f"staging tables left behind: {leftover}")
for t in tables:
    cols = s.table(t).columns
    bad = [c for c in cols if c.lower().endswith("_clean")]
    if bad and t.endswith("silver"):
        problem(f"{t} has *_clean columns {bad}")

KEYS = {
    "facilities_silver": ["facility_id"], "pincode_silver": ["office_id"], "pincode_centroids_silver": ["pincode"],
    "nqas_silver": ["certification_id"], "registry_sites_silver": ["site_id"],
}
for t, key in KEYS.items():
    if t not in tables:
        problem(f"{t} missing")
        continue
    df = s.table(t)
    n, nk = df.count(), df.select(*key).distinct().count()
    nulls = df.where(" OR ".join(f"{k} IS NULL" for k in key)).count()
    print(f"{t}: {n:,} rows, key unique={n == nk}, null keys={nulls}")
    if n != nk or nulls:
        problem(f"{t}: key {key} not unique or NULL")

# Coordinates inside India everywhere they exist
for t in ["facilities_silver", "pincode_silver", "pincode_centroids_silver", "registry_sites_silver"]:
    if t in tables and {"latitude", "longitude"} <= set(s.table(t).columns):
        bad = s.table(t).where("latitude IS NOT NULL AND NOT (latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5)").count()
        half = s.table(t).where("(latitude IS NULL) <> (longitude IS NULL)").count()
        print(f"{t}: coords outside India={bad}, half-missing pairs={half}")
        if bad or half:
            problem(f"{t}: {bad} coords outside India, {half} half-missing pairs")

f = s.table("facilities_silver")
print("facilities_silver key NULL rates:",
      f.select(*[F.round(F.avg(F.col(c).isNull().cast("int")), 3).alias(c)
                 for c in ["name", "state", "city", "pincode", "latitude", "address_full"]]).first().asDict())
neg = f.where("num_doctors < 1 OR capacity < 1 OR year_established > year(current_date()) OR year_established < 1800").count()
if neg:
    problem(f"facilities_silver: {neg} impossible numbers")
pinbad = f.where("pincode IS NOT NULL AND NOT pincode RLIKE '^[1-9][0-9]{5}$'").count()
if pinbad:
    problem(f"facilities_silver: {pinbad} malformed PINs")
emptyname = f.where("trim(name) = '' OR name LIKE '[%'").count()
if emptyname:
    problem(f"facilities_silver: {emptyname} empty or list-shaped names")
claims = s.table("silver_facility_claims")
orphan = claims.join(f, "facility_id", "left_anti").count()
print(f"silver_facility_claims: {claims.count():,} rows, orphan facility_ids={orphan}")
if orphan:
    problem("silver_facility_claims has facility_ids not in facilities_silver")

if "facility_registry_links_silver" in tables:
    L = s.table("facility_registry_links_silver")
    print("links columns:", L.columns)
    print(f"facility_registry_links_silver: {L.count():,} rows")
    for c in ["link_status", "match_status", "status", "decision"]:
        if c in L.columns:
            L.groupBy(c).count().show()
    dcol = next((c for c in ["distance_km", "km", "dist_km"] if c in L.columns), None)
    scol = next((c for c in ["score", "match_score", "total_score"] if c in L.columns), None)
    if dcol:
        L.select(F.expr(f"percentile_approx({dcol}, array(0.5, 0.9, 0.99))").alias("dist_p50_p90_p99"),
                 F.max(dcol).alias("max_dist")).show(truncate=False)
    show_cols = [c for c in ["facility_name", "facility_id", "site_name", "name", "source", scol, dcol,
                             "name_score", "link_status"] if c and c in L.columns]
    print("Sample of the weakest accepted links:")
    if scol:
        L.orderBy(scol).select(*show_cols).show(15, truncate=45)
    else:
        L.select(*show_cols).show(15, truncate=45)
    ff = L.join(f, "facility_id", "left_anti").count()
    if ff:
        problem(f"links to unknown facility_id: {ff}")

print("\nSUMMARY:", "no problems found" if not problems else f"{len(problems)} problem(s)")
for p in problems:
    print(" -", p)
