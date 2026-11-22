# Databricks notebook source
# MAGIC %md
# MAGIC # Verify pipeline outputs (read-only)
# MAGIC Collects row counts, every `*_validation` result, data-quality and naming checks for one schema,
# MAGIC and returns them as JSON via `dbutils.notebook.exit` (readable with `databricks jobs get-run-output`).

# COMMAND ----------

import json
from pyspark.sql import functions as F

dbutils.widgets.text("schema", "workspace.datathon_verify", "Schema to check")
SCHEMA = dbutils.widgets.get("schema").strip()
out = {"schema": SCHEMA, "tables": {}, "validation": {}, "checks": {}}

tables = [r.tableName for r in spark.sql(f"SHOW TABLES IN {SCHEMA}").collect()]
for t in sorted(tables):
    df = spark.table(f"{SCHEMA}.{t}")
    out["tables"][t] = {"rows": df.count(), "clean_cols": [c for c in df.columns if c.lower().endswith("_clean")]}

for t in sorted(x for x in tables if x.endswith("_validation")):
    out["validation"][t] = [{"check": r["check"], "passed": r["passed"], "n_failed": r["n_failed"]}
                            for r in spark.table(f"{SCHEMA}.{t}").collect()]

def q(sql):
    return [r.asDict() for r in spark.sql(sql).collect()]

c = out["checks"]
c["staging_leftovers"] = [t for t in tables if t.startswith("_")]
if "facilities_silver" in tables:
    c["facilities"] = q(f"""SELECT count(*) n, count(DISTINCT facility_id) ids, count_if(latitude IS NOT NULL) with_coords,
        count_if(coord_status IN ('nulled_pin_mismatch','nulled_state_mismatch')) coords_nulled,
        count_if(latitude IS NOT NULL AND NOT (latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5)) coords_outside_india,
        count_if(NOT facility_id RLIKE '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$') non_uuid,
        count_if(pincode IS NOT NULL AND NOT pincode RLIKE '^[1-9][0-9]{{5}}$') bad_pin
        FROM {SCHEMA}.facilities_silver""")
    c["facility_flags"] = q(f"SELECT flag, n_facilities FROM {SCHEMA}.silver_dq_summary ORDER BY n_facilities DESC LIMIT 12")
    c["rejected"] = q(f"SELECT reject_reason, count(*) n FROM {SCHEMA}.silver_rejected_facilities GROUP BY 1")
if "pincode_silver" in tables:
    c["pincode"] = q(f"""SELECT count(*) offices, count_if(coord_status='nulled_far_from_pin') nulled_far,
        count_if(coord_status='missing') missing, max(km_from_pin_median) max_km FROM {SCHEMA}.pincode_silver""")
if "nfhs_silver" in tables:
    c["nfhs"] = q(f"""SELECT count(*) districts, min(sex_ratio_total_f_per_1000_m) sr_min, max(sex_ratio_total_f_per_1000_m) sr_max,
        count_if(state IS NULL) no_state FROM {SCHEMA}.nfhs_silver""")
if "facility_registry_links_silver" in tables:
    c["links"] = q(f"""SELECT count(*) links, count_if(NOT needs_review) accepted,
        count_if(NOT needs_review AND distance_km > 25) accepted_far FROM {SCHEMA}.facility_registry_links_silver""")

dbutils.notebook.exit(json.dumps(out, default=str))
