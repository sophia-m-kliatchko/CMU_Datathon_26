"""Read-only Spark/Unity Catalog checks. No Spark import, writes or row samples.

Pass an existing Spark session. Counts/schema/aggregate violations may be logged;
source records and recommendation payloads stay inside the Databricks process.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TableContract:
    keys: tuple = ()
    required: tuple = ()
    nonempty: bool = False
    provenance: bool = False
    view: bool = False


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError('use simple catalog/schema/table identifiers')
    return value


def qualified(catalog, schema, table):
    return '.'.join(f'`{identifier(x)}`' for x in (catalog,schema,table))


def silver_contracts(kayakalp_table='kayakalp_silver_validation'):
    identifier(kayakalp_table)
    contracts={
        'pincode_silver':TableContract(('office_id',),('pincode','latitude','longitude','dq_flags'),True,True),
        'pincode_centroids_silver':TableContract(('pincode',),('latitude','longitude','centroid_quality'),True,True),
        'pincode_rejected':TableContract(),
        'pincode_dq_summary':TableContract(),
        'facilities_silver':TableContract(('facility_id',),('name','pincode','latitude','longitude','dq_flags'),True),
        'silver_facility_claims':TableContract(('facility_id','claim_field','claim_position'),('claim_text','claim_norm')),
        'silver_possible_duplicates':TableContract(('facility_id_a','facility_id_b')),
        'silver_rejected_facilities':TableContract(),
        'silver_dq_summary':TableContract(),
        'nqas_silver':TableContract(('certification_id',),('department_assessed','validity_from','validity_to','dq_flags'),True,True),
        kayakalp_table:TableContract(('award_id',),('financial_year','source_page','s_no','district','state','dq_flags'),True,True),
        'nfhs_silver':TableContract(('state','district_std'),('district_key',),True,True),
        'nfhs_quarantine':TableContract(),
        'nfhs_quality_history':TableContract(nonempty=True),
        'nfhs_quality_current':TableContract(view=True),
        'registry_sites_silver':TableContract(('site_id',),('source','source_record_id','listing_category','dq_flags'),True,True),
        'registry_services_silver':TableContract(('service_row_id',),('site_id','source','service','evidence_type','evidence_detail','service_specific','dq_flags'),True,True),
        'facility_registry_links_silver':TableContract(('link_id',),('facility_id','site_id','match_score','needs_review','match_method')),
        'facility_registry_summary_silver':TableContract(('facility_id',),nonempty=True),
        'registry_match_review':TableContract(('link_id',),('facility_id','site_id','reviewer_decision')),
    }
    if len(contracts)!=20:
        raise ValueError('Kayakalp output name collides with another expected table')
    return contracts


PROVENANCE=('source_name','source_publisher','source_url','retrieved_on','source_license','produced_by','row_citation')
FOREIGN_KEYS=(
    ('silver_facility_claims','facility_id','facilities_silver','facility_id'),
    ('silver_possible_duplicates','facility_id_a','facilities_silver','facility_id'),
    ('silver_possible_duplicates','facility_id_b','facilities_silver','facility_id'),
    ('registry_services_silver','site_id','registry_sites_silver','site_id'),
    ('facility_registry_links_silver','facility_id','facilities_silver','facility_id'),
    ('facility_registry_links_silver','site_id','registry_sites_silver','site_id'),
    ('facility_registry_summary_silver','facility_id','facilities_silver','facility_id'),
    ('registry_match_review','link_id','facility_registry_links_silver','link_id'),
    ('pincode_centroids_silver','pincode','pincode_silver','pincode'),
)


def _count(spark, query):
    return int(spark.sql(query).first()['n'])


def validate_persisted_silver(spark, catalog, schema, *, kayakalp_table='kayakalp_silver_validation',
                              contracts=None):
    """Fresh-session persisted-table inventory, readback and aggregate checks.

    Entire expected schema (types/nullability) is recorded, not just a temp view.
    Historical row counts are not used as universal hardcoded expectations.
    Missing/inaccessible tables fail. Empty review/quarantine tables are valid.
    """
    identifier(catalog);identifier(schema)
    contracts=silver_contracts(kayakalp_table) if contracts is None else contracts
    reports=[]
    for table,contract in contracts.items():
        fq=qualified(catalog,schema,table)
        report={'table':f'{catalog}.{schema}.{table}','status':'FAIL','errors':[]}
        try:
            meta=spark.catalog.getTable(f'{catalog}.{schema}.{table}')
            if meta.isTemporary:
                raise ValueError('temporary views do not establish persistence')
            table_type=meta.tableType.upper()
            report['table_type']=table_type
            if contract.view:
                if table_type!='VIEW':
                    report['errors'].append('expected persistent view')
            else:
                if table_type=='VIEW':
                    raise ValueError('expected a persisted Delta table, not a view')
                detail=spark.sql(f'DESCRIBE DETAIL {fq}').first().asDict()
                report['format']=str(detail.get('format','')).lower()
                report['delta_table_id']=detail.get('id')
                if report['format']!='delta':
                    report['errors'].append('expected Delta format')
            df=spark.table(fq)
            report['schema']=df.schema.jsonValue()
            report['row_count']=df.count()
            missing=sorted(set(contract.keys+contract.required+(PROVENANCE if contract.provenance else ())) - set(df.columns))
            report['missing_columns']=missing
            if missing:
                report['errors'].append('missing required columns: '+', '.join(missing))
            if contract.nonempty and not report['row_count']:
                report['errors'].append('unexpected empty primary dataset')
            if contract.keys and set(contract.keys)<=set(df.columns):
                report['distinct_keys']=df.select(*contract.keys).distinct().count()
                invalid=' OR '.join(f'`{key}` IS NULL OR TRIM(CAST(`{key}` AS STRING)) = \'\'' for key in contract.keys)
                report['invalid_key_rows']=_count(spark,f'SELECT COUNT(*) AS n FROM {fq} WHERE {invalid}')
                if report['distinct_keys']!=report['row_count'] or report['invalid_key_rows']:
                    report['errors'].append('duplicate, null or blank primary keys')
            mandatory = {
                'facilities_silver': ('name',),
                'registry_services_silver': ('site_id','source','service','evidence_type','evidence_detail'),
                'registry_sites_silver': ('source','source_record_id'),
                'facility_registry_links_silver': ('facility_id','site_id','match_method','needs_review'),
                'silver_facility_claims': ('claim_text',),
                kayakalp_table: ('financial_year','source_page','s_no'),
            }.get(table, ())
            if mandatory and set(mandatory)<=set(df.columns):
                invalid=' OR '.join(f'`{key}` IS NULL OR TRIM(CAST(`{key}` AS STRING)) = \'\'' for key in mandatory)
                report['invalid_required_rows']=_count(spark,f'SELECT COUNT(*) AS n FROM {fq} WHERE {invalid}')
                if report['invalid_required_rows']:report['errors'].append('null or blank required values')
            if contract.provenance and set(PROVENANCE)<=set(df.columns):
                invalid=' OR '.join(f'`{key}` IS NULL OR TRIM(CAST(`{key}` AS STRING)) = \'\'' for key in PROVENANCE)
                report['incomplete_provenance_rows']=_count(spark,f'SELECT COUNT(*) AS n FROM {fq} WHERE {invalid}')
                if report['incomplete_provenance_rows']:
                    report['errors'].append('incomplete source provenance')
            if {'latitude','longitude'}<=set(df.columns):
                bad='(latitude IS NULL) <> (longitude IS NULL) OR (latitude IS NOT NULL AND NOT (latitude BETWEEN 6 AND 37.5 AND longitude BETWEEN 68 AND 97.5))'
                report['invalid_coordinates']=_count(spark,f'SELECT COUNT(*) AS n FROM {fq} WHERE {bad}')
                if report['invalid_coordinates']:report['errors'].append('invalid coordinates')
            if {'geo_latitude','geo_longitude'}<=set(df.columns):
                bad='(geo_latitude IS NULL) <> (geo_longitude IS NULL) OR (geo_latitude IS NOT NULL AND NOT (geo_latitude BETWEEN 6 AND 37.5 AND geo_longitude BETWEEN 68 AND 97.5))'
                report['invalid_geo_coordinates']=_count(spark,f'SELECT COUNT(*) AS n FROM {fq} WHERE {bad}')
                if report['invalid_geo_coordinates']:report['errors'].append('invalid geographic points')
            if 'pincode' in df.columns:
                report['invalid_pins']=_count(spark,f"SELECT COUNT(*) AS n FROM {fq} WHERE pincode IS NOT NULL AND NOT CAST(pincode AS STRING) RLIKE '^[1-9][0-9]{{5}}$'")
                if report['invalid_pins']:report['errors'].append('invalid PINs')
            report['status']='FAIL' if report['errors'] else 'PASS'
        except Exception as exc:
            # No offending row samples or data are included in this report.
            report['errors'].append(f'{type(exc).__name__}: {str(exc)[:1200]}')
        reports.append(report)
    by_name={r['table'].split('.')[-1]:r for r in reports}
    relationships=[]
    for child,child_key,parent,parent_key in FOREIGN_KEYS:
        if child not in by_name or parent not in by_name:continue
        result={'child':child,'parent':parent,'status':'BLOCKED'}
        if by_name[child]['status']=='PASS' and by_name[parent]['status']=='PASS':
            try:
                cq,pq=qualified(catalog,schema,child),qualified(catalog,schema,parent)
                n=_count(spark,f'SELECT COUNT(*) AS n FROM {cq} c LEFT ANTI JOIN {pq} p ON c.`{child_key}` = p.`{parent_key}`')
                result.update(orphan_rows=n,status='FAIL' if n else 'PASS')
            except Exception as exc:result.update(status='FAIL',error=str(exc)[:1200])
        relationships.append(result)
    checks=[]
    if kayakalp_table in by_name and 'row_count' in by_name[kayakalp_table]:
        try:
            n=spark.table(qualified(catalog,schema,'kayakalp_bronze')).count()
            actual=by_name[kayakalp_table]['row_count']
            checks.append(dict(check='KAYAKALP_ROW_CONSERVATION',bronze_rows=n,silver_rows=actual,status='PASS' if n==actual else 'FAIL'))
        except Exception as exc:checks.append(dict(check='KAYAKALP_ROW_CONSERVATION',status='FAIL',error=str(exc)[:1200]))
    if all(x in by_name and 'row_count' in by_name[x] for x in ('facilities_silver','facility_registry_summary_silver')):
        equal=by_name['facilities_silver']['row_count']==by_name['facility_registry_summary_silver']['row_count']
        checks.append(dict(check='SUMMARY_FACILITY_COVERAGE',status='PASS' if equal else 'FAIL'))
    all_status=[r['status'] for r in reports+relationships+checks]
    return {'status':'PASS' if all_status and all(s=='PASS' for s in all_status) else 'FAIL',
        'catalog':catalog,'schema':schema,'expected_table_count':len(contracts),
        'tables':reports,'foreign_keys':relationships,'checks':checks,
        'limitations':['Aggregate readback does not prove source truth or freshness of the pipeline run.',
            'Recorded schemas are actual; required-column contracts do not freeze all upstream types.',
            'Quality and cleanliness require explicit canonical links before Evidence Confidence attribution.']}


def collect_bounded(spark, catalog, schema, table, max_rows):
    """Collect inside the Databricks driver, never to a local export or task output.

    Exceeding the explicit memory guard fails; it never silently takes top-k.
    """
    if type(max_rows) is not int or not 1<=max_rows<=1000000:
        raise ValueError('max_rows must be an integer from 1 to 1000000')
    rows=spark.table(qualified(catalog,schema,table)).limit(max_rows+1).collect()
    if len(rows)>max_rows:
        raise ValueError(f'{table} exceeds max_rows={max_rows}; no truncated batch was processed')
    return [r.asDict(recursive=True) for r in rows]


def validate_evidence_tables(spark, catalog, schema, *, as_of, vocabulary, request=None,
                             candidate_table=None, candidate_context=None,
                             kayakalp_table='kayakalp_silver_validation', quality_link_tables=None,
                             max_rows=100000):
    """Read actual tables into the existing portable engine, return aggregates only.

    Canonical quality links and complete geographic request candidates must be
    supplied by their owners. No IDs, service assertions or distances are inferred.
    Without candidates this is evidence-only PARTIAL, never end-to-end PASS.
    """
    from collections import Counter
    from .silver import adapt_registry_tables, adapt_quality_tables
    from .integration import build_facility_service_rows, join_geographic_candidates
    from .recommendation import build_recommendation_response, normalize_request
    from .validation import validate_integration

    required=('facilities_silver','registry_sites_silver','registry_services_silver','facility_registry_links_silver')
    tables={}
    errors=[]
    for table in required:
        try:tables[table]=collect_bounded(spark,catalog,schema,table,max_rows)
        except Exception as exc:errors.append({'table':table,'error':str(exc)[:1000]})
    if errors:return {'status':'BLOCKED','errors':errors,'real_end_to_end':'NOT RUN'}
    if not tables['facilities_silver']:
        return {'status':'BLOCKED','errors':['empty canonical facility table'],'real_end_to_end':'NOT RUN'}
    try:
        reviews=collect_bounded(spark,catalog,schema,'registry_match_review',max_rows)
    except Exception as exc:
        return {'status':'BLOCKED','errors':[{'table':'registry_match_review','error':str(exc)[:1000]}],
                'real_end_to_end':'NOT RUN'}
    adapted=adapt_registry_tables(*(tables[t] for t in required),canonical_services=vocabulary,reviews=reviews)
    report={k:v for k,v in adapted.items() if k!='evidence'}
    if adapted['status']=='FAIL':
        report.update(status='FAIL',real_end_to_end='NOT RUN')
        return report
    records=list(adapted['evidence'])
    quality={}
    for source,table,key in (('nqas','nqas_silver','certification_id'),('kayakalp',kayakalp_table,'award_id')):
        try:
            rows=collect_bounded(spark,catalog,schema,table,max_rows)
            link_table=(quality_link_tables or {}).get(source)
            links=collect_bounded(spark,catalog,schema,link_table,max_rows) if link_table else []
            records.extend(adapt_quality_tables(rows,links,source=source,
                canonical_facility_ids=[r['facility_id'] for r in tables['facilities_silver']]))
            quality[source]={'source_rows':len(rows),'explicit_links':len(links),
                'unlinked_records':len({r[key] for r in rows}-{r['source_record_id'] for r in links})}
        except Exception as exc:
            quality[source]={'status':'BLOCKED','error':str(exc)[:1000]}
    report['source_counts']={name:dict(sorted(Counter(str(r.get('source') or 'unknown') for r in tables[name]).items()))
        for name in ('registry_sites_silver','registry_services_silver','facility_registry_links_silver')}
    report['canonical_service_record_counts']=dict(sorted(Counter(r['service'] for r in tables['registry_services_silver']).items()))
    report['quality_alignment']=quality
    rows=build_facility_service_rows(records,as_of=as_of)
    report['observed_pair_tiers']=dict(sorted(Counter(r['effective_tier'] for r in rows).items()))
    report['observed_facility_service_pairs']=len(rows)
    report['limitations']=['Observed-pair tiers exclude facilities with no tagged evidence until a requested candidate batch is supplied.',
        'Facility self-report claims need explicit reviewed canonical service/polarity mappings.',
        'Quality/cleanliness without explicit canonical links remain unattributed.',
        'No row-level records, citations or recommendation payloads are returned outside the Databricks driver.']
    if not candidate_table:
        report.update(status='PARTIAL',real_end_to_end='NOT RUN: no complete geographic candidate table supplied')
        return report
    if request is None or candidate_context is None:
        raise ValueError('candidate table requires request and explicit retrieval context')
    normalized=normalize_request({**request,'as_of':as_of.isoformat()})
    if normalized['service'] not in vocabulary:
        raise ValueError('requested service is outside the actual notebook vocabulary')
    expected_context={'pin':normalized['pin'],'radius_km':normalized['radius_km'],
        'service_prefiltered':False,'candidate_limit_applied':False,'retrieval_complete':True}
    if any(candidate_context.get(k)!=v for k,v in expected_context.items()):
        raise ValueError('candidate context must attest matching PIN/radius, complete retrieval, no substring prefilter and no top-k')
    geo=collect_bounded(spark,catalog,schema,candidate_table,max_rows)
    if not geo:
        report.update(status='BLOCKED',real_end_to_end='NOT RUN: empty candidate batch')
        return report
    rows=build_facility_service_rows(records,as_of=as_of,
        facility_services=[(g['facility_id'],normalized['service']) for g in geo])
    joined=join_geographic_candidates(geo,rows,service=normalized['service'],as_of=as_of)
    response=build_recommendation_response(normalized,records,geo)
    checked=validate_integration(canonical_facility_ids=[r['facility_id'] for r in tables['facilities_silver']],
        canonical_services=vocabulary,evidence_records=records,evidence_rows=rows,
        geographic_candidates=geo,joined_rows=joined,as_of=as_of,response=response)
    # Reduce record identifiers/messages from the portable report to counts/codes.
    report['validation']={k:v for k,v in checked.items() if k not in ('errors','warnings')}
    report['validation']['error_codes']=dict(Counter(r['code'] for r in checked['errors']))
    report['validation']['warning_codes']=dict(Counter(r['code'] for r in checked['warnings']))
    report['request']=normalized
    report['urgent_confirmed_recommendations']=len(response['recommendations']) if normalized['mode']=='urgent' else None
    report['candidate_count']=len(geo)
    report['response_count']=len(response['recommendations'])+len(response['alternatives'])
    ordered=sorted(geo,key=lambda g:(float('inf') if g['distance_km'] is None else g['distance_km'],g['facility_id']))
    beyond={g['facility_id'] for g in ordered[25:]}
    report['t1_beyond_nearest_25']=sum(r['facility_id'] in beyond and r['effective_tier']=='T1' for r in rows)
    report['pending_stronger_rows']=sum(r['pending_stronger_tier'] is not None for r in rows)
    report['t3_with_pending_t1']=sum(r['effective_tier']=='T3' and r['pending_stronger_tier']=='T1' for r in rows)
    report['rejected_only_rows']=sum(bool(r['decisions']) and all(d['match_status']=='rejected' for d in r['decisions']) for r in rows)
    report['credible_contradiction_decisions']=sum(d['credible_contradiction'] for r in rows for d in r['decisions'])
    report['supporting_rows_without_citations']=sum(r['supporting_record_count']>0 and not r['citations'] for r in rows)
    report['geo_confidence_counts']=dict(Counter(str(g.get('geo_confidence')) for g in geo))
    report['real_end_to_end']='FAIL' if checked['errors'] else 'PASS'
    report['status']='FAIL' if checked['errors'] else 'PARTIAL'
    return report
