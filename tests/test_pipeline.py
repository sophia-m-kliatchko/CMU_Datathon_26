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

    def test_future_or_planned_claims_are_skipped(self):
        for text in ('plans to introduce an in-house dialysis unit', 'dialysis room (under construction)',
                     'plans to convert into a 17-floor multispeciality hospital including dialysis',
                     'a dialysis unit will be opened next year', 'dialysis centre being set up'):
            self.assertEqual(match_claim(text, 'dialysis'), (False, 'negation_or_qualifier_skipped'), text)
        # Clinical use of "planning" and present-tense claims still match.
        for text in ('hemodialysis and peritoneal dialysis planning initiation and maintenance',
                     'provides dialysis treatment'):
            self.assertTrue(match_claim(text, 'dialysis')[0], text)

    def test_claims_are_attributed_only_to_their_own_facility(self):
        rows = [claim('Dialysis', fid='syn-a'), claim('Nephrology', fid='syn-b')]
        records, _ = claim_evidence(rows, 'dialysis', facility_ids=['syn-a', 'syn-b'])
        self.assertEqual({e.match.facility_id for e in records}, {'syn-a'})
        self.assertEqual(claim_evidence(rows, 'dialysis', facility_ids=['syn-b'])[0], ())

    def test_attribution_guard_cases(self):
        from evidence_confidence.service_claims import attribution
        cases = [('Cesarean delivery (C-section) services offered at LYF Hospital, Indirapuram', 'LYF Hospital', 'own'),
                 ('Cesarean Section performed at Max Super Speciality Hospital, Noida', 'Maa Hospital', 'other'),
                 ('Provides dialysis treatment at Smt. B. C. J. General Hospital - Asha Parekh Hospital', 'J J Eye Hospital', 'other'),
                 # Network/drug-bank membership is affiliation, not another site (false positive on real data).
                 ("Dialysis centre listed within Jivan Jyot Drug Bank's Mumbai network.", 'J J Eye Hospital', 'own'),
                 ('Part of The Renal Project network of dialysis centers', 'Sunshine Hospital', 'own'),
                 ('Dialysis charges at this centre are Rs. 350 or less', 'KJ Somaiya Hospital and Research Centre', 'own'),
                 ("Provides dialysis treatment at K. J. Somaiya Hospital, Chunabhatti as part of JJDB's dialysis network",
                  'KJ Somaiya Hospital and Research Centre', 'own'),
                 ('Provides dialysis treatment at Nair Hospital, Mumbai Central', 'Wockhardt Hospital Nagpur', 'other'),
                 ('City Hospital is listed as a nearby hospital to Millat Dialysis Center', 'City Hospital', 'other'),
                 ('Dialysis at Apollo Hospital and at Fortis Hospital', 'Apollo Hospital', 'mixed'),
                 ('Dialysis unit at Dr. Ram Manohar Lohia Hospital', 'Dr. Ram Manohar Lohia Hospital', 'own'),
                 ('Dialysis available. Also ICU at the hospital', 'Triton Hospital', 'own'),
                 ('Dialysis department serves around 22 patients regularly', 'J J Eye Hospital', 'own')]
        for text, name, expected in cases:
            self.assertEqual(attribution(text, name), expected, (text, name))

    def test_other_facility_claims_excluded_and_record_flagged(self):
        rows = [claim('Dialysis at Asha Parekh Hospital', fid='syn-a', pos='0'),
                claim('Hemodialysis', fid='syn-a', pos='1'),
                claim('Dialysis at Apollo Hospital and at Fortis Hospital', fid='syn-b', pos='0'),
                claim('Dialysis', fid='syn-c', pos='0')]
        names = {'syn-a': 'Sunrise Clinic', 'syn-b': 'Apollo Hospital', 'syn-c': 'Triton Hospital'}
        records, report = claim_evidence(rows, 'dialysis', facility_names=names)
        by = {e.match.facility_id: e for e in records}
        self.assertEqual(set(by), {'syn-a', 'syn-c'})  # syn-b: only claim is mixed -> not credited
        self.assertIn('RECORD_ATTRIBUTION_UNRESOLVED', by['syn-a'].qualifiers)
        self.assertNotIn('RECORD_ATTRIBUTION_UNRESOLVED', by['syn-c'].qualifiers)
        self.assertEqual(set(report['attribution_excluded']), {'syn-a', 'syn-b'})
        self.assertEqual(report['reasons']['other_facility_attribution'], 2)
        t = evidence_tier('syn-a', 'dialysis', [by['syn-a']], date(2026, 11, 22))
        self.assertEqual(t.effective_tier.value, 'T3')
        self.assertTrue(t.flags.attribution_unresolved)

    def test_attribution_guard_skipped_without_names_for_old_callers(self):
        rows = [claim('Cesarean section at LYF Hospital, Indirapuram', fid='syn-l')]
        records, report = claim_evidence(rows, 'emergency_c_section')
        self.assertEqual(len(records), 1)
        self.assertEqual(report['attribution_check'], 'skipped_no_facility_names')
        records, report = claim_evidence(rows, 'emergency_c_section', facility_names={'syn-l': 'LYF Hospital'})
        self.assertEqual((len(records), report['attribution_check']), (1, 'applied'))

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

    def test_freshness_and_expiry_are_attributes(self):
        r = self.run_query(service='emergency_c_section', pincode='110001', max_results=50, max_alternatives=50)
        rows = r['recommendations'] + r['alternatives']
        for x in rows:
            self.assertEqual(set(x['evidence_freshness']), {'latest_evidence_date', 'earliest_valid_until',
                'expired_direct_evidence', 'undated_credited_records', 'self_report_page_updated_on', 'self_report_page_age_days'})
        t2 = [x for x in rows if x['evidence_tier'] == 'T2']
        self.assertTrue(t2 and all(x['evidence_freshness']['expired_direct_evidence'] for x in t2))
        self.assertTrue(any(x['evidence_freshness']['self_report_page_updated_on'] for x in rows if x['self_reported_claims']))

    def test_related_specialty_and_attribution_exposed(self):
        r = self.run_query(service='dialysis', pincode='400001', max_results=50, max_alternatives=50)
        rows = r['recommendations'] + r['alternatives']
        trained = [x for x in rows if x['related_specialty']]
        self.assertTrue(trained)
        for x in trained:  # training is described as expertise, never as current availability
            self.assertTrue(set(x['supporting_source_families']) & {'nmc', 'dnb'})
            self.assertTrue(any('not that this service is currently offered' in t for t in x['explanation']))
        self.assertTrue(any(x['attribution']['unresolved'] for x in rows))

    def test_expertise_only_t2_never_worded_as_availability(self):
        rows = []
        for pin in ('110001', '400001', '600001'):
            for service in ('general_medicine', 'orthopaedics', 'eye_care', 'cardiac_care', 'cancer_care'):
                r = self.run_query(service=service, pincode=pin, max_results=50, max_alternatives=50)
                rows += [x for x in r['recommendations'] + r['alternatives'] if x['evidence_tier'] == 'T2']
        expertise = [x for x in rows if x['evidence_nature'] == ['expertise']]
        self.assertTrue(expertise)
        for x in expertise:
            self.assertEqual(x['tier_label'], 'Specialist department (expertise)')
            self.assertTrue(any('not confirmation that this service is currently offered' in t for t in x['explanation']))
        for x in rows:
            self.assertTrue(x['t2_basis'])

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
