"""Primary deterministic Evidence Tier Framework. Never uses numerical confidence scores."""
from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
import json
from typing import Iterable, Optional

from .engine import IDENTITY_REVIEW_FLAGS, INDIRECT_FLAGS, canonical_service
from .models import (Citation, DatePrecision, Directness, Evidence, MatchStatus, Polarity,
                     Scope, SourceKind, Verification, day, text, _jsonable)
from .temporal import temporal_validity


class Tier(str, Enum):
    T1 = 'T1'
    T2 = 'T2'
    T3 = 'T3'
    U = 'U'
    R = 'R'
    X = 'X'


@dataclass(frozen=True)
class TierPolicy:
    # Reuses the previous baseline's 365-day horizon for undelimited negative notices.
    # A time policy for empirical review, NOT a scoring weight or clinical rule.
    contradiction_max_age_days: int = 365

    def __post_init__(self):
        if type(self.contradiction_max_age_days) is not int or self.contradiction_max_age_days < 1:
            raise ValueError('contradiction_max_age_days must be a positive integer')

    @classmethod
    def from_json(cls, path):
        with open(path, encoding='utf-8') as handle:
            return cls(**json.load(handle))


@dataclass(frozen=True)
class EvidenceFlags:
    conditional_certification: bool = False
    date_year_only: bool = False
    current_listing_undated: bool = False
    expired_certification: bool = False
    identity_review: bool = False
    conflicting_evidence: bool = False
    missing_citation: bool = False
    temporal_uncertainty: bool = False
    rejected_candidate_match: bool = False


@dataclass(frozen=True)
class EvidenceDecision:
    evidence_id: str
    source_family: str
    evidence_basis: str
    match_status: str
    temporal_status: str
    candidate_tier: Optional[Tier]
    credited: bool
    credible_contradiction: bool
    reasons: tuple


@dataclass(frozen=True)
class TierAssessment:
    facility_id: str
    service: str
    as_of: date
    base_tier: Tier
    effective_tier: Tier
    review_status: str
    flags: EvidenceFlags
    supporting_source_families: tuple
    supporting_source_count: int  # Distinct families, not rows, snapshots or source URLs.
    supporting_record_count: int
    evidence_basis: tuple
    citations: tuple
    explanation: tuple
    decisions: tuple
    duplicate_of: tuple
    excluded: tuple
    quality_evidence_ids: tuple
    cleanliness_evidence_ids: tuple
    identity_evidence_ids: tuple
    assumptions: tuple
    contradiction_max_age_days: int
    framework_version: str = 'evidence-tiers/1'
    pending_stronger_tier: Optional[Tier] = None
    pending_source_families: tuple = ()
    identity_review_required: bool = False

    def to_dict(self):
        return _jsonable(self)

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(), allow_nan=False, **kwargs)


ALIASES = {'vf': 'virtue_foundation', 'virtue': 'virtue_foundation', 'nbems': 'dnb', 'abdm_hfr': 'hfr'}
NON_SERVICE = {'nqas': Scope.QUALITY, 'kayakalp': Scope.CLEANLINESS, 'hfr': Scope.IDENTITY}
INDIRECT_BASIS = {'nmc': 'training', 'dnb': 'training', 'ncg': 'membership',
                  'trauma': 'sanctioned_not_confirmed_functional', 'virtue_foundation': 'self_report'}
DIRECT_FAMILIES = {'laqshya', 'nabh'}


def source_family(e):
    key = e.source_id.strip().casefold()
    return ALIASES.get(key, key)


def identity_status(e):
    # Rejection is definitive attribution exclusion, not an ambiguous candidate.
    if e.match.status == MatchStatus.REJECTED:
        return 'rejected'
    if e.match.status == MatchStatus.UNKNOWN:
        return 'unknown'
    if e.match.status == MatchStatus.PENDING or IDENTITY_REVIEW_FLAGS.intersection(e.match.flags + e.qualifiers):
        return 'pending'
    return 'accepted'


