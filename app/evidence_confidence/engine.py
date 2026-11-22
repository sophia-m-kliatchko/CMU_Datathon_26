"""Deterministic evidence-strength baseline. No IO and no statistical calibration."""
from datetime import date
import math
import re
from typing import Iterable, Optional

from .models import (Assessment, Contribution, DatePrecision, Directness, Evidence,
                     LaneAssessment, LocationContext, MatchStatus, Polarity, Scope,
                     SourceKind, Verification, day, text)
from .policy import Policy
from .temporal import temporal_validity

MODEL_VERSION = 'evidence-confidence/1'
# These flags indicate identity ambiguity, not evidence of service absence.
IDENTITY_REVIEW_FLAGS = frozenset({
    'DUP_ROWS_STATE_CONFLICT', 'DUP_ROWS_PINCODE_CONFLICT', 'DUP_ROWS_COORD_CONFLICT',
    'MAY_BE_GROUP_OR_HEAD_OFFICE', 'DUPLICATE_NAME_IN_CITY', 'EMPTY_NAME_CORE',
    'DISTRICT_HEALTH_JURISDICTION', 'MATCH_AMBIGUOUS', 'STATE_CONFLICT',
})
INDIRECT_FLAGS = frozenset({
    'INDIRECT_VIA_SPECIALTY', 'SANCTIONED_NOT_CONFIRMED_FUNCTIONAL',
    'MEMBERSHIP_NOT_INSPECTION', 'DEPARTMENT_NOT_STATED', 'RECENT_LOP_ONLY',
})


def canonical_service(value: str) -> str:
    """Normalize tag formatting only. No substring, specialty or synonym inference."""
    return re.sub(r'[\s-]+', '_', text(value, 'service').casefold())


def _temporal(e, as_of, p):
    facts = temporal_validity(e, as_of)
    reasons = list(facts.reasons)
    if facts.status in ('invalid', 'not_yet_effective'):
        return 0., 'invalid_dates' if facts.status == 'invalid' else 'not_yet_effective', reasons
    exact_event = e.observed_on if e.date_precision in (DatePrecision.EXACT, DatePrecision.FINANCIAL_YEAR) and not facts.date_year_only else None
    age = (as_of - exact_event).days if exact_event else None
    freshness = 2 ** (-age / p.half_life_days) if age is not None else p.unknown_recency
    status = 'recent' if age is not None and age <= p.current_evidence_days else 'stale' if age is not None else 'undated'
    if facts.status == 'current_certificate':
        # Correct the original age-only bug without changing the numerical formula:
        # an in-force interval is current even when issued more than 365 days ago.
        freshness, status = 1., 'recent'
    elif facts.status == 'current_listing':
        # Listing status establishes currentness, not an invented event date.
        status = 'undated' if age is None else 'recent'
    elif facts.status == 'historical':
        freshness *= p.expired_multiplier
        status = 'expired_or_not_current'
    elif status == 'stale':
        reasons.append('Event evidence is stale under the legacy comparison policy.')
    return freshness, status, reasons


