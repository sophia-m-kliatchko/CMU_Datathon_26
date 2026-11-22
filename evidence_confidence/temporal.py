"""Deterministic temporal facts shared by tiers and legacy comparisons; no scoring."""
from dataclasses import dataclass
from datetime import date

from .models import DatePrecision, Directness, Evidence, SourceKind, Verification, day


@dataclass(frozen=True)
class TemporalValidity:
    status: str  # current_certificate/current_listing/historical/undated/dated/invalid/not_yet_effective
    date_year_only: bool
    current_listing_undated: bool
    reasons: tuple


def temporal_validity(e: Evidence, as_of: date) -> TemporalValidity:
    day(as_of, 'as_of')
    if as_of is None:
        raise ValueError('as_of is required')
    year_only = e.date_precision == DatePrecision.YEAR or 'DATE_IS_YEAR_ONLY' in e.qualifiers
    exact_event = e.observed_on if e.date_precision == DatePrecision.EXACT and not year_only else None
    reasons = []
    if year_only:
        reasons.append('Year-only date is not an exact January 1 observation.')
    future_event = e.observed_on and not year_only and e.observed_on > as_of
    future_year = year_only and e.observed_on and e.observed_on.year > as_of.year
    if ((e.valid_from and e.valid_until and e.valid_until < e.valid_from)
            or future_event or future_year or (e.retrieved_on and e.retrieved_on > as_of)):
        return TemporalValidity('invalid', year_only, False, tuple(reasons + ['Invalid/future dates; no temporal credit.']))
    if e.valid_from and e.valid_from > as_of:
        return TemporalValidity('not_yet_effective', year_only, False, tuple(reasons + ['Validity has not started.']))
    # Explicit certificate bounds take precedence over issuance age and cached build-date flags.
    if e.valid_until and e.valid_until < as_of:
        return TemporalValidity('historical', year_only, False, tuple(reasons + ['Validity has expired; not evidence of service absence.']))
    if e.valid_from and e.valid_until and e.valid_from <= as_of <= e.valid_until:
        return TemporalValidity('current_certificate', year_only, False, tuple(reasons + ['As-of date is inside the explicit validity interval.']))
    # Adapters supply certificate issue dates as valid_from when the date is exact.
    # No inferred year-only start date, snapshot date or retrieval date is used here.
    authoritative = (e.source_kind in (SourceKind.GOVERNMENT_REGISTRY, SourceKind.ACCREDITATION)
                     and e.verification == Verification.INDEPENDENT and e.directness == Directness.DIRECT)
    if e.current_status is False:
        return TemporalValidity('historical', year_only, False, tuple(reasons + ['Source explicitly indicates listing is no longer current; historical only.']))
    if not e.valid_from and not e.valid_until and e.current_status is True and authoritative:
        undated = True  # No validity interval or dated confirmation of listing currentness.
        return TemporalValidity('current_listing', year_only, undated,
                                tuple(reasons + ['Authoritative source explicitly confirms current listing; event date may be unknown.']))
    if e.valid_from or e.valid_until:
        reasons.append('Incomplete validity interval does not by itself establish current or expired certification.')
    if exact_event is None:
        reasons.append('Event date is unknown/approximate; snapshot/retrieval dates do not establish freshness.')
    return TemporalValidity('dated' if exact_event else 'undated', year_only, False, tuple(reasons))
