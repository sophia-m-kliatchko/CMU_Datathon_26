"""Deterministic framework tests; synthetic records, no real-world validation claim."""
from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
import unittest

from evidence_confidence import (Citation, DatePrecision, Directness, Evidence, FacilityMatch,
    MatchStatus, Polarity, Policy, Scope, SourceKind, Tier, TierPolicy, Verification, assess, evidence_tier)
from evidence_confidence.adapters import from_facility_claim, from_registry_service, registry_match
from evidence_confidence.temporal import temporal_validity

TODAY = date(2026, 11, 21)
FID = 'synthetic-tier-facility'
QUOTE = Citation('Synthetic certification', 'fixture://certificate/1', 'Synthetic service-specific certification.')


def certificate(key='cert-1', family='laqshya', **kwargs):
    values = dict(evidence_id=key, source_id=family,
        source_kind=SourceKind.ACCREDITATION if family=='nabh' else SourceKind.GOVERNMENT_REGISTRY,
        scope=Scope.SERVICE, service='emergency_c_section', statement='Synthetic service-specific certificate.',
        match=FacilityMatch(FID, MatchStatus.ACCEPTED, .95, 'reviewed_identity', family+':record-1'),
        verification=Verification.INDEPENDENT, directness=Directness.DIRECT, observed_on=date(2025,3,10),
        valid_from=date(2025,3,10),valid_until=date(2028,3,9),citations=(QUOTE,))
    values.update(kwargs)
    return Evidence(**values)


def classify(rows, **kwargs):
    return evidence_tier(FID,'emergency_c_section',rows,TODAY,**kwargs)


def indirect(family='nmc', **kwargs):
    defaults = dict(verification=Verification.INFERRED,directness=Directness.INDIRECT,
                    observed_on=None,valid_from=None,valid_until=None,current_status=None,
                    qualifiers=('INDIRECT_VIA_SPECIALTY',))
    defaults.update(kwargs)
    return certificate(family=family, **defaults)


def negative(key='negative', **kwargs):
    defaults = dict(source_kind=SourceKind.INDEPENDENT_CHECK,verification=Verification.INDEPENDENT,
        polarity=Polarity.CONTRADICTS,observed_on=TODAY-timedelta(days=2),valid_from=None,valid_until=None)
    defaults.update(kwargs)
    return certificate(key, family='independent_review', **defaults)


