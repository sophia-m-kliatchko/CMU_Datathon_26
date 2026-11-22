"""Pipeline tests. Claim-mapping tests are synthetic; RealSilver tests read the local
downloaded Silver bundle (skipped when absent) and never write to it."""
import json
import os
from pathlib import Path
import unittest

from evidence_confidence.service_claims import claim_evidence, match_claim
from evidence_confidence.tiers import evidence_tier
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
SILVER = Path(os.environ.get('EC_SILVER_DIR', ROOT.parent / 'CMU_Datathon_26' / 'silver_dataset'))
NOTEBOOK = os.environ.get('EC_GEO_NOTEBOOK', str(Path.home() / 'Downloads/07_pin_nearby_facilities.py'))
AS_OF = '2026-11-22'


def claim(text, field='procedure', fid='syn-f', pos='0'):
    return dict(facility_id=fid, claim_field=field, claim_position=pos, claim_text=text, claim_norm=text.lower())


class ClaimMappingTests(unittest.TestCase):
    def test_exact_terms_only(self):
        self.assertTrue(match_claim('hemodialysis unit', 'dialysis')[0])
        self.assertTrue(match_claim('caesarean section', 'emergency_c_section')[0])
        for text, service in [('nephrology', 'dialysis'), ('obstetrics and gynecology', 'emergency_c_section'),
                              ('maternity care', 'emergency_c_section')]:
            self.assertFalse(match_claim(text, service)[0], text)

    def test_negations_are_skipped_not_negative(self):
        for text in ('no dialysis', 'upcoming dialysis wing', 'dialysis department is to be shut down',
                     'caesarean section facility not available on site referrals to lnjp'):
            self.assertEqual(match_claim(text, 'dialysis' if 'dial' in text else 'emergency_c_section')[1],
                             'negation_or_qualifier_skipped')
        records, report = claim_evidence([claim('no dialysis')], 'dialysis')
        self.assertEqual(records, ())
        self.assertEqual(report['reasons'], {'negation_or_qualifier_skipped': 1})

    def test_self_report_caps_at_t3_and_is_labelled(self):
        records, _ = claim_evidence([claim('Dialysis'), claim('Dialysis machines', field='equipment', pos='1')], 'dialysis')
        t = evidence_tier('syn-f', 'dialysis', records, date(2026, 11, 22))
        self.assertEqual(t.base_tier.value, 'T3')
        self.assertEqual(t.supporting_source_families, ('virtue_foundation',))
        self.assertTrue(all(e.verification.value == 'self_reported' for e in records))

    def test_duplicate_claims_and_unmapped_services(self):
        records, report = claim_evidence([claim('Dialysis'), claim('Dialysis')], 'dialysis')
        self.assertEqual(len(records), 1)
        self.assertEqual(report['reasons']['duplicate_claim'], 1)
        self.assertEqual(claim_evidence([claim('ICU')], 'icu')[1]['reason'], 'service_not_in_claim_mapping')

    def test_c_section_claims_flag_missing_emergency_wording(self):
        records, _ = claim_evidence([claim('Caesarean section')], 'emergency_c_section')
        self.assertIn('CLAIM_DOES_NOT_STATE_EMERGENCY', records[0].qualifiers)


class EntrypointArgumentTests(unittest.TestCase):
    def test_requires_bundle_or_directory(self):
        from evidence_confidence.pipeline import recommend_facilities
        saved = os.environ.pop('EVIDENCE_SILVER_DIR', None)
        try:
            with self.assertRaises(ValueError):
                recommend_facilities('dialysis', '110001', 50)
        finally:
            if saved is not None:
                os.environ['EVIDENCE_SILVER_DIR'] = saved


@unittest.skipUnless((SILVER / 'facilities_silver.csv').is_file() and Path(NOTEBOOK).is_file(),
                     'downloaded Silver bundle or 07 notebook not available')
class RealSilverPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from evidence_confidence.pipeline import load_bundle, recommend
        cls.bundle, cls.recommend = load_bundle(SILVER, geography_notebook=NOTEBOOK), staticmethod(recommend)

    def run_query(self, **kw):
        return self.recommend(self.bundle, {'radius_km': 50, 'max_results': 5, 'as_of': AS_OF, **kw})

    def test_retention_lists_and_determinism(self):
        r = self.run_query(service='dialysis', pincode='400001')
        self.assertEqual(r['ranked_candidates'], r['geographic_candidates'])
        self.assertEqual((r['returned'], r['returned_alternatives']), (5, 5))
        ids = [x['facility_id'] for x in r['recommendations'] + r['alternatives']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([x['rank'] for x in r['recommendations'] + r['alternatives']], list(range(1, 11)))
        self.assertEqual(json.loads(json.dumps(r, allow_nan=False)), r)
        self.assertEqual(json.dumps(r, sort_keys=True), json.dumps(self.run_query(service='dialysis', pincode='400001'), sort_keys=True))
        for x in r['recommendations'] + r['alternatives']:
            for key in ('evidence_tier', 'distance_km', 'location_uncertainty_km', 'location_basis', 'source_urls', 'explanation'):
                self.assertIn(key, x)

    def test_topk_after_full_enrichment(self):
        r = self.run_query(service='dialysis', pincode='400001', include_self_reported_claims=False)
        top = r['recommendations'][0]
        self.assertEqual(top['evidence_tier'], 'T1')
        self.assertGreater(top['distance_only_rank'], 25)  # would be lost by a nearest-25 cut

    def test_missing_evidence_is_u_and_retained(self):
        r = self.run_query(service='emergency_c_section', pincode='600001')
        self.assertGreater(r['tier_distribution'].get('U', 0), 0)
        self.assertEqual(sum(r['tier_distribution'].values()), r['geographic_candidates'])

    def test_uncertainty_survives(self):
        r = self.run_query(service='emergency_c_section', pincode='110001', max_results=50, max_alternatives=50)
        self.assertGreater(r['coverage']['centre_outside_radius'], 0)
        rows = r['recommendations'] + r['alternatives']
        approx = [x for x in rows if x['location_basis'] == 'pin_centroid']
        self.assertTrue(approx and all(x['location_uncertainty_km'] is not None for x in approx))

    def test_invalid_and_unknown_inputs(self):
        self.assertEqual(self.run_query(service='dialysis', pincode='000001')['status'], 'invalid_location')
        self.assertEqual(self.run_query(service='dialysis', pincode='999999')['status'], 'invalid_location')
        self.assertEqual(self.run_query(service='not_a_service', pincode='110001')['status'], 'unknown_service')

    def test_valid_pin_with_zero_candidates(self):
        ready = [r for r in self.bundle.ready if r['geo_latitude'] is not None]
        from evidence_confidence.geographic_candidates import _Column
        h = self.bundle.producer.haversine
        for pin, c in sorted(self.bundle.centroids.items()):
            if c['latitude'] is None:
                continue
            near = min(h(_Column(c['latitude']), _Column(c['longitude']), _Column(r['geo_latitude']),
                         _Column(r['geo_longitude'])).value - (r['location_uncertainty_km'] or 0) for r in ready)
            if near > 5:
                r = self.recommend(self.bundle, dict(service='dialysis', pincode=pin, radius_km=1, as_of=AS_OF))
                self.assertEqual((r['status'], r['recommendations']), ('no_candidates', []))
                return
        self.skipTest('no isolated PIN found')

    def test_unmapped_service_has_no_claim_evidence(self):
        r = self.run_query(service='nicu', pincode='110001')
        self.assertEqual(r['claim_mapping'].get('reason'), 'service_not_in_claim_mapping')

    def test_recommend_facilities_entrypoint(self):
        from evidence_confidence.pipeline import recommend_facilities
        r = recommend_facilities('dialysis', '400001', 50, bundle=self.bundle, as_of=AS_OF)
        self.assertEqual(json.dumps(r, sort_keys=True),
                         json.dumps(self.run_query(service='dialysis', pincode='400001', max_alternatives=5), sort_keys=True))
        with self.assertRaises(ValueError):
            recommend_facilities('dialysis', '400001', 50, max_results=0, bundle=self.bundle)

    def test_existing_demo_entrypoint_unchanged(self):
        # The website vendors build_recommendation_response + adapt_registry_tables at 2368382.
        import inspect
        from evidence_confidence import build_recommendation_response
        from evidence_confidence.recommendation import CONTRACT_VERSION
        self.assertEqual(CONTRACT_VERSION, 'recommendation-response/1')
        self.assertEqual(list(inspect.signature(build_recommendation_response).parameters)[:3],
                         ['request', 'evidence_records', 'geographic_candidates'])


if __name__ == '__main__':
    unittest.main()
