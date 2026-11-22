"""Read-only checks on already-loaded Silver adapters and integration outputs.

No database access. Errors block integration; warnings require source-owner review.
Canonical inventories must come from the team, not this component.
"""
from collections import Counter
from datetime import date
from urllib.parse import urlparse

from .engine import canonical_service
from .integration import build_facility_service_rows, join_geographic_candidates
from .recommendation import build_recommendation_response
from .tiers import deduplicate_records


def validate_integration(*, canonical_facility_ids, canonical_services, evidence_records,
                         evidence_rows, geographic_candidates, joined_rows, as_of,
                         response=None, tier_policy=None, ranking_config=None):
    """Return JSON-ready errors, warnings, counts and distributions; never mutate.

    Recompute expected assessments and LEFT JOIN from adapted Evidence, rather
    than declaring PASS from caller-supplied tier labels. Pass the production
    TierPolicy explicitly when a non-default notice horizon is in use.
    """
    errors, warnings = [], []
    records, rows, geo, joined = map(list, (evidence_records, evidence_rows, geographic_candidates, joined_rows))
    facility_ids, services = set(canonical_facility_ids), set(canonical_services)

    def issue(code, message, *, warning=False):
        (warnings if warning else errors).append({'code': code, 'message': message})

    def unique(values, code):
        duplicates = sorted(str(key) for key, count in Counter(values).items() if count > 1)
        if duplicates:
            issue(code, f'Duplicate keys: {duplicates}')

    if any(not isinstance(fid, str) or not fid.strip() or fid != fid.strip() for fid in facility_ids):
        issue('FACILITY_INVENTORY', 'Canonical IDs must be nonblank strings without surrounding whitespace.')
    try:
        if any(canonical_service(s) != s for s in services):
            issue('SERVICE_INVENTORY', 'Vocabulary must contain canonical tags.')
    except (TypeError, ValueError) as exc:
        issue('SERVICE_INVENTORY', str(exc))
    for e in records:
        if e.match.facility_id not in facility_ids:
            issue('EVIDENCE_FACILITY_ID', e.evidence_id)
        if e.service is not None and e.service not in services:
            issue('EVIDENCE_SERVICE', e.evidence_id)
        if not e.citations:
            issue('CITATION_MISSING', e.evidence_id, warning=True)
        for citation in e.citations:
            url = urlparse(citation.locator)
            if url.scheme not in ('http', 'https') or not url.netloc:
                issue('SOURCE_URL_MISSING', e.evidence_id, warning=True)
            if not citation.quote.strip():
                issue('ROW_PROVENANCE_MISSING', e.evidence_id, warning=True)
        if e.source_record_id is None:
            issue('STABLE_SOURCE_ID_MISSING', e.evidence_id, warning=True)
        if e.valid_from and e.valid_until and e.valid_from > e.valid_until:
            issue('INVALID_VALIDITY_INTERVAL', e.evidence_id)
        if e.observed_on and e.observed_on > as_of:
            issue('FUTURE_OBSERVATION', e.evidence_id, warning=True)
        if e.retrieved_on and e.retrieved_on > as_of:
            issue('FUTURE_RETRIEVAL', e.evidence_id)
        if e.valid_from and e.valid_from > as_of:
            issue('NOT_YET_VALID', e.evidence_id, warning=True)
        if e.valid_until and e.valid_until < as_of:
            issue('EXPIRED_SOURCE', e.evidence_id, warning=True)
        if not (e.valid_from and e.valid_until) and e.current_status is None:
            issue('VALIDITY_INCOMPLETE', e.evidence_id, warning=True)
        if e.observed_on and e.retrieved_on and e.retrieved_on < e.observed_on:
            issue('RETRIEVAL_BEFORE_OBSERVATION', e.evidence_id, warning=True)
        if e.observed_on and e.valid_until and e.observed_on > e.valid_until:
            issue('OBSERVATION_AFTER_EXPIRY', e.evidence_id, warning=True)
    if not geo:
        issue('NO_GEOGRAPHIC_CANDIDATES', 'No geographic candidates supplied; retrieval coverage is not established.', warning=True)
    ids = Counter(e.evidence_id for e in records)
    if any(n > 1 for n in ids.values()):
        issue('DUPLICATE_EVIDENCE_ID', 'Repeated ingestion IDs require deduplication before publication.', warning=True)
    try:
        deduplicate_records(records)
        payloads = {}
        for e in records:
            if e.evidence_id in payloads and payloads[e.evidence_id] != e:
                issue('CONFLICTING_EVIDENCE_ID', e.evidence_id)
            payloads[e.evidence_id] = e
    except ValueError as exc:
        issue('CONFLICTING_SOURCE_RECORD', str(exc))
    try:
        unique([(r['facility_id'], r['service'], r['as_of'], r['framework_version']) for r in rows], 'DUPLICATE_EVIDENCE_GRAIN')
        for row in rows:
            if row['facility_id'] not in facility_ids:
                issue('OUTPUT_FACILITY_ID', row['facility_id'])
            if row['service'] not in services:
                issue('OUTPUT_SERVICE', row['service'])
            expected = build_facility_service_rows(records, as_of=as_of,
                facility_services=[(row['facility_id'], row['service'])], policy=tier_policy)[0]
            if row != expected:
                issue('ASSESSMENT_MISMATCH', f"{row['facility_id']}: assessment/provenance differs from recomputation")
            for decision in row['decisions']:
                if decision['credited'] and decision['match_status'] != 'accepted':
                    issue('IDENTITY_CREDIT', decision['evidence_id'])
            if row['effective_tier'] not in ('T1', 'T2', 'T3', 'U', 'R', 'X'):
                issue('INVALID_TIER', str(row['effective_tier']))
    except (KeyError, TypeError, ValueError) as exc:
        issue('OUTPUT_SCHEMA', str(exc))
    unique([g.get('facility_id') for g in geo], 'DUPLICATE_GEOGRAPHIC_ID')
    for g in geo:
        if g.get('facility_id') not in facility_ids:
            issue('GEOGRAPHIC_FACILITY_ID', str(g.get('facility_id')))
        if not g.get('name'):
            issue('DISPLAY_NAME_MISSING', str(g.get('facility_id')), warning=True)
        if g.get('geo_confidence') is None or not g.get('location_basis'):
            issue('GEOGRAPHIC_CONFIDENCE_INCOMPLETE', str(g.get('facility_id')), warning=True)
        if g.get('location_basis') == 'pin_centroid' and not any(g.get(k) is not None for k in
                ('location_uncertainty_km', 'distance_min_km', 'distance_max_km')):
            issue('CENTROID_UNCERTAINTY_MISSING', str(g.get('facility_id')), warning=True)
    if Counter(g.get('facility_id') for g in geo) != Counter(r.get('facility_id') for r in joined):
        issue('JOIN_RETENTION_OR_FANOUT', 'Joined facility multiset differs from input candidates.')
    try:
        # One requested slice is required for a candidate batch.
        slices = {(r['service_evidence']['service'], r['service_evidence']['as_of'],
                   r['service_evidence']['framework_version']) for r in joined}
        if len(slices) > 1:
            issue('MIXED_JOIN_SLICE', 'Joined candidates contain mixed services/dates/frameworks.')
        if slices:
            service, day, version = next(iter(slices))
            expected = join_geographic_candidates(geo, rows, service=service,
                as_of=date.fromisoformat(day), framework_version=version)
            if joined != expected:
                issue('JOIN_MISMATCH', 'Joined payload differs from independent LEFT JOIN replay.')
    except (KeyError, TypeError, ValueError) as exc:
        issue('JOIN_SCHEMA', str(exc))
    if response is not None:
        try:
            expected = build_recommendation_response(response['request'], records, geo, tier_policy=tier_policy, ranking_config=ranking_config)
            if response != expected:
                issue('RESPONSE_MISMATCH', 'Response differs from complete pipeline replay (supply the same ranking configuration).')
            all_rows = response['recommendations'] + response['alternatives']
            if Counter(r['facility_id'] for r in all_rows) != Counter(g['facility_id'] for g in geo):
                issue('RESPONSE_RETENTION', 'Response removed or multiplied candidates.')
            if response['request']['mode'] == 'urgent':
                for r in response['recommendations']:
                    if not (r['service_evidence']['effective_tier'] == 'T1'
                            and r.get('capability_eligible') is True and r.get('capability_basis')
                            and r['distance_km'] is not None):
                        issue('UNSUPPORTED_URGENT_CAPABILITY', r['facility_id'])
            for r in all_rows:
                if 'service_available' in r or 'service_unavailable' in r:
                    issue('UNSUPPORTED_AVAILABILITY_CLAIM', r['facility_id'])
        except (KeyError, TypeError, ValueError) as exc:
            issue('RESPONSE_SCHEMA', str(exc))
    distribution = Counter(r.get('effective_tier', 'INVALID') for r in rows)
    return {'status': 'FAIL' if errors else 'PASS_WITH_WARNINGS' if warnings else 'PASS',
            'errors': errors, 'warnings': warnings,
            'counts': {'evidence_records': len(records), 'facility_service_rows': len(rows),
                       'geographic_candidates': len(geo), 'joined_rows': len(joined)},
            'tier_distribution': dict(sorted(distribution.items())),
            'unknown_output_rows': distribution.get('U', 0),
            'unknown_joined_candidates': sum(r.get('service_evidence', {}).get('effective_tier') == 'U' for r in joined),
            'limitations': ['Checks validate loaded adapter outputs, not source truth or retrieval completeness.',
                            'Canonical ID and service inventories must be supplied by source owners.',
                            'Unknown is not service absence; warnings require explicit upstream review.']}
