"""Offline workflow regression checks. Spark SQL is exercised by remote checks,
not claimed validated by these mocked catalog/aggregate responses.
"""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from evidence_confidence.databricks_validation import (TableContract, collect_bounded, identifier,
    qualified, silver_contracts, validate_persisted_silver, validate_evidence_tables)


class DatabricksWorkflowTests(unittest.TestCase):
    def spark(self,rows=3,distinct=3,violations=0,temporary=False,fmt='delta',cols=('id',)):
        s=MagicMock()
        s.catalog.getTable.return_value=SimpleNamespace(isTemporary=temporary,tableType='MANAGED')
        df=s.table.return_value;df.columns=list(cols);df.count.return_value=rows
        df.select.return_value.distinct.return_value.count.return_value=distinct
        df.schema.jsonValue.return_value={'type':'struct','fields':[{'name':c,'type':'string','nullable':True} for c in cols]}
        def sql(q):
            result=MagicMock()
            if q.startswith('DESCRIBE'):
                result.first.return_value.asDict.return_value={'format':fmt,'id':'mock-delta-id'}
            else:result.first.return_value={'n':violations}
            return result
        s.sql.side_effect=sql
        return s

    def test_twenty_expected_outputs_and_current_kayakalp_names(self):
        c=silver_contracts()
        self.assertEqual(len(c),20)
        self.assertIn('kayakalp_silver_validation',c)
        self.assertIn('district',c['kayakalp_silver_validation'].required)
        self.assertIn('registry_match_review',c)
        with self.assertRaises(ValueError):silver_contracts('facilities_silver')

    def test_identifiers_cannot_inject_sql(self):
        self.assertEqual(qualified('cat','schema','table'),'`cat`.`schema`.`table`')
        for value in ('x; DROP TABLE t','a.b','a`b','',None):
            with self.assertRaises(ValueError):identifier(value)

    def test_persisted_table_schema_counts_and_keys(self):
        r=validate_persisted_silver(self.spark(),'cat','schema',contracts={'test':TableContract(('id',),nonempty=True)})
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['tables'][0]['row_count'],3)
        self.assertEqual(r['tables'][0]['distinct_keys'],3)
        self.assertEqual(r['tables'][0]['schema']['fields'][0]['name'],'id')

    def test_temporary_view_is_not_persistence(self):
        r=validate_persisted_silver(self.spark(temporary=True),'cat','schema',contracts={'test':TableContract()})
        self.assertEqual(r['status'],'FAIL')
        self.assertIn('temporary views',r['tables'][0]['errors'][0])

    def test_non_delta_fails(self):
        r=validate_persisted_silver(self.spark(fmt='parquet'),'cat','schema',contracts={'test':TableContract()})
        self.assertEqual(r['status'],'FAIL')

    def test_duplicate_and_invalid_keys_fail(self):
        for s in (self.spark(rows=3,distinct=2),self.spark(violations=1)):
            self.assertEqual(validate_persisted_silver(s,'cat','schema',contracts={'test':TableContract(('id',))})['status'],'FAIL')

    def test_empty_auxiliary_valid_but_empty_main_fails(self):
        s=self.spark(rows=0,distinct=0)
        self.assertEqual(validate_persisted_silver(s,'cat','schema',contracts={'test':TableContract()})['status'],'PASS')
        self.assertEqual(validate_persisted_silver(s,'cat','schema',contracts={'test':TableContract(nonempty=True)})['status'],'FAIL')

    def test_missing_required_fields_fail(self):
        r=validate_persisted_silver(self.spark(),'cat','schema',contracts={'test':TableContract(required=('missing',))})
        self.assertEqual(r['tables'][0]['missing_columns'],['missing'])
        self.assertEqual(r['status'],'FAIL')

    def test_access_error_is_not_silently_skipped(self):
        s=self.spark();s.catalog.getTable.side_effect=PermissionError('mock SELECT denied')
        r=validate_persisted_silver(s,'cat','schema',contracts={'test':TableContract()})
        self.assertEqual(r['status'],'FAIL');self.assertIn('SELECT denied',r['tables'][0]['errors'][0])

    def test_bounded_collection_fails_instead_of_top_k(self):
        s=self.spark();s.table.return_value.limit.return_value.collect.return_value=[MagicMock()]*3
        with self.assertRaisesRegex(ValueError,'no truncated batch'):collect_bounded(s,'cat','schema','table',2)
        for value in (True,0,1000001):
            with self.assertRaises(ValueError):collect_bounded(s,'cat','schema','table',value)

    def test_missing_real_core_inputs_block_evidence(self):
        s=self.spark();s.table.side_effect=PermissionError('mock inaccessible')
        r=validate_evidence_tables(s,'cat','schema',as_of=date(2026,11,21),vocabulary={'dialysis':'Dialysis'})
        self.assertEqual(r['status'],'BLOCKED');self.assertEqual(len(r['errors']),4)

    def test_both_runner_paths_request_kayakalp_persistence(self):
        root=Path(__file__).resolve().parents[1]
        for file in ('setup_pipeline.py','run_pipeline.py'):
            source=(root/'notebooks'/file).read_text()
            self.assertIn('"write_output": "true"',source)
        self.assertIn('"validate_silver_persistence"',(root/'notebooks/setup_pipeline.py').read_text())
