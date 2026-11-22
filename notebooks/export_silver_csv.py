# Databricks notebook source
# MAGIC %md
# MAGIC # Export the silver tables as CSV
# MAGIC
# MAGIC Writes every silver table in the schema to **one CSV file per table** in a Unity Catalog Volume, e.g.
# MAGIC `/Volumes/workspace/datathon/exports/facilities_silver.csv`, plus `_export_manifest.csv` (table, rows, columns, file).
# MAGIC
# MAGIC * **Which tables:** names ending in `_silver` or starting with `silver_` (change with widget 4).
# MAGIC * **List/struct columns** (e.g. `dq_flags`, `possible_duplicate_ids`) can't be stored in CSV, so they're written as **JSON text**, e.g. `["MISSING_COORDS"]`. Read them back with `json.loads`.
# MAGIC * Every run replaces the previous export.
# MAGIC
# MAGIC **Download:**
# MAGIC * **Browser:** *Catalog → workspace → datathon → Volumes → exports →* click a file → **Download**.
# MAGIC * **All files, from your computer:** `databricks fs cp -r dbfs:/Volumes/workspace/datathon/exports ./silver_csv --profile <your-profile>`
# MAGIC
# MAGIC Run after the pipeline job. Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

import re
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, MapType, StructType

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("volume", "exports", "3. Volume to write to (created if missing)")
dbutils.widgets.text("table_pattern", r"(_silver$|^silver_)", "4. Tables to export (regex on the name)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
VOLUME = dbutils.widgets.get("volume").strip()
PATTERN = dbutils.widgets.get("table_pattern").strip()
for x in (CATALOG, SCHEMA, VOLUME):
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x), f"Use a simple name, not {x!r}"

spark.sql(f"CREATE VOLUME IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`.`{VOLUME}`")
OUT = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
TMP = f"{OUT}/_tmp_export"

tables = sorted(r.tableName for r in spark.sql(f"SHOW TABLES IN `{CATALOG}`.`{SCHEMA}`").collect()
                if not r.isTemporary and re.search(PATTERN, r.tableName))
assert tables, f"No tables in {CATALOG}.{SCHEMA} match {PATTERN!r}; run the pipeline first."
print(f"Exporting {len(tables)} tables to {OUT}:\n  " + "\n  ".join(tables))

# COMMAND ----------

def csv_ready(df):
    """Lists, maps and structs -> JSON text (CSV only holds plain values); everything else unchanged."""
    return df.select([
        F.to_json(F.col(f"`{f.name}`")).alias(f.name) if isinstance(f.dataType, (ArrayType, MapType, StructType))
        else F.col(f"`{f.name}`")
        for f in df.schema.fields
    ])


def single_csv(df, target):
    """Write df as ONE CSV file at `target` (Spark writes a folder; move its part file out and clean up)."""
    tmp = f"{TMP}/{target.rsplit('/', 1)[-1]}"
    (df.coalesce(1).write.mode("overwrite").option("header", True)
       .option("quote", '"').option("escape", '"').csv(tmp))
    part = [f.path for f in dbutils.fs.ls(tmp) if f.name.startswith("part-") and f.name.endswith(".csv")]
    assert len(part) == 1, f"expected one part file in {tmp}, found {part}"
    dbutils.fs.rm(target)
    dbutils.fs.mv(part[0], target)
    dbutils.fs.rm(tmp, True)


manifest = []
for t in tables:
    df = csv_ready(spark.table(f"`{CATALOG}`.`{SCHEMA}`.`{t}`"))
    target = f"{OUT}/{t}.csv"
    single_csv(df, target)
    n = df.count()
    manifest.append((t, n, len(df.columns), target))
    print(f"✓ {t}: {n:,} rows, {len(df.columns)} columns -> {target}")

dbutils.fs.rm(TMP, True)
man = spark.createDataFrame(manifest, "table string, rows long, columns int, file string")
single_csv(man, f"{OUT}/_export_manifest.csv")
display(man)

# COMMAND ----------

# Check: each file reads back with the same number of rows as its table
problems = []
for t, n, ncols, path in manifest:
    back = spark.read.option("header", True).option("quote", '"').option("escape", '"').option("multiLine", True).csv(path)
    if back.count() != n or len(back.columns) != ncols:
        problems.append(f"{t}: table {n} rows/{ncols} cols, CSV {back.count()} rows/{len(back.columns)} cols")
assert not problems, "Export check failed: " + "; ".join(problems)
print(f"✓ All {len(manifest)} CSV files read back with the same rows and columns as their tables.")
