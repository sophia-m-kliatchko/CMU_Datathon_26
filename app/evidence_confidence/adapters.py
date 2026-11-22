"""Read-only row adapters for current team contracts. Inputs are mappings or Spark Rows.

No name matching, database access, writes, or free-text service inference happens here.
"""
from dataclasses import replace
from datetime import date, datetime
import hashlib
import json
from collections.abc import Mapping

from .engine import IDENTITY_REVIEW_FLAGS, INDIRECT_FLAGS
from .models import (Citation, DatePrecision, Directness, Evidence, FacilityMatch, LocationContext,
                     MatchStatus, Polarity, Scope, SourceKind, Verification, text, unit)


def _row(value):
    if hasattr(value, 'asDict'):
        value = value.asDict(recursive=True)
    if not isinstance(value, Mapping):
        raise ValueError('expected a mapping or Spark Row')
    return dict(value)


def _optional(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('expected text or None')
    return value.strip() or None


def _date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f'expected ISO date, got {value!r}') from exc
    raise ValueError('expected date/ISO date or None')


def _bool(value):
    if value is None or value == '':
        return None
    if type(value) is bool:
        return value
    if value in (0, 1) and not isinstance(value, str):
        return bool(value)
    if isinstance(value, str) and value.lower().strip() in ('true', 'false', '0', '1'):
        return value.lower().strip() in ('true', '1')
    raise ValueError(f'invalid boolean {value!r}')


def _flags(row):
    value = row.get('dq_flags') or ()
    if not isinstance(value, (list, tuple)):
        raise ValueError('dq_flags must be an array, not serialized text or a mapping')
    return tuple(text(v, 'dq_flags item') for v in value)


def _citation(row, table, key, statement):
    return (Citation(_optional(row.get('source_name')) or table,
                     _optional(row.get('source_url')) or f'{table}#{key}',
                     _optional(row.get('row_citation')) or statement),)


def _provenance(row):
    # Retain actual source metadata as immutable scalar pairs, including PDF row
    # citations. No fallback publisher, licence, date or canonical ID is invented.
    names = ('source_name', 'source_publisher', 'source_url', 'source_license',
             'retrieved_on', 'produced_by', 'row_citation', 'source_file',
             'source_page', 's_no', 'evidence_date', 'validity_from_raw',
             'validity_to_raw', 'financial_year', 'award_raw')
    return tuple((key, row[key]) for key in names if key in row)


def _reference(match, key):
    if not isinstance(match, FacilityMatch) or match.reference_id != key:
        raise ValueError(f'explicit FacilityMatch.reference_id must equal {key!r}; no name-only join')
    return match


def _with_flags(match, flags):
    flags = tuple(dict.fromkeys(match.flags + tuple(flags)))
    status = MatchStatus.PENDING if match.status == MatchStatus.ACCEPTED and IDENTITY_REVIEW_FLAGS.intersection(flags) else match.status
    return replace(match, flags=flags, status=status)


def registry_match(link, *, reviewer_decision=None):
    """Notebook 06 match_score / 100 is a heuristic, not calibrated match probability.

    Missing needs_review/match_score/method does not become an accepted association.
    A human decision never fabricates a missing numeric match score.
    """
    r = _row(link)
    fid, site = text(r.get('facility_id'), 'facility_id'), text(r.get('site_id'), 'site_id')
    confidence = None
    if r.get('match_score') is not None:
        raw = r['match_score']
        if isinstance(raw, bool):
            raise ValueError('match_score must be numeric 0-100')
        confidence = unit(float(raw) / 100, 'match_score / 100')
    needs_review = _bool(r.get('needs_review'))
    method = _optional(r.get('match_method'))
    if reviewer_decision not in (None, 'confirm', 'reject'):
        raise ValueError('reviewer_decision must be confirm/reject or None')
    if reviewer_decision == 'reject':
        status = MatchStatus.REJECTED
    elif reviewer_decision == 'confirm':
        status = MatchStatus.ACCEPTED
    elif needs_review is True:
        status = MatchStatus.PENDING
    elif needs_review is False and confidence is not None and method is not None:
        status = MatchStatus.ACCEPTED
    else:
        status = MatchStatus.UNKNOWN
    flags = _flags(r) + (('MATCH_AMBIGUOUS',) if needs_review and reviewer_decision is None else ())
    return FacilityMatch(fid, status, confidence, method or 'unspecified', site, flags)


