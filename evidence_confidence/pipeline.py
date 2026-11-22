"""End-to-end recommendation pipeline over a local Silver bundle (no Spark, no writes).

    bundle = load_bundle(silver_dir, geography_notebook=..., repository_root=...)
    result = recommend(bundle, {'service': 'dialysis', 'pincode': '110001', 'radius_km': 50, 'max_results': 5})

Order of operations (fixed); alternatives are ranks K+1..K+A of the same ranking:
  validate PIN -> ALL radius-eligible geographic candidates (producer rule, no top-K, no service filter)
  -> canonical service -> registry evidence + mapped self-reported claims for those facilities
  -> build_recommendation_response() (aggregation, LEFT JOIN = U for missing, existing ranking)
  -> top-K selected from the full ranked list -> explainable JSON (`recommendation-pipeline/1`).

Ranking is NOT changed here: the order is exactly `rank_candidates` (tier priority, distance band,
ordinal caveat flags, exact distance, facility_id). Distance-only order is reported for comparison.
Quality (NQAS) and cleanliness (Kayakalp) are reported as unavailable when no canonical facility
link exists; they never change service tiers or ranking.
"""
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path

from .engine import canonical_service
from .geographic_candidates import GeographicProducer, default_notebook, to_join_candidate
from .recommendation import build_recommendation_response
from .service_claims import MAPPING_VERSION, claim_evidence
from .silver import adapt_registry_tables, notebook_service_vocabulary, read_local_export

CONTRACT_VERSION = 'recommendation-pipeline/1'
REQUIRED = ('facilities_silver', 'pincode_centroids_silver', 'registry_sites_silver',
            'registry_services_silver', 'facility_registry_links_silver')
OPTIONAL = ('silver_facility_claims', 'registry_match_review', 'nqas_silver', 'kayakalp_silver')
DOCUMENTARY = ('T1', 'T2', 'T3')
INDEPENDENT_BASES = ('direct_certification', 'service_accreditation')


class Bundle:
    """Loaded, adapted Silver inputs. Built once; recommend() is read-only over it."""

    def __init__(self, tables, missing, producer, vocabulary, ready, centroids, geo_summary, registry):
        self.tables, self.missing, self.producer, self.vocabulary = tables, missing, producer, vocabulary
        self.ready, self.centroids, self.geo_summary = ready, centroids, geo_summary
        self.ready_by_id = {r['facility_id']: r for r in ready}
        self.facilities = {r['facility_id']: r for r in tables['facilities_silver']}
        self.registry_report = {k: v for k, v in registry.items() if k != 'evidence'}
        self.registry_by_facility = defaultdict(list)
        for e in registry['evidence']:
            self.registry_by_facility[e.match.facility_id].append(e)
        self.claims_by_facility = defaultdict(list)
        for c in tables.get('silver_facility_claims', ()):
            self.claims_by_facility[c['facility_id']].append(c)


def load_bundle(directory, *, repository_root=None, geography_notebook=None):
    root = Path(repository_root or Path(__file__).resolve().parents[1]).resolve()
    source = Path(directory).resolve()
    tables, missing = {}, []
    for name in REQUIRED + OPTIONAL:
        path = source / f'{name}.csv'
        if path.is_file():
            tables[name] = read_local_export(path, csv_escapechar='\\')
        elif name in REQUIRED:
            raise ValueError(f'required Silver table missing: {path}')
        else:
            missing.append(name)
    notebook = Path(geography_notebook).resolve() if geography_notebook else default_notebook(root)
    producer = GeographicProducer(notebook, root / 'notebooks/common/validation.py')
    ready, centroids, geo_summary = producer.build_ready(tables['facilities_silver'], tables['pincode_centroids_silver'])
    vocabulary = notebook_service_vocabulary(root / 'notebooks/05_registries_bronze_to_silver.py')
    registry = adapt_registry_tables(tables['facilities_silver'], tables['registry_sites_silver'],
                                     tables['registry_services_silver'], tables['facility_registry_links_silver'],
                                     canonical_services=vocabulary, reviews=tables.get('registry_match_review', ()))
    if registry['status'] != 'PASS':
        raise ValueError('registry adaptation failed: ' + json.dumps(registry['findings'])[:2000])
    geo_summary = {**geo_summary, 'notebook': str(notebook)}
    return Bundle(tables, missing, producer, vocabulary, ready, centroids, geo_summary, registry)


