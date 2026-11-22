"""Synthetic end-to-end and reusable validation regression tests; no external IO."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
import unittest

from evidence_confidence.integration import build_facility_service_rows, join_geographic_candidates
from evidence_confidence.recommendation import (assessment_from_row, build_recommendation_response,
                                                normalize_request)
from evidence_confidence.synthetic_smoke import (AS_OF, SERVICE, adapt_synthetic_evidence,
                                                  run_smoke, synthetic_fixture)
from evidence_confidence.validation import validate_integration


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=synthetic_fixture()
        self.geo=self.fixture['geographic_candidates']
        self.records=adapt_synthetic_evidence(self.fixture)
        self.rows=build_facility_service_rows(self.records,as_of=AS_OF,
            facility_services=[(g['facility_id'],SERVICE) for g in self.geo])
        self.joined=join_geographic_candidates(self.geo,self.rows,service=SERVICE,as_of=AS_OF)
        self.response=build_recommendation_response(self.fixture['request'],self.records,self.geo)
        self.by_id={r['facility_id']:r for r in self.response['recommendations']}

    def validate(self,**overrides):
        args=dict(canonical_facility_ids=[g['facility_id'] for g in self.geo],canonical_services=[SERVICE],
            evidence_records=self.records,evidence_rows=self.rows,geographic_candidates=self.geo,
            joined_rows=self.joined,as_of=AS_OF,response=self.response)
        args.update(overrides)
        return validate_integration(**args)

    def codes(self,result):
        return {e['code'] for e in result['errors']}

    def test_smoke_32_candidates_survive_every_stage(self):
        self.assertEqual((len(self.geo),len(self.rows),len(self.joined),len(self.by_id)),(32,32,32,32))
        self.assertEqual(set(self.by_id),{g['facility_id'] for g in self.geo})
        self.assertEqual(run_smoke()['validation']['errors'],[])

    def test_far_t1_not_lost_to_top25_or_service_substring(self):
        self.assertNotIn('synthetic-030',[g['facility_id'] for g in self.geo[:25]])
        self.assertNotIn(SERVICE,self.geo[30]['name'])
        self.assertEqual(self.by_id['synthetic-030']['service_evidence']['effective_tier'],'T1')
        ordered=list(self.by_id)
        self.assertLess(ordered.index('synthetic-030'),ordered.index('synthetic-003'))

    def test_tier_scenarios_through_response(self):
        expected={0:'T1',1:'T2',2:'T3',3:'U',4:'U',5:'R',6:'T3',7:'X',8:'T1',9:'T3'}
        for index,tier in expected.items():
            self.assertEqual(self.by_id[f'synthetic-{index:03}']['service_evidence']['effective_tier'],tier)

    def test_pending_metadata_survives_ranking_and_json(self):
        r=json.loads(json.dumps(self.response,allow_nan=False))
        row=next(x for x in r['recommendations'] if x['facility_id']=='synthetic-006')
        e=row['service_evidence']
        self.assertEqual(e['pending_stronger_tier'],'T1')
        self.assertEqual(e['pending_source_families'],['laqshya'])
        self.assertTrue(e['identity_review_required'])
        self.assertTrue(any(d['match_status']=='pending' and not d['credited'] for d in e['decisions']))

    def test_duplicate_record_not_independent_support(self):
        e=self.by_id['synthetic-008']['service_evidence']
        self.assertEqual((e['supporting_record_count'],e['supporting_source_count']),(1,1))
        self.assertEqual(len(e['evidence_records']),1)

    def test_duplicate_join_keys_fail(self):
        with self.assertRaisesRegex(ValueError,'duplicate facility'):
            join_geographic_candidates(self.geo,self.rows+[self.rows[0]],service=SERVICE,as_of=AS_OF)

    def test_deterministic_order_with_shuffled_inputs(self):
        other=build_recommendation_response(self.fixture['request'],reversed(self.records),reversed(self.geo))
        self.assertEqual(self.response,other)

    def test_citations_and_full_validity_preserved(self):
        original=next(e for e in self.records if e.match.facility_id=='synthetic-030')
        e=self.by_id['synthetic-030']['service_evidence']
        self.assertEqual(e['citations'][0]['quote'],original.citations[0].quote)
        self.assertEqual(self.by_id['synthetic-030']['source_urls'],[original.citations[0].locator])
        self.assertEqual(e['evidence_records'][0]['valid_until'],original.valid_until.isoformat())
        self.assertEqual(e['evidence_records'][0]['source_record_id'],original.source_record_id)
        self.assertEqual(assessment_from_row(e).to_dict(),{k:v for k,v in e.items() if k!='evidence_records'})

    def test_geographic_uncertainty_separate(self):
        r=self.by_id['synthetic-010']
        for key in ('location_uncertainty_km','distance_min_km','distance_max_km','location_basis','geo_confidence'):
            self.assertEqual(r[key],self.geo[10][key])
        self.assertEqual(r['service_evidence']['effective_tier'],'U')
        self.assertNotIn('geo_confidence',r['service_evidence'])

    def test_no_capability_claim_from_t1(self):
        request={**self.fixture['request'],'mode':'urgent'}
        r=build_recommendation_response(request,self.records,self.geo)
        self.assertEqual(r['recommendations'],[])
        self.assertEqual(len(r['alternatives']),32)
        self.assertTrue(r['requires_review'])
        self.assertTrue(all(x['capability_eligible'] is None for x in r['alternatives']))

    def test_urgent_explicit_capability_still_requires_t1_basis_distance(self):
        geo=deepcopy(self.geo)
        for index in (0,2,30):
            geo[index].update(capability_eligible=True,capability_basis='SYNTHETIC reviewed operational assessment')
        geo[30]['distance_km']=None
        r=build_recommendation_response({**self.fixture['request'],'mode':'urgent'},self.records,geo)
        self.assertEqual([x['facility_id'] for x in r['recommendations']],['synthetic-000'])
        self.assertEqual(len(r['alternatives']),31)

    def test_request_optional_date_resolved_explicitly(self):
        request={k:v for k,v in self.fixture['request'].items() if k!='as_of'}
        self.assertEqual(normalize_request(request,today=AS_OF)['as_of'],AS_OF.isoformat())
        for patch in ({'pin':110001},{'pin':'000001'},{'radius_km':-1},{'radius_km':True},
                      {'mode':'emergency'},{'unknown':True},{'as_of':'invalid'}):
            with self.assertRaises(ValueError): normalize_request({**request,**patch})

    def test_missing_display_fields_stay_null(self):
        geo=deepcopy(self.geo);geo[3].pop('name');geo[3].pop('location_basis')
        r=build_recommendation_response(self.fixture['request'],self.records,geo)
        row=next(x for x in r['recommendations'] if x['facility_id']=='synthetic-003')
        self.assertIsNone(row['name']);self.assertIsNone(row['location_basis'])
        self.assertTrue(any('name is missing' in w for w in row['warnings']))

    def test_unknown_not_unavailable(self):
        r=self.by_id['synthetic-003']
        self.assertNotIn('service_available',r);self.assertNotIn('service_unavailable',r)
        self.assertTrue(any('unknown, not unavailable' in w for w in self.response['warnings']))

    def test_response_contract_field_sets_and_plain_json(self):
        self.assertEqual(set(self.response), {'contract_version','framework_version','request','candidate_count',
            'recommendations','alternatives','requires_review','status','provisional','ranking_explanation',
            'ranking_config','warnings'})
        expected={'facility_id','name','service','distance_km','location_uncertainty_km','distance_min_km',
            'distance_max_km','location_basis','geo_confidence','distance_interpretation','service_evidence',
            'source_urls','warnings','capability_eligible','capability_basis','ranking'}
        self.assertTrue(all(set(r)==expected for r in self.response['recommendations']))
        self.assertEqual(json.loads(json.dumps(self.response,allow_nan=False)),self.response)

    def test_inputs_not_mutated(self):
        fixture=deepcopy(self.fixture)
        records=list(self.records)
        build_recommendation_response(self.fixture['request'],self.records,self.geo)
        self.assertEqual(fixture,self.fixture)
        self.assertEqual(records,self.records)

    def test_incomplete_direct_source_never_silently_verified(self):
        fixture=synthetic_fixture()
        row,link,decision=fixture['registry_entries'][0]
        row.update(valid_until=None,evidence_date=None,is_current=None)
        response=build_recommendation_response(fixture['request'],adapt_synthetic_evidence(fixture),
                                               fixture['geographic_candidates'])
        r=next(r for r in response['recommendations'] if r['facility_id']=='synthetic-000')
        self.assertEqual(r['service_evidence']['effective_tier'],'U')

    def test_custom_ranking_config_validation_replay(self):
        config={'distance_bands_km':[5,15,40]}
        response=build_recommendation_response(self.fixture['request'],self.records,self.geo,ranking_config=config)
        self.assertEqual(self.validate(response=response,ranking_config=config)['errors'],[])

    def test_invalid_name_type_rejected(self):
        geo=deepcopy(self.geo);geo[0]['name']=123
        with self.assertRaisesRegex(ValueError,'name must be'):
            build_recommendation_response(self.fixture['request'],self.records,geo)

    def test_validator_expected_warnings_not_hard_failures(self):
        result=self.validate()
        self.assertEqual(result['errors'],[])
        self.assertEqual(result['status'],'PASS_WITH_WARNINGS')
        self.assertEqual(result['tier_distribution'],{'R':1,'T1':3,'T2':1,'T3':3,'U':23,'X':1})
        self.assertEqual(result['unknown_joined_candidates'],23)
        self.assertIn('DUPLICATE_EVIDENCE_ID',{w['code'] for w in result['warnings']})

    def test_validator_canonical_id_and_service_compatibility(self):
        self.assertIn('EVIDENCE_FACILITY_ID',self.codes(self.validate(canonical_facility_ids=[])))
        self.assertIn('EVIDENCE_SERVICE',self.codes(self.validate(canonical_services=['unrelated_service'])))

    def test_validator_duplicate_output_grain(self):
        self.assertIn('DUPLICATE_EVIDENCE_GRAIN',self.codes(self.validate(evidence_rows=self.rows+[self.rows[0]])))

    def test_validator_missing_and_multiplied_candidates(self):
        for joined in (self.joined[:-1],self.joined+[self.joined[0]]):
            self.assertIn('JOIN_RETENTION_OR_FANOUT',self.codes(self.validate(joined_rows=joined)))

    def test_validator_identity_credit_and_tier_tampering(self):
        rows=deepcopy(self.rows)
        row=next(r for r in rows if r['facility_id']=='synthetic-004')
        row['decisions'][0]['credited']=True;row['effective_tier']='T1'
        codes=self.codes(self.validate(evidence_rows=rows))
        self.assertIn('IDENTITY_CREDIT',codes);self.assertIn('ASSESSMENT_MISMATCH',codes)

    def test_validator_citation_and_provenance_warnings(self):
        e=self.records[0]
        records=[replace(e,citations=(replace(e.citations[0],locator='table#record',quote=''),))]
        result=self.validate(evidence_records=records)
        codes={w['code'] for w in result['warnings']}
        self.assertIn('SOURCE_URL_MISSING',codes);self.assertIn('ROW_PROVENANCE_MISSING',codes)

    def test_validator_invalid_validity(self):
        e=replace(self.records[0],valid_from=date(2028,1,1),valid_until=date(2027,1,1))
        self.assertIn('INVALID_VALIDITY_INTERVAL',self.codes(self.validate(evidence_records=[e])))

    def test_validator_geographic_completeness_warnings(self):
        geo=deepcopy(self.geo);geo[10].pop('location_uncertainty_km');geo[10].pop('distance_min_km');geo[10].pop('distance_max_km')
        geo[10]['geo_confidence']=None
        result=self.validate(geographic_candidates=geo)
        codes={w['code'] for w in result['warnings']}
        self.assertIn('CENTROID_UNCERTAINTY_MISSING',codes)
        self.assertIn('GEOGRAPHIC_CONFIDENCE_INCOMPLETE',codes)

    def test_validator_urgent_claim_tampering(self):
        response=deepcopy(self.response);response['request']['mode']='urgent'
        self.assertIn('UNSUPPORTED_URGENT_CAPABILITY',self.codes(self.validate(response=response)))

    def test_validator_conflicting_record_id(self):
        records=self.records+[replace(self.records[0],statement='SYNTHETIC conflicting version')]
        self.assertIn('CONFLICTING_SOURCE_RECORD',self.codes(self.validate(evidence_records=records)))

    def test_validator_response_candidate_loss(self):
        response=deepcopy(self.response);response['recommendations'].pop()
        self.assertIn('RESPONSE_RETENTION',self.codes(self.validate(response=response)))

    def test_validator_explicit_unavailability_claim(self):
        response=deepcopy(self.response);response['recommendations'][0]['service_unavailable']=True
        self.assertIn('UNSUPPORTED_AVAILABILITY_CLAIM',self.codes(self.validate(response=response)))


if __name__=='__main__': unittest.main()