KINDS = {
    'government_certification': SourceKind.GOVERNMENT_REGISTRY,
    'government_designation': SourceKind.GOVERNMENT_REGISTRY,
    'government_training_approval': SourceKind.GOVERNMENT_REGISTRY,
    'government_scheme_empanelment': SourceKind.GOVERNMENT_REGISTRY,
    'independent_accreditation': SourceKind.ACCREDITATION,
    'network_membership': SourceKind.NETWORK,
}
QUALITY_CATEGORIES = frozenset({'hospital_accreditation', 'entry_level_certification', 'quality_certification'})
NON_SERVICE_CATEGORIES = QUALITY_CATEGORIES | {'empanelment', 'ayush'}


def from_registry_service(row, match, *, site=None):
    """Notebook 05 service row + explicit notebook 06 link. Summary arrays are insufficient."""
    r = _row(row)
    site_id = text(r.get('site_id'), 'site_id')
    _reference(match, site_id)
    source = text(r.get('source'), 'source')
    if not site_id.startswith(source + ':'):
        raise ValueError('site_id/source mismatch')
    key = text(r.get('service_row_id'), 'service_row_id')
    service = text(r.get('service'), 'service')
    flags = _flags(r)
    if site is not None:
        s = _row(site)
        if s.get('site_id') != site_id or s.get('source') != source:
            raise ValueError('service/site keys or source do not match')
        if s.get('listing_category') in NON_SERVICE_CATEGORIES:
            raise ValueError('general accreditation/empanelment belongs to quality/identity, not a service row')
        flags += _flags(s)
    kind = KINDS.get(r.get('evidence_type'), SourceKind.UNKNOWN)
    direct = (_bool(r.get('service_specific')) is True
              and r.get('evidence_type') in ('government_certification', 'independent_accreditation')
              and source not in ('nmc', 'dnb', 'ncg', 'trauma')
              and not INDIRECT_FLAGS.intersection(flags))
    # Even service_specific=true membership/designation is not verified operating capability.
    verification = Verification.INDEPENDENT if direct else Verification.INFERRED if kind != SourceKind.UNKNOWN else Verification.UNKNOWN
    status = _optional(r.get('status'))
    supported_status = status in ('certified', 'conditional', 'sanctioned', 'approved', 'accredited', 'member',
                                  'empaneled', 'empanelled', 'not_current', 'expired')
    if status == 'conditional':
        flags += ('CONDITIONAL_CERTIFICATION',)
    current = _bool(r.get('is_current'))
    if current is None:
        current = _bool(r.get('listing_current'))
    if current is None and site is not None:
        current = _bool(s.get('listing_current'))
    if status in ('not_current', 'expired') or {'CERTIFICATION_EXPIRED', 'LISTING_NOT_CURRENT'}.intersection(flags):
        current = False
    observed = _date(r.get('evidence_date'))
    valid_until = _date(r.get('valid_until'))
    if source == 'ncg':
        # Notebook 05's evidence_date is a member-list snapshot, not service freshness.
        observed = None
        flags += ('SNAPSHOT_NOT_SERVICE_EVENT',)
    if source == 'trauma':
        # Notebook 05 uses the parliamentary answer's date, not the 2007-2017 sanction date.
        observed = None
        flags += ('DOCUMENT_DATE_NOT_SERVICE_EVENT',)
    precision = DatePrecision.YEAR if 'DATE_IS_YEAR_ONLY' in flags else DatePrecision.EXACT if observed else DatePrecision.UNKNOWN
    if precision == DatePrecision.YEAR:
        observed = None  # Preserve the qualifier, not a fictitious Jan 1 event.
    valid_from = _date(r.get('valid_from'))
    if (valid_from is None and direct and precision == DatePrecision.EXACT
            and valid_until is not None and observed is not None and observed <= valid_until):
        valid_from = observed  # Exact certification issue/evidence date in the registry contract.
    statement = text(r.get('evidence_detail'), 'evidence_detail')
    return Evidence(f'registry:{key}:{match.facility_id}', source, kind, Scope.SERVICE, statement,
                    _with_flags(match, flags), service, Polarity.SUPPORTS if supported_status else Polarity.UNKNOWN,
                    verification, Directness.DIRECT if direct else Directness.INDIRECT,
                    observed_on=observed, valid_from=valid_from, valid_until=valid_until,
                    retrieved_on=_date(r.get('retrieved_on')), date_precision=precision,
                    current_status=current if valid_until is None else None,
                    source_record_id=key, source_provenance=_provenance(r), independence_group=f'registry:{source}', citations=_citation(r, 'registry_services_silver', key, statement),
                    qualifiers=tuple(dict.fromkeys(flags + (('STATUS_UNRECOGNIZED',) if not supported_status else ()))))


