"""Portable Evidence Confidence baseline; no database writes or third-party dependencies."""
from .engine import MODEL_VERSION, assess, canonical_service
from .models import (Assessment, Citation, DatePrecision, Directness, Evidence, FacilityMatch,
                     LocationContext, MatchStatus, Polarity, Scope, SourceKind, Verification)
from .policy import Policy

__all__ = ['MODEL_VERSION', 'assess', 'canonical_service', 'Assessment', 'Citation', 'DatePrecision',
           'Directness', 'Evidence', 'FacilityMatch', 'LocationContext', 'MatchStatus', 'Polarity',
           'Scope', 'SourceKind', 'Verification', 'Policy']

# Primary categorical interface; assess() retains numerical lanes for comparison.
from .tiers import EvidenceFlags, Tier, TierAssessment, TierPolicy, evidence_tier
__all__ += ['EvidenceFlags', 'Tier', 'TierAssessment', 'TierPolicy', 'evidence_tier']

from .ranking import Candidate, RankedCandidate, RankingConfig, RankingResult, rank_candidates
__all__ += ['Candidate', 'RankedCandidate', 'RankingConfig', 'RankingResult', 'rank_candidates']

from .integration import build_facility_service_rows, join_geographic_candidates
__all__ += ['build_facility_service_rows', 'join_geographic_candidates']

from .recommendation import build_recommendation_response, normalize_request
from .validation import validate_integration
__all__ += ['build_recommendation_response', 'normalize_request', 'validate_integration']