def normalize_pipeline_request(request):
    allowed = {'service', 'pincode', 'radius_km', 'max_results', 'mode', 'as_of', 'include_self_reported_claims', 'max_alternatives'}
    if set(request) - allowed:
        raise ValueError(f'unknown request fields: {sorted(set(request) - allowed)}')
    raw = request.get('service')
    max_results = request.get('max_results', 5)
    if type(max_results) is not int or not 1 <= max_results <= 50:
        raise ValueError('max_results must be an integer 1-50')
    max_alternatives = request.get('max_alternatives', 5)
    if type(max_alternatives) is not int or not 0 <= max_alternatives <= 50:
        raise ValueError('max_alternatives must be an integer 0-50')
    as_of = request.get('as_of') or date.today().isoformat()
    return dict(service_requested=raw, service=canonical_service(raw), pincode=str(request.get('pincode', '')),
                radius_km=request.get('radius_km'), max_results=max_results, max_alternatives=max_alternatives,
                mode=request.get('mode', 'routine'), as_of=date.fromisoformat(str(as_of)).isoformat(),
                include_self_reported_claims=request.get('include_self_reported_claims', True) is not False)


def _facility(bundle, fid):
    f, g = bundle.facilities.get(fid, {}), bundle.ready_by_id.get(fid, {})
    pick = lambda *keys: next((f[k] for k in keys if f.get(k) not in (None, '')), None)
    return {'city': pick('city', 'city_clean'), 'district': pick('district', 'district_clean'),
            'state': pick('state', 'state_clean'), 'pincode': pick('pincode', 'pincode_clean'),
            'address': pick('address_full'), 'latitude': g.get('geo_latitude'), 'longitude': g.get('geo_longitude')}


def _summary(se):
    decisions = {d['evidence_id']: d for d in se['decisions']}
    claims, registry, pending = [], [], []
    for r in se.get('evidence_records', ()):
        d = decisions.get(r['evidence_id'], {})
        cite = (r.get('citations') or [{}])[0]
        item = {'evidence_id': r['evidence_id'], 'source': r['source_id'], 'statement': r['statement'],
                'credited': bool(d.get('credited')), 'candidate_tier': d.get('candidate_tier'),
                'match_status': d.get('match_status'), 'temporal_status': d.get('temporal_status'),
                'observed_on': r.get('observed_on'), 'valid_until': r.get('valid_until'),
                'citation': {'label': cite.get('label'), 'locator': cite.get('locator')}}
        (claims if r['source_id'] == 'virtue_foundation' else registry).append(item)
        if d.get('match_status') not in (None, 'accepted'):
            pending.append(item)
    independent = any(i['credited'] and decisions[i['evidence_id']]['evidence_basis'] in INDEPENDENT_BASES
                      for i in registry)
    return {'self_reported_claims': claims, 'registry_evidence': registry, 'pending_identity_review': pending,
            'independently_corroborated': independent,
            'self_reported_only': bool(claims) and not any(i['credited'] for i in registry) and any(i['credited'] for i in claims)}


def _explain(row, se, summary):
    tier = se['effective_tier']
    parts = {'T1': 'Current, direct registry certification/accreditation for this service (documentary, not live availability).',
             'T2': 'Direct registry certification for this service exists but has expired (historical only).',
             'T3': ('Only the facility\'s own listing mentions this service (self-reported).' if summary['self_reported_only']
                    else 'Indirect support only (training approval, network membership, designation or self-report).'),
             'R': 'Registry evidence may belong to this facility, but the facility match is pending review; not counted.',
             'X': 'Sources conflict about this service; resolve before relying on it.',
             'U': 'No record of this service was found for this facility. Unknown, not unavailable.'}
    text = [parts[tier]]
    if se.get('pending_stronger_tier'):
        text.append(f"A stronger {se['pending_stronger_tier']} record exists but its facility match is pending review.")
    if row['location_basis'] == 'pin_centroid':
        text.append(f"Location is the facility's PIN centre (±{row['location_uncertainty_km']} km), not its address.")
    return text


