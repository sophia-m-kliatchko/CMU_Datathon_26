"""Real local geographic end-to-end checks using downloaded Silver and source logic.

Creates only new local artifacts in an explicit output directory. No remote jobs,
Silver regeneration, source-file modification, commits, pushes or synthetic input.
"""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from .geographic_candidates import GeographicProducer, default_notebook, to_join_candidate
from .silver import read_local_export, notebook_service_vocabulary, adapt_registry_tables
from .integration import build_facility_service_rows, join_geographic_candidates
from .recommendation import build_recommendation_response
from .validation import validate_integration


def _hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _parquet(rows,path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if path.exists():raise FileExistsError(f'refusing to overwrite {path}')
    table=pa.Table.from_pylist(rows)
    pq.write_table(table,path,compression='snappy')
    reread=pq.read_table(path).to_pylist()
    if reread!=rows:raise ValueError('Parquet readback differs from derived rows')
    return {'path':str(path.resolve()),'rows':len(rows),'bytes':path.stat().st_size,
            'sha256':_hash(path),'schema':str(table.schema),'independent_readback_equal':True}


def run_geographic_validation(directory,output_dir,*,as_of,repository_root,pins=('110001','400001','600001'),
                              services=('emergency_c_section','dialysis'),radius_km=50.,geography_notebook=None):
    root=Path(repository_root).resolve();source=Path(directory).resolve();output=Path(output_dir).resolve()
    if not source.is_dir():raise ValueError('downloaded Silver directory missing')
    if output==source or output.is_relative_to(source):raise ValueError('write derived artifacts outside the downloaded input directory')
    output.mkdir(parents=True,exist_ok=False)
    hashes={str(p):_hash(p) for p in sorted(source.rglob('*')) if p.is_file()}
    def load(name):
        path=source/(name+'.csv')
        if not path.is_file():raise ValueError(f'missing geographic/integration input: {path}')
        return read_local_export(path,csv_escapechar='\\')
    fac=load('facilities_silver');cent=load('pincode_centroids_silver')
    notebook=Path(geography_notebook).resolve() if geography_notebook else default_notebook(root)
    producer=GeographicProducer(notebook,root/'notebooks/common/validation.py')
    ready,centroids,summary=producer.build_ready(fac,cent)
    if {r['facility_id'] for r in ready}!={r['facility_id'] for r in fac} or len(ready)!=len(fac):
        raise ValueError('geographic-ready construction lost/multiplied canonical identities')
    report={'as_of':as_of.isoformat(),'input_directory':str(source),'geography':summary,
        'geo_ready_artifact':_parquet(ready,output/'facility_geo_ready.parquet'),'requests':[],
        'limitations':['Local evaluation of actual producer scalar expressions, not Spark/Databricks execution.',
            'The producer re-verifies numeric/PIN proximity, not ground-truth facility locations.',
            'Own-coordinate uncertainty and PIN fallback margins are the existing producer assumptions.',
            'NQAS/Kayakalp canonical links and reviewed self-report service mappings remain unavailable.',
            'Certification evidence is not a clinical safety, staffing or current emergency-capability guarantee.']}
    sites=load('registry_sites_silver');raw_services=load('registry_services_silver');links=load('facility_registry_links_silver')
    reviews=load('registry_match_review') if (source/'registry_match_review.csv').is_file() else []
    vocabulary=notebook_service_vocabulary(root/'notebooks/05_registries_bronze_to_silver.py')
    if not set(services)<=set(vocabulary):raise ValueError('requested service outside existing canonical vocabulary')
    adapted=adapt_registry_tables(fac,sites,raw_services,links,canonical_services=vocabulary,reviews=reviews)
    report['registry_adaptation']={k:v for k,v in adapted.items() if k!='evidence'}
    if adapted['status']!='PASS':raise ValueError('real source adaptation failed: '+json.dumps(report['registry_adaptation']))
    records=adapted['evidence'];facility_ids={r['facility_id'] for r in fac}
    for pin in pins:
        raw_candidates,context=producer.candidates(ready,centroids,pin=pin,radius_km=radius_km)
        # Validate the box prefilter against the producer's OWN radius rule evaluated
        # over every point (box filters skipped); never change the owner's selection.
        unboxed,_=producer.candidates(ready,centroids,pin=pin,radius_km=radius_km,apply_prefilter=False)
        without_box={r['facility_id'] for r in unboxed}
        candidates=[to_join_candidate(r) for r in raw_candidates]
        ids={r['facility_id'] for r in candidates}
        query={'context':context,'candidate_artifact':_parquet(candidates,output/f'candidates_{pin}.parquet'),
            'basis_counts':dict(Counter(r['location_basis'] for r in candidates)),
            'confidence_counts':dict(Counter(r['geo_confidence'] for r in candidates)),
            'all_points_radius_count':len(without_box),'bbox_omissions':len(without_box-ids),
            'outside_radius_extras':len(ids-without_box),'scenarios':[]}
        for service in services:
            rows=build_facility_service_rows(records,as_of=as_of,
                facility_services=[(r['facility_id'],service) for r in candidates])
            joined=join_geographic_candidates(candidates,rows,service=service,as_of=as_of)
            for mode in ('routine','urgent'):
                if mode=='urgent' and (pin!=pins[0] or service!=services[0]):continue
                request=dict(pin=pin,service=service,radius_km=radius_km,mode=mode,as_of=as_of.isoformat())
                response=build_recommendation_response(request,records,candidates)
                checked=validate_integration(canonical_facility_ids=facility_ids,canonical_services=vocabulary,
                    evidence_records=records,evidence_rows=rows,geographic_candidates=candidates,
                    joined_rows=joined,as_of=as_of,response=response)
                out_rows=response['recommendations']+response['alternatives']
                response_ids={r['facility_id'] for r in out_rows}
                if response_ids!=ids or len(out_rows)!=len(candidates):raise ValueError('candidate retention/fanout failure')
                by_id={r['facility_id']:r for r in candidates}
                if any(any(row.get(key)!=by_id[row['facility_id']].get(key) for key in
                    ('distance_km','location_basis','geo_confidence','location_uncertainty_km','distance_min_km')) for row in out_rows):
                    raise ValueError('geographic metadata changed during recommendation export')
                if json.loads(json.dumps(response,allow_nan=False))!=response:raise ValueError('JSON boundary mismatch')
                # Shuffle both sources to test order independence using actual data.
                if build_recommendation_response(request,reversed(records),reversed(candidates))!=response:
                    raise ValueError('ranking/serialization is not deterministic')
                path=output/f'recommendations_{pin}_{service}_{mode}.json'
                path.write_text(json.dumps(response,ensure_ascii=False,allow_nan=False))
                beyond={r['facility_id'] for r in candidates[25:]}
                scenario={'service':service,'mode':mode,'status':checked['status'],
                    'input_candidates':len(candidates),'joined_candidates':len(joined),'response_candidates':len(out_rows),
                    'tiers':checked['tier_distribution'],'errors':checked['errors'],
                    'warning_codes':dict(Counter(w['code'] for w in checked['warnings'])),
                    'pending_stronger_rows':sum(r['pending_stronger_tier'] is not None for r in rows),
                    't3_with_pending_t1':sum(r['effective_tier']=='T3' and r['pending_stronger_tier']=='T1' for r in rows),
                    't1_beyond_nearest_25':sum(r['effective_tier']=='T1' and r['facility_id'] in beyond for r in rows),
                    'credible_contradiction_decisions':sum(d['credible_contradiction'] for r in rows for d in r['decisions']),
                    'confirmed_urgent_recommendations':len(response['recommendations']) if mode=='urgent' else None,
                    'provenance_json_ranking_replay':'PASS' if not checked['errors'] else 'FAIL',
                    'geographic_fields_preserved':True,'deterministic':True,
                    'response_path':str(path.resolve()),'response_sha256':_hash(path)}
                query['scenarios'].append(scenario)
        report['requests'].append(query)
    report['input_hashes_unchanged']=all(_hash(path)==digest for path,digest in hashes.items())
    report['shared_geography_source_unchanged']=_hash(producer.path)==producer.source_sha256 and _hash(producer.validation_path)==producer.validation_sha256
    fail=any(q['bbox_omissions'] or q['outside_radius_extras'] or any(s['errors'] for s in q['scenarios']) for q in report['requests'])
    report['geographic_end_to_end']='FAIL' if fail else 'PASS'
    report['overall_readiness']='PARTIALLY READY'  # Quality links/source verification still missing.
    if not report['input_hashes_unchanged'] or not report['shared_geography_source_unchanged']:raise ValueError('input/shared source mutation detected')
    (output/'validation.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    p.add_argument('--output-dir',required=True);p.add_argument('--as-of',required=True,type=date.fromisoformat)
    p.add_argument('--repository-root',default=str(Path(__file__).resolve().parents[1]))
    p.add_argument('--geography-notebook',default=None,help='Read-only producer notebook path (default: repo copy)')
    p.add_argument('--pins',default='110001,400001,600001')
    a=p.parse_args();r=run_geographic_validation(a.directory,a.output_dir,as_of=a.as_of,repository_root=a.repository_root,
        pins=tuple(a.pins.split(',')),geography_notebook=a.geography_notebook)
    print(json.dumps({'geography':r['geography'],'geographic_end_to_end':r['geographic_end_to_end'],
        'requests':[{'pin':q['context']['pin'],'candidates':q['context']['candidate_count'],
                    'basis_counts':q['basis_counts'],'bbox_omissions':q['bbox_omissions'],
                    'outside_radius_extras':q['outside_radius_extras'],'radius_rule':q['context']['radius_rule'],'scenarios':q['scenarios']} for q in r['requests']]},indent=2))


if __name__=='__main__':main()
