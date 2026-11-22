"""Regression checks for the actual extractor and Databricks notebook transforms."""
import csv
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from kayakalp_pdf_to_csv import fix_state, split_award, fy_from_filename


class ExtractionTests(unittest.TestCase):
    def test_known_interleaved_spill(self):
        self.assertEqual(fix_state('aGrUJARAT', 'Modhwada,Porband'),
                         ('Gujarat', 'Modhwada,Porbandar', True))

    def test_unknown_is_not_guessed(self):
        self.assertEqual(fix_state('UNRESOLVED', 'Original'), ('Unresolved', 'Original', False))

    def test_award_categories_and_joint_ranks(self):
        self.assertEqual(split_award('JOINT WINNER- Kayakalp'), ('Joint Winner', 'Kayakalp'))
        self.assertEqual(split_award('Runner Up-Eco friendly'), ('Runner Up', 'Eco-friendly'))
        self.assertEqual(fy_from_filename('KAYAKALP WINNER FACILITIES 21-22.pdf'), '2021-22')


class SparkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pyspark.sql import SparkSession
        cls.spark = SparkSession.builder.master('local[1]').appName('kayakalp-regression').config('spark.sql.ansi.enabled','true').getOrCreate()
        cls.spark.sparkContext.setLogLevel('ERROR')
        cls.ns = {'spark': cls.spark}
        exec((ROOT/'notebooks/common/reference_data.py').read_text(), cls.ns)
        cls.source = (ROOT/'notebooks/03_kayakalp_bronze_to_silver.py').read_text()
        cls.rows = list(csv.DictReader(open(ROOT/'data/external/kayakalp_2021_22.csv')))

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def transform(self, rows):
        ns = self.ns.copy()
        ns.update(BRONZE='test_bronze', SOURCE_URL='https://qps.nhsrcindia.org/sites/default/files/2024-09/KAYAKALP%20WINNER%20FACILITIES%2021-22.pdf')
        exec(self.source[self.source.index('SOURCE_NAME ='):self.source.index('bronze = spark.table(BRONZE)')], ns)
        self.spark.createDataFrame(rows).createOrReplaceTempView('test_bronze')
        start = self.source.index('bronze = spark.table(BRONZE)')
        end = self.source.index('# Validate BEFORE any write.')
        exec(self.source[start:end], ns)
        return ns['silver']

    def test_full_committed_data(self):
        df = self.transform(self.rows)
        self.assertEqual(df.count(),1197)
        self.assertEqual(df.select('award_id').distinct().count(),1197)
        self.assertEqual(df.filter('state_clean IS NULL OR row_citation IS NULL').count(),0)
        self.assertEqual(len(df.columns),30)

    def test_verified_pdf_spacing_preserves_raw(self):
        result = self.transform([r for r in self.rows if r['s_no'] in ('607','608')]).collect()
        self.assertEqual({r.district_clean for r in result}, {'North Garo Hills','East Khasi Hills'})
        self.assertTrue(all('DISTRICT_SPACING_VERIFIED' in r.dq_flags for r in result))
        self.assertTrue(all('hills' in r.district_raw for r in result))

    def test_empty_district_ansi_and_missing_identity(self):
        row = dict(self.rows[0], district='', s_no='bad', source_page='bad', financial_year='', award_category='unknown')
        result = self.transform([row]).first().asDict()
        self.assertIsNone(result['district_clean'])
        self.assertTrue({'MISSING_DISTRICT','INVALID_SERIAL','INVALID_SOURCE_PAGE',
                         'FINANCIAL_YEAR_UNEXPECTED','AWARD_CATEGORY_UNRECOGNIZED'} <= set(result['dq_flags']))

    def test_multiple_awards_preserved_and_duplicates_flagged(self):
        first = self.rows[0]
        eco = dict(first, s_no='2000', award_category='Eco-friendly')
        duplicate = dict(first, s_no='2001')
        result = self.transform([first,eco,duplicate]).collect()
        self.assertEqual(len(result),3)
        self.assertEqual(sum('POSSIBLE_DUPLICATE_AWARD' in r.dq_flags for r in result),2)

    def test_notebook_validation_sql(self):
        df = self.transform(self.rows)
        df.createOrReplaceTempView('kayakalp_validation_result')
        start = self.source.index('silver = spark.table("kayakalp_validation_result")')
        outputs = []
        exec(self.source[start:], dict(spark=self.spark, display=lambda result: outputs.append(result.collect())))
        self.assertEqual(len(outputs),3)
        self.assertTrue(all(outputs))

    def test_invalid_identity_blocks_before_write(self):
        from pyspark.sql import functions as F
        df = self.transform([self.rows[0],self.rows[0]])
        start = self.source.index('# Validate BEFORE any write.')
        end = self.source.index('if SOURCE_URL is None:',start)
        with self.assertRaisesRegex(AssertionError, 'award_id is not unique'):
            exec(self.source[start:end], dict(silver=df, bronze=df, F=F, WRITE_OUTPUT=True,
                                             SILVER='should_never_be_written'))
        self.assertFalse(self.spark.catalog.tableExists('should_never_be_written'))

    def test_existing_table_cannot_be_overwritten(self):
        import uuid
        from pyspark.sql import functions as F
        from pyspark.errors import AnalysisException
        table = 'kayakalp_guard_' + uuid.uuid4().hex
        self.spark.createDataFrame([(987654,)], ['sentinel']).write.saveAsTable(table)
        try:
            df = self.transform([self.rows[0]])
            start = self.source.index('# Validate BEFORE any write.')
            end = self.source.index('if SOURCE_URL is None:',start)
            with self.assertRaises(AnalysisException):
                exec(self.source[start:end], dict(silver=df, bronze=df, F=F, spark=self.spark,
                                                 WRITE_OUTPUT=True, SILVER=table))
            self.assertEqual(self.spark.table(table).collect()[0].sentinel, 987654)
        finally:
            self.spark.sql(f'DROP TABLE {table}')

    def test_new_local_table_verified_after_creation(self):
        import uuid
        from pyspark.sql import functions as F
        table = 'kayakalp_created_' + uuid.uuid4().hex
        try:
            df = self.transform([self.rows[0]])
            start = self.source.index('# Validate BEFORE any write.')
            end = self.source.index('if SOURCE_URL is None:',start)
            exec(self.source[start:end], dict(silver=df, bronze=df, F=F, spark=self.spark,
                                             WRITE_OUTPUT=True, SILVER=table))
            self.assertEqual(self.spark.table(table).count(), 1)
            detail = self.spark.sql(f'DESCRIBE TABLE EXTENDED {table}').collect()
            self.assertTrue(any(r.col_name == 'Comment' and 'Kayakalp' in r.data_type for r in detail))
        finally:
            self.spark.sql(f'DROP TABLE IF EXISTS {table}')

    def test_default_dry_run_does_not_write(self):
        from pyspark.sql import functions as F
        df = self.transform([self.rows[0]])
        start = self.source.index('# Validate BEFORE any write.')
        end = self.source.index('if SOURCE_URL is None:',start)
        exec(self.source[start:end], dict(silver=df, bronze=df, F=F, spark=self.spark, WRITE_OUTPUT=False,
                                         SILVER='should_never_be_written'))
        self.assertFalse(self.spark.catalog.tableExists('should_never_be_written'))


if __name__ == '__main__':
    unittest.main()
