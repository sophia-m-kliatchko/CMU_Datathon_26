"""Reproduce Sophia's extraction without changing source files; save audit lineage."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

from kayakalp_pdf_to_csv import parse, STATES, FIELDS
import pdfplumber


def metrics(rows):
    serials = [int(r['s_no']) for r in rows if str(r['s_no']).isascii() and str(r['s_no']).isdigit()]
    keys = [(r['financial_year'], r['s_no']) for r in rows]
    awards = [(r['financial_year'], r['award_category'], r['facility_name'].casefold(),
               r['district'].casefold(), r['state']) for r in rows]
    return {
        'rows': len(rows), 'invalid_serial_rows': len(rows)-len(serials), 'missing_values': {k: sum(not str(r[k]).strip() for r in rows) for k in FIELDS},
        'duplicate_identity_rows': len(keys) - len(set(keys)),
        'possible_duplicate_award_rows': sum(n for n in collections.Counter(awards).values() if n > 1),
        'missing_serials': sorted(set(range(1, max(serials, default=0)+1))-set(serials)),
        'serial_min': min(serials, default=None), 'serial_max': max(serials, default=None),
        'repaired_rows': sum(str(r['district_repaired']).lower() == 'true' for r in rows),
        'mixed_locality_rows': sum(',' in r['district'] for r in rows),
        'health_district_rows': sum('health district' in r['district'].lower() for r in rows),
        'unknown_states': sum(r['state'] not in STATES for r in rows),
        **{k: dict(collections.Counter(str(r[k]) for r in rows)) for k in
           ['financial_year', 'award_category', 'award_rank', 'facility_type', 'state']},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pdf', default='data/KAYAKALP WINNER FACILITIES 21-22.pdf')
    ap.add_argument('--csv', default='data/external/kayakalp_2021_22.csv')
    ap.add_argument('--out', default='shared/runs/kayakalp-validation')
    a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with open(a.csv, encoding='utf-8', newline='') as f:
        committed = list(csv.DictReader(f))
    extracted, warnings = parse(a.pdf, '2021-22')
    normalized = [{k: str(r[k]) for k in FIELDS} for r in extracted]
    # Extra/missing trailing rows are reported separately by count_difference.
    differences = [{'index': i, 'committed': c, 'extracted': e}
                   for i, (c, e) in enumerate(zip(committed, normalized)) if c != e]
    raw = []
    with pdfplumber.open(a.pdf) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            for table_no, table in enumerate(page.extract_tables(), 1):
                for row_no, cells in enumerate(table, 1):
                    raw.append(dict(page=page_no, table=table_no, row=row_no, cells=cells))
    (out/'raw_pdf_rows.json').write_text(json.dumps(raw, indent=2))
    with (out/'reproduced.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(extracted)
    unclassified = [r for r in raw if any(r['cells']) and
                    not str(r['cells'][0] or '').strip().isdigit() and
                    not str(r['cells'][0] or '').startswith(('S.No.', 'KAYAKALP WINNER FACILITIES'))]
    report = dict(raw_table_rows=len(raw), unclassified_rows=unclassified, pdf_sha256=hashlib.sha256(Path(a.pdf).read_bytes()).hexdigest(),
                  csv_sha256=hashlib.sha256(Path(a.csv).read_bytes()).hexdigest(),
                  before=metrics(committed), after=metrics(normalized), differences=differences,
                  count_difference=len(extracted)-len(committed), warnings=warnings,
                  continuation_warnings=[w for w in warnings if 'continuation' in w])
    (out/'validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if differences or len(extracted) != len(committed) or unclassified:
        raise SystemExit('Extraction differs; investigate without replacing source records.')


if __name__ == '__main__':
    main()
