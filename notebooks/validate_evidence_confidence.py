# Databricks notebook source
# MAGIC %md
# MAGIC # Read-only real-Silver Evidence Confidence validation
# MAGIC All actual source rows and recommendation JSON remain in the driver.
# MAGIC Only aggregate checks leave this notebook. No table writes or geographic calculations.

# COMMAND ----------
import json
import sys
from pathlib import Path
from datetime import date

for name,default in (('catalog','workspace'),('schema','datathon'),('repo_root',''),
    ('as_of',''),('kayakalp_table','kayakalp_silver_validation'),('candidate_table',''),
    ('candidate_context_json','{}'),('request_json','{}'),('max_rows','100000'),
    ('nqas_link_table',''),('kayakalp_link_table','')):
    dbutils.widgets.text(name,default)
root=Path(dbutils.widgets.get('repo_root'))
assert (root/'evidence_confidence/databricks_validation.py').is_file(), 'Current Evidence Confidence package missing from repo_root'
sys.path.insert(0,str(root))
from evidence_confidence.databricks_validation import validate_evidence_tables
from evidence_confidence.silver import notebook_service_vocabulary
as_of=date.fromisoformat(dbutils.widgets.get('as_of'))  # Explicit reproducible date required.
report=validate_evidence_tables(spark,dbutils.widgets.get('catalog'),dbutils.widgets.get('schema'),
    as_of=as_of,vocabulary=notebook_service_vocabulary(root/'notebooks/05_registries_bronze_to_silver.py'),
    request=json.loads(dbutils.widgets.get('request_json')) or None,
    candidate_table=dbutils.widgets.get('candidate_table') or None,
    candidate_context=json.loads(dbutils.widgets.get('candidate_context_json')) or None,
    kayakalp_table=dbutils.widgets.get('kayakalp_table'),
    quality_link_tables={source:dbutils.widgets.get(source+'_link_table') for source in ('nqas','kayakalp')
                         if dbutils.widgets.get(source+'_link_table')},
    max_rows=int(dbutils.widgets.get('max_rows')))
# Registry findings can carry IDs; notebook results contain only aggregate codes.
report['findings']=[{k:v for k,v in f.items() if k!='examples'} for f in report.get('findings',[])]
print(json.dumps(report,allow_nan=False))
if report['status'] in ('FAIL','BLOCKED'):
    raise RuntimeError('Real-Silver Evidence Confidence validation '+report['status']+': '+json.dumps(report))
dbutils.notebook.exit(json.dumps(report,allow_nan=False))
