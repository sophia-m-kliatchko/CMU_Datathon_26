"""Schema-independent, immutable input/output contracts. No database dependencies."""
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from collections.abc import Mapping
from types import MappingProxyType
import json
import math
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from .tiers import TierAssessment


class Scope(str, Enum):
    SERVICE = 'service'
    QUALITY = 'quality'
    CLEANLINESS = 'cleanliness'
    IDENTITY = 'identity'


class SourceKind(str, Enum):
    SELF_REPORT = 'self_report'
    GOVERNMENT_REGISTRY = 'government_registry'
    ACCREDITATION = 'accreditation'
    INDEPENDENT_CHECK = 'independent_check'
    NETWORK = 'network'
    UNKNOWN = 'unknown'


class Verification(str, Enum):
    SELF_REPORTED = 'self_reported'
    INDEPENDENT = 'independent'
    INFERRED = 'inferred'
    UNKNOWN = 'unknown'


class Directness(str, Enum):
    DIRECT = 'direct'
    INDIRECT = 'indirect'
    CONTEXT = 'context'


class Polarity(str, Enum):
    SUPPORTS = 'supports'
    CONTRADICTS = 'contradicts'
    UNKNOWN = 'unknown'


class MatchStatus(str, Enum):
    ACCEPTED = 'accepted'
    PENDING = 'pending'
    REJECTED = 'rejected'
    UNKNOWN = 'unknown'


class DatePrecision(str, Enum):
    EXACT = 'exact'
    YEAR = 'year'
    FINANCIAL_YEAR = 'financial_year'
    UNKNOWN = 'unknown'


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonblank string')
    return value.strip()


def unit(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'{name} must be a finite number in [0, 1]')
    return float(value)


def day(value, name):
    if value is not None and type(value) is not date:
        raise ValueError(f'{name} must be a date (not datetime) or None')
    return value


def strings(values, name):
    if isinstance(values, str):
        raise ValueError(f'{name} must be a sequence, not a string')
    return tuple(dict.fromkeys(text(v, name) for v in values))


@dataclass(frozen=True)
class Citation:
    label: str
    locator: str  # Actual URL or table/record locator supplied by caller; never fabricated.
    quote: str = ''

    def __post_init__(self):
        for name in ('label', 'locator'):
            object.__setattr__(self, name, text(getattr(self, name), name))
        if not isinstance(self.quote, str):
            raise ValueError('quote must be a string')


@dataclass(frozen=True)
class FacilityMatch:
    facility_id: str
    status: MatchStatus = MatchStatus.UNKNOWN
    confidence: Optional[float] = None  # Upstream heuristic score, NOT a probability.
    method: str = 'unspecified'
    reference_id: Optional[str] = None  # site_id / award_id / certification_id being linked.
    flags: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'facility_id', text(self.facility_id, 'facility_id'))
        object.__setattr__(self, 'status', MatchStatus(self.status))
        object.__setattr__(self, 'method', text(self.method, 'method'))
        if self.reference_id is not None:
            object.__setattr__(self, 'reference_id', text(self.reference_id, 'reference_id'))
        if self.confidence is not None:
            unit(self.confidence, 'match confidence')
        object.__setattr__(self, 'flags', strings(self.flags, 'match flags'))


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    source_kind: SourceKind
    scope: Scope
    statement: str
    match: FacilityMatch
    service: Optional[str] = None
    polarity: Polarity = Polarity.SUPPORTS
    verification: Verification = Verification.UNKNOWN
    directness: Directness = Directness.INDIRECT
    observed_on: Optional[date] = None  # Event/assessment date, never scrape date by default.
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    retrieved_on: Optional[date] = None
    date_precision: DatePrecision = DatePrecision.EXACT
    current_status: Optional[bool] = None  # False discounts historical evidence; true never refreshes dates.
    independence_group: Optional[str] = None
    citations: Tuple[Citation, ...] = ()
    qualifiers: Tuple[str, ...] = ()
    source_record_id: Optional[str] = None  # Stable ID within source family; never a facility/site ID.
    source_provenance: tuple = ()  # Immutable (field, original scalar value) pairs; no scoring effect.

    def __post_init__(self):
        for name in ('evidence_id', 'source_id', 'statement'):
            object.__setattr__(self, name, text(getattr(self, name), name))
        for name, typ in [('scope', Scope), ('source_kind', SourceKind), ('polarity', Polarity),
                          ('verification', Verification), ('directness', Directness), ('date_precision', DatePrecision)]:
            object.__setattr__(self, name, typ(getattr(self, name)))
        if not isinstance(self.match, FacilityMatch):
            raise ValueError('match must be a FacilityMatch')
        if self.service is not None:
            object.__setattr__(self, 'service', text(self.service, 'service'))
        if self.scope == Scope.SERVICE and self.service is None:
            raise ValueError('service evidence requires a canonical service tag')
        if self.scope != Scope.SERVICE and self.service is not None:
            raise ValueError('non-service evidence cannot carry a service tag')
        if self.source_kind == SourceKind.SELF_REPORT and self.verification == Verification.INDEPENDENT:
            raise ValueError('self-report cannot be independently verified by itself')
        for name in ('observed_on', 'valid_from', 'valid_until', 'retrieved_on'):
            day(getattr(self, name), name)
        if self.current_status is not None and type(self.current_status) is not bool:
            raise ValueError('current_status must be bool or None')
        provenance = tuple(tuple(item) for item in self.source_provenance)
        names = set()
        for item in provenance:
            if len(item) != 2 or not isinstance(item[0], str) or not item[0].strip() or item[0] in names:
                raise ValueError('source_provenance requires unique nonblank field names')
            value = item[1]
            if value is not None and type(value) not in (str, int, float, bool, date, datetime):
                raise ValueError('source_provenance values must be scalar or date')
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError('source_provenance requires finite numbers')
            names.add(item[0])
        object.__setattr__(self, 'source_provenance', tuple(sorted(provenance)))
        if self.source_record_id is not None:
            object.__setattr__(self, 'source_record_id', text(self.source_record_id, 'source_record_id'))
        if self.independence_group is not None:
            object.__setattr__(self, 'independence_group', text(self.independence_group, 'independence_group'))
        object.__setattr__(self, 'citations', tuple(self.citations))
        if any(not isinstance(c, Citation) for c in self.citations):
            raise ValueError('citations must contain Citation objects')
        object.__setattr__(self, 'qualifiers', strings(self.qualifiers, 'qualifiers'))


