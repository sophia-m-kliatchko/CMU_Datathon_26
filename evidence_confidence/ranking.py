"""Isolated provisional ranking interface. No teammate ranking code is imported or changed."""
from dataclasses import dataclass, field, fields
import json
import math
from types import MappingProxyType
from typing import Iterable, Optional

from .models import _jsonable, text
from .tiers import EvidenceFlags, Tier, TierAssessment


@dataclass(frozen=True)
class RankingConfig:
    distance_bands_km: tuple = (10., 25., 50.)  # Provisional display/ranking bins; not clinical rules.
    tier_priority: dict = field(default_factory=lambda: {'T1': 0, 'T2': 1, 'T3': 2, 'U': 3, 'R': 3, 'X': 3})
    ordinal_flag_order: tuple = ('conflicting_evidence', 'identity_review', 'expired_certification',
                                'current_listing_undated', 'date_year_only', 'conditional_certification')

    def __post_init__(self):
        bands = tuple(self.distance_bands_km)
        if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0 for x in bands)
                or any(b <= a for a, b in zip(bands, bands[1:]))):
            raise ValueError('distance_bands_km must be finite, positive and strictly increasing')
        priority = dict(self.tier_priority)
        if set(priority) != {t.value for t in Tier} or any(type(v) is not int or v < 0 for v in priority.values()):
            raise ValueError('tier_priority must map all six tiers to nonnegative ordinal integers')
        allowed = {f.name for f in fields(EvidenceFlags)}
        flag_order = tuple(self.ordinal_flag_order)
        if len(set(flag_order)) != len(flag_order) or not set(flag_order) <= allowed:
            raise ValueError('ordinal_flag_order must contain distinct known evidence flag names')
        object.__setattr__(self, 'distance_bands_km', bands)
        object.__setattr__(self, 'tier_priority', MappingProxyType(priority))
        object.__setattr__(self, 'ordinal_flag_order', flag_order)

    @classmethod
    def from_json(cls, path):
        with open(path, encoding='utf-8') as handle:
            return cls(**json.load(handle))


@dataclass(frozen=True)
class Candidate:
    facility_id: str
    evidence: Optional[TierAssessment] = None  # No evidence stays U; it is never removed.
    distance_km: Optional[float] = None
    capability_eligible: Optional[bool] = None  # Separate upstream operational/capability decision.
    capability_basis: Optional[str] = None  # Required to use an explicit True in urgent ranking.

    def __post_init__(self):
        object.__setattr__(self, 'facility_id', text(self.facility_id, 'facility_id'))
        if self.evidence is not None:
            if not isinstance(self.evidence, TierAssessment) or self.evidence.facility_id != self.facility_id:
                raise ValueError('candidate and tier assessment must refer to the same facility_id')
        if self.distance_km is not None and (isinstance(self.distance_km, bool) or not isinstance(self.distance_km, (int, float))
                                              or not math.isfinite(self.distance_km) or self.distance_km < 0):
            raise ValueError('distance_km must be finite and nonnegative or None')
        if self.capability_eligible is not None and type(self.capability_eligible) is not bool:
            raise ValueError('capability_eligible must be bool or None')
        if self.capability_basis is not None:
            object.__setattr__(self, 'capability_basis', text(self.capability_basis, 'capability_basis'))


@dataclass(frozen=True)
class RankedCandidate:
    candidate: Candidate
    effective_tier: Tier
    label: str
    distance_band: int  # len(bands)+1 represents unknown distance, after all known bins.
    ordinal_evidence_flags: tuple
    sort_key: tuple  # Missing exact distance remains None in serializable metadata.


@dataclass(frozen=True)
class RankingResult:
    mode: str
    ranked: tuple
    alternatives: tuple
    requires_review: bool
    status: str
    provisional: bool
    explanation: tuple
    config: RankingConfig

    def to_dict(self):
        return _jsonable(self)

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(), allow_nan=False, **kwargs)


