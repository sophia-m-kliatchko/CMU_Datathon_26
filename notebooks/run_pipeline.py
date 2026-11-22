# Databricks notebook source
# MAGIC %md
# MAGIC # Run the whole pipeline: 00 → 07
# MAGIC
# MAGIC Runs each notebook in order with `dbutils.notebook.run`, and records what happened in **`pipeline_run_log`** (one row per step per run):
# MAGIC
# MAGIC | column | meaning |
# MAGIC |---|---|
# MAGIC | `run_id`, `run_started_at` | which pipeline run |
# MAGIC | `step`, `notebook` | e.g. `01`, `01_bronze_to_silver` |
# MAGIC | `status` | `OK`, `FAILED`, `SKIPPED` (a step it depends on failed), `MISSING` (notebook not found) |
# MAGIC | `seconds` | how long the step took |
# MAGIC | `error` | the error message (first 4,000 characters), including which cell broke when Databricks reports it |
# MAGIC | `failed_checks` | for steps with a `<dataset>_validation` table: the checks that failed in this run |
# MAGIC
# MAGIC **Dependencies** (a failed step skips the steps that need it; the others still run):
# MAGIC `00` → `01`, `02`, `04`, `05`; `01` + `05` → `06`; `01` + `06` → `07`; `03` is independent.
# MAGIC
# MAGIC **How to use:** set the widgets, then **Run all**. A summary prints at the end, and the notebook fails at the end if any step failed, so a scheduled job shows red.
# MAGIC To see past runs: `SELECT * FROM pipeline_run_log ORDER BY run_started_at DESC, step`.

# COMMAND ----------

