"""Explicitly synthetic pre-Silver smoke: python -m evidence_confidence.synthetic_smoke.

No real hospitals, usable source URLs, actual coordinates or clinical assertions.
The example.invalid domain is intentionally non-resolving; no network is used.
"""
from dataclasses import replace
from datetime import date
import json

from .adapters import from_facility_claim, from_registry_service, registry_match
from .integration import build_facility_service_rows, join_geographic_candidates
from .models import Citation, Directness, Evidence, Polarity, Scope, SourceKind, Verification
from .recommendation import build_recommendation_response
from .validation import validate_integration

AS_OF = date(2026, 11, 21)
SERVICE = 'emergency_c_section'


def synthetic_fixture():
    """Return 32 untruncated geographic candidates plus raw registry/link fixtures."""
    candidates = [dict(facility_id=f'synthetic-{i:03}', name=f'SYNTHETIC Facility {i:03}',
        distance_km=float(i+1), geo_confidence='synthetic_site_coordinates',
        location_basis='site_coordinates') for i in range(32)]
    candidates[10].update(location_basis='pin_centroid', geo_confidence='synthetic_approximate',
        location_uncertainty_km=3., distance_min_km=8., distance_max_km=14.)
    # Deliberately has neither the requested service nor a substring in its name.
    candidates[30]['name'] = 'SYNTHETIC Remote Facility'
    entries = []

    def add(index, source='laqshya', *, pending=False, rejected=False, expired=False):
        key=f'synthetic-{source}-{index}'
        row=dict(service_row_id=key, site_id=f'{source}:{key}', source=source, service=SERVICE,
            evidence_type='government_certification' if source=='laqshya' else 'government_training_approval',
            service_specific=source=='laqshya', evidence_detail='SYNTHETIC service evidence; not a real clinical claim.',
            status='certified' if source=='laqshya' else 'approved',
            evidence_date='2025-01-01', valid_until=('2026-01-01' if expired else '2028-01-01') if source=='laqshya' else None,
            is_current=not expired, retrieved_on=AS_OF.isoformat(),
            source_name='SYNTHETIC source', source_url=f'https://example.invalid/{key}',
            row_citation=f'SYNTHETIC source record {key}, page 1; not real evidence.',
            dq_flags=[] if source=='laqshya' else ['INDIRECT_VIA_SPECIALTY'])
        link=dict(facility_id=candidates[index]['facility_id'], site_id=row['site_id'],
            match_score=95, needs_review=pending, match_method='synthetic_reviewed_identity')
        entries.append((row,link,'reject' if rejected else None))
    add(0)
    add(1,expired=True)
    add(2,source='nmc')
    # 3 intentionally has no evidence.
    add(4,rejected=True)
    add(5,pending=True)
    add(6,source='nmc');add(6,pending=True)
    add(7)
    add(8);entries.append(entries[-1])  # Duplicate ingestion, not corroboration.
    add(30)  # 31st nearest candidate; must survive until AFTER evidence enrichment.
    return {'request':dict(pin='110001',service=SERVICE,radius_km=50.,mode='routine',as_of=AS_OF.isoformat()),
            'geographic_candidates':candidates,'registry_entries':entries}


def adapt_synthetic_evidence(fixture):
    records=[]
    for row,link,decision in fixture['registry_entries']:
        records.append(from_registry_service(row,registry_match(link,reviewer_decision=decision)))
    # An explicitly typed, dated independent counterassertion. Registry adapter
    # does not parse negative statements; never manufacture a negative from absence.
    accepted=next(e for e in records if e.match.facility_id=='synthetic-007')
    records.append(Evidence('synthetic-negative','synthetic_independent_check',SourceKind.INDEPENDENT_CHECK,
        Scope.SERVICE,'SYNTHETIC direct counterassertion requiring review.',
        replace(accepted.match,reference_id='synthetic-negative'),service=SERVICE,
        polarity=Polarity.CONTRADICTS,verification=Verification.INDEPENDENT,directness=Directness.DIRECT,
        observed_on=AS_OF,source_record_id='synthetic-negative',
        citations=(Citation('SYNTHETIC independent notice','https://example.invalid/negative',
                            'SYNTHETIC notice: this service assertion is contested.'),)))
    records.append(from_facility_claim(dict(facility_id='synthetic-009',claim_field='capability',
        claim_position=0,claim_text='SYNTHETIC self-reported service claim.'), service=SERVICE,
        polarity=Polarity.SUPPORTS,citations=(Citation('SYNTHETIC self report',
            'https://example.invalid/self-report','SYNTHETIC self-reported service claim.'),)))
    return records


def run_smoke():
    fixture=synthetic_fixture()
    records=adapt_synthetic_evidence(fixture)
    geo=fixture['geographic_candidates']
    rows=build_facility_service_rows(records,as_of=AS_OF,
        facility_services=[(g['facility_id'],SERVICE) for g in geo])
    joined=join_geographic_candidates(geo,rows,service=SERVICE,as_of=AS_OF)
    response=build_recommendation_response(fixture['request'],records,geo)
    validation=validate_integration(canonical_facility_ids=[g['facility_id'] for g in geo],
        canonical_services=[SERVICE],evidence_records=records,evidence_rows=rows,
        geographic_candidates=geo,joined_rows=joined,as_of=AS_OF,response=response)
    return dict(synthetic_only=True,validation=validation,response=response)


if __name__=='__main__':
    output=run_smoke()
    print(json.dumps({'synthetic_only':True,'validation':output['validation'],
        'candidate_count':output['response']['candidate_count'],
        'ordered_facility_ids':[r['facility_id'] for r in output['response']['recommendations']]},indent=2))
    raise SystemExit(1 if output['validation']['errors'] else 0)
