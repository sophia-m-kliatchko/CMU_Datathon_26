"""Offline Silver input profiling and table-to-Evidence joins.

Only reads caller-provided local exports or mappings. Never connects to a catalog,
executes notebook code, matches names, creates facility IDs or infers services.
"""
import ast
from collections import Counter, defaultdict
from collections.abc import Mapping
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from .adapters import (from_kayakalp, from_nqas, from_registry_service,
                       from_registry_site, registry_match, _row)
from .models import FacilityMatch, MatchStatus

PRIMARY_KEYS = {'facilities_silver': 'facility_id', 'registry_sites_silver': 'site_id',
    'registry_services_silver': 'service_row_id', 'facility_registry_links_silver': 'link_id',
    'nqas_silver': 'certification_id', 'kayakalp_silver': 'award_id', 'facility_geo_ready': 'facility_id',
    'geographic_candidates': 'facility_id'}
CORE_TABLES = ('facilities_silver', 'registry_sites_silver', 'registry_services_silver',
               'facility_registry_links_silver', 'geographic_candidates')
PROVENANCE_FIELDS = ('source_name', 'source_publisher', 'source_url', 'retrieved_on',
                     'source_license', 'produced_by', 'row_citation')


def read_local_export(path):
    """Read a local JSON array/JSONL/CSV/Parquet without remote filesystem APIs.

    CSV arrays must be JSON arrays, not Spark's ambiguous display strings. JSONL
    or Parquet is preferred for typed nulls, booleans and arrays.
    """
    if '://' in str(path):
        raise ValueError('only local exports are supported')
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.json':
        records = json.loads(path.read_text())
    elif suffix in ('.jsonl', '.ndjson'):
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    elif suffix == '.csv':
        with path.open(newline='') as handle:
            records = list(csv.DictReader(handle))
        for row in records:
            for key, value in row.items():
                if value == '':
                    row[key] = None
                elif key == 'dq_flags':
                    row[key] = json.loads(value)
    elif suffix == '.parquet':
        import pyarrow.parquet as pq
        records = pq.read_table(path).to_pylist()
    else:
        raise ValueError('use .json, .jsonl, .ndjson, .csv or .parquet exports')
    if not isinstance(records, list) or any(not isinstance(r, Mapping) for r in records):
        raise ValueError('export must contain row objects')
    return [dict(r) for r in records]


def notebook_service_vocabulary(path):
    """Read the actual literal SERVICES mapping without executing the notebook."""
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SERVICES' for t in node.targets):
            return dict(ast.literal_eval(node.value))
    raise ValueError('literal SERVICES mapping not found')


def _public_url(value):
    try:
        parsed = urlparse(str(value or ''))
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except ValueError:
        return False


def profile_table(rows, primary_key):
    rows = [_row(r) for r in rows]
    keys = Counter(str(r[primary_key]) for r in rows if r.get(primary_key) not in (None, ''))
    def missing(field):
        return sum(r.get(field) is None or r.get(field) == '' for r in rows)
    pair_keys = Counter((r['facility_id'], r['service']) for r in rows if r.get('facility_id') and r.get('service'))
    return {'rows': len(rows),
        'canonical_facility_id_rows': sum(bool(r.get('facility_id')) for r in rows),
        'duplicate_facility_service_rows': sum(n-1 for n in pair_keys.values()) if pair_keys else None,
        'financial_year_counts': dict(sorted(Counter(r['financial_year'] for r in rows if r.get('financial_year')).items())),
        'missing_pdf_pages': missing('source_page') if any('source_page' in r for r in rows) else None,
        'missing_source_serials': missing('s_no') if any('s_no' in r for r in rows) else None, 'columns': sorted({k for r in rows for k in r}),
        'primary_key': primary_key, 'distinct_primary_keys': len(keys),
        'missing_primary_keys': missing(primary_key),
        'invalid_primary_key_types': sum(r.get(primary_key) is not None and not isinstance(r[primary_key], str) for r in rows),
        'duplicate_primary_key_rows': sum(n-1 for n in keys.values()),
        'duplicate_key_examples': sorted(k for k, n in keys.items() if n > 1)[:3],
        'missing_provenance': {field: missing(field) for field in PROVENANCE_FIELDS},
        'invalid_source_urls': sum(not _public_url(r.get('source_url')) for r in rows),
        'source_counts': dict(sorted(Counter(str(r.get('source') or 'not_tagged') for r in rows).items())),
        'service_counts': dict(sorted(Counter(str(r['service']) for r in rows if r.get('service')).items())),
        'dq_flags': dict(sorted(Counter(flag for r in rows for flag in
            (r.get('dq_flags') if isinstance(r.get('dq_flags'), (list, tuple)) else ())).items())),
        'untyped_flag_rows': sum(r.get('dq_flags') is not None and not isinstance(r['dq_flags'], (list, tuple)) for r in rows),
        'geographic_alias_conflicts': sum(any(r.get(a) is not None and r.get(b) is not None and r[a] != r[b]
            for a, b in (('state', 'state_clean'), ('district', 'district_clean'))) for r in rows),
        'examples': [{key: r.get(key) for key in (primary_key, 'facility_name', 'name', 'service', 'source_page', 's_no')
                      if key in r} for r in rows[:3]]}


