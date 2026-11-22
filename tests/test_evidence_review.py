"""Read-only local snapshot tests: real evidence, explicitly controlled geography."""
from datetime import date
from pathlib import Path
import unittest

from evidence_confidence.evidence_review_audit import (
    _reason_codes, load_review_state, audit_rules, audit_r_assessments,
    warning_impacts, validate_controlled_integration,
)
from evidence_confidence.integration import join_geographic_candidates

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / 'CMU_Datathon_26/silver_dataset'


class ReviewReasonTests(unittest.TestCase):
    def test_overlapping_reasons_are_preserved(self):
        self.assertEqual(_reason_codes('score below link threshold; near-tie; more than 10 km apart'),
                         {'below_link_threshold', 'competing_candidates', 'distance_review'})

    def test_missing_reason_does_not_invent_ambiguity(self):
        self.assertEqual(_reason_codes(None), set())


@unittest.skipUnless((DATA / 'facility_registry_links_silver.csv').is_file(),
                     'Downloaded real Silver snapshot unavailable')
class DownloadedReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = load_review_state(DATA, as_of=date(2026, 11, 22), repository_root=ROOT)

    def test_snapshot_r_rows_have_actual_pending_links(self):
        report, ledger = audit_r_assessments(self.state)
        self.assertEqual(report['count'], 1771)
        self.assertEqual(sum(report['exclusive_reason_buckets'].values()), 1771)
        self.assertTrue(report['all_R_links_explicitly_need_review'])
        self.assertEqual(report['rejected_only_R'], 0)
        self.assertEqual(report['missing_identity_links_in_R'], 0)
        self.assertEqual(len({(r['facility_id'], r['service']) for r in ledger}), 1771)

    def test_real_tier_premises(self):
        self.assertEqual(audit_rules(self.state)['violations'], [])

    def test_all_eight_pending_t1_rows_remain_t3(self):
        rows = [r for r in self.state['rows'] if r['pending_stronger_tier'] == 'T1'
                and r['base_tier'] == 'T3']
        self.assertEqual(len(rows), 8)
        for row in rows:
            self.assertEqual(row['effective_tier'], 'T3')
            self.assertTrue(row['citations'])
            self.assertTrue(row['identity_review_required'])

    def test_warning_snapshot_counts(self):
        report = warning_impacts(self.state)
        self.assertEqual(report['missing_directory_pin']['facilities'], 205)
        self.assertEqual(report['state_pin_disagreement']['facilities'], 69)
        self.assertEqual(report['nqas_district_reference']['records'], 234)
        self.assertEqual(report['nqas_district_reference']['current_service_assessment_impact'], 0)

    def test_real_evidence_controlled_geography_full_path(self):
        result = validate_controlled_integration(self.state)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['counts']['joined_rows'], 40)
        self.assertEqual(result['response_count'], 40)
        self.assertEqual(result['t1_initial_nearest_position'], 40)
        self.assertTrue(result['deterministic'])
        self.assertEqual(result['confirmed_urgent_recommendations'], 0)

    def test_pending_metadata_survives_controlled_path(self):
        result = validate_controlled_integration(self.state, 'emergency',
                        '320add3e-1571-45a1-b56f-27736f35c4aa')
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['included_assessment']['effective_tier'], 'T3')
        self.assertEqual(result['included_assessment']['pending_stronger_tier'], 'T1')

    def test_real_duplicate_evidence_grain_fails(self):
        row = self.state['rows'][0]
        candidate = {'facility_id': row['facility_id'], 'distance_km': None, 'geo_confidence': None}
        with self.assertRaises(ValueError):
            join_geographic_candidates([candidate], [row, row], service=row['service'],
                                       as_of=self.state['as_of'])