def _basis(e, family):
    if family in NON_SERVICE:
        return 'non_service'
    if family in INDIRECT_BASIS:
        return INDIRECT_BASIS[family]
    if e.source_kind == SourceKind.SELF_REPORT or e.verification == Verification.SELF_REPORTED:
        return 'self_report'
    if family == 'laqshya':
        return 'direct_certification'
    if family == 'nabh':
        return 'service_accreditation'
    return 'unmapped_source'


def _candidate(e, family, basis, temporal):
    """Candidate semantics before identity; only accepted candidates can become base tier."""
    reasons = list(temporal.reasons)
    if temporal.status in ('invalid', 'not_yet_effective'):
        return None, reasons
    if basis in INDIRECT_BASIS.values():
        return Tier.T3, reasons + [f'{family}: {basis}; never independent direct verification.']
    if family not in DIRECT_FAMILIES:
        return None, reasons + ['Source-specific direct-service semantics are not mapped; no direct upgrade.']
    expected_kind = SourceKind.GOVERNMENT_REGISTRY if family == 'laqshya' else SourceKind.ACCREDITATION
    if (e.source_kind != expected_kind or e.verification != Verification.INDEPENDENT
            or e.directness != Directness.DIRECT or INDIRECT_FLAGS.intersection(e.qualifiers)):
        return None, reasons + ['Source row is not an independent direct certification/accreditation of this service.']
    if not e.citations:
        return None, reasons + ['Direct verification requires a source citation.']
    if temporal.status in ('current_certificate', 'current_listing'):
        return Tier.T1, reasons
    if temporal.status == 'historical':
        return Tier.T2, reasons
    return None, reasons + ['Direct evidence validity is unknown, not automatically historical from issuance age.']


def _credible_negative(e, family, match_status, temporal, as_of, policy):
    if match_status != 'accepted' or not e.citations or e.verification != Verification.INDEPENDENT:
        return False, 'Contradiction lacks accepted identity, independent verification or citation.'
    if (e.directness != Directness.DIRECT or INDIRECT_FLAGS.intersection(e.qualifiers)
            or family in INDIRECT_BASIS or family in NON_SERVICE):
        return False, 'Indirect, self-reported, quality or identity assertions do not establish service counterevidence.'
    mapped_authority = ((family == 'laqshya' and e.source_kind == SourceKind.GOVERNMENT_REGISTRY)
                        or (family == 'nabh' and e.source_kind == SourceKind.ACCREDITATION))
    if not (e.source_kind == SourceKind.INDEPENDENT_CHECK or mapped_authority):
        return False, 'Negative source credibility needs an explicit independent-check or mapped authoritative source.'
    if e.date_precision != DatePrecision.EXACT or e.observed_on is None or temporal.status in ('invalid', 'not_yet_effective', 'historical'):
        return False, 'Contradiction is undated, approximate, future, expired or otherwise temporally invalid.'
    if temporal.status == 'current_certificate' or 0 <= (as_of - e.observed_on).days <= policy.contradiction_max_age_days:
        return True, 'Independent, direct, cited, dated and accepted-facility contradiction requires resolution.'
    return False, 'Dated contradiction is stale under the configured notice horizon; retained without overriding support.'


def _review_status(statuses):
    values = set(statuses)
    if not values:
        return 'not_applicable'
    if values == {'accepted'}:
        return 'clear'
    if 'accepted' in values:
        return 'partial'
    if len(values) == 1:
        return next(iter(values))
    return 'mixed_unresolved'


def deduplicate_records(records):
    """Stable source IDs are family-scoped; conflicting versions fail closed.

    Without a source-record ID, the existing classifier also collapses equivalent
    payloads. A site ID is not a service-record ID and must never be substituted.
    """
    records = tuple(records)
    if any(not isinstance(e, Evidence) for e in records):
        raise ValueError('records must contain Evidence objects')
    seen, result = {}, []
    for e in sorted(records, key=lambda e: e.evidence_id):
        key = (source_family(e), e.source_record_id, e.match.facility_id,
               canonical_service(e.service) if e.service else None, e.scope)
        if e.source_record_id is not None:
            payload = tuple(getattr(e, f.name) for f in fields(Evidence)
                            if f.name not in ('evidence_id', 'source_id', 'independence_group'))
            if key in seen:
                if seen[key] != payload:
                    raise ValueError(f'conflicting versions of source record {key}')
                continue
            seen[key] = payload
        result.append(e)
    return tuple(result)