def adapt_registry_tables(facilities, sites, services, links, *, canonical_services):
    """Join actual 05/06 tables, including pending/rejected links, without filtering.

    Errors are returned with counts/examples; callers must not publish partial
    results when errors exist. Unlinked sites remain unattached, never matched by name.
    """
    issues = defaultdict(list)
    def add(code, table, example, severity='ERROR'):
        issues[(code, table, severity)].append(str(example))
    def index(rows, key, table):
        result = {}
        for raw in rows:
            row = _row(raw)
            value = row.get(key)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                add('MISSING_OR_INVALID_KEY', table, value)
            elif value in result:
                add('DUPLICATE_KEY', table, value)
            else:
                result[value] = row
        return result
    fac = index(facilities, 'facility_id', 'facilities_silver')
    site = index(sites, 'site_id', 'registry_sites_silver')
    service = index(services, 'service_row_id', 'registry_services_silver')
    link = index(links, 'link_id', 'facility_registry_links_silver')
    allowed = set(canonical_services)
    by_site = defaultdict(list)
    for row in service.values():
        if row.get('site_id') not in site:
            add('ORPHAN_SERVICE_SITE', 'registry_services_silver', row['service_row_id'])
        elif row.get('service') not in allowed:
            add('UNSUPPORTED_SERVICE', 'registry_services_silver', row['service_row_id'])
        else:
            by_site[row['site_id']].append(row)
    evidence, statuses, linked_sites, linked_facilities, seen_pairs = [], Counter(), set(), set(), set()
    for row in link.values():
        fid, sid = row.get('facility_id'), row.get('site_id')
        if fid not in fac or sid not in site:
            add('ORPHAN_LINK', 'facility_registry_links_silver', row['link_id'])
            continue
        if row.get('source') is not None and row['source'] != site[sid].get('source'):
            add('LINK_SOURCE_CONFLICT', 'facility_registry_links_silver', row['link_id'])
            continue
        if (fid, sid) in seen_pairs:
            add('DUPLICATE_FACILITY_SITE_LINK', 'facility_registry_links_silver', row['link_id'])
            continue
        seen_pairs.add((fid,sid))
        try:
            match = registry_match(row, reviewer_decision=row.get('reviewer_decision'))
            statuses[match.status.value] += 1
            linked_sites.add(sid);linked_facilities.add(fid)
            evidence.append(from_registry_site(site[sid], match))
            for source in by_site[sid]:
                evidence.append(from_registry_service(source, match, site=site[sid]))
        except (ValueError, TypeError) as exc:
            add('ADAPTER_ERROR', 'facility_registry_links_silver', f"{row['link_id']}: {exc}")
    unlinked = sorted(set(site)-linked_sites)
    if unlinked:
        for sid in unlinked:
            add('UNLINKED_SITE', 'registry_sites_silver', sid, 'WARNING')
    findings=[dict(code=code,table=table,severity=severity,count=len(examples),examples=examples[:3])
              for (code,table,severity),examples in sorted(issues.items())]
    return {'status': 'FAIL' if any(f['severity']=='ERROR' for f in findings) else 'PASS',
        'evidence': tuple(evidence), 'findings': findings,
        'coverage': {'canonical_facilities': len(fac), 'registry_sites': len(site),
            'registry_service_records': len(service), 'registry_links': len(link),
            'linked_sites': len(linked_sites), 'linked_facilities': len(linked_facilities),
            'facilities_without_registry_links': len(fac)-len(linked_facilities),
            'unlinked_service_records': sum(r.get('site_id') not in linked_sites for r in service.values()),
            'identity_statuses': dict(sorted(statuses.items()))}}


def adapt_quality_tables(rows, links, *, source, canonical_facility_ids):
    """Explicit supplemental link contract; no such shared link output exists yet.

    Each link supplies facility_id, source_record_id, status (accepted/pending/
    rejected/unknown), method and optional flags. This is Alice's input adapter
    contract, not a claim that main produces these links.
    """
    if source not in ('nqas','kayakalp'):
        raise ValueError('source must be nqas or kayakalp')
    key = 'award_id' if source=='kayakalp' else 'certification_id'
    index = {}
    for raw in rows:
        row = _row(raw)
        if not row.get(key) or row[key] in index:
            raise ValueError(f'missing/duplicate {key}')
        index[row[key]]=row
    ids=set(canonical_facility_ids)
    result,seen=[],set()
    for raw in links:
        link=_row(raw)
        fid,record=link['facility_id'],link['source_record_id']
        if fid not in ids or record not in index:
            raise ValueError('orphan quality/cleanliness link')
        if (fid,record) in seen:
            raise ValueError('duplicate quality/cleanliness link')
        seen.add((fid,record))
        match=FacilityMatch(fid,MatchStatus(link['status']),method=link['method'],
                            reference_id=record,flags=link.get('flags',()))
        result.append((from_kayakalp if source=='kayakalp' else from_nqas)(index[record],match))
    return tuple(result)


def local_inventory(directory, *, additional_exports=None):
    """Profile actual local exports. Never substitutes raw CSVs for Silver tables."""
    directory=Path(directory)
    exports={}
    for name in PRIMARY_KEYS:
        found=[directory/(name+suffix) for suffix in ('.jsonl','.json','.parquet','.csv') if (directory/(name+suffix)).is_file()]
        if len(found)>1:
            raise ValueError(f'ambiguous exports for {name}; supply one format')
        if found:
            exports[name]=found[0]
    for name,path in (additional_exports or {}).items():
        if name not in PRIMARY_KEYS or name in exports:
            raise ValueError('unknown or duplicate additional export')
        exports[name]=Path(path)
    result={}
    for name,path in sorted(exports.items()):
        result[name]={'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'profile':profile_table(read_local_export(path),PRIMARY_KEYS[name])}
    missing=[name for name in CORE_TABLES if name not in result]
    return {'readiness':'BLOCKED' if missing else 'NOT_YET_VALIDATED',
        'exports':result,'missing_core_exports':missing,
        'limitations':['Inventory and source profiling do not establish facility matching or end-to-end readiness.',
                       'No Databricks access, notebook execution or synthetic substitution.']}