class EvidenceTierTests(unittest.TestCase):
    def test_current_certificate_older_than_365_days_is_t1(self):
        e=certificate()
        self.assertGreater((TODAY-e.observed_on).days,365)
        r=classify([e])
        self.assertEqual((r.base_tier,r.effective_tier),(Tier.T1,Tier.T1))
        self.assertEqual(r.review_status,'clear')
        # Existing numeric API survives, but no longer calls an in-force interval historical.
        self.assertEqual(assess(FID,e.service,[e],as_of=TODAY).service_availability.status,'independently_supported')

    def test_expired_direct_is_t2_not_service_absence(self):
        r=classify([certificate(valid_until=date(2026,11,20))])
        self.assertEqual(r.effective_tier,Tier.T2)
        self.assertTrue(r.flags.expired_certification)
        self.assertIn('expiry does not establish service absence',' '.join(r.explanation))

    def test_validity_boundaries_inclusive_and_override_frozen_status(self):
        for as_of in [date(2025,3,10),date(2028,3,9)]:
            r=evidence_tier(FID,'emergency_c_section',[certificate(current_status=False)],as_of)
            self.assertEqual(r.effective_tier,Tier.T1)
        self.assertEqual(evidence_tier(FID,'emergency_c_section',[certificate()],date(2025,3,9)).effective_tier,Tier.U)

    def test_current_year_only_nabh_listing_t1_with_caveats(self):
        r=classify([certificate(family='nabh',valid_from=None,valid_until=None,
                               observed_on=date(2021,1,1),date_precision=DatePrecision.YEAR,current_status=True)])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.date_year_only)
        self.assertTrue(r.flags.current_listing_undated)
        self.assertTrue(r.flags.temporal_uncertainty)
        self.assertIn('Year-only date is not an exact January 1 observation.',r.decisions[0].reasons)

    def test_current_listing_without_interval_has_caveat_even_with_old_issue_date(self):
        e=certificate(family='nabh',valid_from=None,valid_until=None,current_status=True)
        r=classify([e]);self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.current_listing_undated)

    def test_listing_explicitly_no_longer_current_is_t2(self):
        r=classify([certificate(family='nabh',valid_from=None,valid_until=None,observed_on=None,current_status=False)])
        self.assertEqual(r.effective_tier,Tier.T2)
        self.assertTrue(r.flags.temporal_uncertainty)

    def test_missing_validity_not_made_historical_by_issuance_age(self):
        e=certificate(valid_from=None,valid_until=None,current_status=None)
        r=classify([e])
        self.assertEqual(r.effective_tier,Tier.U)
        self.assertTrue(r.flags.temporal_uncertainty)
        self.assertIn('validity is unknown',' '.join(r.decisions[0].reasons))

    def test_recent_retrieval_does_not_make_undated_record_current(self):
        e=certificate(observed_on=None,valid_from=None,valid_until=None,retrieved_on=TODAY)
        self.assertEqual(classify([e]).effective_tier,Tier.U)

    def test_future_retrieval_invalid_and_unknown_intervals_not_current(self):
        for e in [certificate(retrieved_on=TODAY+timedelta(days=1)),
                  certificate(observed_on=TODAY+timedelta(days=1),date_precision=DatePrecision.UNKNOWN),
                  certificate(valid_from=date(2027,1,1)),
                  certificate(valid_from=date(2028,1,1),valid_until=date(2027,1,1))]:
            self.assertEqual(classify([e]).effective_tier,Tier.U)

    def test_year_only_without_listing_does_not_become_exact_observation(self):
        e=certificate(family='nabh',valid_from=None,valid_until=None,observed_on=TODAY,
                      date_precision=DatePrecision.YEAR,current_status=None)
        self.assertEqual(classify([e]).effective_tier,Tier.U)

    def test_all_named_indirect_families_remain_t3_even_if_mislabelled_direct(self):
        for family in ['nmc','dnb','ncg','trauma','virtue_foundation']:
            with self.subTest(family=family):
                r=classify([certificate(family=family,current_status=True)])
                self.assertEqual(r.effective_tier,Tier.T3)
                self.assertEqual(r.supporting_source_families,(family,))

    def test_virtue_self_report_cannot_be_t1_or_t2(self):
        e=from_facility_claim(dict(facility_id=FID,claim_field='capability',claim_text='Synthetic C-section'),
                              service='emergency_c_section',polarity='supports',direct=True,observed_on=TODAY)
        self.assertEqual(classify([e]).effective_tier,Tier.T3)
        self.assertEqual(classify([replace(e,current_status=False)]).effective_tier,Tier.T3)

    def test_conditional_flag_preserved(self):
        r=classify([certificate(qualifiers=('CONDITIONAL_CERTIFICATION',))])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.conditional_certification)

    def test_department_not_stated_cannot_directly_verify_service(self):
        r=classify([certificate(qualifiers=('DEPARTMENT_NOT_STATED',))])
        self.assertEqual(r.effective_tier,Tier.U)

    def test_ambiguous_only_is_r_and_has_no_accepted_base(self):
        e=certificate(match=replace(certificate().match,status=MatchStatus.PENDING))
        r=classify([e])
        self.assertEqual((r.base_tier,r.effective_tier),(Tier.U,Tier.R))
        self.assertEqual(r.review_status,'pending')
        self.assertEqual(r.decisions[0].candidate_tier,Tier.T1)
        self.assertFalse(r.decisions[0].credited)
        self.assertTrue(r.flags.identity_review)
        self.assertEqual(r.supporting_source_count,0)

    def test_rejected_distinct_from_ambiguous_and_never_verifies(self):
        e=certificate(match=replace(certificate().match,status=MatchStatus.REJECTED))
        r=classify([e])
        self.assertEqual((r.base_tier,r.effective_tier),(Tier.U,Tier.U))
        self.assertEqual(r.review_status,'not_applicable')
        self.assertEqual(r.decisions[0].match_status,'rejected')
        self.assertFalse(r.decisions[0].credited)

    def test_identity_flag_even_on_accepted_link_is_review(self):
        for flags in [('MATCH_AMBIGUOUS',),('DUP_ROWS_STATE_CONFLICT',),('EMPTY_NAME_CORE',)]:
            e=certificate(match=replace(certificate().match,flags=flags))
            self.assertEqual(classify([e]).effective_tier,Tier.R)

    def test_unknown_match_is_not_verified(self):
        e=certificate(match=replace(certificate().match,status=MatchStatus.UNKNOWN))
        r=classify([e]);self.assertEqual(r.effective_tier,Tier.R);self.assertEqual(r.review_status,'unknown')

    def test_accepted_t3_and_unresolved_direct_stay_t3_with_review_flag(self):
        e=certificate('direct',match=replace(certificate().match,status=MatchStatus.PENDING))
        r=classify([indirect(key='indirect'),e])
        self.assertEqual((r.base_tier,r.effective_tier),(Tier.T3,Tier.T3))
        self.assertEqual(r.review_status,'partial')
        self.assertTrue(r.flags.identity_review)

    def test_accepted_direct_not_downgraded_by_rejected_extra_support(self):
        e=certificate('rejected',match=replace(certificate().match,status=MatchStatus.REJECTED))
        r=classify([certificate(),e])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertEqual(r.review_status,'clear')

    def test_credible_unresolved_conflict_overlays_base(self):
        r=classify([certificate(),negative()])
        self.assertEqual((r.base_tier,r.effective_tier),(Tier.T1,Tier.X))
        self.assertTrue(r.flags.conflicting_evidence)
        self.assertTrue(next(d for d in r.decisions if d.evidence_id=='negative').credible_contradiction)
        self.assertEqual(len(r.citations),1)  # Same fixture citation deduplicated, assertions remain separate.
        self.assertEqual(len(r.decisions),2)

    def test_weak_stale_undated_uncited_or_unmatched_negatives_do_not_override_t1(self):
        variants=[negative(verification=Verification.SELF_REPORTED),
                  negative(source_kind=SourceKind.UNKNOWN),negative(directness=Directness.INDIRECT),
                  replace(negative(),source_id='laqshya',source_kind=SourceKind.UNKNOWN),
                  negative(observed_on=TODAY-timedelta(days=366)),negative(observed_on=None),
                  negative(citations=()),negative(date_precision=DatePrecision.YEAR),
                  negative(match=replace(certificate().match,status=MatchStatus.PENDING)),
                  negative(match=replace(certificate().match,status=MatchStatus.REJECTED)),
                  negative(valid_until=TODAY-timedelta(days=1))]
        for n in variants:
            with self.subTest(n=n):
                self.assertEqual(classify([certificate(),n]).effective_tier,Tier.T1)

    def test_unrelated_negative_does_not_override(self):
        wrong_facility=negative('wrong-facility',match=replace(certificate().match,facility_id='other'))
        wrong_service=negative('wrong-service',service='dialysis')
        r=classify([certificate(),wrong_facility,wrong_service])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertEqual(len(r.excluded),2)

    def test_counterevidence_only_is_u_not_absence(self):
        r=classify([negative()])
        self.assertEqual(r.effective_tier,Tier.U)
        self.assertFalse(r.flags.conflicting_evidence)

    def test_current_negative_interval_not_made_stale_by_issuance_age(self):
        n=negative(observed_on=date(2025,1,1),valid_from=date(2025,1,1),valid_until=date(2027,1,1))
        self.assertEqual(classify([certificate(),n]).effective_tier,Tier.X)

    def test_no_relevant_evidence_is_u_and_keeps_id(self):
        r=classify([])
        self.assertEqual(r.effective_tier,Tier.U)
        self.assertEqual(r.facility_id,FID)
        self.assertEqual(r.review_status,'not_applicable')

    def test_nqas_kayakalp_hfr_never_supply_service_verification_even_if_mis_scoped(self):
        for family,dimension in [('nqas','quality_evidence_ids'),('kayakalp','cleanliness_evidence_ids'),('hfr','identity_evidence_ids')]:
            r=classify([certificate(family=family)])
            self.assertEqual(r.effective_tier,Tier.U)
            self.assertEqual(getattr(r,dimension),('cert-1',))

    def test_general_nabh_quality_scope_is_not_service(self):
        r=classify([certificate(family='nabh',scope=Scope.QUALITY,service=None)])
        self.assertEqual(r.effective_tier,Tier.U)
        self.assertEqual(r.quality_evidence_ids,('cert-1',))

    def test_payload_duplicates_and_repeated_indirect_rows_do_not_false_corroborate(self):
        e=indirect()
        r=classify([e,e,replace(e,evidence_id='alias')])
        self.assertEqual(r.effective_tier,Tier.T3)
        self.assertEqual(r.supporting_source_count,1)
        self.assertEqual(r.supporting_record_count,1)
        self.assertEqual(len(r.duplicate_of),2)
        many=[indirect(key=str(i),statement=f'Synthetic training course {i}') for i in range(20)]
        self.assertEqual(classify(many).effective_tier,Tier.T3)
        self.assertEqual(classify(many).supporting_source_count,1)

    def test_source_families_separate_not_weighted_by_row_count(self):
        r=classify([indirect('nmc',key='n'),indirect('dnb',key='d'),indirect('ncg',key='c'),
                    indirect('trauma',key='t'),indirect('virtue_foundation',key='v')])
        self.assertEqual(r.effective_tier,Tier.T3)
        self.assertEqual(r.supporting_source_count,5)
        self.assertEqual(set(r.evidence_basis),{'training','membership','sanctioned_not_confirmed_functional','self_report'})

    def test_direct_families_are_counted_separately_without_changing_tier(self):
        r=classify([certificate('l'),certificate('n',family='nabh')])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertEqual(r.supporting_source_families,('laqshya','nabh'))
        self.assertEqual(r.supporting_source_count,2)

    def test_conflicting_id_payloads_not_silently_deduplicated(self):
        with self.assertRaises(ValueError):classify([certificate(),replace(certificate(),polarity=Polarity.CONTRADICTS)])

    def test_current_and_historical_same_family_choose_strongest_without_deleting(self):
        r=classify([certificate(),certificate('expired',valid_until=date(2026,1,1))])
        self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.expired_certification)
        self.assertEqual(r.supporting_record_count,2)
        self.assertEqual(r.supporting_source_count,1)

    def test_unmapped_source_does_not_get_direct_tier_from_generic_type(self):
        r=classify([certificate(family='unmapped_registry')])
        self.assertEqual(r.effective_tier,Tier.U)
        self.assertTrue(r.assumptions)

    def test_unmapped_source_with_unresolved_identity_remains_review_not_verified(self):
        e=certificate(family='unmapped',match=replace(certificate().match,status=MatchStatus.PENDING))
        r=classify([e]);self.assertEqual(r.base_tier,Tier.U);self.assertEqual(r.effective_tier,Tier.R)
        self.assertTrue(r.assumptions)

    def test_accepted_status_not_numeric_match_or_legacy_score_assigns_tier(self):
        e=certificate(match=replace(certificate().match,confidence=None))
        self.assertEqual(classify([e]).effective_tier,Tier.T1)
        p=Policy(source_overrides={'laqshya':0.})
        a=assess(FID,e.service,[e],as_of=TODAY,policy=p)
        self.assertIsNone(a.service_availability.score)
        self.assertEqual(a.service_evidence.effective_tier,Tier.T1)

    def test_primary_tier_added_to_assess_generator_and_json_without_removing_scores(self):
        a=assess(FID,'emergency_c_section',(e for e in [certificate()]),as_of=TODAY)
        self.assertIsNotNone(a.service_availability.score)
        self.assertEqual(a.service_evidence.effective_tier,Tier.T1)
        self.assertEqual(json.loads(a.to_json())['service_evidence']['effective_tier'],'T1')

    def test_order_invariance_and_serialization(self):
        a,b=certificate(),indirect(key='training')
        self.assertEqual(classify([a,b]).to_json(sort_keys=True),classify([b,a]).to_json(sort_keys=True))
        self.assertEqual(json.loads(classify([a]).to_json())['base_tier'],'T1')

    def test_tier_policy_is_time_rule_not_score_and_validated(self):
        p=TierPolicy.from_json(Path(__file__).resolve().parents[1]/'config/evidence-tiers.json')
        self.assertEqual(p.contradiction_max_age_days,365)
        n=negative(observed_on=TODAY-timedelta(days=20))
        self.assertEqual(classify([certificate(),n],policy=TierPolicy(10)).effective_tier,Tier.T1)
        for bad in [0,-1,True,1.5]:
            with self.assertRaises(ValueError):TierPolicy(bad)


