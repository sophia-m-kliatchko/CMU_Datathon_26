"""Offline semantic regression tests. No Spark, sockets, credentials or table writes."""
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import random
import unittest

from evidence_confidence import (Citation, DatePrecision, Directness, Evidence, FacilityMatch,
    LocationContext, MatchStatus, Polarity, Policy, Scope, SourceKind, Verification, assess)
from evidence_confidence.adapters import (from_facility_claim, from_kayakalp, from_nqas,
    from_registry_service, from_registry_site, location_context, registry_match)

AS_OF = date(2026, 11, 21)
FID = 'facility-demo-1'
CITATION = Citation('Synthetic fixture only', 'fixture://evidence/1', 'Synthetic documentary assertion.')


def fact(key='e1', **kwargs):
    defaults = dict(evidence_id=key, source_id='registry_a', source_kind=SourceKind.INDEPENDENT_CHECK,
        scope=Scope.SERVICE, statement='Synthetic direct documentary dialysis evidence.',
        match=FacilityMatch(FID, MatchStatus.ACCEPTED, .95, 'reviewed_identity', 'site:1'),
        service='dialysis', verification=Verification.INDEPENDENT, directness=Directness.DIRECT,
        observed_on=AS_OF - timedelta(days=30), citations=(CITATION,))
    defaults.update(kwargs)
    return Evidence(**defaults)


def result(evidence, **kwargs):
    return assess(FID, 'dialysis', evidence, as_of=AS_OF, **kwargs)


