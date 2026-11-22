# Databricks notebook source
# MAGIC %md
# MAGIC # One-time setup: bronze tables + pipeline Job in THIS workspace
# MAGIC
# MAGIC For teammates who cloned this repo into their own Databricks workspace. Run every cell once, on serverless compute.
# MAGIC
# MAGIC Creates (only when missing - existing tables are never overwritten):
# MAGIC * schema `workspace.datathon`
# MAGIC * bronze tables `nqas_certified_facilities`, `kayakalp_bronze`, the 9 registry `*_bronze` tables, and `facilities` (all text, from this repo's CSVs)
# MAGIC * the Lakeflow Job **CMU Datathon pipeline 00-06**: notebooks 00-06 as sequential tasks on serverless job compute
# MAGIC
# MAGIC Step sources default to this repo's CSVs, so no shared dataset catalog or Volume is needed.
# MAGIC Do NOT use `run_pipeline.py` on serverless - `dbutils.notebook.run` cannot start from serverless notebook compute; the Job is the runner.
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog for the tables")
dbutils.widgets.text("schema", "datathon", "2. Schema for the tables")
dbutils.widgets.text("job_name", "CMU Datathon pipeline 00-06", "3. Job name")
dbutils.widgets.text("repo_root", "", "4. Repo folder (blank = auto-detect)")
dbutils.widgets.dropdown("run_job_after", "no", ["no", "yes"], "5. Trigger the first job run when setup finishes")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
JOB_NAME = dbutils.widgets.get("job_name").strip()
REPO_ROOT = dbutils.widgets.get("repo_root").strip()
RUN_AFTER = dbutils.widgets.get("run_job_after") == "yes"

# COMMAND ----------

# MAGIC %md ## 1 - Find this repo in the workspace

# COMMAND ----------

def _exists(path):
    try:
        dbutils.fs.ls(path)
        return True
    except Exception:
        return False

from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

if not REPO_ROOT:
    me = w.current_user.me().user_name
    for c in (f"/Workspace/Repos/{me}/CMU_Datathon_26",
              "/Workspace/Datathon Fall 26/CMU_Datathon_26"):
        if _exists(f"{c}/notebooks/06_registry_matching.py"):
            REPO_ROOT = c
            break
assert _exists(f"{REPO_ROOT}/notebooks/06_registry_matching.py"), (
    "Repo not found. Clone it first (Workspace > Create > Git folder, "
    "https://github.com/sophia-m-kliatchko/CMU_Datathon_26), then set repo_root to that folder.")
NB_ROOT = REPO_ROOT[len("/Workspace"):] if REPO_ROOT.startswith("/Workspace") else REPO_ROOT
print("Repo folder:", REPO_ROOT)

# COMMAND ----------

# MAGIC %md ## 2 - Bronze tables (created only when missing)

# COMMAND ----------

from pyspark.sql import functions as F

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")

REGISTRY = {
    "laqshya_facilities_bronze": "laqshya_bronze",
    "laqshya_certifications_bronze": "laqshya_bronze",
    "trauma_care_facilities_bronze": "trauma_care_bronze",
    "nmc_colleges_bronze": "nmc_bronze",
    "nmc_college_courses_bronze": "nmc_bronze",
    "dnb_hospitals_bronze": "anbai_dnb_bronze",
    "dnb_hospital_specialties_bronze": "anbai_dnb_bronze",
    "ncg_members_bronze": "ncg_bronze",
    "nabh_organisations_bronze": "nabh_bronze",
}
SOURCES = {
    "nqas_certified_facilities": f"{REPO_ROOT}/data/external/nqas_certified_facilities.csv",
    "kayakalp_bronze": f"{REPO_ROOT}/data/external/kayakalp_2021_22.csv",
    "facilities": f"{REPO_ROOT}/data/raw/facilities.csv",
    **{s: f"{REPO_ROOT}/datasets/external/{folder}/{s}.csv" for s, folder in REGISTRY.items()},
}

