"""
Download the NHSRC list of NQAS certified facilities into one CSV.

Source page: https://qps.nhsrcindia.org/nqas-facility-list
The site shows 10 rows per page, in two lists:
  - Full Facility certification     -> /nqas-certification-full
  - Partial Facility certification  -> /nqas-certification-partial

WHY THIS ISN'T A SIMPLE PAGE LOOP
The site's sort order isn't stable across pages: walking ?page=0,1,2... returns some
facilities twice and silently skips others (found on 2026-11-21; about 12% of rows were
repeats). To get every row, the script splits each list into small queries using the
site's own filters (state, then district; both are case-insensitive "contains" matches)
until each query's unique rows equal the total the pager reports. Results are merged
and de-duplicated.

Uses only the Python standard library (no installs needed).

Usage:
    python scripts/scrape_nqas.py                     # -> data/external/nqas_certified_facilities.csv
    python scripts/scrape_nqas.py --out my.csv --delay 1.0
"""
import argparse
import csv
import html
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser

BASE = "https://qps.nhsrcindia.org"
LISTS = {"full": "/nqas-certification-full", "partial": "/nqas-certification-partial"}
COLUMNS = ["state", "district", "facility_name", "department_assessed", "validity_from", "validity_to"]
HEADER_MAP = {  # the site's <td headers="..."> value -> our column name
    "view-field-state1-table-column": "state",
    "view-field-district1-table-column": "district",
    "view-title-table-column": "facility_name",
    "view-field-department-assessed-table-column": "department_assessed",
    "view-field-validity-from-table-column": "validity_from",
    "view-field-validity-date1-table-column": "validity_to",
}
USER_AGENT = "Mozilla/5.0 (compatible; datathon-research-script)"
PAGE_SIZE = 10


class TableRows(HTMLParser):
    """Collect the <td> cells of each table row, keyed by their headers= attribute."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._key, self._buf = [], None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {}
        elif tag == "td" and self._row is not None:
            self._key = HEADER_MAP.get(dict(attrs).get("headers", ""))
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "td" and self._row is not None and self._key:
            self._row[self._key] = html.unescape(" ".join("".join(self._buf).split()))
            self._key = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(tuple(self._row.get(c, "") for c in COLUMNS))
            self._row = None

    def handle_data(self, data):
        if self._key:
            self._buf.append(data)


class Scraper:
    def __init__(self, delay):
        self.delay, self.requests = delay, 0

    def fetch(self, url, retries=4):
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read().decode("utf-8", errors="replace")
                self.requests += 1
                time.sleep(self.delay)  # be polite to a government server
                return body
            except Exception as e:
                wait = 2 ** (attempt + 1)
                print(f"  ! {e} - retrying in {wait}s", file=sys.stderr)
                time.sleep(wait)
        raise RuntimeError(f"Failed to fetch {url}")

    def query(self, path, state="", district=""):
        """Walk every page of one filtered query. Returns (unique rows, total reported, rows seen)."""
        seen, n_raw, page = set(), 0, 0
        while True:
            qs = urllib.parse.urlencode({"field_state1_value": state, "field_district1_value": district,
                                         "title": "", "page": page})
            p = TableRows()
            p.feed(self.fetch(f"{BASE}{path}?{qs}"))
            seen.update(p.rows)
            n_raw += len(p.rows)
            if len(p.rows) < PAGE_SIZE:  # last page reached
                return seen, n_raw
            page += 1


def scrape_list(s, kind, path):
    all_rows, n_total = s.query(path)
    print(f"[{kind}] unfiltered: {n_total} rows reported, {len(all_rows)} unique")
    if len(all_rows) == n_total:
        return all_rows, n_total

    # Split by state. The state names come from the rows found so far.
    for state in sorted({r[0] for r in all_rows if r[0]}):
        rows, n = s.query(path, state=state)
        all_rows |= rows
        if len(rows) == n:
            continue
        # Still overlapping inside this state: split by district
        for district in sorted({r[1] for r in rows if r[1]}):
            drows, dn = s.query(path, state=state, district=district)
            all_rows |= drows
            if len(drows) != dn:
                print(f"  [{kind}] {state} / {district}: {dn} reported, {len(drows)} unique "
                      f"(the site may list true duplicates)")
        print(f"[{kind}] {state}: running total {len(all_rows)} unique")
    return all_rows, n_total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join("data", "external", "nqas_certified_facilities.csv"))
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests (default 0.5)")
    args = ap.parse_args()

    s = Scraper(args.delay)
    today = date.today().isoformat()
    out = []
    for kind, path in LISTS.items():
        rows, n_total = scrape_list(s, kind, path)
        status = "COMPLETE" if len(rows) >= n_total else f"INCOMPLETE ({n_total - len(rows)} missing or true duplicates)"
        print(f"[{kind}] {len(rows)} unique rows vs {n_total} reported by the site: {status}")
        for r in sorted(rows):
            out.append(dict(zip(COLUMNS, r), certification_type=kind, source_url=f"{BASE}{path}", scraped_on=today))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS + ["certification_type", "source_url", "scraped_on"])
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {len(out)} rows to {args.out} ({s.requests} requests)")


if __name__ == "__main__":
    main()