def from_registry_site(row, match):
    """A site listing proves neither a requested service nor membership in every programme."""
    r = _row(row)
    key = text(r.get('site_id'), 'site_id')
    _reference(match, key)
    source = text(r.get('source'), 'source')
    if not key.startswith(source + ':'):
        raise ValueError('site_id/source mismatch')
    quality = r.get('listing_category') in QUALITY_CATEGORIES
    statement = _optional(r.get('row_citation')) or f"Registry listing: {text(r.get('name'), 'name')}; {r.get('listing_type') or 'scope unspecified'}."
    flags = _flags(r)
    if 'listing_current' in r and _bool(r['listing_current']) is False:
        flags += ('LISTING_NOT_CURRENT',)
    observed = _date(r.get('evidence_date'))
    kind = SourceKind.ACCREDITATION if quality else SourceKind.GOVERNMENT_REGISTRY if r.get('listing_category') == 'empanelment' else SourceKind.UNKNOWN
    precision = DatePrecision.YEAR if 'DATE_IS_YEAR_ONLY' in flags else DatePrecision.EXACT if observed else DatePrecision.UNKNOWN
    return Evidence(f'site:{key}:{match.facility_id}', source, kind,
                    Scope.QUALITY if quality else Scope.IDENTITY, statement, _with_flags(match, flags),
                    verification=Verification.INDEPENDENT if quality else Verification.UNKNOWN,
                    directness=Directness.DIRECT, observed_on=observed, date_precision=precision,
                    current_status=_bool(r.get('listing_current')), retrieved_on=_date(r.get('retrieved_on')),
                    source_record_id=key, source_provenance=_provenance(r), independence_group=f'registry:{source}', citations=_citation(r, 'registry_sites_silver', key, statement),
                    qualifiers=flags + ('LISTING_IS_NOT_SERVICE_VERIFICATION',))


def from_registry_service_context(row, match, *, site):
    """Preserve a tagged row whose listing is explicitly quality/identity only.

    This does not relax from_registry_service's direct-service scope guard.
    Original row ID, statement, citations, dates and upstream tag are retained.
    """
    parent = _row(site)
    if parent.get('listing_category') not in NON_SERVICE_CATEGORIES:
        raise ValueError('context routing requires an explicitly non-service listing category')
    context = from_registry_site(parent, match)
    evidence = from_registry_service(row, context.match)
    return replace(evidence, scope=context.scope, service=None,
        qualifiers=tuple(dict.fromkeys(evidence.qualifiers + ('LISTING_IS_NOT_SERVICE_VERIFICATION',
            'UPSTREAM_SERVICE_TAG_IS_NON_SERVICE_CONTEXT'))),
        source_provenance=evidence.source_provenance + (('upstream_service_tag', evidence.service),))


def from_facility_claim(row, *, service, polarity, direct=False, observed_on=None, citations=(), facility_flags=()):
    """Canonical service and assertion polarity MUST be supplied by a reviewed service matcher.

    No substring matching of 'ent', no 'nephrology => dialysis', no automatic negation parsing.
    Equipment/specialties remain indirect even when direct=True is supplied.
    """
    r = _row(row)
    fid = text(r.get('facility_id'), 'facility_id')
    field = text(r.get('claim_field'), 'claim_field')
    if field not in ('specialties', 'capability', 'procedure', 'equipment'):
        raise ValueError('unsupported claim_field; descriptions require an explicit generic Evidence record')
    statement = text(r.get('claim_text'), 'claim_text')
    position = r.get('claim_position')
    signature = json.dumps([fid, field, position, statement], ensure_ascii=False)
    key = hashlib.sha256(signature.encode()).hexdigest()[:24]
    match = _with_flags(FacilityMatch(fid, MatchStatus.ACCEPTED, 1., 'same_canonical_facility_id'), tuple(facility_flags))
    return Evidence(f'vf:{key}', 'virtue_foundation', SourceKind.SELF_REPORT, Scope.SERVICE, statement, match,
                    text(service, 'service'), Polarity(polarity), Verification.SELF_REPORTED,
                    Directness.DIRECT if direct and field in ('capability', 'procedure') else Directness.INDIRECT,
                    observed_on=_date(observed_on), independence_group='virtue_foundation',
                    citations=tuple(citations) or (Citation('silver_facility_claims (self-reported)',
                        'silver_facility_claims:' + signature, statement),),
                    qualifiers=('SELF_REPORTED_SOURCE',) + tuple(facility_flags))


