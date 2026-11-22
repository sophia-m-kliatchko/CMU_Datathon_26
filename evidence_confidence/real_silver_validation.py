"""Read-only local-export runner. No Databricks, Spark execution or fabricated data.

python -m evidence_confidence.real_silver_validation --export-dir PATH --as-of YYYY-MM-DD
Add --kayakalp-export PATH to profile an existing isolated/legacy Silver export.
For real end-to-end validation also supply --pin, --service and --radius-km and
an untruncated geographic_candidates export from that PIN/radius search.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

from .integration import build_facility_service_rows, join_geographic_candidates
from .recommendation import build_recommendation_response
from .silver import (adapt_quality_tables, adapt_registry_tables, local_inventory,
                     notebook_service_vocabulary, read_local_export)
from .validation import validate_integration


def run_local_validation(export_dir, *, as_of, notebook_path, request=None, kayakalp_export=None, csv_escapechar=None):
    inventory=local_inventory(export_dir,additional_exports=(
        {'kayakalp_silver':kayakalp_export} if kayakalp_export else None),csv_escapechar=csv_escapechar)
    hard_profile_fields=('missing_primary_keys','invalid_primary_key_types','duplicate_primary_key_rows',
                         'untyped_flag_rows','geographic_alias_conflicts')
    invalid_profiles=[name for name,entry in inventory['exports'].items()
                      if any(entry['profile'][key] for key in hard_profile_fields)]
    report={'readiness':inventory['readiness'],'inventory':inventory,
            'service_vocabulary':notebook_service_vocabulary(notebook_path),
            'source_profiles_status':'FAIL' if invalid_profiles else 'PASS' if inventory['exports'] else 'BLOCKED',
            'invalid_profiles':invalid_profiles,
            'real_end_to_end':{'status':'BLOCKED','reason':'Missing core local Silver exports.'}}
    if inventory['missing_core_exports']:
        return report
    if invalid_profiles:
        report.update(readiness='BLOCKED',real_end_to_end={'status':'FAIL','reason':'Resolve local export integrity failures.'})
        return report
    tables={name:read_local_export(entry['path'],csv_escapechar=csv_escapechar) for name,entry in inventory['exports'].items()}
    adapted=adapt_registry_tables(tables['facilities_silver'],tables['registry_sites_silver'],
        tables['registry_services_silver'],tables['facility_registry_links_silver'],
        canonical_services=report['service_vocabulary'],reviews=tables.get('registry_match_review',()))
    report['registry_adaptation']={key:value for key,value in adapted.items() if key!='evidence'}
    if adapted['status']=='FAIL':
        report.update(readiness='BLOCKED',real_end_to_end={'status':'FAIL','reason':'Resolve registry integrity/adapter errors.'})
        return report
    if request is None:
        report['readiness']='BLOCKED'
        report['real_end_to_end']['reason']='Supply the real candidate batch PIN/service/radius context.'
        return report
    if request['service'] not in report['service_vocabulary']:
        raise ValueError('requested service is outside notebook 05 vocabulary')
    records=list(adapted['evidence'])
    unlinked_quality={}
    for source in ('nqas','kayakalp'):
        table=source+'_silver'
        if table not in tables:
            unlinked_quality[table]='export_missing'
            continue
        paths=[Path(export_dir)/(source+'_facility_links'+suffix) for suffix in ('.jsonl','.json','.parquet','.csv')
               if (Path(export_dir)/(source+'_facility_links'+suffix)).is_file()]
        if len(paths)>1:
            raise ValueError('ambiguous supplemental quality link exports')
        links=read_local_export(paths[0],csv_escapechar=csv_escapechar) if paths else []
        records.extend(adapt_quality_tables(tables[table],links,source=source,
            canonical_facility_ids=[r['facility_id'] for r in tables['facilities_silver']]))
        key='award_id' if source=='kayakalp' else 'certification_id'
        unlinked_quality[table]=len({r[key] for r in tables[table]}-{l['source_record_id'] for l in links})
    geo=tables['geographic_candidates']
    if not tables['facilities_silver'] or not geo:
        report.update(readiness='BLOCKED',real_end_to_end={'status':'BLOCKED',
            'reason':'Empty canonical facility inventory or geographic batch cannot establish real end-to-end coverage.'})
        return report
    # Caller must provide an export from precisely this request, before top-k or
    # service substring filtering. This runner does not calculate distances.
    rows=build_facility_service_rows(records,as_of=as_of,
        facility_services=[(g['facility_id'],request['service']) for g in geo])
    joined=join_geographic_candidates(geo,rows,service=request['service'],as_of=as_of)
    response=build_recommendation_response({**request,'as_of':as_of.isoformat()},records,geo)
    checks=validate_integration(canonical_facility_ids=[r['facility_id'] for r in tables['facilities_silver']],
        canonical_services=report['service_vocabulary'],evidence_records=records,evidence_rows=rows,
        geographic_candidates=geo,joined_rows=joined,as_of=as_of,response=response)
    report['real_end_to_end']={'status':'FAIL' if checks['errors'] else 'PASS',
        'validation':checks,'candidate_count':len(geo),
        'response_count':len(response['recommendations'])+len(response['alternatives']),
        'credible_contradiction_decisions':sum(d['credible_contradiction'] for r in rows for d in r['decisions']),
        'citation_count':sum(len(r['citations']) for r in rows),
        'supporting_source_family_counts':dict(Counter(str(r['supporting_source_count']) for r in rows)),
        'unlinked_quality_records':unlinked_quality,
        'limitations':['Registry/quality evidence only; facility text claims need reviewed service/polarity mappings.',
            'Upstream geographic truncation and substring filtering cannot be detected from an incomplete export.',
            'No emergency capability assessments are inferred; urgent mode requires an explicit upstream source.']}
    report['readiness']='BLOCKED' if checks['errors'] else 'PARTIALLY READY'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-dir',required=True)
    parser.add_argument('--as-of',required=True,type=date.fromisoformat)
    parser.add_argument('--notebook',default='notebooks/05_registries_bronze_to_silver.py')
    parser.add_argument('--kayakalp-export')
    parser.add_argument('--csv-escapechar',help='Explicit one-character CSV escape convention; no automatic repair')
    parser.add_argument('--pin');parser.add_argument('--service');parser.add_argument('--radius-km',type=float)
    parser.add_argument('--mode',choices=('routine','urgent'),default='routine')
    args=parser.parse_args()
    if args.csv_escapechar is not None and len(args.csv_escapechar)!=1:
        parser.error('--csv-escapechar must be exactly one character')
    supplied=(args.pin,args.service,args.radius_km)
    if any(x is not None for x in supplied) and not all(x is not None for x in supplied):
        parser.error('--pin, --service and --radius-km must be supplied together')
    request=dict(pin=args.pin,service=args.service,radius_km=args.radius_km,mode=args.mode) if args.pin else None
    result=run_local_validation(args.export_dir,as_of=args.as_of,notebook_path=args.notebook,
        request=request,kayakalp_export=args.kayakalp_export,csv_escapechar=args.csv_escapechar)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 1 if result['readiness']=='BLOCKED' else 0


if __name__=='__main__':
    raise SystemExit(main())
