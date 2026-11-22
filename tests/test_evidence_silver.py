"""Contract tests use explicit SYNTHETIC links. Real export tests profile only;
no synthetic identity is attached to a real source row.
"""
from dataclasses import replace
from datetime import date, datetime
import json
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from evidence_confidence.adapters import from_kayakalp, from_nqas, from_registry_service, registry_match
from evidence_confidence.integration import build_facility_service_rows
from evidence_confidence.real_silver_validation import run_local_validation
from evidence_confidence.silver import (adapt_quality_tables, adapt_registry_tables, local_inventory,
    notebook_service_vocabulary, profile_table, read_local_export)
from evidence_confidence.synthetic_smoke import synthetic_fixture, AS_OF, SERVICE
from test_evidence_tiers import certificate

ROOT=Path(__file__).resolve().parents[1]
REAL_KAYAKALP=ROOT.parent/'kayakalp-validation/shared/runs/kayakalp-validation/kayakalp_silver_local.json'


def registry_tables():
    # Raw field names follow main 05/06, but every value/link is synthetic.
    fixture=synthetic_fixture()
    entries=fixture['registry_entries']
    sites={};services={};links={}
    for row,link,decision in entries:
        sites[row['site_id']]=dict(site_id=row['site_id'],source=row['source'],name='SYNTHETIC registry site',
            listing_category='service_certification',source_url=row['source_url'],row_citation=row['row_citation'],dq_flags=[])
        services[row['service_row_id']]=row
        links[(link['facility_id'],link['site_id'])]={**link,'source':row['source'],
            'link_id':'SYNTHETIC-'+row['service_row_id'],'reviewer_decision':decision}
    return fixture,[dict(facility_id=g['facility_id'],name=g['name']) for g in fixture['geographic_candidates']],list(sites.values()),list(services.values()),list(links.values())