class ScoringTests(unittest.TestCase):
    def test_missing_means_unknown_not_absent(self):
        r = result([]).service_availability
        self.assertIsNone(r.score)
        self.assertEqual((r.category, r.status), ('unknown', 'unknown'))
        self.assertIn('Missing evidence is not proof of absence.', ' '.join(r.explanations))

    def test_current_independent_documentary_support(self):
        r = result([fact()]).service_availability
        self.assertEqual(r.status, 'independently_supported')
        self.assertEqual(r.category, 'high')
        self.assertEqual(r.independent_current_evidence_ids, ('e1',))
        self.assertIn('not confirmation of current operational availability', ' '.join(r.explanations))

    def test_self_report_is_never_independent(self):
        e = fact(source_kind=SourceKind.SELF_REPORT, verification=Verification.SELF_REPORTED)
        r = result([e]).service_availability
        self.assertEqual(r.status, 'self_reported')
        self.assertLessEqual(r.score, 55)
        self.assertFalse(r.independent_current_evidence_ids)

    def test_quality_cleanliness_and_identity_do_not_raise_service_score(self):
        base = fact()
        others = [fact(str(s), scope=s, service=None) for s in [Scope.QUALITY, Scope.CLEANLINESS, Scope.IDENTITY]]
        a, b = result([base]), result([base, *others])
        self.assertEqual(a.service_availability, b.service_availability)
        self.assertIsNotNone(b.quality_evidence.score)
        self.assertIsNone(result(others).service_availability.score)

    def test_negative_quality_is_not_service_counterevidence(self):
        poor=fact('quality-counter',scope=Scope.QUALITY,service=None,polarity=Polarity.CONTRADICTS)
        a,b=result([fact()]),result([fact(),poor])
        self.assertEqual(a.service_availability,b.service_availability)
        self.assertGreater(b.quality_evidence.counterevidence_strength,0)

    def test_retrieval_date_does_not_refresh_old_event(self):
        r = result([fact(observed_on=date(2021, 3, 31), retrieved_on=AS_OF)]).service_availability
        self.assertEqual(r.status, 'historical_only')
        self.assertLessEqual(r.score, 40)
        self.assertFalse(r.independent_current_evidence_ids)

    def test_unknown_date_cannot_verify(self):
        r = result([fact(observed_on=None, retrieved_on=AS_OF)]).service_availability
        self.assertLessEqual(r.score, 45)
        self.assertEqual(r.status, 'indirect_or_unverified')
        self.assertFalse(r.independent_current_evidence_ids)

    def test_expired_certificate_is_historical_support_not_negative(self):
        r = result([fact(valid_until=AS_OF-timedelta(days=1))]).service_availability
        self.assertEqual(r.status, 'historical_only')
        self.assertGreater(r.score, 0)
        self.assertEqual(r.counterevidence_strength, 0)

    def test_valid_until_inclusive(self):
        self.assertEqual(result([fact(valid_until=AS_OF)]).service_availability.status, 'independently_supported')

    def test_future_and_inverted_dates_not_credited(self):
        for e in [fact(observed_on=AS_OF+timedelta(days=1)), fact(valid_from=AS_OF+timedelta(days=1)),
                  fact(valid_from=AS_OF, valid_until=AS_OF-timedelta(days=1)), fact(retrieved_on=AS_OF+timedelta(days=1))]:
            with self.subTest(e=e):
                r = result([e]).service_availability
                self.assertIsNone(r.score)
                self.assertFalse(r.independent_current_evidence_ids)

    def test_pending_rejected_and_missing_matches(self):
        for status in [MatchStatus.PENDING, MatchStatus.REJECTED, MatchStatus.UNKNOWN]:
            e = fact(match=replace(fact().match, status=status))
            r = result([e]).service_availability
            self.assertFalse(r.independent_current_evidence_ids)
            self.assertTrue(r.score is None or r.score <= 25)
        self.assertIsNone(result([fact(match=replace(fact().match, confidence=None))]).service_availability.score)

    def test_identity_flags_block_verification_even_if_marked_accepted(self):
        for flag in ['MATCH_AMBIGUOUS', 'DUP_ROWS_STATE_CONFLICT', 'MAY_BE_GROUP_OR_HEAD_OFFICE']:
            r = result([fact(match=replace(fact().match, flags=(flag,)))]).service_availability
            self.assertEqual(r.status, 'needs_review')
            self.assertLessEqual(r.score, 25)
            self.assertFalse(r.independent_current_evidence_ids)

    def test_stronger_match_increases_strength(self):
        high = result([fact()]).service_availability.score
        low = result([fact(match=replace(fact().match, confidence=.3))]).service_availability.score
        self.assertGreater(high, low)

    def test_missing_citations_cannot_verify(self):
        r = result([fact(citations=())]).service_availability
        self.assertLessEqual(r.score, 25)
        self.assertFalse(r.independent_current_evidence_ids)

    def test_indirect_and_designation_flags_cannot_verify(self):
        for e in [fact(directness=Directness.INDIRECT), fact(verification=Verification.INFERRED),
                  fact(qualifiers=('SANCTIONED_NOT_CONFIRMED_FUNCTIONAL',)), fact(date_precision=DatePrecision.YEAR)]:
            r = result([e]).service_availability
            self.assertFalse(r.independent_current_evidence_ids)
            self.assertNotEqual(r.category, 'high')

    def test_material_conflict_is_capped_and_explained(self):
        positive = fact('yes')
        negative = fact('no', source_id='registry_b', polarity=Polarity.CONTRADICTS)
        r = result([positive, negative]).service_availability
        self.assertEqual(r.status, 'conflicting')
        self.assertGreater(r.contradiction_reduction,0)
        self.assertLess(r.score, result([positive]).service_availability.score)
        self.assertLessEqual(r.score, 35)
        self.assertFalse(r.independent_current_evidence_ids)
        self.assertEqual(set(r.evidence_ids), {'yes', 'no'})

    def test_same_lineage_conflicts_are_not_deduplicated_away(self):
        r = result([fact('yes'), fact('no', polarity=Polarity.CONTRADICTS)]).service_availability
        self.assertEqual(r.status, 'conflicting')

    def test_counterevidence_only_is_not_an_absence_probability(self):
        r = result([fact(polarity=Polarity.CONTRADICTS)]).service_availability
        self.assertIsNone(r.score)
        self.assertEqual(r.status, 'counterevidence_only')
        self.assertGreater(r.counterevidence_strength, 0)

    def test_unknown_assertion_is_preserved_not_scored(self):
        r = result([fact(polarity=Polarity.UNKNOWN)]).service_availability
        self.assertIsNone(r.score)
        self.assertEqual(r.evidence_ids, ('e1',))
        self.assertEqual(r.citations, (CITATION,))

    def test_same_source_repetitions_do_not_inflate(self):
        one = result([fact()]).service_availability
        many = result([fact(str(i)) for i in range(100)]).service_availability
        self.assertEqual(one.score, many.score)
        self.assertEqual(many.independent_groups, 1)
        self.assertEqual(len(many.evidence_ids), 100)

    def test_shared_document_lineage_across_sources_does_not_inflate(self):
        a = fact('a', independence_group='one_original_document')
        b = fact('b', source_id='syndicated_copy', independence_group='one_original_document')
        self.assertEqual(result([a]).service_availability.score, result([a,b]).service_availability.score)

    def test_distinct_sources_add_bounded_agreement(self):
        a, b = fact('a'), fact('b', source_id='independent_registry')
        one, two = result([a]).service_availability, result([a,b]).service_availability
        self.assertGreater(two.score, one.score)
        self.assertLessEqual(two.score, 100)
        self.assertEqual(two.independent_groups, 2)
        self.assertGreater(two.agreement_gain,0)
        self.assertEqual(one.agreement_gain,0)

    def test_duplicates_idempotent_but_collision_rejected(self):
        e = fact()
        self.assertEqual(result([e,e]).service_availability, result([e]).service_availability)
        self.assertEqual(result([e,e]).duplicate_evidence_ids, ('e1',))
        with self.assertRaisesRegex(ValueError, 'conflicting payloads'):
            result([e, replace(e, polarity=Polarity.CONTRADICTS)])

    def test_wrong_facility_or_service_is_explicitly_excluded(self):
        other = fact('other', match=replace(fact().match, facility_id='other'))
        near = fact('nephrology', service='kidney_care')
        r = result([other, near])
        self.assertIsNone(r.service_availability.score)
        self.assertEqual(len(r.excluded), 2)

    def test_permutation_invariant_serializable_and_reproducible(self):
        rows = [fact(str(i), source_id=f'source_{i}', polarity=Polarity.CONTRADICTS if i==2 else Polarity.SUPPORTS) for i in range(5)]
        original = result(rows).to_json(sort_keys=True)
        random.Random(41).shuffle(rows)
        self.assertEqual(original, result(rows).to_json(sort_keys=True))
        self.assertEqual(json.loads(original)['as_of'], '2026-11-21')
        self.assertEqual(len(result(rows).policy_fingerprint), 64)

    def test_location_context_never_inflates_service(self):
        loc = location_context({'latitude':19.,'longitude':73.,'pin_ambiguous':True}, basis='pin_centroid')
        self.assertEqual(result([fact()]).service_availability, result([fact()],location=loc).service_availability)
        self.assertIn('PIN_CENTROID_NOT_FACILITY_LOCATION', result([fact()],location=loc).location.flags)

    def test_policy_snapshot_is_immutable_and_location_binds_facility(self):
        r=result([fact()])
        with self.assertRaises(TypeError):r.policy['half_life_days']=10
        with self.assertRaises(TypeError):r.policy['weights']['recency']=1
        with self.assertRaisesRegex(ValueError,'different facility_id'):
            result([fact()],location=LocationContext('unknown',facility_id='other'))

    def test_configurable_weights_source_and_agreement(self):
        low = Policy(source_overrides={'registry_a': .1})
        self.assertLess(result([fact()],policy=low).service_availability.score, result([fact()]).service_availability.score)
        p = Policy(agreement_bonus=0)
        self.assertEqual(result([fact()],policy=p).service_availability.score,
                         result([fact(),fact('e2',source_id='other')],policy=p).service_availability.score)
        self.assertNotEqual(Policy(weights={'reliability':1.,'facility_match':0.,'recency':0.}).fingerprint, Policy().fingerprint)

    def test_custom_caps_cannot_make_self_report_high_or_independent(self):
        p=Policy(self_report_cap=1.,indirect_cap=1.,unknown_date_cap=1.,high_threshold=.5,medium_threshold=.3)
        e=fact(source_kind=SourceKind.SELF_REPORT,verification=Verification.SELF_REPORTED)
        r=result([e],policy=p).service_availability
        self.assertEqual(r.status,'self_reported')
        self.assertNotEqual(r.category,'high')
        self.assertFalse(r.independent_current_evidence_ids)

    def test_older_evidence_never_increases_its_strength(self):
        values = [result([fact(observed_on=AS_OF-timedelta(days=n))]).service_availability.score for n in [0,30,180,365,730,1800]]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_score_range_under_extreme_valid_inputs(self):
        for confidence in [0,.01,.5,1]:
            for kind in SourceKind:
                e = fact(source_kind=kind, verification=Verification.UNKNOWN,
                         match=replace(fact().match,confidence=confidence))
                score = result([e]).service_availability.score
                self.assertTrue(score is None or 0 <= score <= 100)


