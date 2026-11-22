# Databricks notebook source
# MAGIC %md
# MAGIC # common/validation
# MAGIC Checks that a silver table is **accurate to its bronze table** before it is written.
# MAGIC
# MAGIC Each check is a DataFrame of the rows that **break** a rule. An empty result means the check passed.
# MAGIC `run_validations()` counts each one, keeps up to 3 example rows, and writes a `<dataset>_validation` table:
# MAGIC
# MAGIC | column | meaning |
# MAGIC |---|---|
# MAGIC | `check` | short name, e.g. `COORDS_FROM_BRONZE` |
# MAGIC | `description` | the rule in plain words |
# MAGIC | `passed` | true if no row breaks it |
# MAGIC | `n_failed` | how many rows break it |
# MAGIC | `examples` | up to 3 offending rows |
# MAGIC
# MAGIC If any check fails, it raises an error, so the notebook stops **before** the silver table is overwritten.
# MAGIC Load with `%run ./common/validation`.

# COMMAND ----------

from pyspark.sql import functions as F


def mismatch_rows(name, expected, actual):
    """A one-row DataFrame if two numbers differ, else an empty one (for count reconciliations)."""
    rows = [] if expected == actual else [(name, int(expected), int(actual))]
    return spark.createDataFrame(rows, "what string, expected long, actual long")


def run_validations(checks, results_table, fail_on_error=True):
    """
    checks: list of (check_name, description, DataFrame_of_offending_rows).
    Writes the results table, displays it, and raises AssertionError if any check fails.
    """
    results, failed = [], []
    for name, description, bad in checks:
        n = bad.count()
        examples = [str(r.asDict())[:400] for r in bad.limit(3).collect()] if n else []
        results.append((name, description, n == 0, n, examples))
        print(f"{'PASS' if n == 0 else 'FAIL'}  {name}: {n:,} rows break it")
        if n:
            failed.append(f"{name} ({n:,} rows)")
    res = (spark.createDataFrame(results, "check string, description string, passed boolean, n_failed long, examples array<string>")
           .withColumn("checked_at", F.current_timestamp()))
    res.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(results_table)
    display(res)
    if failed and fail_on_error:
        raise AssertionError(f"Validation failed; the silver table was NOT written. See {results_table}. Failed: "
                             + "; ".join(failed))
    return res


def haversine_km_col(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two points given as Columns (NULL if any input is NULL)."""
    p = 3.141592653589793 / 180
    h = (F.pow(F.sin((lat2 - lat1) * p / 2), 2) +
         F.cos(lat1 * p) * F.cos(lat2 * p) * F.pow(F.sin((lon2 - lon1) * p / 2), 2))
    # F.least() skips NULLs, so least(1.0, NULL) would be 1.0 -> 20,015 km for a missing point.
    # h is NULL whenever any coordinate is NULL; keep the distance NULL in that case.
    return F.when(h.isNotNull(), 2 * 6371.0 * F.asin(F.least(F.lit(1.0), F.sqrt(h))))


def same_number(a, b, tol=1e-6):
    return F.abs(a - b) <= F.lit(tol)
