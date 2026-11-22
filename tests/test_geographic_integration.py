"""Regression tests: geographic producer -> Evidence Confidence LEFT JOIN -> response.

Synthetic, contract-shaped fixtures only. They do not establish real-world accuracy.
The producer logic is the repository copy of the teammate notebook, read-only; the
uncertainty-radius variant is derived in a temp dir from the exact upstream diff.
"""
from datetime import date
from pathlib import Path
import tempfile
import unittest

from evidence_confidence.adapters import from_registry_service, registry_match
from evidence_confidence.geographic_candidates import GeographicProducer, to_join_candidate
from evidence_confidence.integration import join_geographic_candidates
from evidence_confidence.recommendation import build_recommendation_response

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'notebooks/common/pin_nearby_facilities.py'
RENAMED = ROOT / 'notebooks/07_pin_nearby_facilities.py'  # after Elliot_New_Branch merges
NOTEBOOK = LEGACY if LEGACY.is_file() else RENAMED
HELPERS = ROOT / 'notebooks/common/validation.py'
AS_OF = date(2026, 11, 22)
PIN, LAT0, LON0 = '110001', 28.6300, 77.2200
OLD_WHERE = '        .where(F.col("distance_km") <= radius))'
NEW_WHERE = ('        .withColumn("uncertainty_adjusted_distance_km",\n'
             '                    F.greatest(F.round(F.col("distance_km") - F.coalesce(F.col("location_uncertainty_km"), F.lit(0.0)), 2),\n'
             '                               F.lit(0.0)))\n'
             '        .where(F.col("uncertainty_adjusted_distance_km") <= radius))')
OLD_BOX = 'dlon = radius / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 0.01))\n'
NEW_BOX = OLD_BOX + (
    'max_uncertainty = float(spark.table("facility_geo_ready").agg(\n'
    '    F.max(F.coalesce(F.col("location_uncertainty_km"), F.lit(0.0))).alias("max_uncertainty")\n'
    ').first()["max_uncertainty"] or 0.0)\n'
    'dlat += max_uncertainty / KM_PER_DEG_LAT\n'
    'dlon += max_uncertainty / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 0.01))\n')


def uncertainty_notebook(directory):
    if RENAMED.is_file():
        return RENAMED  # the real uncertainty-rule notebook; no derivation needed
    source = LEGACY.read_text()
    assert source.count(OLD_WHERE) == 1 and source.count(OLD_BOX) == 1, 'repository notebook changed; update fixture'
    path = Path(directory) / '07_uncertainty_variant.py'
    path.write_text(source.replace(OLD_WHERE, NEW_WHERE).replace(OLD_BOX, NEW_BOX))
    return path


def facility(fid, lat, lon, pin=PIN):
    return dict(facility_id=fid, name=f'Synthetic {fid}', city='Delhi', state='Delhi', pincode=pin,
                latitude=lat, longitude=lon, coords_low_precision=False, coord_status='ok', dq_flags=[])


def centroid(pin, lat, lon, spread):
    return dict(pincode=pin, latitude=lat, longitude=lon, max_office_distance_km=spread,
                centroid_quality='ok', pin_ambiguous=False, main_state='Delhi', main_district='New Delhi')


def t1_record(fid):
    link = registry_match(dict(facility_id=fid, site_id='laqshya:syn-1', match_score=95,
                               needs_review=False, match_method='name+pin'))
    return from_registry_service(dict(
        service_row_id='syn-row-1', site_id='laqshya:syn-1', source='laqshya', service='emergency_c_section',
        evidence_type='government_certification', service_specific=True, evidence_detail='Synthetic OT certificate',
        status='certified', evidence_date='2025-03-10', valid_until='2028-03-09', is_current=True,
        retrieved_on='2026-11-22', source_url='fixture://laqshya/1', dq_flags=[]), link)


def request(mode='routine'):
    return dict(pin=PIN, service='emergency_c_section', radius_km=50., mode=mode, as_of=AS_OF.isoformat())


class GeographicIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def search(self, facilities, centroids, notebook=NOTEBOOK, radius=50.):
        producer = GeographicProducer(notebook, HELPERS)
        ready, lookup, _ = producer.build_ready(facilities, centroids)
        rows, context = producer.candidates(ready, lookup, pin=PIN, radius_km=radius)
        return producer, ready, lookup, [to_join_candidate(r) for r in rows], context

    def test_no_premature_truncation_far_t1_reaches_response(self):
        # 30 facilities in a line; the T1 facility is the farthest (beyond any top-25).
        facs = [facility(f'syn-{i:02d}', LAT0 + 0.01 * i, LON0) for i in range(1, 31)]
        _, _, _, cands, context = self.search(facs, [centroid(PIN, LAT0, LON0, 1.0)])
        self.assertEqual(len(cands), 30)
        self.assertFalse(context['candidate_limit_applied'])
        farthest = max(cands, key=lambda r: r['distance_km'])['facility_id']
        response = build_recommendation_response(request(), [t1_record(farthest)], cands)
        rows = response['recommendations'] + response['alternatives']
        self.assertEqual(len(rows), 30)
        self.assertEqual(response['recommendations'][0]['facility_id'], farthest)
        self.assertEqual(response['recommendations'][0]['service_evidence']['effective_tier'], 'T1')

    def test_missing_service_evidence_stays_eligible_as_u(self):
        facs = [facility('syn-a', LAT0 + 0.01, LON0), facility('syn-b', LAT0 + 0.02, LON0)]
        _, _, _, cands, _ = self.search(facs, [centroid(PIN, LAT0, LON0, 1.0)])
        response = build_recommendation_response(request(), [], cands)
        rows = response['recommendations'] + response['alternatives']
        self.assertEqual({r['facility_id'] for r in rows}, {'syn-a', 'syn-b'})
        self.assertTrue(all(r['service_evidence']['effective_tier'] == 'U' for r in rows))

    def test_service_keyword_is_not_a_pre_enrichment_filter(self):
        producer = GeographicProducer(NOTEBOOK, HELPERS)
        ready, lookup, _ = producer.build_ready([facility('syn-a', LAT0, LON0)], [centroid(PIN, LAT0, LON0, 1.0)])
        _, context = producer.candidates(ready, lookup, pin=PIN, radius_km=50.)
        self.assertFalse(context['service_prefiltered'])

    def test_duplicate_ids_fail_closed(self):
        facs = [facility('syn-dup', LAT0, LON0), facility('syn-dup', LAT0 + 0.01, LON0)]
        with self.assertRaisesRegex(ValueError, 'duplicate canonical facilities'):
            self.search(facs, [centroid(PIN, LAT0, LON0, 1.0)])
        geo = to_join_candidate(dict(facility_id='syn-x', distance_km=1., geo_confidence='high'))
        with self.assertRaisesRegex(ValueError, 'duplicate geographic'):
            join_geographic_candidates([geo, dict(geo)], [], service='emergency_c_section', as_of=AS_OF)
        with self.assertRaisesRegex(ValueError, 'duplicate PIN centroids'):
            self.search([facility('syn-a', LAT0, LON0)], [centroid(PIN, LAT0, LON0, 1.), centroid(PIN, LAT0, LON0, 1.)])

    def test_approximate_pin_location_inclusion_and_uncertainty_survive(self):
        # Facility with no coordinates falls back to a spread-out PIN ~55 km away.
        far_pin, spread = '110099', 30.0
        facs = [facility('syn-near', LAT0 + 0.01, LON0), facility('syn-pin', None, None, pin=far_pin)]
        cents = [centroid(PIN, LAT0, LON0, 1.0), centroid(far_pin, LAT0 + 0.5, LON0, spread)]
        notebook = uncertainty_notebook(self.tmp.name)
        producer, ready, lookup, cands, context = self.search(facs, cents, notebook=notebook)
        self.assertEqual(context['radius_rule'], 'uncertainty_adjusted_distance_km <= radius_km')
        unboxed, _ = producer.candidates(ready, lookup, pin=PIN, radius_km=50., apply_prefilter=False)
        self.assertEqual({r['facility_id'] for r in unboxed}, {r['facility_id'] for r in cands})
        approx = next(r for r in cands if r['facility_id'] == 'syn-pin')
        self.assertEqual((approx['location_basis'], approx['geo_confidence']), ('pin_centroid', 'approximate_pin_centroid'))
        self.assertEqual(approx['location_uncertainty_km'], spread)
        self.assertGreater(approx['distance_km'], 50.)
        self.assertEqual(approx['distance_min_km'], round(approx['distance_km'] - spread, 2))
        out = build_recommendation_response(request(), [], cands)
        row = next(r for r in out['recommendations'] + out['alternatives'] if r['facility_id'] == 'syn-pin')
        for key in ('distance_km', 'distance_min_km', 'location_uncertainty_km', 'location_basis', 'geo_confidence'):
            self.assertEqual(row[key], approx[key])
        self.assertEqual(row['distance_interpretation'], 'reported_estimate_with_bounds')
        self.assertTrue(any('exceeds request radius' in w for w in row['warnings']))
        if LEGACY.is_file() and NOTEBOOK == LEGACY and not RENAMED.is_file():
            # The original notebook rule (point distance only) excludes the same facility.
            _, _, _, old, _ = self.search(facs, cents)
            self.assertNotIn('syn-pin', {r['facility_id'] for r in old})

    def test_shared_pin_centroid_points_get_identical_distances(self):
        facs = [facility(f'syn-p{i}', None, None, pin='110002') for i in range(3)]
        _, _, _, cands, _ = self.search(facs, [centroid(PIN, LAT0, LON0, 1.), centroid('110002', LAT0 + 0.05, LON0, 3.)])
        self.assertEqual(len({r['distance_km'] for r in cands}), 1)
        self.assertTrue(all(r['location_uncertainty_km'] == 3. for r in cands))

    def test_unsearchable_facility_is_reported_not_silently_ranked(self):
        _, ready, _, cands, _ = self.search([facility('syn-a', LAT0, LON0), facility('syn-none', None, None, pin='999999')],
                                            [centroid(PIN, LAT0, LON0, 1.)])
        self.assertIn('syn-none', {r['facility_id'] for r in ready if r['geo_latitude'] is None})
        self.assertNotIn('syn-none', {r['facility_id'] for r in cands})

    def test_unrecognized_bound_update_fails_closed(self):
        source = Path(uncertainty_notebook(self.tmp.name)).read_text().replace(
            'F.max(F.coalesce(F.col("location_uncertainty_km"), F.lit(0.0)))', 'F.max(F.col("pin_spread_km"))')
        path = Path(self.tmp.name) / 'bad.py'
        path.write_text(source)
        with self.assertRaisesRegex(ValueError, 'unrecognized max_uncertainty'):
            GeographicProducer(path, HELPERS)


if __name__ == '__main__':
    unittest.main()