@dataclass(frozen=True)
class LocationContext:
    """Location metadata only; never added to service or quality scores."""
    basis: str  # site_coordinates / pin_centroid / unknown
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    state: Optional[str] = None
    district: Optional[str] = None
    flags: Tuple[str, ...] = ()
    facility_id: Optional[str] = None

    def __post_init__(self):
        if self.facility_id is not None:
            object.__setattr__(self, 'facility_id', text(self.facility_id, 'location facility_id'))
        for name in ('state', 'district'):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, text(getattr(self, name), name))
        if self.basis not in ('site_coordinates', 'pin_centroid', 'unknown'):
            raise ValueError('unrecognized coordinate basis')
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('latitude and longitude must both be present or both absent')
        if self.latitude is not None:
            for v, limit in [(self.latitude, 90), (self.longitude, 180)]:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > limit:
                    raise ValueError('invalid coordinate')
            if self.basis == 'unknown':
                raise ValueError('coordinates require explicit basis')
        object.__setattr__(self, 'flags', strings(self.flags, 'location flags'))


@dataclass(frozen=True)
class Contribution:
    evidence: Evidence
    reliability: float
    match_confidence: float
    recency: float
    temporal_status: str
    strength: float  # 0..1 heuristic evidence strength after gates/caps.
    independent_current_support: bool
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class LaneAssessment:
    scope: Scope
    score: Optional[float]  # 0..100 supporting evidence score; None = no scoreable support.
    category: str
    status: str
    support_strength: float
    counterevidence_strength: float
    agreement_gain: float
    contradiction_reduction: float
    independent_groups: int  # Positive contributing source lineages, not all referenced sources.
    independent_current_evidence_ids: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    citations: Tuple[Citation, ...]
    explanations: Tuple[str, ...]
    contributions: Tuple[Contribution, ...]


@dataclass(frozen=True)
class Assessment:
    facility_id: str
    requested_service: str
    as_of: date
    model_version: str
    policy_fingerprint: str
    policy: dict
    service_availability: LaneAssessment
    quality_evidence: LaneAssessment
    cleanliness_evidence: LaneAssessment
    identity_evidence: LaneAssessment
    location: Optional[LocationContext]
    excluded: Tuple[Tuple[str, str], ...]
    duplicate_evidence_ids: Tuple[str, ...]
    limitations: Tuple[str, ...]
    service_evidence: Optional["TierAssessment"] = None  # Primary categorical output; legacy lanes retained.

    def __post_init__(self):
        def freeze(value):
            if isinstance(value, Mapping):
                return MappingProxyType({k: freeze(v) for k, v in value.items()})
            return value
        object.__setattr__(self, 'policy', freeze(self.policy))

    def to_dict(self):
        return _jsonable(self)

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(), allow_nan=False, **kwargs)


def _jsonable(x):
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, date):
        return x.isoformat()
    if is_dataclass(x):
        return {f.name: _jsonable(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, Mapping):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, (tuple, list)):
        return [_jsonable(v) for v in x]
    return x