import time
import traceback
import uuid
from datetime import datetime, timezone

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("steps", "00,01,02,03,04,05,06,07", "3. Steps to run (comma-separated)")
dbutils.widgets.dropdown("stop_on_failure", "no", ["no", "yes"], "4. Stop everything at the first failure")
dbutils.widgets.text("timeout_minutes", "60", "5. Timeout per notebook (minutes)")
# Optional input overrides; leave blank to use each notebook's own default
dbutils.widgets.text("pincode_source", "", "6. 00: PIN directory CSV path or table (blank = default)")
dbutils.widgets.text("facilities_source_table", "", "7. 01: facilities source table (blank = default)")
dbutils.widgets.text("nfhs_source", "", "8. 04: NFHS CSV path or table (blank = default)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
WANT = [s.strip() for s in dbutils.widgets.get("steps").split(",") if s.strip()]
STOP_ON_FAILURE = dbutils.widgets.get("stop_on_failure") == "yes"
TIMEOUT_S = int(float(dbutils.widgets.get("timeout_minutes")) * 60)
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

# Widget values passed to every notebook (each notebook ignores the ones it doesn't define)
COMMON_ARGS = {"catalog": CATALOG, "schema": SCHEMA, "target_catalog": CATALOG, "target_schema": SCHEMA}

def _opt(widget, arg):
    v = dbutils.widgets.get(widget).strip()
    return {arg: v} if v else {}

# step, notebook (relative to this folder), extra arguments, steps it depends on, its validation table
PIPELINE = [
    ("00", "00_pincode_bronze_to_silver", _opt("pincode_source", "source"), [], "pincode_validation"),
    ("01", "01_bronze_to_silver", _opt("facilities_source_table", "source_table"), ["00"], "facilities_validation"),
    ("02", "02_nqas_bronze_to_silver", {}, ["00"], "nqas_validation"),
    ("03", "03_kayakalp_bronze_to_silver", {}, [], None),
    ("04", "04_nfhs_bronze_to_silver", _opt("nfhs_source", "source"), ["00"], "nfhs_validation"),
    ("05", "05_registries_bronze_to_silver", {}, ["00"], None),
    ("06", "06_registry_matching", {}, ["01", "05"], None),
    ("07", "07_pin_nearby_facilities", {"rebuild_geo_ready": "yes", "pincode": "110001", "radius_km": "50", "max_results": "25"}, ["01", "06"], "facility_geo_ready_validation"),
]

# COMMAND ----------

def failed_checks(table, since):
    """Names of checks that failed in `table` during this run (empty if the table doesn't exist)."""
    if not table or not spark.catalog.tableExists(f"{CATALOG}.{SCHEMA}.{table}"):
        return []
    rows = (spark.table(table).where((~F.col("passed")) & (F.col("checked_at") >= F.lit(since)))
            .select("check", "n_failed").collect())
    return [f"{r['check']} ({r['n_failed']} rows)" for r in rows]


def short_error(e):
    """The most useful part of a notebook failure: Databricks' message, plus the last traceback line."""
    msg = str(e).strip()
    tb = traceback.format_exc().strip().splitlines()
    last = tb[-1] if tb else ""
    text = msg if last in msg else f"{msg}\n{last}"
    return text[:4000]


run_id = uuid.uuid4().hex[:12]
run_started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
results, status_of = [], {}
print(f"Pipeline run {run_id} started {run_started} UTC -> {CATALOG}.{SCHEMA}\n")

for step, nb, extra, deps, vtable in PIPELINE:
    if step not in WANT:
        continue
    row = {"run_id": run_id, "run_started_at": run_started, "step": step, "notebook": nb,
           "status": None, "seconds": 0.0, "error": None, "failed_checks": []}
    blocked = [d for d in deps if status_of.get(d) in ("FAILED", "SKIPPED", "MISSING")]
    stopped = STOP_ON_FAILURE and any(s in ("FAILED", "MISSING") for s in status_of.values())
    if blocked or stopped:
        row["status"] = "SKIPPED"
        row["error"] = (f"not run: depends on {', '.join(blocked)}, which did not succeed" if blocked
                        else "not run: stop_on_failure is on and an earlier step failed")
    else:
        print(f"▶ {step} {nb} ...", flush=True)
        step_start = spark.sql("SELECT current_timestamp() AS t").first()["t"]  # same clock as checked_at
        t0 = time.time()
        try:
            dbutils.notebook.run(f"./{nb}", TIMEOUT_S, {**COMMON_ARGS, **extra})
            row["status"] = "OK"
        except Exception as e:
            text = str(e)
            # MISSING only when the notebook itself can't be found (not when a notebook reports a missing data file)
            notebook_missing = "notebook not found" in text.lower() or "RESOURCE_DOES_NOT_EXIST" in text
            row["status"] = "MISSING" if notebook_missing else "FAILED"
            row["error"] = short_error(e)
        row["seconds"] = round(time.time() - t0, 1)
        row["failed_checks"] = failed_checks(vtable, step_start)
    status_of[step] = row["status"]
    results.append(row)
    print(f"  {row['status']:<8} {step} {nb} ({row['seconds']}s)"
          + (f"\n    error: {row['error'].splitlines()[0][:300]}" if row["error"] else "")
          + (f"\n    failed checks: {', '.join(row['failed_checks'])}" if row["failed_checks"] else ""), flush=True)

# COMMAND ----------

# Append this run to pipeline_run_log (kept across runs)
log_df = spark.createDataFrame(
    results,
    "run_id string, run_started_at string, step string, notebook string, status string, seconds double, "
    "error string, failed_checks array<string>",
).withColumn("run_started_at", F.to_timestamp("run_started_at")) if results else None
if log_df is not None:
    log_df.write.mode("append").option("mergeSchema", "true").saveAsTable("pipeline_run_log")
    display(spark.table("pipeline_run_log").where(f"run_id = '{run_id}'").orderBy("step"))

counts = {s: sum(1 for r in results if r["status"] == s) for s in ["OK", "FAILED", "SKIPPED", "MISSING"]}
print(f"\nPipeline run {run_id}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
broken = [r for r in results if r["status"] in ("FAILED", "MISSING")]
for r in broken:
    print(f"\n✗ {r['step']} {r['notebook']}: {r['status']}\n{r['error']}")
if broken:
    raise RuntimeError(f"Pipeline run {run_id}: {len(broken)} step(s) failed: "
                       + ", ".join(f"{r['step']} {r['notebook']}" for r in broken)
                       + ". Details in pipeline_run_log.")
print("\n✓ All steps succeeded")