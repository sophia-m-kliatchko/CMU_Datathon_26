"""Synthetic fixtures only: these tests do not establish real-world validity."""
from dataclasses import replace
import unittest

from evidence_confidence import (MatchStatus, Tier, build_facility_service_rows,
    join_geographic_candidates, evidence_tier, Scope)
from test_evidence_tiers import certificate, indirect, negative, TODAY, FID

SERVICE = 'emergency_c_section'


def pending(e):
    return replace(e, match=replace(e.match, status=MatchStatus.PENDING))


def rows(records=(), pairs=None):
    return build_facility_service_rows(records, as_of=TODAY, facility_services=pairs)


def geo(fid=FID, **kwargs):
    return dict(facility_id=fid, distance_km=5.0, geo_confidence='approximate', **kwargs)


def join(candidates, records=(), **kwargs):
    return join_geographic_candidates(candidates, records, service=SERVICE, as_of=TODAY, **kwargs)


class IntegrationTests(unittest.TestCase):
    def test_rejected_only_u_diagnostic(self):
        e=certificate();e=replace(e,match=replace(e.match,status=MatchStatus.REJECTED))
        r=rows([e])[0]
        self.assertEqual(r['effective_tier'],'U')
        self.assertEqual(r['supporting_record_count'],0)
        self.assertTrue(r['flags']['rejected_candidate_match'])
        self.assertFalse(r['identity_review_required'])
        self.assertIsNone(r['pending_stronger_tier'])
        self.assertEqual(len(r['evidence_records']),1)

    def test_ambiguous_only_r(self):
        r=rows([pending(certificate())])[0]
        self.assertEqual(r['effective_tier'],'R')
        self.assertTrue(r['identity_review_required'])

    def test_t3_pending_t1_preserves_identity_citations(self):
        e=pending(certificate('potential'))
        r=rows([indirect('virtue_foundation',key='accepted'),e])[0]
        self.assertEqual((r['base_tier'],r['effective_tier']),('T3','T3'))
        self.assertEqual(r['pending_stronger_tier'],'T1')
        self.assertEqual(r['pending_source_families'],['laqshya'])
        self.assertTrue(r['identity_review_required'])
        record=next(x for x in r['evidence_records'] if x['evidence_id']=='potential')
        self.assertEqual(record['citations'][0]['locator'],e.citations[0].locator)
        self.assertEqual(record['match']['status'],'pending')
        self.assertEqual(record['valid_until'],'2028-03-09')

    def test_t1_pending_t3_no_promotion(self):
        r=rows([certificate(),pending(indirect('ncg',key='potential'))])[0]
        self.assertEqual(r['effective_tier'],'T1')
        self.assertIsNone(r['pending_stronger_tier'])
        self.assertEqual(r['pending_source_families'],['ncg'])
        self.assertTrue(r['identity_review_required'])

    def test_rejected_extra_does_not_override_accepted(self):
        e=certificate('bad');e=replace(e,match=replace(e.match,status=MatchStatus.REJECTED))
        r=rows([certificate(),e])[0]
        self.assertEqual((r['effective_tier'],r['review_status']),('T1','clear'))
        self.assertEqual(r['supporting_record_count'],1)

    def test_stable_source_record_deduplication(self):
        e=replace(certificate('one'),source_record_id='certificate-1')
        r=rows([replace(e,evidence_id='two'),e,e])[0]
        self.assertEqual(r['supporting_record_count'],1)
        self.assertEqual(len(r['evidence_records']),1)
        self.assertEqual(evidence_tier(FID,SERVICE,[e,replace(e,evidence_id='two')],TODAY).supporting_record_count,1)

    def test_conflicting_source_record_versions_fail(self):
        e=replace(certificate(),source_record_id='certificate-1')
        with self.assertRaisesRegex(ValueError,'conflicting versions'):
            rows([e,replace(e,evidence_id='changed',valid_until=TODAY)])

    def test_payload_duplicates_without_stable_id(self):
        e=certificate()
        r=rows([e,replace(e,evidence_id='alias')])[0]
        self.assertEqual(r['supporting_record_count'],1)
        self.assertEqual(len(r['evidence_records']),1)

    def test_one_family_is_not_independent_corroboration(self):
        r=rows([certificate(),certificate('different',statement='Another synthetic source record')])[0]
        self.assertEqual(r['supporting_record_count'],2)
        self.assertEqual(r['supporting_source_count'],1)

    def test_contradiction_preserved(self):
        r=rows([certificate(),negative()])[0]
        self.assertEqual(r['effective_tier'],'X')
        self.assertEqual(len(r['evidence_records']),2)
        self.assertTrue(any(d['credible_contradiction'] for d in r['decisions']))

    def test_deterministic_aggregation(self):
        a,b=certificate(),indirect(key='second')
        self.assertEqual(rows([a,b]),rows(iter([b,a])))
        self.assertEqual(len(rows([a,b])),1)

    def test_explicit_empty_request_is_u(self):
        r=rows(pairs=[(FID,SERVICE)])[0]
        self.assertEqual((r['facility_id'],r['service'],r['effective_tier']),(FID,SERVICE,'U'))

    def test_missing_id_and_service_rejected(self):
        for pair in [('',SERVICE),(FID,''),(None,SERVICE)]:
            with self.assertRaises(ValueError): rows(pairs=[pair])

    def test_nonservice_never_invents_service_pair(self):
        e=replace(certificate(),source_id='kayakalp',scope=Scope.CLEANLINESS,service=None)
        self.assertEqual(rows([e]),[])
        r=rows([e],[(FID,SERVICE)])[0]
        self.assertEqual(r['effective_tier'],'U')
        self.assertEqual(r['cleanliness_evidence_ids'],[e.evidence_id])
        self.assertEqual(len(r['evidence_records']),1)

    def test_left_join_preserves_missing(self):
        result=join([geo(),geo('synthetic-no-evidence')],rows([certificate()]))
        self.assertEqual(len(result),2)
        self.assertEqual([r['service_evidence']['effective_tier'] for r in result],['T1','U'])
        self.assertEqual(result[1]['service_evidence']['facility_id'],'synthetic-no-evidence')

    def test_service_filter(self):
        r=rows([replace(certificate(),service='another_service')])
        self.assertEqual(join([geo()],r)[0]['service_evidence']['effective_tier'],'U')

    def test_as_of_filter(self):
        r=rows([certificate()]);r[0]['as_of']='2025-01-01'
        self.assertEqual(join([geo()],r)[0]['service_evidence']['effective_tier'],'U')

    def test_geo_confidence_and_uncertainty_separate(self):
        g=geo(location_uncertainty_km=2,distance_min_km=3,distance_max_km=7)
        r=join([g],rows([certificate()]))[0]
        for key,value in g.items(): self.assertEqual(r[key],value)
        self.assertEqual(r['service_evidence']['effective_tier'],'T1')
        self.assertEqual(r['distance_interpretation'],'reported_estimate_with_bounds')
        self.assertNotIn('geo_confidence',r['service_evidence'])

    def test_no_precision_claim_without_metadata(self):
        self.assertEqual(join([geo()])[0]['distance_interpretation'],'reported_distance_precision_unspecified')

    def test_duplicate_geo_ids_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate geographic'): join([geo(),geo()])

    def test_duplicate_evidence_slice_rejected(self):
        r=rows([certificate()])
        with self.assertRaisesRegex(ValueError,'duplicate facility'): join([geo()],r+r)

    def test_invalid_distances_rejected(self):
        for value in [-1,float('nan'),float('inf'),True]:
            g=geo();g['distance_km']=value
            with self.assertRaises(ValueError): join([g])

    def test_invalid_bounds_rejected(self):
        with self.assertRaises(ValueError): join([geo(distance_min_km=7,distance_max_km=3)])
        with self.assertRaises(ValueError): join([geo(distance_min_km=6)])

    def test_missing_geo_contract_fields_rejected(self):
        with self.assertRaises(ValueError): join([{'facility_id':FID}])

    def test_unknown_distance_preserved(self):
        g=geo();g['distance_km']=None;g['geo_confidence']=None
        self.assertIsNone(join([g])[0]['distance_km'])

    def test_unsupported_framework_not_silently_mixed(self):
        with self.assertRaises(ValueError): join([geo()],framework_version='unagreed/v2')