def load_bronze(name, path):
    full = f"{CATALOG}.{SCHEMA}.{name}"
    if spark.catalog.tableExists(full):
        print(f"{name:34s} exists ({spark.table(full).count():,} rows) - kept")
        return
    # facilities.csv escapes quotes with a backslash (\"); the other CSVs (written by Python's csv module)
    # double them (""). Reading facilities.csv with escape='"' splits rows and shifts columns.
    escape = "\\" if name == "facilities" else '"'
    r = (spark.read.option("header", True).option("inferSchema", False)
         .option("multiLine", True).option("escape", escape).csv(path))
    df = r.select([F.col(f"`{c}`").cast("string").alias(c.strip()) for c in r.columns])
    (df.withColumn("_ingested_at", F.current_timestamp()).withColumn("_source_file", F.lit(path))
       .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(full))
    print(f"{name:34s} created ({spark.table(full).count():,} rows)")

for _name, _path in SOURCES.items():
    assert _exists(_path), f"CSV missing from the repo: {_path}"
    load_bronze(_name, _path)

# COMMAND ----------

# MAGIC %md ## 3 - Create or update the pipeline Job (00 -> 06, sequential, serverless)

# COMMAND ----------

def _csv(p):
    return f"{REPO_ROOT}/{p}"          # /Workspace-prefixed, readable by Spark

def _nb(n):
    return f"{NB_ROOT}/notebooks/{n}"  # notebook path without the /Workspace prefix

CS = {"catalog": CATALOG, "schema": SCHEMA}
NT = lambda key, nb, params, dep: {
    "task_key": key,
    **({"depends_on": [{"task_key": dep}]} if dep else {}),
    "environment_key": "default",
    "timeout_seconds": 3600,
    "notebook_task": {"notebook_path": _nb(nb), "source": "WORKSPACE", "base_parameters": params},
}
tasks = [
    NT("step_00_pincode", "00_pincode_bronze_to_silver",
       {**CS, "source": _csv("data/raw/india_post_pincode_directory.csv"), "retrieved_on": "2026-11-21"}, None),
    NT("step_01_facilities", "01_bronze_to_silver",
       {"source_table": f"{CATALOG}.{SCHEMA}.facilities", "target_catalog": CATALOG, "target_schema": SCHEMA},
       "step_00_pincode"),
    NT("step_02_nqas", "02_nqas_bronze_to_silver",
       {**CS, "bronze_table": "nqas_certified_facilities", "silver_table": "nqas_silver"}, "step_01_facilities"),
    NT("step_03_kayakalp", "03_kayakalp_bronze_to_silver",
       {**CS, "bronze_table": "kayakalp_bronze", "silver_table": "kayakalp_silver_validation", "write_output": "true"}, "step_02_nqas"),
    NT("step_04_nfhs", "04_nfhs_bronze_to_silver",
       {**CS, "source": _csv("data/raw/nfhs_5_district_health_indicators.csv"), "retrieved_on": "2026-11-21"},
       "step_03_kayakalp"),
    NT("step_05_registries", "05_registries_bronze_to_silver",
       {**CS, "reload_bronze": "no"}, "step_04_nfhs"),
    NT("step_06_matching", "06_registry_matching", CS, "step_05_registries"),
    NT("validate_silver", "validate_silver_persistence",
       {**CS, "repo_root": REPO_ROOT, "kayakalp_table": "kayakalp_silver_validation"}, "step_06_matching"),
]
settings = {
    "name": JOB_NAME,
    "tasks": tasks,
    "environments": [{"environment_key": "default",
                      "spec": {"environment_version": "5", "dependencies": []}}],
    "max_concurrent_runs": 1,
}

# Raw REST with plain JSON dicts: the exact payload shape the live pipeline job uses
# (the SDK's typed helpers reject dict arguments for `environments`).
def _api(method, api_path, body=None, query=None):
    return w.api_client.do(method, api_path, body=body, query=query)

found = (_api("GET", "/api/2.2/jobs/list", query={"name": JOB_NAME, "limit": 10}) or {}).get("jobs") or []
if found:
    job_id = found[0]["job_id"]
    _api("POST", "/api/2.2/jobs/update", body={"job_id": job_id, "new_settings": settings})
    print(f"Updated existing job {JOB_NAME} (id {job_id})")
else:
    job_id = _api("POST", "/api/2.2/jobs/create", body=settings)["job_id"]
    print(f"Created job {JOB_NAME} (id {job_id})")

if RUN_AFTER:
    first = _api("POST", "/api/2.2/jobs/run-now", body={"job_id": job_id})
    print(f"First run started (run id {first['run_id']})")
print(f"Job page: {w.config.host}/jobs/{job_id}")
print("Next: open the Job and click Run now. 00 -> 06 runs sequentially, roughly 20-40 minutes.")
