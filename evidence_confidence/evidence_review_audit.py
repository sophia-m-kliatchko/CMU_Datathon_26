"""Read-only review of real Silver tiers; controlled geographic fixtures only.

No geographic generation, source mutation, remote access or policy changes.
Every R row gets a ledger entry, including exact source links/review reasons.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path

from .adapters import _bool
from .engine import IDENTITY_REVIEW_FLAGS, INDIRECT_FLAGS
from .models import MatchStatus, Polarity, Scope, SourceKind, Verification, Directness
from .silver import read_local_export, notebook_service_vocabulary, adapt_registry_tables
from .temporal import temporal_validity
from .tiers import Tier, _evidence_class, _tier_from_classes
from .integration import build_facility_service_rows, join_geographic_candidates
from .recommendation import build_recommendation_response
from .validation import validate_integration

CORE=('facilities_silver','registry_sites_silver','registry_services_silver','facility_registry_links_silver')


def _hash(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def load_review_state(directory, *, as_of, repository_root):
    source=Path(directory).resolve();root=Path(repository_root).resolve()
    tables={name:read_local_export(source/(name+'.csv'),csv_escapechar='\\') for name in CORE}
    tables['pincode_centroids_silver']=read_local_export(source/'pincode_centroids_silver.csv',csv_escapechar='\\')
    tables['nqas_silver']=read_local_export(source/'nqas_silver.csv',csv_escapechar='\\')
    reviews=read_local_export(source/'registry_match_review.csv',csv_escapechar='\\') if (source/'registry_match_review.csv').is_file() else []
    vocabulary=notebook_service_vocabulary(root/'notebooks/05_registries_bronze_to_silver.py')
    adapted=adapt_registry_tables(*(tables[name] for name in CORE),canonical_services=vocabulary,reviews=reviews)
    if adapted['status']!='PASS':raise ValueError('real source adaptation failed: '+json.dumps(adapted['findings']))
    records=adapted['evidence'];rows=build_facility_service_rows(records,as_of=as_of)
    return dict(directory=source,root=root,as_of=as_of,tables=tables,adapted=adapted,records=records,rows=rows,
        evidence={e.evidence_id:e for e in records},vocabulary=vocabulary,
        facilities={r['facility_id']:r for r in tables['facilities_silver']},
        links={(r['facility_id'],r['site_id']):r for r in tables['facility_registry_links_silver']})


def _reason_codes(reason):
    reason=reason or ''
    return {code for needle,code in (
        ('near-tie','competing_candidates'),('distinctive name words on one side only','weak_distinctive_name'),
        ('generic (type + place)','generic_type_unconfirmed'),('score below link threshold','below_link_threshold'),
        ('more than 10 km apart','distance_review')) if needle in reason}


def _example(row,state):
    sources=[]
    for d in row['decisions']:
        e=state['evidence'][d['evidence_id']]
        link=state['links'].get((e.match.facility_id,e.match.reference_id))
        sources.append(dict(evidence_id=e.evidence_id,source_record_id=e.source_record_id,source=e.source_id,
            match_status=d['match_status'],candidate_tier=d['candidate_tier'],credited=d['credited'],
            observed_on=e.observed_on.isoformat() if e.observed_on else None,
            valid_from=e.valid_from.isoformat() if e.valid_from else None,
            valid_until=e.valid_until.isoformat() if e.valid_until else None,
            link_id=link.get('link_id') if link else None,review_reason=link.get('review_reason') if link else None,
            match_method=link.get('match_method') if link else None,
            citations=[dict(label=c.label,locator=c.locator,quote=c.quote) for c in e.citations]))
    return dict(facility_id=row['facility_id'],name=state['facilities'][row['facility_id']]['name'],service=row['service'],
        base_tier=row['base_tier'],effective_tier=row['effective_tier'],pending_stronger_tier=row['pending_stronger_tier'],
        pending_source_families=row['pending_source_families'],sources=sources)


def audit_rules(state):
    """Cross-check credited premises and overlays, not numerical confidence.

    Uses the shared temporal fact helper but independently tests attribution,
    source/directness gates, scope, strongest-support choice and pending promotion.
    """
    issues=[];premises=Counter();family_counts=Counter();records=state['evidence'];as_of=state['as_of']
    order={'T1':0,'T2':1,'T3':2}
    for row in state['rows']:
        credited=[];families=set();unresolved=[]
        for decision in row['decisions']:
            e=records[decision['evidence_id']];temporal=temporal_validity(e,as_of)
            expected_identity=('rejected' if e.match.status==MatchStatus.REJECTED else 'unknown' if e.match.status==MatchStatus.UNKNOWN
                else 'pending' if e.match.status==MatchStatus.PENDING or IDENTITY_REVIEW_FLAGS.intersection(e.match.flags+e.qualifiers) else 'accepted')
            if decision['match_status']!=expected_identity:issues.append(('IDENTITY_STATUS',e.evidence_id))
            if e.match.facility_id!=row['facility_id'] or e.service!=row['service'] or e.scope!=Scope.SERVICE:
                issues.append(('FACILITY_SERVICE_SCOPE',e.evidence_id))
            if e.polarity==Polarity.SUPPORTS and temporal.status not in ('invalid','not_yet_effective') and expected_identity!='rejected':unresolved.append(expected_identity)
            if decision['credited']:
                tier=decision['candidate_tier'];credited.append(tier);families.add(decision['source_family'])
                premises[tier]+=1;family_counts[(tier,decision['source_family'])]+=1
                if expected_identity!='accepted' or e.polarity!=Polarity.SUPPORTS:issues.append(('UNACCEPTED_CREDIT',e.evidence_id))
                if tier in ('T1','T2'):
                    expected_kind=SourceKind.GOVERNMENT_REGISTRY if e.source_id=='laqshya' else SourceKind.ACCREDITATION
                    if not (e.source_id in ('laqshya','nabh') and e.source_kind==expected_kind and e.verification==Verification.INDEPENDENT
                            and e.directness==Directness.DIRECT and e.citations and not INDIRECT_FLAGS.intersection(e.qualifiers)):
                        issues.append(('DIRECT_PREMISE',e.evidence_id))
                    if tier=='T1' and temporal.status not in ('current_certificate','current_listing'):issues.append(('T1_CURRENCY',e.evidence_id))
                    if tier=='T2' and temporal.status!='historical':issues.append(('T2_HISTORICAL',e.evidence_id))
                elif tier=='T3':
                    if not (e.source_id in ('nmc','dnb','ncg','trauma','virtue_foundation') or
                            e.source_kind==SourceKind.SELF_REPORT or e.verification==Verification.SELF_REPORTED):
                        issues.append(('INDIRECT_PREMISE',e.evidence_id))
                else:issues.append(('INVALID_CREDIT_TIER',e.evidence_id))
        base=min(credited,key=order.get) if credited else 'U'
        if credited:  # tiers/2 class-based upgrade, recomputed from the raw records
            items=[(_evidence_class(records[d['evidence_id']],d['source_family'],Tier(d['candidate_tier']),row['service']),d['source_family'])
                   for d in row['decisions'] if d['credited']]
            base=_tier_from_classes(Tier(base),items)[0].value
        if base!=row['base_tier']:issues.append(('STRONGEST_BASE',row['facility_id'],row['service']))
        if row['supporting_record_count']!=len(credited) or row['supporting_source_count']!=len(families):issues.append(('CORROBORATION_COUNTS',row['facility_id'],row['service']))
        if row['effective_tier']=='R' and (base!='U' or not unresolved or 'accepted' in unresolved):issues.append(('INVALID_R_OVERLAY',row['facility_id'],row['service']))
        if row['effective_tier']=='X' and not any(d['credible_contradiction'] for d in row['decisions']):issues.append(('UNSUPPORTED_X',row['facility_id'],row['service']))
        if row['effective_tier'] in order and row['effective_tier']!=base:issues.append(('PENDING_PROMOTION',row['facility_id'],row['service']))
    return {'status':'PASS' if not issues else 'FAIL','violations':issues,'credited_record_decisions':dict(premises),
        'credited_family_decisions':{f'{tier}:{family}':n for (tier,family),n in sorted(family_counts.items())},
        'limitations':['Temporal facts reuse the existing temporal helper; no independent external certificate authentication.',
            'Correct processing of an accepted link does not establish ground-truth matching accuracy.']}


def audit_r_assessments(state):
    buckets=Counter();overlap=Counter();record_reasons=Counter();family_rows=Counter();ledger=[]
    mapping_issues=Counter();examples={};record_count=0
    for row in state['rows']:
        if row['effective_tier']!='R':continue
        codes=set();sources=set();missing=0;rejected=0;no_candidate=0
        for decision in row['decisions']:
            e=state['evidence'][decision['evidence_id']];link=state['links'].get((e.match.facility_id,e.match.reference_id))
            record_count+=1;sources.add(e.source_id)
            if link is None:missing+=1
            else:codes|=_reason_codes(link.get('review_reason'));record_reasons[link.get('review_reason') or 'unrecorded']+=1
            if decision['match_status']=='rejected':rejected+=1
            if decision['candidate_tier'] is None:no_candidate+=1
            if e.service not in state['vocabulary']:mapping_issues['unknown_canonical_service']+=1
        if missing:bucket='missing_link_provenance'
        elif rejected==len(row['decisions']):bucket='rejected_only_in_R_defect'
        else:bucket=next((c for c in ('competing_candidates','weak_distinctive_name','generic_type_unconfirmed','below_link_threshold','distance_review') if c in codes),'unrecorded_review_reason')
        buckets[bucket]+=1;overlap.update(codes);family_rows.update(sources)
        if no_candidate:mapping_issues['R_pairs_with_nonqualifying_scope_or_validity_record']+=1
        record=dict(facility_id=row['facility_id'],service=row['service'],bucket=bucket,reason_codes=sorted(codes),
            evidence_ids=[d['evidence_id'] for d in row['decisions']],link_ids=sorted({state['links'][(state['evidence'][d['evidence_id']].match.facility_id,state['evidence'][d['evidence_id']].match.reference_id)]['link_id'] for d in row['decisions'] if (state['evidence'][d['evidence_id']].match.facility_id,state['evidence'][d['evidence_id']].match.reference_id) in state['links']}),
            all_links_need_review=all(_bool(state['links'][(state['evidence'][d['evidence_id']].match.facility_id,state['evidence'][d['evidence_id']].match.reference_id)]['needs_review']) is True for d in row['decisions'] if (state['evidence'][d['evidence_id']].match.facility_id,state['evidence'][d['evidence_id']].match.reference_id) in state['links']),
            missing_links=missing,rejected_decisions=rejected,nonqualifying_candidate_decisions=no_candidate)
        ledger.append(record);examples.setdefault(bucket,_example(row,state))
    return {'count':len(ledger),'service_record_decisions':record_count,'exclusive_reason_buckets':dict(buckets),
        'reason_overlap_pair_counts':dict(overlap),'source_family_pair_counts_overlap':dict(family_rows),
        'record_review_reasons':dict(record_reasons),'service_mapping_checks':dict(mapping_issues),
        'all_R_links_explicitly_need_review':all(r['all_links_need_review'] and not r['missing_links'] for r in ledger),
        'rejected_only_R':sum(r['bucket']=='rejected_only_in_R_defect' for r in ledger),
        'missing_identity_links_in_R':sum(r['missing_links']>0 for r in ledger),'examples':examples},ledger


def warning_impacts(state):
    centroids={r['pincode']:r for r in state['tables']['pincode_centroids_silver']}
    groups={'missing_directory_pin':set(),'state_pin_disagreement':set()}
    for fid,row in state['facilities'].items():
        pin=row.get('pincode_clean',row.get('pincode'));region=row.get('state_clean',row.get('state'));ref=centroids.get(pin)
        if pin and ref is None:groups['missing_directory_pin'].add(fid)
        elif region and ref:
            states=json.loads(ref['states']) if isinstance(ref.get('states'),str) else ref.get('states',[])
            if region not in states:groups['state_pin_disagreement'].add(fid)
    results={}
    for name,ids in groups.items():
        links=[r for r in state['tables']['facility_registry_links_silver'] if r['facility_id'] in ids]
        rows=[r for r in state['rows'] if r['facility_id'] in ids]
        example=[]
        for fid in sorted(ids)[:3]:
            fac=state['facilities'][fid];subset=[r for r in links if r['facility_id']==fid]
            example.append(dict(facility_id=fid,name=fac['name'],pincode=fac.get('pincode_clean',fac.get('pincode')),
                state=fac.get('state_clean',fac.get('state')),links=len(subset),
                match_methods=sorted({r['match_method'] for r in subset})))
        results[name]={'facilities':len(ids),'with_registry_links':len({r['facility_id'] for r in links}),
            'links':len(links),'link_statuses':dict(Counter('pending' if _bool(r['needs_review']) else 'accepted' for r in links)),
            'method_components_overlap':dict(Counter(part for r in links for part in r['match_method'].split('+'))),
            'observed_pair_tiers':dict(Counter(r['effective_tier'] for r in rows)),'examples':example,
            'impact':'Geographic input/reference issue; may weaken PIN-based identity corroboration. It does not itself prove a wrong match or service absence.',
            'current_tier_policy':'Not an automatic tier gate; existing categorical links and explicit identity-review flags remain authoritative.'}
    flagged=[r for r in state['tables']['nqas_silver'] if _bool(r.get('district_in_state')) is False]
    results['nqas_district_reference']={'records':len(flagged),'canonical_facility_id_rows':sum(bool(r.get('facility_id')) for r in flagged),
        'current_service_assessment_impact':0,'examples':[{k:r.get(k) for k in ('certification_id','facility_name','state','district','district_in_state')} for r in flagged[:3]],
        'impact':'Requires source-owner review before district-based canonical quality matching or geographic alignment; not linked into current service tiers.'}
    return results


def controlled_candidates(state,service,*,count=40,include_facility=None):
    """Real IDs/names; all distances/confidence/uncertainty are CONTROLLED fixtures.

    No coordinates are assigned and these rows are never called a real PIN search.
    """
    t1=next((r['facility_id'] for r in state['rows'] if r['service']==service and r['effective_tier']=='T1'),None)
    linked={r['facility_id'] for r in state['tables']['facility_registry_links_silver']}
    missing=next(fid for fid in sorted(state['facilities']) if fid not in linked)
    selected=[fid for fid in sorted(state['facilities']) if fid!=t1][:count-1]
    for fid in (missing,include_facility):
        if fid and fid not in selected and fid!=t1:selected[-1 if fid==missing else -2]=fid
    if t1:selected.append(t1)
    else:selected.append(next(fid for fid in sorted(state['facilities']) if fid not in selected))
    if len(set(selected))!=count:raise ValueError('controlled fixture identities must be unique')
    rows=[dict(facility_id=fid,name=state['facilities'][fid]['name'],distance_km=float(i+1),
        geo_confidence='controlled_fixture_only',location_basis='controlled_fixture_only',location_uncertainty_km=.5,
        distance_min_km=float(i+1)-.5,distance_max_km=float(i+1)+.5,fixture_only=True) for i,fid in enumerate(selected)]
    return rows,dict(t1_facility_id=t1,missing_evidence_facility_id=missing,geography='CONTROLLED, NOT REAL')


def validate_controlled_integration(state,service='emergency_c_section',include_facility=None):
    candidates,metadata=controlled_candidates(state,service,include_facility=include_facility)
    rows=build_facility_service_rows(state['records'],as_of=state['as_of'],facility_services=[(r['facility_id'],service) for r in candidates])
    joined=join_geographic_candidates(candidates,rows,service=service,as_of=state['as_of'])
    request=dict(pin='110001',service=service,radius_km=100,mode='routine',as_of=state['as_of'].isoformat())
    response=build_recommendation_response(request,state['records'],candidates)
    checks=validate_integration(canonical_facility_ids=state['facilities'],canonical_services=state['vocabulary'],
        evidence_records=state['records'],evidence_rows=rows,geographic_candidates=candidates,
        joined_rows=joined,as_of=state['as_of'],response=response)
    by_id={r['facility_id']:r for r in rows}
    serialized=json.loads(json.dumps(response,allow_nan=False))
    candidate_index={r['facility_id']:r for r in candidates}
    for item in serialized['recommendations']+serialized['alternatives']:
        fid=item['facility_id']
        if item['service_evidence']!=by_id[fid]:
            raise ValueError('evidence/provenance changed during ranking or JSON export')
        for field in ('geo_confidence','location_basis','distance_km','location_uncertainty_km',
                      'distance_min_km','distance_max_km'):
            if item[field]!=candidate_index[fid][field]:
                raise ValueError('controlled geographic metadata changed during export: '+field)
    if by_id[metadata['missing_evidence_facility_id']]['effective_tier']!='U':raise ValueError('missing evidence did not stay U')
    if build_recommendation_response(request,reversed(state['records']),reversed(candidates))!=response:raise ValueError('nondeterministic fixture result')
    urgent=build_recommendation_response({**request,'mode':'urgent'},state['records'],candidates)
    if urgent['recommendations']:raise ValueError('unsupported urgent-capability claim')
    result={'data_origin':'REAL EVIDENCE / CONTROLLED GEOGRAPHY','service':service,'status':checks['status'],
        'errors':checks['errors'],'warning_codes':dict(Counter(w['code'] for w in checks['warnings'])),
        'counts':checks['counts'],'tiers':checks['tier_distribution'],'metadata':metadata,
        't1_initial_nearest_position':next((i+1 for i,r in enumerate(candidates) if r['facility_id']==metadata['t1_facility_id']),None),
        'response_count':len(response['recommendations'])+len(response['alternatives']),
        'provenance_ranking_json_replay':'PASS' if not checks['errors'] else 'FAIL',
        'confirmed_urgent_recommendations':len(urgent['recommendations']),'deterministic':True}
    if include_facility:result['included_assessment']={k:by_id[include_facility][k] for k in ('facility_id','service','base_tier','effective_tier','pending_stronger_tier','pending_source_families')}
    return result


def run_review_audit(directory,output_dir,*,as_of,repository_root):
    source=Path(directory).resolve();output=Path(output_dir).resolve()
    if output==source or output.is_relative_to(source):raise ValueError('write audit artifacts outside the source data directory')
    output.mkdir(parents=True,exist_ok=True)
    for name in ('review-audit.json','r-assessment-ledger.jsonl'):
        if (output/name).exists():raise FileExistsError('use a new output directory; preserve previous reports')
    hashes={str(p):_hash(p) for p in source.rglob('*') if p.is_file()}
    state=load_review_state(source,as_of=as_of,repository_root=repository_root)
    r_audit,ledger=audit_r_assessments(state);rules=audit_rules(state)
    pending=[r for r in state['rows'] if r['effective_tier']=='T3' and r['pending_stronger_tier']=='T1']
    report={'as_of':as_of.isoformat(),'input_directory':str(source),'tier_counts':dict(Counter(r['effective_tier'] for r in state['rows'])),
        'coverage':state['adapted']['coverage'],'r_assessments':r_audit,'rule_checks':rules,
        'pending_t3_t1':{'count':len(pending),'examples':[_example(r,state) for r in pending]},
        'tier_examples':{tier:_example(next(r for r in state['rows'] if r['effective_tier']==tier),state)
            for tier in sorted({r['effective_tier'] for r in state['rows']})},
        'quality_context_warnings':state['adapted']['findings'],
        'warning_impacts':warning_impacts(state),
        'source_assertion_polarities':dict(Counter(e.polarity.value for e in state['records'])),
        'source_record_ids_missing':sum(e.source_record_id is None for e in state['records']),
        'missing_citation_records':sum(not e.citations for e in state['records']),
        'invalid_temporal_records':sum(temporal_validity(e,as_of).status=='invalid' for e in state['records']),
        'controlled_integration':[validate_controlled_integration(state)],
        'real_geographic_validation':'NOT RUN; waiting for teammate facility_geo_ready and retrieval interface',
        'limitations':['Upstream needs-review labels are not independently adjudicated ground-truth ambiguity.',
            'Rejected and credible negative-assertion cases absent from this snapshot remain covered by regression fixtures.',
            'NQAS/Kayakalp canonical links, reviewed self-report mappings and the review queue are missing.']}
    if pending:report['controlled_integration'].append(validate_controlled_integration(state,pending[0]['service'],pending[0]['facility_id']))
    report['input_hashes_unchanged']=all(_hash(path)==digest for path,digest in hashes.items())
    if not report['input_hashes_unchanged']:raise ValueError('source input changed during audit')
    report['status']='FAIL' if rules['violations'] or any(r['errors'] for r in report['controlled_integration']) else 'PARTIAL'
    (output/'r-assessment-ledger.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in ledger))
    (output/'review-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    p.add_argument('--output-dir',required=True);p.add_argument('--as-of',required=True,type=date.fromisoformat)
    p.add_argument('--repository-root',default=str(Path(__file__).resolve().parents[1]))
    a=p.parse_args();r=run_review_audit(a.directory,a.output_dir,as_of=a.as_of,repository_root=a.repository_root)
    print(json.dumps({'status':r['status'],'tiers':r['tier_counts'],'R':{k:v for k,v in r['r_assessments'].items() if k!='examples'},
        'rules':r['rule_checks'],'pending_t3_t1':r['pending_t3_t1']['count'],
        'warning_impacts':r['warning_impacts'],'controlled_integration':r['controlled_integration']},indent=2))


if __name__=='__main__':main()