class AdapterTests(unittest.TestCase):
    def registry_row(self, **kw):
        row = dict(service_row_id='s1',site_id='laqshya:1',source='laqshya',service='dialysis',
                   evidence_type='government_certification',service_specific=True,status='certified',
                   evidence_detail='Synthetic service certification',evidence_date='2026-10-21',
                   valid_until='2027-10-21',retrieved_on='2026-11-21',is_current=True,dq_flags=[],
                   source_name='Synthetic certification list',source_url='fixture://registry',row_citation='Synthetic source quote')
        row.update(kw)
        return row

    def match(self, **kw):
        row = dict(facility_id=FID,site_id='laqshya:1',match_score=95,needs_review=False,match_method='name+pin')
        row.update(kw)
        return registry_match(row)

    def test_real_registry_contract_shape_and_boolean_false_string(self):
        e = from_registry_service(self.registry_row(is_current='true'),self.match(needs_review='false'))
        self.assertEqual(result([e]).service_availability.status,'independently_supported')
        self.assertEqual(e.match.confidence,.95)
        self.assertEqual(e.citations[0].quote,'Synthetic source quote')

    def test_pending_high_match_cannot_verify(self):
        e = from_registry_service(self.registry_row(),self.match(needs_review='true',match_score=100))
        self.assertEqual(result([e]).service_availability.status,'needs_review')

    def test_missing_link_fields_fail_closed(self):
        for extra in [dict(needs_review=None),dict(match_score=None),dict(match_method=None)]:
            self.assertEqual(self.match(**extra).status,MatchStatus.UNKNOWN)
        with self.assertRaises(ValueError):self.match(match_score=101)
        with self.assertRaises(ValueError):self.match(needs_review='perhaps')
        self.assertEqual(registry_match(dict(facility_id=FID,site_id='x:1'),reviewer_decision='reject').status,MatchStatus.REJECTED)

    def test_cross_site_join_and_quality_promotion_rejected(self):
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(site_id='nabh:2'),self.match())
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(),self.match(),site={'site_id':'laqshya:1','source':'laqshya','listing_category':'hospital_accreditation'})
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(source='nmc'),self.match())

    def test_nmc_dnb_membership_and_trauma_never_directly_verify(self):
        for source,typ in [('nmc','government_training_approval'),('dnb','government_training_approval'),('ncg','network_membership'),('trauma','government_designation')]:
            m = self.match(site_id=source+':1')
            e = from_registry_service(self.registry_row(source=source,site_id=source+':1',evidence_type=typ),m)
            self.assertEqual(e.verification,Verification.INFERRED)
            self.assertFalse(result([e]).service_availability.independent_current_evidence_ids)
            if source=='trauma':self.assertIsNone(e.observed_on)

    def test_expiry_recalculated_as_of_not_frozen_build_date(self):
        e=from_registry_service(self.registry_row(evidence_date='2022-10-01',valid_until='2023-12-31',retrieved_on='2022-10-15',is_current=False,status='expired'),self.match())
        r=assess(FID,'dialysis',[e],as_of=date(2022,11,21))
        self.assertEqual(r.service_availability.contributions[0].temporal_status,'recent')
        self.assertEqual(result([e]).service_availability.status,'historical_only')

    def test_blank_expiry_preserves_expired_hint_and_cannot_verify(self):
        e=from_registry_service(self.registry_row(valid_until='',is_current=False,status='not_current'),self.match())
        self.assertEqual(result([e]).service_availability.status,'historical_only')
        n=from_nqas(dict(certification_id='c',department_assessed='All',validity_from='2026-10-01',
                         validity_to='',certification_status='expired'),replace(self.match(),reference_id='c'))
        self.assertEqual(result([n]).quality_evidence.status,'historical_only')

    def test_year_only_and_unknown_status_do_not_verify(self):
        for row in [self.registry_row(dq_flags=['DATE_IS_YEAR_ONLY']),self.registry_row(status='unknown')]:
            self.assertFalse(result([from_registry_service(row,self.match())]).service_availability.independent_current_evidence_ids)

    def test_expired_and_conditional_flags_retained(self):
        e=from_registry_service(self.registry_row(status='conditional',valid_until='2025-01-01'),self.match())
        self.assertIn('CONDITIONAL_CERTIFICATION',e.qualifiers)
        self.assertEqual(result([e]).service_availability.status,'historical_only')

    def test_site_accreditation_only_contributes_quality(self):
        row=dict(site_id='nabh:1',source='nabh',name='Synthetic Hospital',listing_category='hospital_accreditation',
                 listing_type='Hospital accreditation',listing_current=True,dq_flags=[])
        e=from_registry_site(row,self.match(site_id='nabh:1'))
        r=result([e])
        self.assertIsNone(r.service_availability.score)
        self.assertIsNotNone(r.quality_evidence.score)

    def test_empanelment_is_identity_not_accreditation_or_service(self):
        row=dict(site_id='nabh:1',source='nabh',name='Synthetic Hospital',listing_category='empanelment',
                 listing_type='Scheme empanelment',listing_current=True,dq_flags=[])
        e=from_registry_site(row,self.match(site_id='nabh:1'))
        self.assertEqual(e.scope,Scope.IDENTITY)
        self.assertEqual(e.source_kind,SourceKind.GOVERNMENT_REGISTRY)
        r=result([e])
        self.assertIsNone(r.service_availability.score)
        self.assertIsNone(r.quality_evidence.score)
        self.assertIsNotNone(r.identity_evidence.score)

    def test_claim_matcher_must_supply_service_polarity_and_quotes(self):
        row=dict(facility_id=FID,claim_field='capability',claim_position=0,claim_text='No dialysis; referred elsewhere')
        e=from_facility_claim(row,service='dialysis',polarity=Polarity.UNKNOWN,direct=True)
        self.assertEqual(e.statement,row['claim_text'])
        self.assertIsNone(result([e]).service_availability.score)
        negative=from_facility_claim(row,service='dialysis',polarity=Polarity.CONTRADICTS,direct=True)
        self.assertEqual(result([negative]).service_availability.status,'counterevidence_only')
        with self.assertRaises(TypeError):from_facility_claim(row,service='dialysis')

    def test_equipment_and_specialty_are_not_direct_services(self):
        for field in ['equipment','specialties']:
            e=from_facility_claim(dict(facility_id=FID,claim_field=field,claim_text='Nephrology'),service='dialysis',polarity='supports',direct=True)
            self.assertEqual(e.directness,Directness.INDIRECT)
            self.assertEqual(e.verification,Verification.SELF_REPORTED)

    def test_quality_adapters_require_explicit_record_match(self):
        with self.assertRaises(ValueError):from_kayakalp(dict(award_id='award-1',financial_year='2021-22'),self.match())
        with self.assertRaises(ValueError):from_nqas(dict(certification_id='cert-1'),self.match())

    def test_kayakalp_keeps_30_column_variants_and_never_supports_service(self):
        base=dict(award_id='kayakalp-2021-22-607',financial_year='2021-22',award_raw='Winner',
                  state_clean='Meghalaya',district_clean='North Garo Hills',retrieved_on='2026-11-21',
                  row_citation='Synthetic page 10 serial 607 citation',dq_flags=['DISTRICT_SPACING_VERIFIED'])
        m=replace(self.match(),reference_id=base['award_id'])
        a=from_kayakalp(base,m)
        b=from_kayakalp({**base,'state':'Meghalaya','district':'North Garo Hills'},m)
        self.assertEqual(a,b)
        self.assertEqual(a.observed_on,date(2022,3,31))
        self.assertEqual(a.date_precision,DatePrecision.FINANCIAL_YEAR)
        self.assertIsNone(result([a]).service_availability.score)
        self.assertEqual(result([a]).cleanliness_evidence.status,'historical_only')

    def test_kayakalp_duplicate_awards_do_not_add_confidence(self):
        row=dict(award_id='a',financial_year='2021-22',award_raw='Winner',dq_flags=[])
        m=replace(self.match(),reference_id='a')
        a=from_kayakalp(row,m)
        b=from_kayakalp({**row,'award_id':'b'},replace(m,reference_id='b'))
        self.assertEqual(result([a]).cleanliness_evidence.score,result([a,b]).cleanliness_evidence.score)

    def test_nqas_department_never_becomes_service(self):
        row=dict(certification_id='n1',department_assessed='Dialysis and ICU',validity_from='2020-01-01',
                 validity_to='2023-01-01',covers_all_departments=False,certification_status='expired',dq_flags=[])
        e=from_nqas(row,replace(self.match(),reference_id='n1'))
        self.assertIsNone(result([e]).service_availability.score)
        self.assertEqual(result([e]).quality_evidence.status,'historical_only')
        self.assertIn('PARTIAL_OR_UNKNOWN_DEPARTMENT_SCOPE',e.qualifiers)

    def test_location_aliases_pin_scope_and_invalid_coordinates(self):
        a=location_context(dict(latitude_clean=20.,longitude_clean=73.,state_clean='Maharashtra'),basis='site_coordinates')
        b=location_context(dict(latitude=20.,longitude=73.,state='Maharashtra'),basis='site_coordinates')
        self.assertEqual(a,b)
        with self.assertRaises(ValueError):location_context(dict(state='A',state_clean='B'),basis='unknown')
        self.assertIsNone(location_context(dict(latitude=0.,longitude=0.,coord_status='outside_india'),basis='site_coordinates').latitude)
        with self.assertRaises(ValueError):location_context(dict(latitude=300.,longitude=0.),basis='site_coordinates')

    def test_date_and_flag_inputs_not_mutated(self):
        r=self.registry_row(dq_flags=['CONDITIONAL_CERTIFICATION'])
        saved=json.dumps(r,sort_keys=True)
        from_registry_service(r,self.match())
        self.assertEqual(json.dumps(r,sort_keys=True),saved)
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(dq_flags={'FLAG':True}),self.match())

    def test_location_unusable_flag_without_status_discards_coordinates(self):
        loc=location_context(dict(latitude=0.,longitude=0.,dq_flags=['COORDS_ZERO']),basis='site_coordinates')
        self.assertIsNone(loc.latitude)
        self.assertIn('UNUSABLE_COORDINATES',loc.flags)

    def test_claim_locator_contains_actual_row_tuple(self):
        e=from_facility_claim(dict(facility_id=FID,claim_field='capability',claim_position=3,claim_text='Dialysis'),
                              service='dialysis',polarity='supports')
        self.assertIn(FID,e.citations[0].locator)
        self.assertIn('capability',e.citations[0].locator)
        self.assertIn('3',e.citations[0].locator)

    def test_bad_date_and_serialized_flag_array_not_silently_ignored(self):
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(evidence_date='yesterday'),self.match())
        with self.assertRaises(ValueError):from_registry_service(self.registry_row(dq_flags='["FLAG"]'),self.match())