class SilverContractTests(unittest.TestCase):
    def test_bulk_registry_uses_all_link_statuses(self):
        _,fac,site,svc,links=registry_tables()
        r=adapt_registry_tables(fac,site,svc,links,canonical_services=[SERVICE])
        self.assertEqual(r['status'],'PASS')
        self.assertEqual(r['coverage']['identity_statuses'],{'accepted':7,'pending':2,'rejected':1})
        rows=build_facility_service_rows(r['evidence'],as_of=AS_OF)
        by_id={r['facility_id']:r for r in rows}
        self.assertEqual(by_id['synthetic-004']['effective_tier'],'U')
        self.assertEqual(by_id['synthetic-005']['effective_tier'],'R')
        self.assertEqual(by_id['synthetic-006']['pending_stronger_tier'],'T1')

    def test_bulk_orphans_report_count_and_example(self):
        _,fac,site,svc,links=registry_tables();links[0]['facility_id']='SYNTHETIC-orphan'
        r=adapt_registry_tables(fac,site,svc,links,canonical_services=[SERVICE])
        self.assertEqual(r['status'],'FAIL')
        finding=next(f for f in r['findings'] if f['code']=='ORPHAN_LINK')
        self.assertEqual(finding['count'],1);self.assertTrue(finding['examples'])

    def test_duplicate_link_key_fails(self):
        _,fac,site,svc,links=registry_tables()
        r=adapt_registry_tables(fac,site,svc,links+[links[0]],canonical_services=[SERVICE])
        self.assertTrue(any(f['code']=='DUPLICATE_KEY' for f in r['findings']))

    def test_different_link_ids_same_pair_fails(self):
        _,fac,site,svc,links=registry_tables();links.append({**links[0],'link_id':'SYNTHETIC-other'})
        r=adapt_registry_tables(fac,site,svc,links,canonical_services=[SERVICE])
        self.assertTrue(any(f['code']=='DUPLICATE_FACILITY_SITE_LINK' for f in r['findings']))

    def test_unknown_services_never_silently_mapped(self):
        _,fac,site,svc,links=registry_tables();svc[0]={**svc[0],'service':'unreviewed_service'}
        r=adapt_registry_tables(fac,site,svc,links,canonical_services=[SERVICE])
        self.assertEqual(r['status'],'FAIL')
        self.assertTrue(any(f['code']=='UNSUPPORTED_SERVICE' for f in r['findings']))

    def test_link_source_conflict_fails(self):
        _,fac,site,svc,links=registry_tables();links[0]={**links[0],'source':'wrong'}
        r=adapt_registry_tables(fac,site,svc,links,canonical_services=[SERVICE])
        self.assertTrue(any(f['code']=='LINK_SOURCE_CONFLICT' for f in r['findings']))

    def test_unlinked_service_coverage_is_reported(self):
        _,fac,site,svc,links=registry_tables()
        r=adapt_registry_tables(fac,site,svc,[],canonical_services=[SERVICE])
        self.assertEqual(r['evidence'],())
        self.assertEqual(r['coverage']['unlinked_service_records'],len(svc))
        self.assertEqual(r['coverage']['facilities_without_registry_links'],32)

    def test_metadata_retains_original_page_publisher_and_date(self):
        row,link,_=synthetic_fixture()['registry_entries'][0]
        row={**row,'source_publisher':'SYNTHETIC publisher','source_license':'SYNTHETIC licence',
             'source_page':3,'s_no':17,'retrieved_on':datetime(2026,11,21,12)}
        e=from_registry_service(row,registry_match(link))
        self.assertEqual(dict(e.source_provenance)['source_page'],3)
        output=build_facility_service_rows([e],as_of=AS_OF)[0]['evidence_records'][0]
        self.assertEqual(dict(output['source_provenance'])['source_publisher'],'SYNTHETIC publisher')
        json.dumps(output)

    def test_provenance_is_immutable_and_hashable(self):
        e=replace(certificate(),source_provenance=(('source_page',2),))
        self.assertIsInstance(hash(e),int)
        for value in ((('source_page',[]),),(('x',1),('x',2))):
            with self.assertRaises(ValueError):replace(e,source_provenance=value)

    def test_quality_source_ids_retained_without_service_claim(self):
        row=dict(award_id='SYNTHETIC-award',financial_year='2021-22',award_raw='Winner',
            source_page=1,s_no=2,source_url='https://example.invalid/award',row_citation='SYNTHETIC award citation.')
        link=dict(facility_id='SYNTHETIC-facility',source_record_id=row['award_id'],status='accepted',method='SYNTHETIC-reviewed')
        evidence=adapt_quality_tables([row],[link],source='kayakalp',canonical_facility_ids=['SYNTHETIC-facility'])
        self.assertEqual(evidence[0].source_record_id,'SYNTHETIC-award')
        self.assertEqual(dict(evidence[0].source_provenance)['s_no'],2)
        out=build_facility_service_rows(evidence,as_of=AS_OF,facility_services=[('SYNTHETIC-facility',SERVICE)])[0]
        self.assertEqual(out['effective_tier'],'U')
        self.assertEqual(len(out['cleanliness_evidence_ids']),1)
        nqas=dict(certification_id='SYNTHETIC-cert',department_assessed='All departments',
            covers_all_departments=True,validity_from='2025-01-01',validity_to='2028-01-01')
        e=adapt_quality_tables([nqas],[{**link,'source_record_id':'SYNTHETIC-cert'}],source='nqas',canonical_facility_ids=['SYNTHETIC-facility'])[0]
        self.assertEqual(e.source_record_id,'SYNTHETIC-cert');self.assertEqual(e.scope.value,'quality')

    def test_quality_does_not_invent_links(self):
        row={'award_id':'SYNTHETIC-award'}
        self.assertEqual(adapt_quality_tables([row],[],source='kayakalp',canonical_facility_ids=[]),())
        with self.assertRaisesRegex(ValueError,'orphan'):
            adapt_quality_tables([row],[dict(facility_id='missing',source_record_id='SYNTHETIC-award')],
                source='kayakalp',canonical_facility_ids=[])

    def test_real_vocabulary_read_without_executing_notebook(self):
        vocabulary=notebook_service_vocabulary(ROOT/'notebooks/05_registries_bronze_to_silver.py')
        self.assertEqual(len(vocabulary),61)
        self.assertIn(SERVICE,vocabulary)

    def test_reader_preserves_flags_and_rejects_untyped_arrays(self):
        with TemporaryDirectory() as temp:
            p=Path(temp)/'input.csv';p.write_text('award_id,dq_flags\na,"[""FLAG""]"\n')
            self.assertEqual(read_local_export(p)[0]['dq_flags'],['FLAG'])
            p.write_text('award_id,dq_flags\na,[FLAG]\n')
            with self.assertRaises(ValueError):read_local_export(p)
            p=Path(temp)/'bad.json';p.write_text('{}')
            with self.assertRaises(ValueError):read_local_export(p)
        with self.assertRaisesRegex(ValueError,'only local'):read_local_export('https://example.invalid/input.json')

    def test_inventory_empty_is_blocked_not_synthetic_pass(self):
        with TemporaryDirectory() as temp:
            r=run_local_validation(temp,as_of=AS_OF,notebook_path=ROOT/'notebooks/05_registries_bronze_to_silver.py')
        self.assertEqual(r['readiness'],'BLOCKED')
        self.assertEqual(len(r['inventory']['missing_core_exports']),5)

    def test_ambiguous_export_formats_fail(self):
        with TemporaryDirectory() as temp:
            for ext in ('json','jsonl'):(Path(temp)/('facilities_silver.'+ext)).write_text('[]' if ext=='json' else '')
            with self.assertRaisesRegex(ValueError,'ambiguous'):local_inventory(temp)

    def test_runner_complete_path_uses_contract_fixtures_not_real_data(self):
        fixture,fac,sites,services,links=registry_tables()
        with TemporaryDirectory() as temp:
            for name,rows in dict(facilities_silver=fac,registry_sites_silver=sites,registry_services_silver=services,
                facility_registry_links_silver=links,geographic_candidates=fixture['geographic_candidates']).items():
                (Path(temp)/(name+'.json')).write_text(json.dumps(rows))
            r=run_local_validation(temp,as_of=AS_OF,notebook_path=ROOT/'notebooks/05_registries_bronze_to_silver.py',request=fixture['request'])
        self.assertEqual(r['readiness'],'PARTIALLY READY')
        self.assertEqual(r['real_end_to_end']['candidate_count'],32)
        self.assertEqual(r['real_end_to_end']['response_count'],32)
        self.assertEqual(r['real_end_to_end']['validation']['errors'],[])

    def test_validator_batch_recompute_not_one_scan_per_pair(self):
        from evidence_confidence.validation import validate_integration
        fixture,fac,sites,services,links=registry_tables()
        r=adapt_registry_tables(fac,sites,services,links,canonical_services=[SERVICE])
        rows=build_facility_service_rows(r['evidence'],as_of=AS_OF)
        with patch('evidence_confidence.validation.build_facility_service_rows',wraps=build_facility_service_rows) as build:
            validate_integration(canonical_facility_ids=[f['facility_id'] for f in fac],canonical_services=[SERVICE],
                evidence_records=r['evidence'],evidence_rows=rows,geographic_candidates=[],joined_rows=[],as_of=AS_OF)
        self.assertEqual(build.call_count,1)