def recommend(bundle, request):
    req = normalize_pipeline_request(request)
    base = {'contract_version': CONTRACT_VERSION, 'claim_mapping_version': MAPPING_VERSION,
            'query': {k: req[k] for k in ('service_requested', 'service', 'pincode', 'radius_km', 'max_results', 'max_alternatives', 'mode', 'as_of')},
            'missing_optional_tables': list(bundle.missing)}
    if req['service'] not in bundle.vocabulary:
        return {**base, 'status': 'unknown_service', 'recommendations': [], 'alternatives': [],
                'warnings': [f"'{req['service']}' is not in the shared service vocabulary (notebook 05)."]}
    try:
        raw, context = bundle.producer.candidates(bundle.ready, bundle.centroids, pin=req['pincode'], radius_km=req['radius_km'])
    except ValueError as exc:
        return {**base, 'status': 'invalid_location', 'recommendations': [], 'alternatives': [], 'warnings': [str(exc)]}
    loc = context['query_location']
    base['query'].update(query_latitude=loc.get('latitude'), query_longitude=loc.get('longitude'),
                         query_centroid_quality=loc.get('centroid_quality'), query_pin_ambiguous=loc.get('pin_ambiguous'),
                         query_main_district=loc.get('main_district'), query_main_state=loc.get('main_state'),
                         radius_rule=context['radius_rule'])
    query_warnings = []
    if loc.get('pin_ambiguous'):
        query_warnings.append('Query PIN spans several districts/states; its centre is a median.')
    if loc.get('centroid_quality') in ('spread_out', 'single_office'):
        query_warnings.append(f"Query PIN centre quality: {loc.get('centroid_quality')}.")
    query_warnings.append('Distances are straight-line from the query PIN centre, not road distance.')
    if not raw:
        return {**base, 'status': 'no_candidates', 'geographic_candidates': 0, 'recommendations': [], 'alternatives': [],
                'warnings': query_warnings + ['No facility with a usable location is within the radius.']}
    candidates = [to_join_candidate(r) for r in raw]
    ids = [c['facility_id'] for c in candidates]
    records = [e for fid in ids for e in bundle.registry_by_facility.get(fid, ()) if e.service == req['service']]
    claim_report = {'included': False}
    if req['include_self_reported_claims'] and 'silver_facility_claims' not in bundle.missing:
        claims, claim_report = claim_evidence([c for fid in ids for c in bundle.claims_by_facility.get(fid, ())], req['service'])
        records += claims
        claim_report = {**claim_report, 'included': True}
    response = build_recommendation_response(
        dict(pin=req['pincode'], service=req['service'], radius_km=req['radius_km'], mode=req['mode'], as_of=req['as_of']),
        records, candidates)
    ranked = response['recommendations'] + response['alternatives']
    if len(ranked) != len(candidates) or len({r['facility_id'] for r in ranked}) != len(candidates):
        raise ValueError('candidate retention failure')
    by_dist = {fid: i + 1 for i, fid in enumerate(c['facility_id'] for c in sorted(candidates, key=lambda c: (c['distance_km'], c['facility_id'])))}
    tiers = Counter(r['service_evidence']['effective_tier'] for r in ranked)

    def export(position, row):
        se = row['service_evidence']
        summary = _summary(se)
        warnings = list(row['warnings'][len(se['explanation']):])
        if row['location_basis'] == 'pin_centroid':
            warnings.append('Approximate location (PIN centre).')
        if row['distance_km'] is not None and row['distance_km'] > req['radius_km']:
            warnings.append('Displayed centre is outside the radius; included because it may be inside after location uncertainty.')
        if tier_of(row) in ('U', 'R'):
            warnings.append('No verified service evidence.')
        warnings.append('Current availability of this service is not verified.')
        return {'rank': position, 'distance_only_rank': by_dist[row['facility_id']], 'facility_id': row['facility_id'],
                'name': row.get('name'), **_facility(bundle, row['facility_id']),
                **{k: row.get(k) for k in ('distance_km', 'distance_min_km', 'location_basis', 'geo_confidence', 'location_uncertainty_km')},
                'evidence_tier': se['effective_tier'], 'base_tier': se['base_tier'], 'review_status': se['review_status'],
                'pending_stronger_tier': se.get('pending_stronger_tier'),
                'supporting_source_families': se['supporting_source_families'], 'evidence_basis': se['evidence_basis'],
                'flags': se['flags'], 'contradiction': bool(se['flags'].get('conflicting_evidence')), **summary,
                'source_urls': row['source_urls'],
                'quality_signals': {'nqas': 'unavailable: no canonical facility link in the Silver bundle',
                                    'kayakalp': 'unavailable: kayakalp_silver not in the Silver bundle'
                                    if 'kayakalp_silver' in bundle.missing else 'unavailable: no canonical facility link'},
                'ranking': row['ranking'], 'explanation': _explain(row, se, summary), 'warnings': list(dict.fromkeys(warnings))}

    tier_of = lambda r: r['service_evidence']['effective_tier']
    k, a = req['max_results'], req['max_alternatives']
    # Alternatives = the next-highest-ranked facilities after the top K (same ranking, no re-sort).
    top = [export(i + 1, r) for i, r in enumerate(ranked[:k])]
    alternatives = [export(k + i + 1, r) for i, r in enumerate(ranked[k:k + a])]
    if len({x['facility_id'] for x in top + alternatives}) != len(top) + len(alternatives):
        raise ValueError('duplicate facility across recommendations/alternatives')
    documentary = [r for r in ranked if tier_of(r) in DOCUMENTARY]
    response_warnings = query_warnings + list(response['warnings'])
    if not any(tier_of(r) == 'T1' for r in ranked):
        response_warnings.append('No facility in the radius has current direct (T1) evidence for this service.')
    if not documentary:
        response_warnings.append('No facility in the radius has any documentary evidence for this service; results are ordered by distance only.')
    return {**base, 'status': response['status'], 'geographic_candidates': len(candidates),
            'ranked_candidates': len(ranked), 'returned': len(top), 'returned_alternatives': len(alternatives),
            'tier_distribution': dict(sorted(tiers.items())),
            'coverage': {'independently_corroborated': sum(_summary(r['service_evidence'])['independently_corroborated'] for r in ranked),
                         'self_reported_only': sum(_summary(r['service_evidence'])['self_reported_only'] for r in ranked),
                         'pending_identity_review': sum(r['service_evidence']['review_status'] not in ('clear', 'not_applicable') for r in ranked),
                         'pin_centroid_locations': sum(r['location_basis'] == 'pin_centroid' for r in ranked),
                         'centre_outside_radius': sum((r['distance_km'] or 0) > req['radius_km'] for r in ranked)},
            'claim_mapping': claim_report, 'ranking_explanation': response['ranking_explanation'],
            'ranking_config': response['ranking_config'], 'recommendations': top, 'alternatives': alternatives,
            'nearest_first_top': [{'facility_id': c['facility_id'], 'distance_km': c['distance_km'],
                                   'evidence_tier': next(tier_of(r) for r in ranked if r['facility_id'] == c['facility_id'])}
                                  for c in sorted(candidates, key=lambda c: (c['distance_km'], c['facility_id']))[:req['max_results']]],
            'warnings': list(dict.fromkeys(response_warnings))}


