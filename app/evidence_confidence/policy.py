"""Explicit policy choices, not fitted/calibrated probabilities."""
from dataclasses import dataclass, field, fields
import hashlib
import json
from types import MappingProxyType

from .models import Directness, SourceKind, text, unit


@dataclass(frozen=True)
class Policy:
    version: str = 'baseline-1'
    weights: dict = field(default_factory=lambda: {'reliability': .4, 'facility_match': .35, 'recency': .25})
    source_reliability: dict = field(default_factory=lambda: {
        'self_report': .45, 'government_registry': .85, 'accreditation': .85,
        'independent_check': .9, 'network': .6, 'unknown': .2})
    source_overrides: dict = field(default_factory=dict)
    directness: dict = field(default_factory=lambda: {'direct': 1., 'indirect': .5, 'context': .25})
    half_life_days: float = 365.
    current_evidence_days: int = 365
    unknown_recency: float = .35
    expired_multiplier: float = .2
    pending_match_multiplier: float = .25
    conditional_multiplier: float = .8
    uncited_multiplier: float = .25
    agreement_bonus: float = .15
    contradiction_penalty: float = 1.
    conflict_threshold: float = .2
    qualified_match_min: float = .85
    qualified_strength_min: float = .65
    self_report_cap: float = .55
    indirect_cap: float = .6
    unknown_date_cap: float = .45
    historical_cap: float = .4
    pending_cap: float = .25
    uncited_cap: float = .25
    conflict_cap: float = .35
    medium_threshold: float = .4
    high_threshold: float = .7

    def __post_init__(self):
        text(self.version, 'version')
        for name, required in [('weights', {'reliability', 'facility_match', 'recency'}),
                               ('source_reliability', {v.value for v in SourceKind}),
                               ('directness', {v.value for v in Directness})]:
            value = dict(getattr(self, name))
            if set(value) != required:
                raise ValueError(f'{name} requires exactly {sorted(required)}')
            for k, v in value.items():
                unit(v, f'{name}.{k}')
            if name == 'weights' and sum(value.values()) <= 0:
                raise ValueError('weights must have positive total')
            object.__setattr__(self, name, MappingProxyType(value))
        overrides = dict(self.source_overrides)
        for k, v in overrides.items():
            text(k, 'source override key')
            unit(v, 'source override reliability')
        object.__setattr__(self, 'source_overrides', MappingProxyType(overrides))
        for f in fields(self):
            if f.name not in ('version', 'weights', 'source_reliability', 'source_overrides', 'directness', 'half_life_days', 'current_evidence_days'):
                unit(getattr(self, f.name), f.name)
        import math
        if isinstance(self.half_life_days, bool) or not isinstance(self.half_life_days, (int, float)) or not math.isfinite(self.half_life_days) or self.half_life_days <= 0:
            raise ValueError('half_life_days must be finite and positive')
        if type(self.current_evidence_days) is not int or self.current_evidence_days < 1:
            raise ValueError('current_evidence_days must be a positive integer')
        if not 0 < self.medium_threshold < self.high_threshold <= 1:
            raise ValueError('category thresholds must increase in (0,1]')

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise ValueError('policy must be an object')
        unknown = set(values) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f'unknown policy keys: {sorted(unknown)}')
        return cls(**values)

    @classmethod
    def from_json(cls, path):
        with open(path, encoding='utf-8') as handle:
            return cls.from_dict(json.load(handle))

    def to_dict(self):
        return {f.name: dict(getattr(self, f.name)) if isinstance(getattr(self, f.name), MappingProxyType)
                else getattr(self, f.name) for f in fields(self)}

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, allow_nan=False).encode()).hexdigest()