@unittest.skipUnless(REAL_KAYAKALP.is_file(),'Real Kayakalp export unavailable locally; no synthetic substitute')
class RealSilverSourceTests(unittest.TestCase):
    def test_actual_award_export_provenance_and_unique_keys(self):
        rows=read_local_export(REAL_KAYAKALP)
        profile=profile_table(rows,'award_id')
        self.assertEqual((profile['rows'],profile['distinct_primary_keys']),(1197,1197))
        self.assertEqual(profile['duplicate_primary_key_rows'],0)
        self.assertTrue(all(v==0 for v in profile['missing_provenance'].values()))
        self.assertEqual(profile['canonical_facility_id_rows'],0)
        self.assertEqual(profile['missing_pdf_pages'],0)
        self.assertEqual(profile['missing_source_serials'],0)
        with (ROOT/'data/external/kayakalp_2021_22.csv').open(newline='') as handle:
            source=list(csv.DictReader(handle))
        self.assertEqual({str(r['s_no']) for r in rows},{r['s_no'] for r in source})
        self.assertEqual(profile['dq_flags'],{'AWARD_ORDINAL_IN_RAW':11,'DISTRICT_FIELD_HAD_LOCALITY':112,
            'DISTRICT_HEALTH_JURISDICTION':11,'DISTRICT_REPAIRED_FROM_PDF':17,'DISTRICT_SPACING_VERIFIED':2,
            'FACILITY_TYPE_CONFLICT':47,'POSSIBLE_DUPLICATE_AWARD':20})

    def test_actual_awards_do_not_gain_a_service_mapping(self):
        rows=read_local_export(REAL_KAYAKALP)
        self.assertTrue(all('service' not in r and 'facility_id' not in r for r in rows))
        self.assertEqual(adapt_quality_tables(rows,[],source='kayakalp',canonical_facility_ids=[]),())
        self.assertEqual(profile_table(rows,'award_id')['financial_year_counts'],{'2021-22':1197})