_BUNDLES = {}


def recommend_facilities(service, pincode, radius_km, max_results=5, max_alternatives=5, *,
                         silver_dir=None, bundle=None, geography_notebook=None, **options):
    """Website entrypoint. Returns the `recommendation-pipeline/1` dict (JSON-serialisable).

    Pass a preloaded `bundle`, or `silver_dir` (loaded once and cached per resolved path; env var
    EVIDENCE_SILVER_DIR is the fallback). `options` may set mode, as_of, include_self_reported_claims.
    Invalid PIN / unknown service are returned as `status`, not raised; bad argument types raise ValueError.
    """
    if bundle is None:
        import os
        directory = silver_dir or os.environ.get('EVIDENCE_SILVER_DIR')
        if not directory:
            raise ValueError('recommend_facilities needs bundle= or silver_dir= (or EVIDENCE_SILVER_DIR)')
        notebook = geography_notebook or os.environ.get('EVIDENCE_GEO_NOTEBOOK')
        key = (str(Path(directory).resolve()), notebook)
        if key not in _BUNDLES:
            _BUNDLES[key] = load_bundle(key[0], geography_notebook=notebook)
        bundle = _BUNDLES[key]
    return recommend(bundle, {'service': service, 'pincode': pincode, 'radius_km': radius_km,
                              'max_results': max_results, 'max_alternatives': max_alternatives, **options})
