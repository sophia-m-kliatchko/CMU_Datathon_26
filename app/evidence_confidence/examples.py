"""Run fictional, realistic contract-shaped scenarios: python -m evidence_confidence.examples.

All fixture citations/names are synthetic. They are not claims about actual hospitals.
"""
import argparse
from dataclasses import replace
from datetime import date
import json

from . import (Citation, Directness, Evidence, FacilityMatch, MatchStatus, Polarity,
               Policy, Scope, SourceKind, Verification, assess)
from .adapters import (from_facility_claim, from_kayakalp, from_nqas, from_registry_service,
                       location_context, registry_match)

AS_OF = date(2026, 11, 21)
FACILITY = 'synthetic-facility-001'


def cases(policy=None):
    citation = Citation('Synthetic self-report fixture', 'fixture://claims/dialysis', 'Dialysis claimed in capability list.')
    claim = from_facility_claim(dict(facility_id=FACILITY,claim_field='capability',claim_position=0,
                                    claim_text='Dialysis'), service='dialysis', polarity=Polarity.SUPPORTS,
                                direct=True, observed_on=AS_OF, citations=(citation,))
    link = registry_match(dict(facility_id=FACILITY,site_id='laqshya:synthetic-1',match_score=95,
                               needs_review=False,match_method='reviewed_name+address'))
    certificate = from_registry_service(dict(service_row_id='synthetic-cert-1',site_id=link.reference_id,
        source='laqshya',service='emergency_c_section',evidence_type='government_certification',
        service_specific=True,evidence_detail='Synthetic maternity OT certification; valid until 2027-10-21.',
        status='certified',evidence_date='2026-10-21',valid_until='2027-10-21',is_current=True,
        retrieved_on='2026-11-21',source_url='fixture://laqshya/synthetic-1',dq_flags=[]),link)
    training = from_registry_service(dict(service_row_id='synthetic-course-1',site_id='nmc:synthetic-2',
        source='nmc',service='dialysis',evidence_type='government_training_approval',service_specific=False,
        evidence_detail='Synthetic NMC-approved D.M. Nephrology course; service tag is inferred.',status='approved',
        evidence_date=None,is_current=True,retrieved_on='2026-11-21',dq_flags=['INDIRECT_VIA_SPECIALTY'],
        source_url='fixture://nmc/synthetic-course'),replace(link,reference_id='nmc:synthetic-2'))
    negative = Evidence('synthetic-negative','independent_review',SourceKind.INDEPENDENT_CHECK,Scope.SERVICE,
        'Synthetic dated independent notice explicitly states dialysis is not offered at this branch.',
        replace(link,reference_id='notice-1'), service='dialysis', polarity=Polarity.CONTRADICTS,
        verification=Verification.INDEPENDENT,directness=Directness.DIRECT,observed_on=AS_OF,
        citations=(Citation('Synthetic notice','fixture://notices/1','Dialysis not offered at this branch.'),))
    award = from_kayakalp(dict(award_id='synthetic-kayakalp-2021-22-1',financial_year='2021-22',
        award_raw='Winner-Kayakalp',row_citation='Synthetic FY 2021-22 cleanliness-award citation.',
        retrieved_on='2026-11-21',source_url='fixture://kayakalp/page-1',dq_flags=[]),
        replace(link,reference_id='synthetic-kayakalp-2021-22-1'))
    nqas = from_nqas(dict(certification_id='synthetic-nqas-1',department_assessed='Partial departments',
        covers_all_departments=False,validity_from='2020-01-01',validity_to='2023-01-01',
        certification_status='expired',row_citation='Synthetic expired partial NQAS certificate.',
        source_url='fixture://nqas/cert-1',dq_flags=['CERTIFICATION_EXPIRED']),
        replace(link,reference_id='synthetic-nqas-1'))
    pending = replace(certificate,match=replace(certificate.match,status=MatchStatus.PENDING))
    scenarios = [
        ('no_evidence','dialysis',[],None),
        ('self_report_only','dialysis',[claim],None),
        ('training_is_indirect','dialysis',[training],None),
        ('current_scoped_documentary_support','emergency_c_section',[certificate],None),
        ('ambiguous_branch_match','emergency_c_section',[pending],None),
        ('explicit_conflict','dialysis',[claim,negative],None),
        ('historical_award_only','dialysis',[award],None),
        ('expired_partial_nqas_only','dialysis',[nqas],None),
        ('service_plus_historical_quality','dialysis',[claim,award,nqas],None),
        ('uncertain_postal_location','dialysis',[claim],location_context(dict(latitude=19.1,longitude=72.9,
            pin_ambiguous=True,centroid_quality='spread_out'),basis='pin_centroid')),
    ]
    return {name:assess(FACILITY,service,evidence,as_of=AS_OF,policy=policy,location=location)
            for name,service,evidence,location in scenarios}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',help='Optional policy JSON; no external data is read.')
    parser.add_argument('--full',action='store_true',help='Print every component, citation, qualifier and policy value.')
    args = parser.parse_args()
    scenarios = cases(Policy.from_json(args.policy) if args.policy else Policy())
    output = {name:r.to_dict() if args.full else dict(
        requested_service=r.requested_service,
        base_tier=r.service_evidence.base_tier.value,
        effective_tier=r.service_evidence.effective_tier.value,
        review_status=r.service_evidence.review_status,
        evidence_flags=r.service_evidence.to_dict()['flags'],
        supporting_source_families=r.service_evidence.supporting_source_families,
        evidence_basis=r.service_evidence.evidence_basis,
        citations=r.service_evidence.to_dict()['citations'],
        explanation=r.service_evidence.explanation,
    ) for name,r in scenarios.items()}
    print(json.dumps({'synthetic_examples_only':True,'as_of':AS_OF.isoformat(),'cases':output},indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