class ExampleTests(unittest.TestCase):
    def test_all_examples_run_with_serializable_output_and_expected_gates(self):
        from evidence_confidence.examples import cases
        examples=cases()
        self.assertEqual(len(examples),10)
        for r in examples.values():json.loads(r.to_json())
        self.assertEqual(examples['current_scoped_documentary_support'].service_availability.status,'independently_supported')
        self.assertIsNone(examples['historical_award_only'].service_availability.score)
        self.assertEqual(examples['explicit_conflict'].service_availability.status,'conflicting')
        self.assertEqual(examples['service_plus_historical_quality'].service_availability.score,
                         examples['self_report_only'].service_availability.score)


class InputValidationTests(unittest.TestCase):
    def test_numeric_validation(self):
        for bad in [float('nan'),float('inf'),-1,1.01,True]:
            with self.assertRaises(ValueError):FacilityMatch(FID,confidence=bad)
            with self.assertRaises(ValueError):Policy(agreement_bonus=bad)
        with self.assertRaises(ValueError):Policy(half_life_days=float('inf'))

    def test_policy_unknown_keys_and_weights(self):
        with self.assertRaises(ValueError):Policy.from_dict({'half_life_day':365})
        with self.assertRaises(ValueError):Policy(weights={'reliability':0.,'facility_match':0.,'recency':0.})
        with self.assertRaises(ValueError):Policy(high_threshold=.2,medium_threshold=.4)
        p=Policy.from_json(Path(__file__).resolve().parents[1]/'config/evidence-confidence.json')
        self.assertEqual(p,Policy())
        with self.assertRaises(TypeError):p.weights['recency']=1

    def test_no_malformed_scope_or_self_verification(self):
        with self.assertRaises(ValueError):fact(source_kind=SourceKind.SELF_REPORT)
        with self.assertRaises(ValueError):fact(scope=Scope.QUALITY)
        with self.assertRaises(ValueError):fact(service=' ')
        with self.assertRaises(ValueError):Citation('source',' ')
        with self.assertRaises(ValueError):LocationContext('unknown',state=123)
        with self.assertRaises(ValueError):assess(FID,'dialysis',[],as_of=None)
        with self.assertRaises(ValueError):Evidence(**{**fact().__dict__,'qualifiers':'FLAG'})


if __name__ == '__main__':
    unittest.main()
