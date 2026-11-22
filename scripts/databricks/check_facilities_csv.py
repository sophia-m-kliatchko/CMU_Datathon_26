# Databricks notebook source
# MAGIC %md
# MAGIC # Check how Spark parses facilities.csv on Databricks (read-only)
# MAGIC Compares setup_pipeline's old read options (escape='"') with the fixed ones (escape='\\').

# COMMAND ----------

import json
from pyspark.sql import functions as F

dbutils.widgets.text("path", "/Workspace/Datathon Fall 26/CMU_Datathon_26/data/raw/facilities.csv", "CSV path")
PATH = dbutils.widgets.get("path")
UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
res = {}
for label, esc in [("old escape='\"'", '"'), ("fixed escape='\\\\'", "\\")]:
    df = (spark.read.option("header", True).option("inferSchema", False)
          .option("multiLine", True).option("escape", esc).csv(PATH))
    res[label] = {
        "columns": len(df.columns), "rows": df.count(),
        "non_uuid_ids": df.where(~F.col("unique_id").rlike(UUID)).count(),
        "non_numeric_latitude": df.where(F.col("latitude").isNotNull() & F.expr("try_cast(latitude AS DOUBLE)").isNull()).count(),
    }
dbutils.notebook.exit(json.dumps(res))
