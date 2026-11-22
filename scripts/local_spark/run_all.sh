#!/bin/bash
# Run every notebook in the documented order on a local Spark (WSL), using the repo's real CSVs.
# Usage (from Windows):  wsl -d Ubuntu -- bash "/mnt/c/.../scripts/local_spark/run_all.sh" [notebook-number ...]
# Needs scripts/local_spark/setup_wsl.sh to have been run once.
set -o pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BASE=~/sparkcheck
export JAVA_HOME="$BASE/jdk" PATH="$BASE/jdk/bin:$BASE/venv/bin:$PATH"
PY="$BASE/venv/bin/python"
NB="$REPO/notebooks"
LOGS="$BASE/logs"; mkdir -p "$LOGS"
CAT="--widget catalog=spark_catalog --widget schema=datathon --widget target_catalog=spark_catalog --widget target_schema=datathon"

# Flat folder of registry bronze CSVs, as notebook 05 expects in its Volume
EXT="$BASE/external"; mkdir -p "$EXT"
cp "$REPO"/datasets/external/*/*_bronze.csv "$EXT"/ 2>/dev/null

# Source tables that exist in Databricks but not locally (created once from the repo CSVs)
$PY - <<EOF
import sys; sys.path.insert(0, "$REPO/scripts/local_spark")
from nbrun import get_spark
s = get_spark()
s.sql("CREATE SCHEMA IF NOT EXISTS spark_catalog.datathon")
s.sql("CREATE SCHEMA IF NOT EXISTS spark_catalog.vf")
def load(name, path, **opts):
    if s.catalog.tableExists(name):
        return
    r = s.read.option("header", True).option("inferSchema", False)
    for k, v in opts.items():
        r = r.option(k, v)
    r.csv(path).write.mode("overwrite").saveAsTable(name)
    print("created", name, s.table(name).count())
load("spark_catalog.vf.facilities", "$REPO/data/raw/facilities.csv", escape="\\\\", multiLine="false")
load("spark_catalog.datathon.nqas_certified_facilities", "$REPO/data/external/nqas_certified_facilities.csv")
load("spark_catalog.datathon.kayakalp_bronze", "$REPO/data/external/kayakalp_2021_22.csv")
EOF

run() {  # run <label> <args...>
  local label="$1"; shift
  echo "================ $label ================"
  "$PY" "$REPO/scripts/local_spark/nbrun.py" "$@" $CAT > "$LOGS/$label.log" 2>&1
  local rc=$?
  tail -25 "$LOGS/$label.log"
  [ $rc -eq 0 ] && echo "RESULT $label: OK" || echo "RESULT $label: FAILED (log: $LOGS/$label.log)"
  return $rc
}

WANT="${*:-00 01 02 03 04 05 06}"
for n in $WANT; do
  case $n in
    00) run 00_pincode "$NB/00_pincode_bronze_to_silver.py" --widget source="$REPO/data/raw/india_post_pincode_directory.csv" ;;
    01) run 01_facilities "$NB/01_bronze_to_silver.py" --widget source_table=spark_catalog.vf.facilities ;;
    02) run 02_nqas "$NB/02_nqas_bronze_to_silver.py" ;;
    03) run 03_kayakalp "$NB/03_kayakalp_bronze_to_silver.py" --widget write_output=true ;;
    05) run 05_registries "$NB/05_registries_bronze_to_silver.py" --widget external_path="$EXT" --widget reload_bronze=yes ;;
    06) run 06_matching "$NB/06_registry_matching.py" ;;
    audit_nfhs) "$PY" "$REPO/scripts/local_spark/audit_nfhs.py" 2>&1 | grep -v "Stage [0-9]\|WARN\|ivy\|:: \|found \|central\|downloading\|SUCCESSFUL" ;;
    audit_links) "$PY" "$REPO/scripts/local_spark/audit_links.py" 2>&1 | grep -v "Stage [0-9]\|WARN\|ivy\|:: \|found \|central\|downloading\|SUCCESSFUL" ;;
    audit) echo "================ audit ================"; "$PY" "$REPO/scripts/local_spark/audit.py" 2>&1 | grep -v "Stage [0-9]\|WARN\|ivy\|:: \|found \|central\|downloading\|SUCCESSFUL" ;;
    04|nfhs) run 04_nfhs "$NB/04_nfhs_bronze_to_silver.py" --widget source="$REPO/data/raw/nfhs_5_district_health_indicators.csv" ;;
  esac
done
