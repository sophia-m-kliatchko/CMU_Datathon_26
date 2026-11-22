"""Provisional ranking contract tests, not empirical/clinical ranking validation."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import unittest

from evidence_confidence import Candidate, RankingConfig, Tier, evidence_tier, rank_candidates
from evidence_confidence.models import MatchStatus
from test_evidence_tiers import FID, TODAY, certificate, indirect, negative


def candidate(fid, tier='T1', distance=5., **kwargs):
    e=certificate()
    if tier=='T2':e=replace(e,valid_until=date(2026,1,1))
    if tier=='T3':e=indirect()
    if tier=='R':e=replace(e,match=replace(e.match,status=MatchStatus.PENDING))
    rows=[] if tier=='U' else [e]
    if tier=='X':rows.append(negative())
    rows=[replace(x,match=replace(x.match,facility_id=fid)) for x in rows]
    return Candidate(fid,evidence_tier(fid,'emergency_c_section',rows,TODAY),distance,**kwargs)


class RankingTests(unittest.TestCase):
    def ids(self,rows):return [r.candidate.facility_id for r in rows]

    def test_routine_tier_precedes_band_and_distance(self):
        r=rank_candidates([candidate('historical','T2',1),candidate('current','T1',80),candidate('self','T3',.1)])
        self.assertEqual(self.ids(r.ranked),['current','historical','self'])
        self.assertTrue(r.provisional)

    def test_routine_band_precedes_flags_and_flags_precede_exact_distance(self):
        conditional=replace(candidate('conditional',distance=8),evidence=replace(candidate('x').evidence,
            facility_id='conditional',flags=replace(candidate('x').evidence.flags,conditional_certification=True)))
        clear=candidate('clear',distance=9)
        other_band=candidate('other-band',distance=11)
        r=rank_candidates([conditional,clear,other_band])
        self.assertEqual(self.ids(r.ranked),['clear','conditional','other-band'])
        r=rank_candidates([conditional,other_band])
        self.assertEqual(self.ids(r.ranked),['conditional','other-band'])

    def test_routine_exact_distance_after_equal_flags(self):
        self.assertEqual(self.ids(rank_candidates([candidate('far',distance=9),candidate('near',distance=1)]).ranked),['near','far'])

    def test_distance_band_boundaries_and_configurable_bins(self):
        distances=[0,10,10.001,25,25.001,50,50.001,None]
        r=rank_candidates([candidate(str(i),distance=d) for i,d in enumerate(distances)])
        by_id={x.candidate.facility_id:x.distance_band for x in r.ranked}
        self.assertEqual([by_id[str(i)] for i in range(8)],[0,0,1,1,2,2,3,4])
        r=rank_candidates([candidate('a',distance=10)],config={'distance_bands_km':[5,15]})
        self.assertEqual(r.ranked[0].distance_band,1)

    def test_missing_evidence_keeps_facility_in_routine(self):
        r=rank_candidates([Candidate('unknown',distance_km=.1)])
        self.assertEqual(self.ids(r.ranked),['unknown'])
        self.assertEqual(r.ranked[0].effective_tier,Tier.U)
        self.assertTrue(r.requires_review)

    def test_urgent_missing_capability_requires_review_not_inferred_by_proximity(self):
        r=rank_candidates([candidate('nearest','T1',.1)],mode='urgent')
        self.assertFalse(r.ranked)
        self.assertEqual(self.ids(r.alternatives),['nearest'])
        self.assertTrue(r.requires_review)
        self.assertEqual(r.status,'requires_review')

    def test_urgent_explicit_t1_capability_by_distance_no_detour_rule(self):
        supplied=dict(capability_eligible=True,capability_basis='Synthetic explicit capability assessment')
        rows=[candidate('near','T1',.1,**supplied),candidate('far','T1',100,**supplied),candidate('unknown','U',.01)]
        r=rank_candidates(rows,mode='urgent')
        self.assertEqual(self.ids(r.ranked),['near','far'])
        self.assertEqual(self.ids(r.alternatives),['unknown'])
        self.assertIn('not_confirmed_emergency_capable',r.alternatives[0].label)
        self.assertTrue(r.requires_review)
        self.assertNotIn('detour_km',r.to_dict()['config'])

    def test_u_r_x_never_urgent_eligible_even_with_true_flag(self):
        for tier in ['U','R','X','T2','T3']:
            r=rank_candidates([candidate('f',tier,.1,capability_eligible=True,capability_basis='Synthetic supplied assertion')],mode='urgent')
            self.assertFalse(r.ranked)
            self.assertEqual(len(r.alternatives),1)
            self.assertTrue(r.requires_review)

    def test_true_capability_without_basis_or_distance_requires_review(self):
        for kw in [dict(capability_eligible=True),dict(capability_eligible=True,capability_basis='Synthetic source')]:
            r=rank_candidates([candidate('f',distance=None,**kw)],mode='urgent')
            self.assertFalse(r.ranked);self.assertTrue(r.requires_review)
        r=rank_candidates([candidate('f',capability_eligible=True)],mode='urgent')
        self.assertFalse(r.ranked);self.assertTrue(r.requires_review)

    def test_unknown_alternatives_by_proximity_retained_exactly_once(self):
        rows=[candidate('a','U',1),candidate('b','R',2),candidate('c','X',3),Candidate('d')]
        r=rank_candidates(rows,mode='urgent')
        self.assertEqual(self.ids(r.alternatives),['a','b','c','d'])
        self.assertEqual(len(r.ranked)+len(r.alternatives),len(rows))
        self.assertEqual(len(set(self.ids(r.ranked)+self.ids(r.alternatives))),len(rows))

    def test_mixed_eligible_and_explicitly_ineligible_not_silently_removed(self):
        rows=[candidate('a','T1',2,capability_eligible=True,capability_basis='Synthetic assessment'),
              candidate('b','T1',1,capability_eligible=False)]
        r=rank_candidates(rows,mode='urgent')
        self.assertEqual(self.ids(r.ranked),['a']);self.assertEqual(self.ids(r.alternatives),['b'])
        self.assertIn('supplied_capability_assessment',r.alternatives[0].label)

    def test_stable_ties_and_json_without_infinity(self):
        rows=[Candidate('b'),Candidate('a')]
        a=rank_candidates(rows);b=rank_candidates(reversed(rows))
        self.assertEqual(a.to_json(sort_keys=True),b.to_json(sort_keys=True))
        self.assertEqual(self.ids(a.ranked),['a','b'])
        self.assertIsNone(json.loads(a.to_json())['ranked'][0]['candidate']['distance_km'])
        self.assertNotIn('Infinity',rank_candidates(rows,mode='urgent').to_json())

    def test_empty_input_is_valid(self):
        r=rank_candidates([],mode='urgent')
        self.assertEqual(r.ranked,());self.assertEqual(r.alternatives,())

    def test_bad_config_distance_ids_and_mixed_queries_rejected(self):
        for distance in [-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):Candidate('x',distance_km=distance)
        for bands in [[25,10],[10,10],[0,5],[float('inf')]]:
            with self.assertRaises(ValueError):RankingConfig(distance_bands_km=bands)
        with self.assertRaises(ValueError):RankingConfig(ordinal_flag_order=('arbitrary_weight',))
        with self.assertRaises(ValueError):rank_candidates([Candidate('x'),Candidate('x')])
        with self.assertRaises(ValueError):rank_candidates([],mode='clinical_rule')
        with self.assertRaises(ValueError):Candidate('wrong',candidate('right').evidence)
        c=candidate('other');e=replace(c.evidence,service='dialysis')
        with self.assertRaises(ValueError):rank_candidates([candidate('a'),replace(c,evidence=e)])
        with self.assertRaises(ValueError):rank_candidates([candidate('a'),replace(c,evidence=replace(c.evidence,as_of=date(2025,1,1)))])

    def test_configuration_file_has_only_provisional_ordinal_parameters(self):
        p=Path(__file__).resolve().parents[1]/'config/evidence-ranking.json'
        config=RankingConfig.from_json(p)
        self.assertEqual(config.distance_bands_km,(10.,25.,50.))
        self.assertEqual(set(json.loads(p.read_text())),{'distance_bands_km','tier_priority','ordinal_flag_order'})


if __name__=='__main__':unittest.main()
