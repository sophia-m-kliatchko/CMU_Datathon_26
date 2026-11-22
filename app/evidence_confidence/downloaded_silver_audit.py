"""Read-only, explicit-dialect audit of downloaded CSVs; no Spark or remote access.

Data remains untouched. Large tables are streamed. Only core evidence tables and
bounded aggregate/key sets are retained. CSV types are inferred/validated values,
not a claimed original Spark schema. Optional inventory-join probes have unknown
distances and are explicitly NOT geographic searches.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import uuid

from .databricks_validation import silver_contracts
from .silver import adapt_registry_tables, notebook_service_vocabulary
from .adapters import _bool, _date
from .integration import build_facility_service_rows, join_geographic_candidates
from .recommendation import build_recommendation_response
from .validation import validate_integration

KEYS={name:contract.keys for name,contract in silver_contracts().items()}
KEYS.update(pincode_silver_quality_history=('run_timestamp',),silver_dq_summary=('flag',),pincode_dq_summary=('flag',))
ARRAYS={
 'facilities_silver':('dq_flags','possible_duplicate_ids','name_variants','state_variants','pincode_variants',
    'states_mentioned_in_text','description_all','specialties','procedure','equipment','capability','source_row_ids'),
 'registry_sites_silver':('dq_flags',),'registry_services_silver':('dq_flags',),'nqas_silver':('dq_flags',),
 'pincode_silver':('dq_flags','source_row_ids'),'pincode_centroids_silver':('districts','states'),
 'facility_registry_summary_silver':('registry_sources','listing_categories','services_evidenced','services_evidenced_pending_review'),
 'silver_rejected_facilities':('source_row_ids',),
}
NUMBERS={
 'facilities_silver':('latitude_clean','longitude_clean','year_established_clean','num_doctors_clean','capacity_clean'),
 'facility_registry_links_silver':('match_score','distance_km','name_score'),
 'facility_registry_summary_silver':('n_registry_links','n_links_needing_review','best_match_score'),
 'silver_dq_summary':('n_facilities','pct_of_facilities'),
 'registry_sites_silver':('latitude','longitude','pin_latitude','pin_longitude'),
 'registry_services_silver':('approved_seats',),
 'pincode_silver':('latitude','longitude','km_from_pin_median'),
 'pincode_centroids_silver':('latitude','longitude','max_office_distance_km','n_offices'),
 'nfhs_silver':('households_surveyed','women_15_49_interviewed','men_15_54_interviewed',
    'sex_ratio_total_f_per_1000_m','sex_ratio_at_birth_5y_f_per_1000_m',
    'female_population_age_6_years_and_above_ever_schooled_pct','population_below_age_15_years_pct',
    'child_u5_whose_birth_was_civil_reg_pct'),
}
BOOLS={'facility_registry_links_silver':('needs_review','pin_match','place_match','type_match'),
 'registry_services_silver':('service_specific','is_current'), 'registry_sites_silver':('listing_current',),
 'facilities_silver':('coords_low_precision','pin_state_consistent','pincode_from_address_text'),
 'nqas_silver':('district_in_state','covers_all_departments'),
 'pincode_silver':('is_delivery_office','coords_far_from_pin','pin_ambiguous'),
 'pincode_centroids_silver':('pin_ambiguous',)}
DATES={'nqas_silver':('validity_from','validity_to','retrieved_on'),
 'registry_sites_silver':('retrieved_on',), 'registry_services_silver':('evidence_date','valid_until','retrieved_on')}
RETAIN={'facilities_silver','registry_sites_silver','registry_services_silver','facility_registry_links_silver','registry_match_review',
        'facility_registry_summary_silver','pincode_centroids_silver','nqas_silver'}
PII=('email','officialPhone','phone','phone_number','contact_email')


def audit_downloads(directory, *, as_of, notebook_path, prior_report=None, inventory_probe=True):
    directory=Path(directory).resolve()
    if not directory.is_dir():raise ValueError('download directory not found')
    csv.field_size_limit(sys.maxsize)
    inventory=[];issues=defaultdict(lambda: {'count':0,'examples':[]});tables={}
    all_ids={};refs=defaultdict(list);site_service_pairs=Counter();pin_values=set();files=list(sorted(directory.rglob('*')))
    hashes={};vocabulary=notebook_service_vocabulary(notebook_path)
    expected=silver_contracts();prior={}
    if prior_report and Path(prior_report).is_file():
        old=json.loads(Path(prior_report).read_text())
        prior={r['table'].split('.')[-1]:r['row_count'] for r in json.loads(old['notebook_output']['result'])['tables']}
    def issue(table,code,row=None,*,severity='ERROR',field=None):
        item=issues[(table,code,severity)];item['count']+=1
        if len(item['examples'])<3:
            item['examples'].append({'record':row,'field':field})
    for path in files:
        if not path.is_file():continue
        relative=str(path.relative_to(directory));name=path.stem
        digest=hashlib.sha256(path.read_bytes()).hexdigest();hashes[str(path)]=digest
        if path.suffix.lower()!='.csv':
            issue(relative,'UNEXPECTED_FORMAT');continue
        if name in tables or any(r['dataset']==name for r in inventory):
            issue(name,'DUPLICATE_EXPORT');continue
        entry={'dataset':name,'path':str(path),'format':'CSV','bytes':path.stat().st_size,'sha256':digest,
               'csv_dialect':{'escapechar':'\\','quotechar':'"','strict':True},'records':0,'columns':[],
               'null_counts':{},'logical_type_checks':{},'array_columns':list(ARRAYS.get(name,())),
               'dataframe_schema_available':False,'contact_field_nonempty':{},'source_counts':{},'dq_flags':{},
               'prior_databricks_rows':prior.get(name),'legacy_aliases':[]}
        seen=set();row_hashes=set();full_duplicates=0;facids=set();nulls=Counter();contact=Counter();sources=Counter();flags=Counter();type_errors=Counter()
        rows=[];ids=set();parse_ok=True
        try:
            with path.open(newline='',encoding='utf-8-sig') as handle:
                reader=csv.reader(handle,escapechar='\\',doublequote=True,strict=True)
                header=next(reader);entry['columns']=header
                if len(set(header))!=len(header):issue(name,'DUPLICATE_HEADER')
                contract=expected.get(name)
                if contract is None:issue(name,'OUTPUT_NOT_IN_CURRENT_PIPELINE',severity='WARNING')
                # A legacy schema is reported rather than relabelled in place.
                for col in header:
                    if '_clean' in col:entry['legacy_aliases'].append(col)
                required=set(contract.required+contract.keys) if contract else set()
                missing=required-set(header)
                for field in sorted(missing):
                    legacy=field+'_clean'
                    if legacy in header:
                        issue(name,'LEGACY_COLUMN_MAPPING_REQUIRED',severity='WARNING',field=f'{legacy} -> {field}')
                    else:issue(name,'REQUIRED_COLUMN_MISSING',field=field)
                if contract and contract.provenance:
                    for field in ('source_name','source_publisher','source_url','retrieved_on','source_license','produced_by','row_citation'):
                        if field not in header:issue(name,'PROVENANCE_COLUMN_MISSING',field=field)
                for index,values in enumerate(reader,1):
                    entry['records']+=1
                    if len(values)!=len(header):
                        issue(name,'CSV_RECORD_WIDTH',index);parse_ok=False;continue
                    fingerprint=hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).digest()
                    if fingerprint in row_hashes:full_duplicates+=1;issue(name,'DUPLICATE_FULL_ROW',index)
                    row_hashes.add(fingerprint)
                    row={k:(None if value=='' else value) for k,value in zip(header,values)}
                    for key,value in row.items():
                        if value is None:nulls[key]+=1
                    for field in PII:
                        if row.get(field):contact[field]+=1
                    # Screen for credential shapes without exposing matched values.
                    if any(value and re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b',value) for value in values):
                        issue(name,'POSSIBLE_CREDENTIAL',index)
                    for field in ARRAYS.get(name,()):
                        if row.get(field) is not None:
                            try:
                                value=json.loads(row[field])
                                if not isinstance(value,list):raise ValueError('not array')
                                row[field]=value
                            except (ValueError,TypeError):
                                issue(name,'INVALID_JSON_ARRAY',index,field=field);parse_ok=False
                    for field in NUMBERS.get(name,()):
                        if row.get(field) is not None:
                            try:
                                if not math.isfinite(float(row[field])):raise ValueError('nonfinite')
                            except (ValueError,TypeError):
                                type_errors[field]+=1;issue(name,'INVALID_NUMBER',index,field=field)
                    for field in BOOLS.get(name,()):
                        if row.get(field) is not None:
                            try:_bool(row[field])
                            except ValueError:type_errors[field]+=1;issue(name,'INVALID_BOOLEAN',index,field=field)
                    for field in DATES.get(name,()):
                        if row.get(field) is not None:
                            try:_date(row[field])
                            except ValueError:type_errors[field]+=1;issue(name,'INVALID_DATE',index,field=field)
                    keys=KEYS.get(name,())
                    if keys and set(keys)<=set(header):
                        key=tuple(row.get(k) for k in keys)
                        if any(v is None or isinstance(v,str) and not v.strip() for v in key):issue(name,'NULL_OR_BLANK_KEY',index)
                        elif key in seen:issue(name,'DUPLICATE_KEY',index)
                        else:seen.add(key)
                    pk=keys[0] if len(keys)==1 else None
                    if pk and row.get(pk) is not None:ids.add(row[pk])
                    if name=='facilities_silver':
                        fid=row.get('facility_id');facids.add(fid)
                        try:
                            if str(uuid.UUID(fid))!=fid:raise ValueError('noncanonical')
                        except (ValueError,TypeError,AttributeError):issue(name,'INVALID_CANONICAL_UUID',index)
                    if name in ('pincode_silver','pincode_centroids_silver','facilities_silver','registry_sites_silver'):
                        pinfield='pincode_clean' if name=='facilities_silver' and 'pincode_clean' in header else 'pincode'
                        pin=row.get(pinfield)
                        if pin is not None and not re.fullmatch(r'[1-9][0-9]{5}',pin):issue(name,'INVALID_PIN',index,field=pinfield)
                        latfield='latitude_clean' if name=='facilities_silver' and 'latitude_clean' in header else 'latitude'
                        lonfield='longitude_clean' if name=='facilities_silver' and 'longitude_clean' in header else 'longitude'
                        lat,lon=row.get(latfield),row.get(lonfield)
                        if (lat is None)!=(lon is None):issue(name,'HALF_COORDINATE_PAIR',index)
                        if lat is not None and lon is not None:
                            try:
                                if not (6<=float(lat)<=37.5 and 68<=float(lon)<=97.5):issue(name,'COORDINATES_OUTSIDE_INDIA',index)
                            except (ValueError,TypeError):issue(name,'INVALID_COORDINATE_TYPE',index)
                    if name=='pincode_silver' and row.get('pincode') is not None:pin_values.add(row['pincode'])
                    if name=='registry_services_silver':
                        if row.get('service') not in vocabulary:issue(name,'UNKNOWN_CANONICAL_SERVICE',index)
                        refs[(name,'site_id','registry_sites_silver')].append((index,row.get('site_id')))
                        site_service_pairs[(row.get('site_id'),row.get('service'))]+=1
                    if name=='facility_registry_links_silver':
                        refs[(name,'site_id','registry_sites_silver')].append((index,row.get('site_id')))
                        refs[(name,'facility_id','facilities_silver')].append((index,row.get('facility_id')))
                        try:
                            score=float(row['match_score'])
                            if not 0<=score<=100:raise ValueError('range')
                        except (ValueError,TypeError,KeyError):issue(name,'INVALID_MATCH_SCORE',index)
                    if name in ('silver_facility_claims','facility_registry_summary_silver'):
                        refs[(name,'facility_id','facilities_silver')].append((index,row.get('facility_id')))
                    if name=='silver_possible_duplicates':
                        for key in ('facility_id_a','facility_id_b'):refs[(name,key,'facilities_silver')].append((index,row.get(key)))
                    if contract and contract.provenance:
                        for field in ('source_name','source_publisher','source_url','retrieved_on','source_license','produced_by','row_citation'):
                            if not row.get(field) or not str(row[field]).strip():issue(name,'INCOMPLETE_PROVENANCE',index,field=field)
                        from .silver import _public_url
                        if row.get('source_url') and not _public_url(row['source_url']):issue(name,'INVALID_SOURCE_URL',index)
                    if name=='nqas_silver':
                        try:
                            start,end=_date(row.get('validity_from')),_date(row.get('validity_to'))
                            if start and end and start>end:issue(name,'REVERSED_VALIDITY',index)
                            if end and row.get('certification_status')=='current' and end<as_of:
                                issue(name,'STALE_BUILD_DATE_STATUS',index,severity='WARNING')
                        except ValueError:pass
                    if row.get('source'):sources[row['source']]+=1
                    if isinstance(row.get('dq_flags'),list):flags.update(row['dq_flags'])
                    if name in RETAIN:rows.append(row)
                entry['distinct_keys']=len(seen) if keys else None
        except (csv.Error,UnicodeError,StopIteration,ValueError) as exc:
            issue(name,'CSV_PARSE_ERROR',entry['records'],field=str(exc));parse_ok=False
        entry['full_row_duplicates']=full_duplicates
        entry['null_counts']=dict(sorted(nulls.items()));entry['contact_field_nonempty']=dict(contact)
        entry['source_counts']=dict(sorted(sources.items()));entry['dq_flags']=dict(sorted(flags.items()))
        entry['logical_type_checks']={'numeric_fields':list(NUMBERS.get(name,())),
            'boolean_fields':list(BOOLS.get(name,())),'date_fields':list(DATES.get(name,())),'invalid_values':dict(type_errors)}
        if prior.get(name) is not None and entry['records']!=prior[name]:issue(name,'ROW_COUNT_DIFFERS_FROM_PRIOR_RUN',severity='WARNING')
        entry['status']='FAIL' if any(key[0]==name and key[2]=='ERROR' for key in issues) else 'PARTIAL' if entry['legacy_aliases'] else 'PASS'
        inventory.append(entry);all_ids[name]=ids
        if name in RETAIN and parse_ok:tables[name]=rows
    for (child,field,parent),values in refs.items():
        if parent not in all_ids:issue(child,'MISSING_REFERENCE_DATASET',field=parent);continue
        for index,value in values:
            if value is None or value not in all_ids[parent]:issue(child,'ORPHAN_REFERENCE',index,field=field)
    if 'pincode_centroids_silver' in tables:
        for index,row in enumerate(tables['pincode_centroids_silver'],1):
            if row.get('pincode') not in pin_values:issue('pincode_centroids_silver','ORPHAN_PIN_REFERENCE',index)
        centroids={r['pincode']:r for r in tables['pincode_centroids_silver']}
        for index,row in enumerate(tables.get('facilities_silver',()),1):
            pin=row.get('pincode_clean',row.get('pincode'));state=row.get('state_clean',row.get('state'))
            ref=centroids.get(pin)
            if pin and ref is None:issue('facilities_silver','PIN_NOT_IN_AVAILABLE_DIRECTORY',index,severity='WARNING')
            elif state and ref and isinstance(ref.get('states'),list) and state not in ref['states']:
                issue('facilities_silver','STATE_PIN_REFERENCE_DISAGREEMENT',index,severity='WARNING')
        for index,row in enumerate(tables.get('nqas_silver',()),1):
            if row.get('district_in_state') is not None and _bool(row['district_in_state']) is False:
                issue('nqas_silver','UPSTREAM_DISTRICT_NOT_IN_STATE_REFERENCE',index,severity='WARNING')
    if all(name in tables for name in ('facility_registry_summary_silver','facility_registry_links_silver','registry_services_silver')):
        services=defaultdict(set)
        for row in tables['registry_services_silver']:services[row['site_id']].add(row['service'])
        by_facility=defaultdict(list)
        for row in tables['facility_registry_links_silver']:by_facility[row['facility_id']].append(row)
        for index,row in enumerate(tables['facility_registry_summary_silver'],1):
            links=by_facility[row['facility_id']]
            expected_counts={'n_registry_links':len({l['site_id'] for l in links}),
                'n_links_needing_review':len({l['site_id'] for l in links if _bool(l['needs_review']) is True})}
            for field,value in expected_counts.items():
                try:
                    if row.get(field) is None or float(row[field])!=value:issue('facility_registry_summary_silver','SUMMARY_COUNT_MISMATCH',index,field=field)
                except (ValueError,TypeError):issue('facility_registry_summary_silver','SUMMARY_COUNT_UNPARSEABLE',index,field=field)
            for field,review in (('services_evidenced',False),('services_evidenced_pending_review',True)):
                tags=set().union(*(services[l['site_id']] for l in links if _bool(l['needs_review']) is review)) if links else set()
                actual=set(row.get(field) or [])
                if actual!=tags:issue('facility_registry_summary_silver','SUMMARY_SERVICE_MISMATCH',index,field=field)
    missing=sorted(set(expected)-{r['dataset'] for r in inventory})
    findings=[dict(table=table,code=code,severity=severity,**values) for (table,code,severity),values in sorted(issues.items())]
    evidence_result={'status':'BLOCKED','reason':'Core exports have structural errors or are missing.'}
    core=('facilities_silver','registry_sites_silver','registry_services_silver','facility_registry_links_silver')
    if all(name in tables for name in core) and not any(f['severity']=='ERROR' and f['table'] in core for f in findings):
        adapted=adapt_registry_tables(*(tables[name] for name in core),canonical_services=vocabulary,
            reviews=tables.get('registry_match_review',()))
        evidence_result={k:v for k,v in adapted.items() if k!='evidence'}
        if adapted['status']=='PASS':
            records=adapted['evidence'];assessments=build_facility_service_rows(records,as_of=as_of)
            evidence_result['observed_pair_tiers']=dict(sorted(Counter(r['effective_tier'] for r in assessments).items()))
            evidence_result['observed_pairs']=len(assessments)
            evidence_result['pending_stronger_rows']=sum(r['pending_stronger_tier'] is not None for r in assessments)
            evidence_result['t3_with_pending_t1']=sum(r['effective_tier']=='T3' and r['pending_stronger_tier']=='T1' for r in assessments)
            evidence_result['real_geographic_end_to_end']='BLOCKED: no geographic candidate export or facility_geo_ready provided'
            evidence_result['review_queue']='missing; only review metadata present in core links was processed'
            if inventory_probe:
                geo=[dict(facility_id=r['facility_id'],name=r.get('name'),distance_km=None,
                    geo_confidence=None,location_basis=None) for r in tables['facilities_silver']]
                probes={}
                for service,mode in (('emergency_c_section','routine'),('dialysis','routine'),('emergency_c_section','urgent')):
                    output=build_facility_service_rows(records,as_of=as_of,facility_services=[(r['facility_id'],service) for r in geo])
                    joined=join_geographic_candidates(geo,output,service=service,as_of=as_of)
                    request=dict(pin='110001',service=service,radius_km=50,mode=mode,as_of=as_of.isoformat())
                    response=build_recommendation_response(request,records,geo)
                    checked=validate_integration(canonical_facility_ids=all_ids['facilities_silver'],canonical_services=vocabulary,
                        evidence_records=records,evidence_rows=output,geographic_candidates=geo,joined_rows=joined,as_of=as_of,response=response)
                    probes[service if mode=='routine' else service+':urgent']={'mode':mode,
                        'urgent_confirmed_recommendations':len(response['recommendations']) if mode=='urgent' else None,'status':checked['status'],'counts':checked['counts'],'tiers':checked['tier_distribution'],
                        'error_codes':dict(Counter(e['code'] for e in checked['errors'])),
                        'warning_codes':dict(Counter(e['code'] for e in checked['warnings'])),
                        'geographic_search':False,'distances':'all unknown; no radius applied',
                        'citations_preserved':not checked['errors']}
                evidence_result['non_geographic_facility_inventory_probes']=probes
            evidence_result['status']='PARTIAL'
    for entry in inventory:
        if any(f['table']==entry['dataset'] and f['severity']=='ERROR' for f in findings):entry['status']='FAIL'
        elif entry['legacy_aliases'] or any(f['table']==entry['dataset'] for f in findings):entry['status']='WARNING'
    report={'directory':str(directory),'as_of':as_of.isoformat(),'files':len(inventory),
        'total_bytes':sum(r['bytes'] for r in inventory),'data_quality_status':'FAIL' if any(f['severity']=='ERROR' for f in findings) else 'PASS_WITH_WARNINGS',
        'inventory':inventory,'findings':findings,
        'missing_expected_outputs':missing,'extra_outputs':sorted({r['dataset'] for r in inventory}-set(expected)),'missing_geography':['facility_geo_ready','geographic_candidates'],
        'legitimate_multiple_site_service_groups':sum(n>1 for n in site_service_pairs.values()),
        'evidence_confidence':evidence_result,
        'publication':{'status':'BLOCKED','oversize_regular_git_files':[r['dataset'] for r in inventory if r['bytes']>100*1024**2],
            'warning_size_files':[r['dataset'] for r in inventory if 50*1024**2<r['bytes']<=100*1024**2],
            'unresolved_rights':['Virtue Foundation Marketplace terms','NCG redistribution permission','other source-specific licences'],
            'repository_visibility':'must be checked independently','contact_fields_present':{r['dataset']:r['contact_field_nonempty'] for r in inventory if r['contact_field_nonempty']}},
        'limitations':['CSV has no authoritative Spark type/nullability metadata; value checks do not recover an original schema.',
            'Prior counts are a comparison to an independently generated earlier run, not proof of the downloaded export origin.',
            'No source manifest or extraction timestamp was supplied; source lineage is inferred from headers/provenance and code.',
            'Non-geographic probes use real IDs/evidence with explicit unknown distance/confidence; they are not real PIN search validation.',
            'Absent rejected links/negative assertions cannot validate those rules on real observations; retain synthetic regression coverage.']}
    # Confirm the audit did not mutate or race with changing inputs.
    by_hash=defaultdict(list)
    for path,digest in hashes.items():by_hash[digest].append(str(Path(path).relative_to(directory)))
    report['duplicate_file_hashes']=[paths for paths in by_hash.values() if len(paths)>1]
    report['input_hashes_unchanged']=all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    p.add_argument('--as-of',required=True,type=date.fromisoformat)
    p.add_argument('--notebook',default='notebooks/05_registries_bronze_to_silver.py')
    p.add_argument('--prior-report');p.add_argument('--output',required=True)
    a=p.parse_args();report=audit_downloads(a.directory,as_of=a.as_of,notebook_path=a.notebook,prior_report=a.prior_report)
    Path(a.output).write_text(json.dumps(report,indent=2,allow_nan=False))
    print(json.dumps({'files':report['files'],'bytes':report['total_bytes'],'findings':len(report['findings']),
        'missing':report['missing_expected_outputs'],'evidence_status':report['evidence_confidence']['status'],
        'publication':report['publication'],'inputs_unchanged':report['input_hashes_unchanged']},indent=2))


if __name__=='__main__':main()