class TemporalAdapterTests(unittest.TestCase):
    def row(self,source='laqshya',**kwargs):
        values=dict(source=source,site_id=source+':1',service_row_id='service-1',service='emergency_c_section',
            evidence_type='independent_accreditation' if source=='nabh' else 'government_certification',
            service_specific=True,evidence_detail='Synthetic source statement.',status='certified',
            evidence_date='2025-03-10',valid_until='2028-03-09',is_current=True,dq_flags=[],
            retrieved_on='2026-11-21',source_url='fixture://registry')
        values.update(kwargs);return values

    def link(self,source='laqshya'):
        return registry_match(dict(facility_id=FID,site_id=source+':1',match_score=95,needs_review=False,match_method='name+pin'))

    def test_registry_issue_date_becomes_valid_from_only_for_exact_direct_certification(self):
        e=from_registry_service(self.row(),self.link())
        self.assertEqual(e.valid_from,date(2025,3,10))
        self.assertEqual(classify([e]).effective_tier,Tier.T1)
        self.assertEqual(temporal_validity(e,TODAY).status,'current_certificate')

    def test_current_nabh_year_listing_drops_jan1_but_retains_flag(self):
        e=from_registry_service(self.row('nabh',evidence_date='2021-01-01',valid_until=None,
                                        status='accredited',dq_flags=['DATE_IS_YEAR_ONLY']),self.link('nabh'))
        self.assertIsNone(e.observed_on)
        self.assertIsNone(e.valid_from)
        r=classify([e]);self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.date_year_only);self.assertTrue(r.flags.current_listing_undated)

    def test_ncg_snapshot_is_not_a_service_event(self):
        e=from_registry_service(self.row('ncg',evidence_type='network_membership',evidence_date='2026-11-21',
            valid_until=None,is_current=True,status='member'),self.link('ncg'))
        self.assertIsNone(e.observed_on)
        self.assertIsNone(e.valid_from)
        self.assertIn('SNAPSHOT_NOT_SERVICE_EVENT',e.qualifiers)
        r=classify([e]);self.assertEqual(r.effective_tier,Tier.T3)
        self.assertTrue(r.flags.temporal_uncertainty)

    def test_authoritative_listing_current_alias_supported(self):
        row=self.row('nabh',evidence_date=None,valid_until=None,is_current=None,listing_current=True,status='accredited')
        self.assertEqual(classify([from_registry_service(row,self.link('nabh'))]).effective_tier,Tier.T1)

    def test_exact_issue_date_without_expiry_is_still_current_listing_with_caveat(self):
        e=from_registry_service(self.row('nabh',valid_until=None,status='accredited'),self.link('nabh'))
        self.assertIsNone(e.valid_from)
        r=classify([e]);self.assertEqual(r.effective_tier,Tier.T1)
        self.assertTrue(r.flags.current_listing_undated)

    def test_conditional_registry_row_is_flagged(self):
        e=from_registry_service(self.row(status='conditional'),self.link())
        self.assertTrue(classify([e]).flags.conditional_certification)


if __name__=='__main__':
    unittest.main()
