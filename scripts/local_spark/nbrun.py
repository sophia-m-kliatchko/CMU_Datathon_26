"""
Run Databricks source-format notebooks (notebooks/*.py) on a LOCAL Spark session, to catch runtime bugs
before running them on Databricks. Not used by Databricks itself.

What it emulates:
  * cells split on "# COMMAND ----------"; %md cells skipped; %sql cells run with spark.sql(...).show()
  * "%run ./path" executes that notebook into the same namespace (like Databricks)
  * dbutils.widgets.text/dropdown/get, dbutils.fs.ls, display()
  * catalog `workspace` -> local `spark_catalog` (pass --widget catalog=spark_catalog etc.)
  * ANSI SQL mode ON, as on Databricks serverless

Usage (inside WSL, with the venv from scripts/local_spark/setup_wsl.sh):
  python nbrun.py <notebook.py> [--widget name=value ...] [--replace 'OLD=>NEW' ...]
"""
import argparse
import os
import re
import sys
import time
import traceback

from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession, DataFrame

WAREHOUSE = os.path.expanduser("~/sparkcheck/warehouse")


def get_spark():
    b = (SparkSession.builder.master("local[4]").appName("nbrun")
         .config("spark.sql.warehouse.dir", WAREHOUSE)
         .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
         .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
         .config("spark.sql.sources.default", "delta")
         .config("spark.sql.ansi.enabled", "true")
         .config("spark.sql.shuffle.partitions", "8")
         .config("spark.driver.memory", "6g")
         .config("spark.ui.enabled", "false")
         # Persistent local metastore, so tables written by one notebook are visible to the next (like Unity Catalog)
         .config("spark.sql.catalogImplementation", "hive")
         .config("spark.driver.extraJavaOptions", f"-Dderby.system.home={os.path.expanduser('~/sparkcheck')}")
         .config("javax.jdo.option.ConnectionURL",
                 f"jdbc:derby:;databaseName={os.path.expanduser('~/sparkcheck/metastore_db')};create=true"))
    spark = configure_spark_with_delta_pip(b).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


class SparkProxy:
    """Delegates to the real SparkSession; translates Databricks-only SQL that open-source Spark spells differently."""

    def __init__(self, spark):
        object.__setattr__(self, "_s", spark)

    def __getattr__(self, name):
        return getattr(self._s, name)

    def sql(self, query, *args, **kwargs):
        q = re.sub(r"^\s*USE\s+CATALOG\b", "SET CATALOG", query, flags=re.I)
        return self._s.sql(q, *args, **kwargs)


class _Widgets:
    def __init__(self, overrides):
        self.values, self.overrides = {}, overrides

    def text(self, name, default="", label=None):
        self.values[name] = self.overrides.get(name, default)

    def dropdown(self, name, default, choices=None, label=None):
        self.values[name] = self.overrides.get(name, default)

    combobox = dropdown

    def get(self, name):
        if name not in self.values:
            if name in self.overrides:
                return self.overrides[name]
            raise ValueError(f"widget {name} not defined")
        return self.values[name]


class _FileInfo:
    def __init__(self, path):
        self.path, self.name = path, os.path.basename(path)


class _Fs:
    def ls(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if os.path.isdir(path):
            return [_FileInfo(os.path.join(path, n)) for n in sorted(os.listdir(path))]
        return [_FileInfo(path)]


class DBUtils:
    def __init__(self, overrides):
        self.widgets, self.fs = _Widgets(overrides), _Fs()


def display(obj, *a, **k):
    if isinstance(obj, DataFrame):
        obj.show(25, truncate=80)
    else:
        print(obj)


CELL_SPLIT = re.compile(r"^# COMMAND -{5,}\s*$", re.M)


def cells_of(path, replacements):
    src = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    for old, new in replacements:
        old, new = old.replace("\r", ""), new.replace("\r", "")
        if old not in src:
            raise SystemExit(f"--replace target not found in {path}: {old!r}")
        src = src.replace(old, new)
    src = re.sub(r"^# Databricks notebook source\s*$", "", src, count=1, flags=re.M)
    return [c.strip("\n") for c in CELL_SPLIT.split(src)]


def run_notebook(path, g, replacements=(), depth=0):
    nb_dir = os.path.dirname(os.path.abspath(path))
    for i, cell in enumerate(cells_of(path, replacements if depth == 0 else ())):
        lines = [l for l in cell.split("\n")]
        magic = [l for l in lines if l.startswith("# MAGIC")]
        first = next((l for l in lines if l.strip()), "")
        if first.startswith("# MAGIC %md") or not cell.strip():
            continue
        if first.startswith("# MAGIC %run"):
            target = first.split("%run", 1)[1].strip()
            target = os.path.normpath(os.path.join(nb_dir, target))
            target = target if target.endswith(".py") else target + ".py"
            print(f"{'  ' * depth}[%run {os.path.relpath(target)}]")
            run_notebook(target, g, depth=depth + 1)
            continue
        if first.startswith("# MAGIC %pip"):
            args = [a for a in first.split("%pip", 1)[1].split() if a not in ("install", "--quiet", "-q")]
            print(f"{'  ' * depth}[%pip install {' '.join(args)}]")
            import subprocess
            subprocess.run([os.path.expanduser("~/.local/bin/uv"), "pip", "install", "-q", "--python", sys.executable, *args],
                           check=True)
            continue
        if first.startswith("# MAGIC %sql"):
            sql = "\n".join(l[len("# MAGIC"):].lstrip(" ") if l.startswith("# MAGIC") else l for l in lines)
            sql = sql.replace("%sql", "", 1)
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                stmt_body = "\n".join(l for l in stmt.split("\n") if not l.strip().startswith("--")).strip()
                if not stmt_body:
                    continue
                print(f"{'  ' * depth}[sql cell {i}]")
                g["spark"].sql(stmt_body).show(25, truncate=80)
            continue
        code = "\n".join(l for l in lines if not l.startswith("# DBTITLE"))
        t0 = time.time()
        try:
            exec(compile(code, f"{os.path.basename(path)}[cell {i}]", "exec"), g)
        except Exception:
            print(f"\n!!! ERROR in {path} cell {i}:\n" + "\n".join(code.split("\n")[:6]) + "\n...")
            raise
        print(f"{'  ' * depth}[cell {i} ok, {time.time() - t0:.1f}s]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("notebook")
    ap.add_argument("--widget", action="append", default=[])
    ap.add_argument("--replace", action="append", default=[], help="OLD=>NEW text substitution in the top notebook")
    a = ap.parse_args()
    overrides = dict(w.split("=", 1) for w in a.widget)
    replacements = [tuple(r.split("=>", 1)) for r in a.replace]
    spark = get_spark()
    g = {"__name__": "__main__", "spark": SparkProxy(spark), "dbutils": DBUtils(overrides), "display": display}
    t0 = time.time()
    try:
        run_notebook(a.notebook, g, replacements)
    except Exception:
        traceback.print_exc()
        print(f"\nNOTEBOOK FAILED: {a.notebook} after {time.time() - t0:.0f}s")
        sys.exit(1)
    print(f"\nNOTEBOOK OK: {a.notebook} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
