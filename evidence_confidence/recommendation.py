"""Versioned JSON boundary around existing aggregation, LEFT JOIN and ranking.

Geographic retrieval is supplied by the caller. This module never queries a
service substring, truncates candidates, computes distances or infers capability.
"""
from dataclasses import fields
from datetime import date
import json
import math
import re

from .engine import canonical_service
from .integration import build_facility_service_rows, join_geographic_candidates
from .models import Citation, day
from .ranking import Candidate, rank_candidates
from .tiers import EvidenceDecision, EvidenceFlags, Tier, TierAssessment

CONTRACT_VERSION = 'recommendation-response/1'


def normalize_request(request, *, today=None):
    allowed = {'pin', 'service', 'radius_km', 'mode', 'as_of'}
    if set(request) - allowed:
        raise ValueError('unknown request fields')
    pin = request.get('pin')
    if not isinstance(pin, str) or not re.fullmatch(r'[1-9][0-9]{5}', pin):
        raise ValueError('pin must be a six-digit string with nonzero first digit')
    radius = request.get('radius_km')
    if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or radius <= 0:
        raise ValueError('radius_km must be finite and positive')
    mode = request.get('mode')
    if mode not in ('routine', 'urgent'):
        raise ValueError('mode must be routine or urgent')
    as_of = request.get('as_of')
    if as_of is None:
        as_of = date.today() if today is None else today
    elif isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    day(as_of, 'as_of')
    if as_of is None:
        raise ValueError('as_of date required')
    return dict(pin=pin, service=canonical_service(request.get('service')),
                radius_km=radius, mode=mode, as_of=as_of.isoformat())


def assessment_from_row(row):
    """Restore only existing TierAssessment fields for the strict ranking API.

    This is a trusted builder-output adapter, not a source-data classifier.
    The original JSON row (including evidence_records) remains the response payload.
    """
    values = {f.name: row[f.name] for f in fields(TierAssessment) if f.name in row}
    values['as_of'] = date.fromisoformat(values['as_of'])
    for key in ('base_tier', 'effective_tier', 'pending_stronger_tier'):
        if values.get(key) is not None:
            values[key] = Tier(values[key])
    values['flags'] = EvidenceFlags(**values['flags'])
    values['citations'] = tuple(Citation(**c) for c in values['citations'])
    values['decisions'] = tuple(EvidenceDecision(**{
        **d, 'candidate_tier': Tier(d['candidate_tier']) if d['candidate_tier'] else None,
        'reasons': tuple(d['reasons'])}) for d in values['decisions'])
    for field in fields(TierAssessment):
        if isinstance(values.get(field.name), list):
            values[field.name] = tuple(tuple(x) if isinstance(x, list) else x for x in values[field.name])
    return TierAssessment(**values)


def build_recommendation_response(request, evidence_records, geographic_candidates, *,
                                  today=None, ranking_config=None, tier_policy=None):
    """Run every supplied geographic candidate through enrichment then ranking.

    Caller owns PIN/radius retrieval completeness, canonical names/IDs and explicit
    capability assessments. Missing names/bases stay null; missing support stays U.
    """
    request = normalize_request(request, today=today)
    as_of = date.fromisoformat(request['as_of'])
    candidates = list(geographic_candidates)
    for candidate in candidates:
        for key in ('name', 'location_basis'):
            value = candidate.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f'{key} must be a nonblank string or null')
    evidence_rows = build_facility_service_rows(evidence_records, as_of=as_of,
        facility_services=[(g['facility_id'], request['service']) for g in candidates], policy=tier_policy)
    joined = join_geographic_candidates(candidates, evidence_rows, service=request['service'], as_of=as_of)
    ranking = rank_candidates([
        Candidate(row['facility_id'], assessment_from_row(row['service_evidence']), row['distance_km'],
                  row.get('capability_eligible'), row.get('capability_basis')) for row in joined
    ], mode=request['mode'], config=ranking_config)
    by_id = {row['facility_id']: row for row in joined}

    def export(ranked):
        row = by_id[ranked.candidate.facility_id]
        evidence = row['service_evidence']
        warnings = list(evidence['explanation'])
        if row.get('name') is None:
            warnings.append('Facility display name is missing; no name was inferred.')
        if row.get('location_basis') is None:
            warnings.append('Location basis is unspecified.')
        if row['distance_interpretation'] != 'reported_distance_precision_unspecified':
            warnings.append('Reported distance is approximate; supplied uncertainty is retained.')
        if row['distance_km'] is not None and row['distance_km'] > request['radius_km']:
            warnings.append('Reported distance exceeds request radius; upstream retrieval must explain inclusion.')
        return {
            'facility_id': row['facility_id'], 'name': row.get('name'), 'service': request['service'],
            **{key: row.get(key) for key in ('distance_km', 'location_uncertainty_km', 'distance_min_km',
                'distance_max_km', 'location_basis', 'geo_confidence', 'distance_interpretation')},
            'service_evidence': evidence,
            'source_urls': sorted({c['locator'] for c in evidence['citations']
                                   if c['locator'].startswith(('https://', 'http://'))}),
            'warnings': warnings,
            'capability_eligible': row.get('capability_eligible'), 'capability_basis': row.get('capability_basis'),
            'ranking': {'label': ranked.label, 'distance_band': ranked.distance_band,
                        'ordinal_evidence_flags': list(ranked.ordinal_evidence_flags),
                        'sort_key': list(ranked.sort_key)},
        }

    result = {
        'contract_version': CONTRACT_VERSION, 'framework_version': 'evidence-tiers/2',
        'request': request, 'candidate_count': len(candidates),
        'recommendations': [export(r) for r in ranking.ranked],
        'alternatives': [export(r) for r in ranking.alternatives],
        'requires_review': ranking.requires_review, 'status': ranking.status,
        'provisional': ranking.provisional, 'ranking_explanation': list(ranking.explanation),
        'ranking_config': ranking.to_dict()['config'],
        'warnings': ['Documentary evidence is not current service availability or emergency capability.',
                     'Missing service evidence means unknown, not unavailable.',
                     'PIN/radius retrieval coverage must be verified by the geographic provider.'],
    }
    # Guarantee a plain JSON boundary, detached from internal tuples and input objects.
    return json.loads(json.dumps(result, allow_nan=False))