def _contribution(e, as_of, p):
    reliability = p.source_overrides.get(e.source_id, p.source_reliability[e.source_kind.value])
    match = e.match.confidence if e.match.confidence is not None else 0.
    freshness, temporal, reasons = _temporal(e, as_of, p)
    values = {'reliability': reliability, 'facility_match': match, 'recency': freshness}
    weights = p.weights
    # Zero-valued identity/time gates always apply, even if someone sets that component's weight to zero.
    if match == 0 or freshness == 0 or reliability == 0:
        strength = 0.
    else:
        strength = math.exp(sum(w * math.log(values[k]) for k, w in weights.items()) / sum(weights.values()))
    review = e.match.status == MatchStatus.PENDING or bool(IDENTITY_REVIEW_FLAGS.intersection(e.match.flags + e.qualifiers))
    indirect = e.directness != Directness.DIRECT or bool(INDIRECT_FLAGS.intersection(e.qualifiers))
    strength *= p.directness[Directness.INDIRECT.value if indirect and e.directness == Directness.DIRECT else e.directness.value]
    caps = []
    if e.match.status in (MatchStatus.UNKNOWN, MatchStatus.REJECTED):
        strength = 0.
        reasons.append('Facility association is unknown/rejected; not credited to the requested facility.')
    if e.match.confidence is None:
        reasons.append('Facility-match confidence is missing; no association credit.')
    if review:
        strength *= p.pending_match_multiplier
        caps.append(p.pending_cap)
        reasons.append('Facility association requires review; independent verification label is blocked.')
    if not e.citations:
        strength *= p.uncited_multiplier
        caps.append(p.uncited_cap)
        reasons.append('Citation missing; contribution is capped and cannot independently verify a service.')
    if e.source_kind == SourceKind.SELF_REPORT or e.verification == Verification.SELF_REPORTED:
        caps.append(p.self_report_cap)
        reasons.append('Self-reported evidence, not independent service verification.')
    if indirect or e.verification in (Verification.INFERRED, Verification.UNKNOWN):
        caps.append(p.indirect_cap)
        reasons.append('Indirect/contextual or unverified support; no direct service verification.')
    if e.observed_on is None or e.date_precision != DatePrecision.EXACT:
        caps.append(p.unknown_date_cap)
    if temporal in ('stale', 'expired_or_not_current'):
        caps.append(p.historical_cap)
    if 'CONDITIONAL_CERTIFICATION' in e.qualifiers:
        strength *= p.conditional_multiplier
        reasons.append(f'Certification is conditional (configured multiplier {p.conditional_multiplier:g}).')
    if caps:
        strength = min(strength, *caps)
    qualified = (e.polarity == Polarity.SUPPORTS and e.verification == Verification.INDEPENDENT
                 and e.source_kind not in (SourceKind.SELF_REPORT, SourceKind.NETWORK, SourceKind.UNKNOWN)
                 and not indirect and e.match.status == MatchStatus.ACCEPTED and not review
                 and match >= p.qualified_match_min and temporal == 'recent'
                 and e.date_precision == DatePrecision.EXACT and bool(e.citations)
                 and strength >= p.qualified_strength_min)
    if e.polarity == Polarity.UNKNOWN:
        reasons.append('Assertion polarity is unknown; kept for explanation but not scored as support or absence.')
    reasons.extend(f'Source qualifier: {flag}' for flag in e.qualifiers)
    reasons.extend(f'Match qualifier: {flag}' for flag in e.match.flags)
    return Contribution(e, reliability, match, freshness, temporal, max(0., min(1., strength)), qualified, tuple(reasons))


def _group_strength(contributions, polarity, p):
    groups = {}
    for c in contributions:
        if c.evidence.polarity == polarity and c.strength > 0:
            key = c.evidence.independence_group or c.evidence.source_id
            groups[key] = max(groups.get(key, 0.), c.strength)
    strongest = sorted(groups.values(), reverse=True)
    if not strongest:
        return 0., groups
    # Diminishing, bounded corroboration across distinct declared lineages. Never sum course/award rows.
    other_support = 1 - math.prod(1 - s for s in strongest[1:])
    return strongest[0] + p.agreement_bonus * (1 - strongest[0]) * other_support, groups


def _lane(scope, contributions, p):
    rows = tuple(c for c in contributions if c.evidence.scope == scope)
    positive, groups = _group_strength(rows, Polarity.SUPPORTS, p)
    negative, _ = _group_strength(rows, Polarity.CONTRADICTS, p)
    supports = [c for c in rows if c.evidence.polarity == Polarity.SUPPORTS and c.strength > 0]
    qualified = tuple(c.evidence.evidence_id for c in supports if c.independent_current_support)
    score = positive * (1 - p.contradiction_penalty * negative) if positive else None
    if positive and negative >= p.conflict_threshold:
        status = 'conflicting'
        score = min(score, p.conflict_cap)
    elif not positive:
        status = 'counterevidence_only' if negative else 'needs_review' if rows else 'unknown'
    elif all(c.temporal_status in ('stale', 'expired_or_not_current') for c in supports):
        status = 'historical_only'
        score = min(score, p.historical_cap)
    elif qualified:
        status = 'independently_supported'
    elif all(c.evidence.match.status != MatchStatus.ACCEPTED or
             IDENTITY_REVIEW_FLAGS.intersection(c.evidence.match.flags + c.evidence.qualifiers) for c in supports):
        status = 'needs_review'
        score = min(score, p.pending_cap)
    elif all(c.evidence.verification == Verification.SELF_REPORTED or c.evidence.source_kind == SourceKind.SELF_REPORT for c in supports):
        status = 'self_reported'
        score = min(score, p.self_report_cap)
    else:
        status = 'indirect_or_unverified'
        score = min(score, p.indirect_cap)
    category = ('unknown' if score is None else 'high' if score >= p.high_threshold and status == 'independently_supported'
                else 'medium' if score >= p.medium_threshold else 'low')
    if status == 'conflicting':
        qualified = ()  # No unqualified verification label while material counterevidence exists.
    citations = tuple(dict.fromkeys(citation for c in rows for citation in c.evidence.citations))
    explanation = [f'{scope.value}: {status.replace("_", " ")}.']
    if not rows:
        explanation.append('No relevant evidence supplied. Missing evidence is not proof of absence.')
    elif not positive:
        explanation.append('No scoreable positive support. Counterevidence is reported separately; no absence probability is inferred.')
    else:
        explanation.append(f'Support {positive:.3f}; counterevidence {negative:.3f}; {len(groups)} declared source lineage(s).')
        explanation.append('Within each lineage, only the strongest contribution per polarity affects the score; citations and conflicts remain visible.')
    if status == 'conflicting':
        explanation.append('Material conflicting evidence reduces/caps support; resolve the contradiction before use.')
    if scope != Scope.SERVICE:
        explanation.append('This score measures support for the supplied scoped assertion, not clinical quality/safety or service availability.')
    else:
        explanation.append('Documentary service support is not confirmation of current operational availability; confirm directly before relying on it.')
    return LaneAssessment(
        scope=scope, score=round(100 * score, 2) if score is not None else None,
        category=category, status=status, support_strength=round(positive, 6),
        counterevidence_strength=round(negative, 6),
        agreement_gain=round(positive - max(groups.values(), default=0.), 6),
        contradiction_reduction=round(positive * p.contradiction_penalty * negative, 6),
        independent_groups=len(groups), independent_current_evidence_ids=qualified,
        evidence_ids=tuple(c.evidence.evidence_id for c in rows), citations=citations,
        explanations=tuple(explanation), contributions=rows,
    )