def rank_candidates(candidates: Iterable[Candidate], mode='routine', config=None) -> RankingResult:
    """Routine tier/band/flags/distance; urgent explicitly eligible T1 first by distance.

    All input facilities appear exactly once across ranked and alternatives. Proximity
    never establishes capability. No urgent detour radius or clinical cutoff is assumed.
    """
    if mode not in ('routine', 'urgent'):
        raise ValueError('mode must be routine or urgent')
    if config is None:
        config = RankingConfig()
    elif isinstance(config, dict):
        config = RankingConfig(**config)
    if not isinstance(config, RankingConfig):
        raise ValueError('config must be RankingConfig or a configuration mapping')
    rows = tuple(Candidate(**c) if isinstance(c, dict) else c for c in candidates)
    if any(not isinstance(c, Candidate) for c in rows):
        raise ValueError('candidates must contain Candidate objects or row dictionaries')
    if len({c.facility_id for c in rows}) != len(rows):
        raise ValueError('duplicate facility_id candidates; resolve input identity without silently deleting a facility')
    if len({c.evidence.service for c in rows if c.evidence is not None}) > 1:
        raise ValueError('cannot rank different requested services in one list')
    if len({c.evidence.as_of for c in rows if c.evidence is not None}) > 1:
        raise ValueError('cannot rank tier assessments with different as_of dates')
    ranked, alternatives = [], []
    requires_review = False
    for c in rows:
        tier = c.evidence.effective_tier if c.evidence else Tier.U
        flags = c.evidence.flags if c.evidence else EvidenceFlags()
        ordinal = tuple(int(getattr(flags, flag)) for flag in config.ordinal_flag_order)
        band = (len(config.distance_bands_km) + 1 if c.distance_km is None else
                next((i for i, edge in enumerate(config.distance_bands_km) if c.distance_km <= edge), len(config.distance_bands_km)))
        priority = config.tier_priority[tier.value]
        if mode == 'routine':
            key = (priority, band, ordinal, c.distance_km)
            label = 'documentary_tier_not_operational_guarantee' if tier in (Tier.T1, Tier.T2, Tier.T3) else 'unknown_or_review_service_evidence'
            ranked.append(RankedCandidate(c, tier, label, band, ordinal, key))
            requires_review |= tier in (Tier.U, Tier.R, Tier.X) or c.distance_km is None
        else:
            eligible = (tier == Tier.T1 and c.capability_eligible is True and bool(c.capability_basis)
                        and c.distance_km is not None)
            if eligible:
                key = (c.distance_km, ordinal, priority)
                ranked.append(RankedCandidate(c, tier, 'eligible_by_supplied_capability_assessment', band, ordinal, key))
            else:
                key = (c.distance_km, priority, ordinal)
                if tier in (Tier.U, Tier.R, Tier.X):
                    label = 'nearby_alternative_not_confirmed_emergency_capable'
                elif c.capability_eligible is False:
                    label = 'alternative_not_eligible_under_supplied_capability_assessment'
                else:
                    label = 'alternative_requires_capability_or_distance_review'
                alternatives.append(RankedCandidate(c, tier, label, band, ordinal, key))
                requires_review |= c.capability_eligible is not False
    # None exact distances sort after finite values; no Infinity leaks into JSON.
    def sort_key(row):
        if mode == 'routine':
            p, band, ordinal, distance = row.sort_key
            return p, band, ordinal, float('inf') if distance is None else distance, row.candidate.facility_id
        distance, rest1, rest2 = row.sort_key
        return float('inf') if distance is None else distance, rest1, rest2, row.candidate.facility_id
    ranked.sort(key=sort_key)
    alternatives.sort(key=sort_key)
    if mode == 'urgent' and not ranked and rows:
        requires_review = True
    explanation = (
        'Ranking parameters and distance bands are provisional, pending cleaned-data validation and team agreement.',
        'Routine ordering: tier priority, distance band, ordinal evidence flags, exact distance, then stable facility ID.',
        'Urgent ordering: explicitly capability-eligible T1 candidates by exact distance; all other facilities retained as labelled alternatives.',
        'No proximity-to-capability inference, emergency-care guarantee or fixed urgent detour rule is implemented.',
    )
    return RankingResult(mode, tuple(ranked), tuple(alternatives), requires_review,
                         'requires_review' if requires_review else 'provisional', True, explanation, config)
