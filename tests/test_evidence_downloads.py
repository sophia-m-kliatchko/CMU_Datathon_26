"""Synthetic CSV dialect/audit fixtures; not real-data validation claims."""
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evidence_confidence.silver import read_local_export
from evidence_confidence.downloaded_silver_audit import audit_downloads

NOTEBOOK=Path(__file__).resolve().parents[1]/'notebooks/05_registries_bronze_to_silver.py'


class DownloadAuditTests(unittest.TestCase):
    def test_explicit_backslash_dialect_preserves_json_arrays_and_input(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv'
            with path.open('w',newline='') as handle:
                writer=csv.writer(handle,escapechar='\\',doublequote=False)
                writer.writerow(['id','dq_flags']);writer.writerow(['SYNTHETIC',json.dumps(['FLAG','OTHER'])])
            before=path.read_bytes()
            rows=read_local_export(path,csv_escapechar='\\')
            self.assertEqual(rows[0]['dq_flags'],['FLAG','OTHER'])
            self.assertEqual(path.read_bytes(),before)

    def test_wrong_record_width_fails_instead_of_discarding(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv';path.write_text('id,value\na,b,c\n')
            with self.assertRaisesRegex(ValueError,'record width'):read_local_export(path)

    def test_strict_quotes_fail_instead_of_partial_import(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'input.csv';path.write_text('id,value\na,"unterminated\n')
            with self.assertRaises(csv.Error):read_local_export(path)

    def test_streaming_audit_reports_duplicates_without_changing_records(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'silver_dq_summary.csv'
            path.write_text('flag,n_facilities,pct_of_facilities\nSYNTHETIC,1,1\nSYNTHETIC,2,2\n')
            report=audit_downloads(directory,as_of=date(2026,11,22),notebook_path=NOTEBOOK,inventory_probe=False)
            self.assertEqual(report['inventory'][0]['records'],2)
            self.assertTrue(any(f['code']=='DUPLICATE_KEY' and f['count']==1 for f in report['findings']))
            self.assertTrue(report['input_hashes_unchanged'])
            self.assertEqual(report['evidence_confidence']['status'],'BLOCKED')

    def test_unexpected_format_reported_not_silently_skipped(self):
        with TemporaryDirectory() as directory:
            (Path(directory)/'partial.zip').write_bytes(b'not a real export')
            report=audit_downloads(directory,as_of=date(2026,11,22),notebook_path=NOTEBOOK,inventory_probe=False)
            self.assertTrue(any(f['code']=='UNEXPECTED_FORMAT' for f in report['findings']))
            self.assertEqual(report['publication']['status'],'BLOCKED')

    def test_empty_download_cannot_pass_real_validation(self):
        with TemporaryDirectory() as directory:
            report=audit_downloads(directory,as_of=date(2026,11,22),notebook_path=NOTEBOOK,inventory_probe=False)
            self.assertEqual(report['evidence_confidence']['status'],'BLOCKED')
            self.assertTrue(report['missing_expected_outputs'])