def assess(facility_id: str, requested_service: str, evidence: Iterable[Evidence], *, as_of: date,
           policy: Optional[Policy] = None, location: Optional[LocationContext] = None, tier_policy=None) -> Assessment:
    """Score only evidence associated with this facility/service. Does not query or mutate sources."""
    facility_id = text(facility_id, 'facility_id')
    service = canonical_service(requested_service)
    day(as_of, 'as_of')
    if as_of is None:
        raise ValueError('as_of is required for reproducible scoring')
    if location is not None and not isinstance(location, LocationContext):
        raise ValueError('location must be a LocationContext')
    if location is not None and location.facility_id not in (None, facility_id):
        raise ValueError('location belongs to a different facility_id')
    p = policy if policy is not None else Policy()
    if not isinstance(p, Policy):
        raise ValueError('policy must be a Policy')
    evidence = tuple(evidence)  # Both independent paths must see generator inputs.
    seen, duplicates, excluded, relevant = {}, set(), [], []
    for e in evidence:
        if not isinstance(e, Evidence):
            raise ValueError('evidence must contain Evidence objects')
        if e.evidence_id in seen:
            if seen[e.evidence_id] != e:
                raise ValueError(f'conflicting payloads for evidence_id {e.evidence_id}')
            duplicates.add(e.evidence_id)
            continue
        seen[e.evidence_id] = e
        if e.match.facility_id != facility_id:
            excluded.append((e.evidence_id, 'different facility_id'))
        elif e.scope == Scope.SERVICE and canonical_service(e.service) != service:
            excluded.append((e.evidence_id, 'different service tag; no synonym/specialty inference'))
        else:
            relevant.append(e)
    contributions = tuple(_contribution(e, as_of, p) for e in sorted(relevant, key=lambda e: e.evidence_id))
    from .tiers import evidence_tier
    categorical = evidence_tier(facility_id, service, evidence, as_of, policy=tier_policy)
    return Assessment(facility_id, service, as_of, MODEL_VERSION, p.fingerprint, p.to_dict(),
                      _lane(Scope.SERVICE, contributions, p), _lane(Scope.QUALITY, contributions, p),
                      _lane(Scope.CLEANLINESS, contributions, p), _lane(Scope.IDENTITY, contributions, p),
                      location, tuple(sorted(excluded)), tuple(sorted(duplicates)), (
                          'Heuristic policy score on 0-100; not a statistically calibrated probability or a clinical recommendation.',
                          'Missing/expired/ambiguous records do not establish absence of a service or poor quality.',
                          'Facility matches and declared source independence are upstream assertions requiring validation.',
                          'Quality, cleanliness, identity and service scores are separate and must not be added together.',
                          'No real-time staffing, equipment uptime, appointment access or operational availability is established.',
                      ), service_evidence=categorical)