def from_kayakalp(row, match):
    """Supports the historical award assertion only; never service availability."""
    r = _row(row)
    key = text(r.get('award_id'), 'award_id')
    _reference(match, key)
    fy = text(r.get('financial_year'), 'financial_year')
    import re
    if not re.fullmatch(r'\d{4}-\d{2}', fy) or (int(fy[:4]) + 1) % 100 != int(fy[-2:]):
        raise ValueError('expected a consecutive financial year YYYY-YY')
    # Reference-period endpoint only: not a known award/inspection date or its upper bound.
    observed = date(int(fy[:4]) + 1, 3, 31)
    statement = _optional(r.get('row_citation')) or f"Kayakalp {fy}: {text(r.get('award_raw'), 'award_raw')}."
    flags = _flags(r) + ('HISTORICAL_CLEANLINESS_AWARD', 'DATE_IS_FY_END_REFERENCE')
    return Evidence(f'kayakalp:{key}:{match.facility_id}', 'kayakalp', SourceKind.GOVERNMENT_REGISTRY,
                    Scope.CLEANLINESS, statement, _with_flags(match, flags),
                    verification=Verification.INDEPENDENT, directness=Directness.DIRECT,
                    observed_on=observed, retrieved_on=_date(r.get('retrieved_on')),
                    date_precision=DatePrecision.FINANCIAL_YEAR, source_record_id=key, source_provenance=_provenance(r), independence_group=f'nhsrc:kayakalp:{fy}',
                    citations=_citation(r, 'kayakalp_silver', key, statement), qualifiers=flags)


def from_nqas(row, match):
    """Certificate scope remains quality, even when departments mention a requested service."""
    r = _row(row)
    key = text(r.get('certification_id'), 'certification_id')
    _reference(match, key)
    statement = _optional(r.get('row_citation')) or text(r.get('department_assessed'), 'department_assessed')
    flags = _flags(r)
    if _bool(r.get('covers_all_departments')) is not True:
        flags += ('PARTIAL_OR_UNKNOWN_DEPARTMENT_SCOPE',)
    valid_until = _date(r.get('validity_to'))
    current = False if r.get('certification_status') == 'expired' else None  # Recompute against assess(as_of), not build-date status.
    return Evidence(f'nqas:{key}:{match.facility_id}', 'nqas', SourceKind.GOVERNMENT_REGISTRY,
                    Scope.QUALITY, statement, _with_flags(match, flags),
                    verification=Verification.INDEPENDENT, directness=Directness.DIRECT,
                    observed_on=_date(r.get('validity_from')), valid_from=_date(r.get('validity_from')),
                    valid_until=valid_until, retrieved_on=_date(r.get('retrieved_on')),
                    current_status=current if valid_until is None else None,
                    source_record_id=key, source_provenance=_provenance(r), independence_group='nhsrc:nqas', citations=_citation(r, 'nqas_silver', key, statement), qualifiers=flags)


def _alias(row, current, legacy):
    a, b = row.get(current), row.get(legacy)
    if a is not None and b is not None and a != b:
        raise ValueError(f'conflicting {current}/{legacy} values; no silent alias preference')
    return a if a is not None else b


def location_context(row, *, basis):
    """Elliot/Sophia coordinate contract. A PIN centroid stays a centroid, never a hospital point.

    basis is required; no auto-detection can distinguish identical latitude/longitude column names.
    This does not manufacture a facility match, verified service, or quality score.
    """
    r = _row(row)
    flags = _flags(r)
    if _bool(r.get('pin_ambiguous')) is True:
        flags += ('PIN_AMBIGUOUS',)
    if basis == 'pin_centroid':
        flags += ('PIN_CENTROID_NOT_FACILITY_LOCATION',)
    if r.get('centroid_quality'):
        flags += ('CENTROID_' + str(r['centroid_quality']).upper(),)
    lat, lon = _alias(r, 'latitude', 'latitude_clean'), _alias(r, 'longitude', 'longitude_clean')
    if (r.get('coord_status') not in (None, 'ok', 'swapped_fixed')
            or {'MISSING_COORDS', 'COORDS_ZERO', 'COORDS_OUTSIDE_INDIA'}.intersection(flags)):
        lat, lon = None, None
        flags += ('UNUSABLE_COORDINATES',)
    return LocationContext(basis, lat, lon, _alias(r, 'state', 'state_clean') or r.get('main_state'),
                           _alias(r, 'district', 'district_clean') or r.get('main_district'), flags,
                           _optional(r.get('facility_id')))
