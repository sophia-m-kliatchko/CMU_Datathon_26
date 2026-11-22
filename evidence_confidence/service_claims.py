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

from dataclasses import replace

from .adapters import from_facility_claim
from .models import Polarity
from .tiers import ATTRIBUTION_FLAG

MAPPING_VERSION = 'service-claims/3'  # /2: future/planned claims skipped; /3: cross-facility attribution guard

CLAIM_PATTERNS = {
    'dialysis': re.compile(r'\b(?:ha?e?mo|peritoneal )?dialysis\b'),
    'emergency_c_section': re.compile(r'\bc ?-? ?sections?\b|\bca?esarean\b|\blscs\b'),
}
EXTRA_QUALIFIERS = {'emergency_c_section': ('CLAIM_DOES_NOT_STATE_EMERGENCY',)}
NEGATION = re.compile(r'\b(?:no|not|without|non|refer|referred|referral|referrals|planned|upcoming|'
                      r'coming soon|proposed|unavailable|except|inaugurated soon|shut down|shutdown|closed|discontinued|'
                      # Future/planned capability is not current capability. Narrow phrases only:
                      # "dialysis planning, initiation and maintenance" (clinical) stays matched.
                      r'plans? to|planning to|under construction|being set up|to be (?:set up|started|opened|established|built|commissioned)|'
                      r'will (?:be|have|start|open|offer|provide)|in future|future plans?)\b')
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


# --- Cross-facility attribution guard -------------------------------------------------
# A claim that places the service AT/UNDER/WITHIN another named place ("dialysis treatment at
# Asha Parekh Hospital", "listed within Jivan Jyot Drug Bank's network") may describe another
# facility. Such claims are never credited; the rest of the record is flagged, not demoted.
# Concrete care-site types only: network/trust/drug-bank membership describes affiliation, not another site.
_PLACE_WORDS = r'(?:hospitals?|centres?|centers?|clinics?|nursing home|institute|medical college)'
_MENTION = re.compile(r"\b(?:at|c/o|under|within|listed (?:as|under|within))\s+([^;:()]{0,80}?\b" + _PLACE_WORDS + r"\b)", re.I)
_GENERIC = {'hospital', 'hospitals', 'centre', 'center', 'centres', 'centers', 'clinic', 'clinics', 'the', 'and', 'of',
            'pvt', 'ltd', 'private', 'limited', 'medical', 'health', 'healthcare', 'care', 'super', 'speciality',
            'specialty', 'multispeciality', 'multi', 'nursing', 'home', 'institute', 'research', 'sciences',
            'india', 'general', 'government', 'govt', 'civil', 'district', 'memorial', 'charitable', 'trust',
            'foundation', 'eye', 'children', 'women', 'maternity', 'dialysis', 'kidney', 'network', 'unit',
            # determiners/pronouns: "at this centre", "at our hospital" are self-references
            'this', 'that', 'these', 'our', 'its', 'their', 'same', 'said'}


def _tokens(text):
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) >= 3 and w not in _GENERIC}


def attribution(statement, facility_name):
    """'own' (no other place named, or every named place matches the facility's distinctive
    name tokens), 'other' (a named place shares none), or 'mixed' (both). Tokens of length >= 3
    count, so short brand names such as "LYF" still identify the facility itself. Generic phrases
    with no distinctive token ("at the hospital") are ignored. A facility with no distinctive
    name tokens cannot be confirmed, so any distinctly named place counts as other."""
    own = _tokens(facility_name)
    kinds = set()
    for m in _MENTION.finditer(statement or ''):
        named = _tokens(m.group(1))
        if not named:  # "at the hospital", "within this centre": generic self-reference, no named place
            continue
        kinds.add('own' if own & named else 'other')
    if 'other' not in kinds:
        return 'own'
    return 'mixed' if 'own' in kinds else 'other'


def claim_evidence(claims, service, *, facility_ids=None, facility_names=None):
    """Self-reported Evidence for one canonical service. Returns (records, report).

    `facility_names` (facility_id -> name) enables the cross-facility attribution guard. Callers
    that do not pass it (older contract) get the guard skipped, reported as
    `attribution_check: 'skipped_no_facility_names'`, rather than every named place being
    treated as another facility (which would drop the facility's own claims).
    """
    wanted = None if facility_ids is None else set(facility_ids)
    guard = facility_names is not None
    names = facility_names or {}
    reasons, records, seen = Counter(), [], set()
    excluded = {}
    if service not in CLAIM_PATTERNS:
        return (), {'mapping_version': MAPPING_VERSION, 'service': service, 'mapped': False,
                    'reason': 'service_not_in_claim_mapping', 'records': 0, 'attribution_excluded': {}}
    for row in claims:
        if wanted is not None and row['facility_id'] not in wanted:
            continue
        if row.get('claim_field') not in FIELDS:
            reasons['unsupported_field'] += 1
            continue
        ok, why = match_claim(row.get('claim_norm'), service)
        if ok and guard and attribution(row.get('claim_text'), names.get(row['facility_id'])) != 'own':
            ok, why = False, 'other_facility_attribution'
            excluded.setdefault(row['facility_id'], []).append(row.get('claim_text'))
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
    # Record-level: a facility whose credited claims sit beside other-facility claims is flagged,
    # not demoted and not re-attributed (we cannot tell which facility the record describes).
    records = [replace(e, qualifiers=e.qualifiers + (ATTRIBUTION_FLAG,)) if e.match.facility_id in excluded else e
               for e in records]
    return tuple(records), {'mapping_version': MAPPING_VERSION, 'service': service, 'mapped': True,
                            'records': len(records), 'facilities': len({e.match.facility_id for e in records}),
                            'reasons': dict(sorted(reasons.items())),
                            'attribution_check': 'applied' if guard else 'skipped_no_facility_names',
                            'attribution_excluded': {k: v for k, v in sorted(excluded.items())}}
