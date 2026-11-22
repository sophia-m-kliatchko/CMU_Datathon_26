# Databricks notebook source
# MAGIC %md
# MAGIC # Read-only post-run Silver persistence checks
# MAGIC Run as a separate Lakeflow task after 06. No table or source-record writes.
# MAGIC Counts/schema/violations only; this notebook fails the job if checks fail.

# COMMAND ----------
import json
import sys
from pathlib import Path

dbutils.widgets.text('catalog','workspace')
dbutils.widgets.text('schema','datathon')
dbutils.widgets.text('repo_root','')
dbutils.widgets.text('kayakalp_table','kayakalp_silver_validation')
dbutils.widgets.text('include_geography','false')
root=Path(dbutils.widgets.get('repo_root'))
assert (root/'evidence_confidence/databricks_validation.py').is_file(), 'Set repo_root to the current workspace checkout containing Evidence Confidence.'
sys.path.insert(0,str(root))
from evidence_confidence.databricks_validation import validate_persisted_silver, silver_contracts, TableContract
contracts=silver_contracts(dbutils.widgets.get('kayakalp_table'))
if dbutils.widgets.get('include_geography') == 'true':
    for table in ('facility_geo_ready','evidence_candidates_110001','evidence_candidates_400001'):
        contracts[table]=TableContract(('facility_id',),('geo_latitude','geo_longitude','geo_confidence','location_basis','location_uncertainty_km'),True)
report=validate_persisted_silver(spark,dbutils.widgets.get('catalog'),dbutils.widgets.get('schema'),
    kayakalp_table=dbutils.widgets.get('kayakalp_table'),contracts=contracts)
print(json.dumps(report,allow_nan=False))
dbutils.jobs.taskValues.set(key='silver_persistence_status',value=report['status'])
if report['status']!='PASS':
    raise RuntimeError('Silver persistence validation failed: '+json.dumps([
        {'table':r['table'],'errors':r['errors']} for r in report['tables'] if r['status']!='PASS']))
dbutils.notebook.exit(json.dumps(report,allow_nan=False))
