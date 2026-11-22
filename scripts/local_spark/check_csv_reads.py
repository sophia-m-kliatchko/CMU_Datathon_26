"""
Compare how Spark parses each repo CSV with setup_pipeline.py's read options (escape='"', multiLine=True)
versus the options the file actually needs. Reports row counts and rows whose ID / first column is malformed.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nbrun import get_spark
from pyspark.sql import functions as F

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
s = get_spark()
UUID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def read(path, **opts):
    r = s.read.option("header", True).option("inferSchema", False)
    for k, v in opts.items():
        r = r.option(k, v)
    return r.csv(path)


fac = f"{REPO}/data/raw/facilities.csv"
for label, opts in [("setup_pipeline options (escape='\"', multiLine)", {"multiLine": True, "escape": '"'}),
                    ("backslash escape (as the file is written)", {"multiLine": True, "escape": "\\"})]:
    df = read(fac, **opts)
    n = df.count()
    bad = df.where(~F.col("unique_id").rlike(UUID)).count()
    lat_bad = df.where(F.col("latitude").isNotNull() & F.expr("try_cast(latitude AS DOUBLE)").isNull()).count()
    print(f"facilities.csv | {label}: {len(df.columns)} columns, {n:,} rows, "
          f"non-UUID unique_id: {bad:,}, non-numeric latitude: {lat_bad:,}")

others = {
    "nqas": f"{REPO}/data/external/nqas_certified_facilities.csv",
    "kayakalp": f"{REPO}/data/external/kayakalp_2021_22.csv",
    "nabh": f"{REPO}/datasets/external/nabh_bronze/nabh_organisations_bronze.csv",
    "nmc_courses": f"{REPO}/datasets/external/nmc_bronze/nmc_college_courses_bronze.csv",
}
for k, p in others.items():
    a = read(p, multiLine=True, escape='"')
    b = read(p, multiLine=True, escape="\\")
    print(f"{k}: escape='\"' -> {a.count():,} rows / {len(a.columns)} cols; escape='\\\\' -> {b.count():,} rows / {len(b.columns)} cols")
