"""Portable, read-only facility/service export and geographic LEFT JOIN.

Inputs are already canonical upstream identities and service tags. No matching,
service synonym inference, distance computation, ranking or database operations.
"""
import math
from collections import defaultdict
from collections.abc import Mapping

from .engine import canonical_service
from .models import Evidence, Scope, _jsonable, text
from .tiers import evidence_tier, deduplicate_records


def build_facility_service_rows(evidence_records, *, as_of, facility_services=None, policy=None):
    """Aggregate evidence BEFORE classification, returning sorted JSON-ready rows.

    Optional facility_services is an iterable of (canonical ID, canonical tag)
    requests, including pairs with no evidence. Otherwise pairs come only from
    explicit service tags. Non-service context never invents a service mapping.
    Full retained records accompany the assessment to preserve validity/provenance.
    """
    records = deduplicate_records(evidence_records)
    by_facility = defaultdict(list)
    for e in records:
        by_facility[e.match.facility_id].append(e)
    pairs = ([(e.match.facility_id, e.service) for e in records if e.scope == Scope.SERVICE]
             if facility_services is None else list(facility_services))
    pairs = sorted({(text(fid, 'facility_id'), canonical_service(service)) for fid, service in pairs})
    result = []
    # Validate as_of/policy even for an empty request set.
    evidence_tier('_validation_only', '_validation_only', (), as_of, policy=policy)
    for fid, service in pairs:
        group = [e for e in by_facility[fid]
                 if e.scope != Scope.SERVICE or canonical_service(e.service) == service]
        assessment = evidence_tier(fid, service, group, as_of, policy=policy)
        duplicate_ids = {alias for alias, original in assessment.duplicate_of if alias != original}
        retained = {e.evidence_id: e for e in group if e.evidence_id not in duplicate_ids}
        row = assessment.to_dict()
        row['evidence_records'] = [_jsonable(retained[key]) for key in sorted(retained)]
        result.append(row)
    return result


def _distance(value, name):
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                              or not math.isfinite(value) or value < 0):
        raise ValueError(f'{name} must be finite nonnegative kilometres or None')


def join_geographic_candidates(candidates, evidence_rows, *, service, as_of,
                               framework_version='evidence-tiers/2'):
    """One output per unique canonical candidate ID; service evidence is nested.

    Select one service/date/version slice before the LEFT JOIN. Duplicate slice
    keys fail rather than multiply candidates. geo_confidence is opaque upstream
    metadata; it is never converted into service evidence or ranking weights.
    """
    service = canonical_service(service)
    empty = evidence_tier('_validation_only', service, (), as_of).to_dict()
    if framework_version != empty['framework_version']:
        raise ValueError('unsupported framework_version for missing-evidence U rows')
    index = {}
    for row in evidence_rows:
        if not isinstance(row, Mapping):
            raise ValueError('evidence rows must be mappings')
        if (canonical_service(row['service']) != service or row['as_of'] != as_of.isoformat()
                or row['framework_version'] != framework_version):
            continue
        fid = text(row['facility_id'], 'facility_id')
        if fid in index:
            raise ValueError(f'duplicate facility/service/date/version row: {fid}')
        index[fid] = row
    seen, output = set(), []
    for candidate in candidates:
        row = dict(candidate)
        fid = text(row['facility_id'], 'facility_id')
        if fid in seen:
            raise ValueError(f'duplicate geographic facility_id: {fid}')
        seen.add(fid)
        if 'geo_confidence' not in row or 'distance_km' not in row:
            raise ValueError('geographic candidate requires distance_km and geo_confidence')
        if 'service_evidence' in row or 'distance_interpretation' in row:
            raise ValueError('reserved integration output fields already present')
        for name in ('distance_km', 'location_uncertainty_km', 'distance_min_km', 'distance_max_km'):
            _distance(row.get(name), name)
        low, high = row.get('distance_min_km'), row.get('distance_max_km')
        if low is not None and high is not None and low > high:
            raise ValueError('distance_min_km exceeds distance_max_km')
        distance = row['distance_km']
        if distance is not None and ((low is not None and distance < low)
                                     or (high is not None and distance > high)):
            raise ValueError('reported distance lies outside supplied bounds')
        row['facility_id'] = fid
        row['distance_interpretation'] = ('reported_estimate_with_bounds' if low is not None or high is not None
            else 'reported_estimate_with_uncertainty' if row.get('location_uncertainty_km') is not None
            else 'reported_distance_precision_unspecified')
        row['service_evidence'] = dict(index[fid]) if fid in index else {
            **evidence_tier(fid, service, (), as_of).to_dict(), 'evidence_records': []}
        output.append(row)
    return output
