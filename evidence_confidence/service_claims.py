"""Conservative, versioned mapping of self-reported facility claims to canonical services.

Input: silver_facility_claims rows (facility_id, claim_field, claim_position, claim_text, claim_norm).
Output: SELF-REPORTED Evidence via adapters.from_facility_claim -> at most tier T3.

Rules (deliberately narrow; reviewed list, not fuzzy matching):
* Only services listed in CLAIM_PATTERNS are mapped. Each pattern names the service itself
  (e.g. "dialysis", "caesarean"), never a related specialty: nephrology is NOT dialysis and
  obstetrics/maternity is NOT a C-section.
* A claim containing any negation/qualifier word (no, not, without, referred, planned...) is
  skipped entirely. A skipped claim is NOT negative evidence; it is simply unmapped.
* Claims are self-reported: polarity SUPPORTS, verification SELF_REPORTED, never T1/T2.
* emergency_c_section: claims say "caesarean"/"C-section", not "emergency". Mapping them to the
  registry tag `emergency_c_section` is a vocabulary decision flagged for team approval
  (qualifier CLAIM_DOES_NOT_STATE_EMERGENCY is attached to every such record).
"""
from collections import Counter
import re

from .adapters import from_facility_claim
from .models import Polarity

MAPPING_VERSION = 'service-claims/1'

CLAIM_PATTERNS = {
    'dialysis': re.compile(r'\b(?:ha?e?mo|peritoneal )?dialysis\b'),
    'emergency_c_section': re.compile(r'\bc ?-? ?sections?\b|\bca?esarean\b|\blscs\b'),
}
EXTRA_QUALIFIERS = {'emergency_c_section': ('CLAIM_DOES_NOT_STATE_EMERGENCY',)}
NEGATION = re.compile(r'\b(?:no|not|without|non|refer|referred|referral|referrals|planned|upcoming|'
                      r'coming soon|proposed|unavailable|except|inaugurated soon|shut down|shutdown|closed|discontinued)\b')
FIELDS = ('specialties', 'capability', 'procedure', 'equipment')


def match_claim(claim_norm, service):
    """Return (matched, reason). Pure function; used by tests and the coverage report."""
    pattern = CLAIM_PATTERNS.get(service)
    if pattern is None:
        return False, 'service_not_in_claim_mapping'
    if not isinstance(claim_norm, str) or not pattern.search(claim_norm):
        return False, 'no_service_term'
    if NEGATION.search(claim_norm):
        return False, 'negation_or_qualifier_skipped'
    return True, 'matched'


def claim_evidence(claims, service, *, facility_ids=None):
    """Self-reported Evidence for one canonical service. Returns (records, report)."""
    wanted = None if facility_ids is None else set(facility_ids)
    reasons, records, seen = Counter(), [], set()
    if service not in CLAIM_PATTERNS:
        return (), {'mapping_version': MAPPING_VERSION, 'service': service, 'mapped': False,
                    'reason': 'service_not_in_claim_mapping', 'records': 0}
    for row in claims:
        if wanted is not None and row['facility_id'] not in wanted:
            continue
        if row.get('claim_field') not in FIELDS:
            reasons['unsupported_field'] += 1
            continue
        ok, why = match_claim(row.get('claim_norm'), service)
        if why != 'no_service_term':
            reasons[why] += 1
        if not ok:
            continue
        e = from_facility_claim(row, service=service, polarity=Polarity.SUPPORTS,
                                direct=row['claim_field'] in ('capability', 'procedure'),
                                facility_flags=EXTRA_QUALIFIERS.get(service, ()))
        if e.evidence_id in seen:  # identical facility/field/position/text
            reasons['duplicate_claim'] += 1
            continue
        seen.add(e.evidence_id)
        records.append(e)
    return tuple(records), {'mapping_version': MAPPING_VERSION, 'service': service, 'mapped': True,
                            'records': len(records), 'facilities': len({e.match.facility_id for e in records}),
                            'reasons': dict(sorted(reasons.items()))}
