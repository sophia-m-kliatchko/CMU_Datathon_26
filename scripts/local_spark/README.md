# Local Spark check for the Databricks notebooks

Runs every notebook in `notebooks/` on a **local** Spark (PySpark 4.0 + Delta, inside WSL Ubuntu) against the CSVs in this repo, in the pipeline order, so runtime errors show up before anything is run on Databricks. Databricks itself never uses these files.

## One-time setup (WSL, no admin rights; ~550 MB in `~/sparkcheck`)
```powershell
wsl -d Ubuntu -- bash "/mnt/c/Users/<you>/OneDrive/Bookmarks/Datathon Project Code/scripts/local_spark/setup_wsl.sh"
```
It installs uv, Java 17 (Temurin), Python 3.12, PySpark 4.0.1, delta-spark, pandas and pyarrow.

## Run
```powershell
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh"                 # all notebooks, in order
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh" 01 06            # selected notebooks
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh" audit            # output checks
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh" audit_links      # notebook 06 link quality
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/summary.sh"                  # validation results of the last run
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh" pipeline         # notebooks/run_pipeline.py (00 -> 06 via dbutils.notebook.run)
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/test_pipeline_failure.sh"    # forced failure in 00: 00 FAILED, dependants SKIPPED, 03 OK
wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/show_pipeline_log.sh"        # step-by-step output of the last pipeline run
```
Logs: `~/sparkcheck/logs/<notebook>.log` (inside WSL).

## How it emulates Databricks (`nbrun.py`)
- Cells split on `# COMMAND ----------`; `%md` skipped; `%sql` run with `spark.sql`; `%run` executes the referenced notebook into the same namespace; `%pip install` installs into the local venv.
- `dbutils.widgets` (text/dropdown/get), `dbutils.fs.ls`, `dbutils.notebook.run` (fresh namespace, its own widget values, relative paths) and `display()` are stubbed. Command-line `--widget` values also reach notebooks started by `dbutils.notebook.run`. The catalog is local `spark_catalog` (widgets overridden to `spark_catalog` / `datathon`); `USE CATALOG` is translated to Spark's `SET CATALOG`.
- ANSI SQL mode is on, as on Databricks serverless. Tables persist between notebooks in a local Hive/Derby metastore.
- Source tables that exist only in Databricks (the Marketplace facilities table, the NQAS and Kayakalp bronze tables) are created once from the repo CSVs.

## Limits
- Spark Connect / serverless-only restrictions (e.g. `.cache()` not supported on serverless) do **not** show up locally.
- Unity Catalog features (volumes, permissions) are not emulated.