def evidence_tier(facility_id: str, service: str, evidence_records: Iterable[Evidence], as_of: date,
                  *, policy: Optional[TierPolicy] = None) -> TierAssessment:
    """Strongest qualifying base tier, then conflict/review overlay; no score or weights."""
    facility_id, service = text(facility_id, 'facility_id'), canonical_service(service)
    day(as_of, 'as_of')
    if as_of is None:
        raise ValueError('as_of is required')
    policy = TierPolicy() if policy is None else policy
    if not isinstance(policy, TierPolicy):
        raise ValueError('policy must be TierPolicy')
    evidence_records = deduplicate_records(evidence_records)
    ids, fingerprints, duplicates, excluded, relevant = {}, {}, [], [], []
    dimensions = {scope: [] for scope in (Scope.QUALITY, Scope.CLEANLINESS, Scope.IDENTITY)}
    for e in sorted(evidence_records, key=lambda x: x.evidence_id if isinstance(x, Evidence) else ''):
        if not isinstance(e, Evidence):
            raise ValueError('evidence_records must contain Evidence objects')
        if e.evidence_id in ids:
            if ids[e.evidence_id] != e:
                raise ValueError(f'conflicting payloads for evidence_id {e.evidence_id}')
            duplicates.append((e.evidence_id, e.evidence_id))
            continue
        ids[e.evidence_id] = e
        family = source_family(e)
        if e.match.facility_id != facility_id:
            excluded.append((e.evidence_id, 'different facility_id'))
            continue
        actual_scope = NON_SERVICE.get(family, e.scope)
        if family == 'nabh' and 'LISTING_IS_NOT_SERVICE_VERIFICATION' in e.qualifiers and e.scope == Scope.SERVICE:
            actual_scope = Scope.QUALITY
        if actual_scope != Scope.SERVICE:
            dimensions[actual_scope].append(e.evidence_id)
            excluded.append((e.evidence_id, f'{actual_scope.value} evidence is not service verification'))
            continue
        if canonical_service(e.service) != service:
            excluded.append((e.evidence_id, 'different requested service'))
            continue
        # Equivalent payloads with alias IDs in a family are counted once. Differing
        # assertions/dates/matches/citations are NOT deduplicated, including conflicts.
        fingerprint = (family,) + tuple(getattr(e, f.name) for f in fields(Evidence)
                                        if f.name not in ('evidence_id', 'source_id', 'independence_group'))
        if fingerprint in fingerprints:
            duplicates.append((e.evidence_id, fingerprints[fingerprint]))
            continue
        fingerprints[fingerprint] = e.evidence_id
        relevant.append(e)
    decisions, supporters, candidates, support_matches, negatives, assumptions = [], [], [], [], [], []
    for e in relevant:
        family, match = source_family(e), identity_status(e)
        basis = _basis(e, family)
        temporal = temporal_validity(e, as_of)
        candidate, reasons = _candidate(e, family, basis, temporal)
        credit, contradiction = False, False
        if e.polarity == Polarity.SUPPORTS:
            if basis == 'unmapped_source':
                assumptions.append(f'{family}: William must confirm service-specific source semantics before direct classification.')
            if temporal.status not in ('invalid', 'not_yet_effective') and match != 'rejected':
                support_matches.append(match)
            if candidate and match == 'accepted':
                supporters.append(e)
                candidates.append(candidate)
                credit = True
            elif match != 'accepted':
                reasons.append(f'Identity {match}; candidate evidence cannot establish verification at this facility.')
        elif e.polarity == Polarity.CONTRADICTS:
            contradiction, reason = _credible_negative(e, family, match, temporal, as_of, policy)
            reasons.append(reason)
            if contradiction:
                negatives.append(e)
        else:
            reasons.append('Unknown assertion polarity is not positive evidence or service absence.')
        decisions.append(EvidenceDecision(e.evidence_id, family, basis, match, temporal.status,
                                          candidate if e.polarity == Polarity.SUPPORTS else None,
                                          credit, contradiction, tuple(reasons)))
    order = {Tier.T1: 0, Tier.T2: 1, Tier.T3: 2}
    base = min(candidates, key=order.__getitem__) if candidates else Tier.U
    pending = [d for d in decisions if d.match_status in ('pending', 'unknown')
               and d.candidate_tier is not None]
    stronger = [d.candidate_tier for d in pending
                if base == Tier.U or order[d.candidate_tier] < order[base]]
    review = _review_status(support_matches)
    all_unresolved = bool(support_matches) and 'accepted' not in support_matches
    conflict = bool(supporters and negatives)
    effective = Tier.X if conflict else Tier.R if all_unresolved else base
    temporal = {e.evidence_id: temporal_validity(e, as_of) for e in relevant}
    positive_records = [e for e in relevant if e.polarity == Polarity.SUPPORTS]
    flags = EvidenceFlags(
        conditional_certification=any('CONDITIONAL_CERTIFICATION' in e.qualifiers for e in positive_records),
        date_year_only=any(t.date_year_only for t in temporal.values()),
        current_listing_undated=any(t.current_listing_undated for t in temporal.values()),
        expired_certification=any(source_family(e) in DIRECT_FAMILIES and temporal[e.evidence_id].status == 'historical' for e in positive_records),
        identity_review=any(status != 'accepted' for status in support_matches),
        rejected_candidate_match=any(identity_status(e) == 'rejected' for e in relevant),
        conflicting_evidence=conflict,
        missing_citation=any(not e.citations for e in positive_records),
        temporal_uncertainty=any(
            e.observed_on is None or e.date_precision != DatePrecision.EXACT
            or temporal[e.evidence_id].status in ('undated', 'dated', 'invalid', 'not_yet_effective')
            or temporal[e.evidence_id].current_listing_undated
            or temporal[e.evidence_id].date_year_only
            or (temporal[e.evidence_id].status == 'historical' and e.valid_until is None)
            for e in relevant),
    )
    families = tuple(sorted({source_family(e) for e in supporters}))
    basis = tuple(sorted({d.evidence_basis for d in decisions if d.credited}))
    explanation = [f'Base {base.value}; effective {effective.value}; identity review status: {review}.']
    if base == Tier.U:
        explanation.append('No accepted, eligible service support. Retain the facility; unknown is not unavailable.')
    if effective == Tier.R:
        explanation.append('All applicable supporting associations are unresolved; no verification credit. Rejected links are excluded from support.')
    if pending:
        explanation.append('Pending identity evidence is explanatory only; candidate tiers do not establish verification.')
    if flags.rejected_candidate_match:
        explanation.append('Rejected candidate matches are excluded from supporting evidence.')
    if effective == Tier.X:
        explanation.append(f'Credible unresolved counterevidence overlays {base.value}; base tier and source statements remain available.')
    if base == Tier.T2:
        explanation.append('Historical direct verification supports past capability only; expiry does not establish service absence.')
    if flags.current_listing_undated:
        explanation.append('Authoritative current-listing assertion is undated; no scrape/snapshot freshness inferred.')
    explanation.append('Certification/listing is not proof of current staffing, operational readiness or patient acceptance.')
    return TierAssessment(
        facility_id, service, as_of, base, effective, review, flags, families, len(families), len(supporters),
        basis, tuple(dict.fromkeys(c for e in relevant for c in e.citations)), tuple(explanation),
        tuple(decisions), tuple(duplicates), tuple(excluded), tuple(dimensions[Scope.QUALITY]),
        tuple(dimensions[Scope.CLEANLINESS]), tuple(dimensions[Scope.IDENTITY]), tuple(sorted(set(assumptions))),
        policy.contradiction_max_age_days,
        pending_stronger_tier=min(stronger, key=order.__getitem__) if stronger else None,
        pending_source_families=tuple(sorted({d.source_family for d in pending})),
        identity_review_required=flags.identity_review,
    )
