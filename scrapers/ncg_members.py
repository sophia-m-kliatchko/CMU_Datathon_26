"""
Scrape the National Cancer Grid (NCG) member list for India.

NCG is a network of cancer centres, research institutions, patient groups and professional
societies, set up by the Government of India's Department of Atomic Energy and run from
Tata Memorial Centre. Its "Cancer Centres / Units" members are hospitals that treat cancer
and have joined the network's shared standards (NCG treatment guidelines, tumour boards,
quality programmes). Membership is evidence that a hospital runs a cancer service.

Source page: https://www.ncgindia.org/hospitals-and-institutions/members
The page loads its table from an HTML fragment endpoint, which this script calls directly:
  /hospitalsandinstitutions/_index?type_id=&country_id=&state_id=
robots.txt allows all paths (checked 2026-11-21). 5 requests in total, 1 s apart.

Outputs (default: datasets/external/ncg_bronze/):
  raw/ncg_<type>_<date>.html        the fragments as fetched (git-ignored)
  ncg_members_bronze.csv            one row per Indian member institution

Usage:
  python scrapers/ncg_members.py              # fetch and build
  python scrapers/ncg_members.py --offline    # rebuild from raw/
Needs: requests, beautifulsoup4
"""

import argparse
import csv
import datetime as dt
import hashlib
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.ncgindia.org"
PAGE_URL = BASE + "/hospitals-and-institutions/members"
ENDPOINT = BASE + "/hospitalsandinstitutions/_index"
INDIA_ID = "11C3A0AA-1A39-4F27-9B0D-1072DE3567E5"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; datathon-research-scraper/1.0)"}
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "ncg_bronze"

# Member types (radio buttons on the page) -> our label, related services
MEMBER_TYPES = {
    "cancer_centre": ("D83F0EAA-2B81-4E98-92B7-67AE3DA693FD", "Cancer Centres / Units", "cancer_care"),
    "research_institution": ("C5B8761F-35DE-47B1-9C44-B8552F3F6039", "Research Institutions", ""),
    "ngo_charity": ("9C6E09D4-F8C2-41EB-8B79-6AFBEFB46456", "NGOs / Charities", ""),
    "professional_society": ("D7BC404E-F674-4C4B-B040-D7372721CD83", "Professional Societies", ""),
}

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]


def _key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower().replace("&", " and "))


STATE_LOOKUP = {_key(s): s for s in STATES}
STATE_LOOKUP.update({"chattisgarh": "Chhattisgarh", "orissa": "Odisha", "pondicherry": "Puducherry",
                     "andamanandnicobarislands": "Andaman and Nicobar Islands"})


def ws(s):
    return re.sub(r"\s+", " ", (s or "").replace("\x00", "")).strip()


def name_norm(s):
    return ws(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower().replace("&", " and ")))


def pin_from(address):
    """Last 6-digit Indian PIN in the address; tolerates '400 012' and 'lndia'-style typos."""
    cands = re.findall(r"(?<!\d)([1-8]\d{2})\s?(\d{3})(?!\d)", address or "")
    return (cands[-1][0] + cands[-1][1]) if cands else None


def parse_fragment(html):
    """Yield (state_group, name, address, website) from one fragment."""
    soup = BeautifulSoup(html, "html.parser")
    group = None
    for tr in soup.select("table tr"):
        th = tr.find("th")
        if th:
            group = ws(th.get_text(" "))
            continue
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        link = tr.find("a", href=True)
        yield group, ws(tds[0].get_text(" ")), ws(tds[1].get_text(" ")), (link["href"].strip() if link else None)


def fetch(raw, date):
    with requests.Session() as s:
        jobs = [("all", "")] + [(k, v[0]) for k, v in MEMBER_TYPES.items()]
        for i, (label, type_id) in enumerate(jobs):
            if i:
                time.sleep(1)
            r = s.get(ENDPOINT, params={"type_id": type_id, "country_id": INDIA_ID, "state_id": ""},
                      headers=HEADERS, timeout=60)
            r.raise_for_status()
            if "<table" not in r.text:
                sys.exit(f"No table in response for {label}: the endpoint has changed.")
            (raw / f"ncg_{label}_{date}.html").write_text(r.text, encoding="utf-8")
            print(f"Fetched {label}: {r.text.count('<tr') } rows incl. headers")


def build(raw):
    files = sorted(raw.glob("ncg_all_*.html"))
    if not files:
        sys.exit(f"No raw files in {raw}; run without --offline first.")
    date = re.search(r"\d{4}-\d{2}-\d{2}", files[-1].name).group(0)

    type_of = {}
    for label in MEMBER_TYPES:
        f = raw / f"ncg_{label}_{date}.html"
        for group, name, address, _ in parse_fragment(f.read_text(encoding="utf-8")):
            type_of.setdefault((group, name, address), label)

    rows, ids = [], Counter()
    for group, name, address, website in parse_fragment((raw / f"ncg_all_{date}.html").read_text(encoding="utf-8")):
        label = type_of.get((group, name, address), "unknown")
        _, type_name, services = MEMBER_TYPES.get(label, (None, "Unknown", ""))
        state = STATE_LOOKUP.get(_key(group))
        base = "ncg_" + hashlib.sha1(f"{group}|{name}|{address}".lower().encode()).hexdigest()[:10]
        ids[base] += 1
        rows.append({
            "ncg_member_id": base if ids[base] == 1 else f"{base}_{ids[base]}",
            "member_name": name,
            "name_norm": name_norm(name),
            "member_type": label,
            "member_type_label": type_name,
            "address": address,
            "pincode_clean": pin_from(address),
            "state_group": group,
            "state_clean": state,
            "is_national_member": int(_key(group) == "national"),
            "website": website,
            "related_services": services,
            "source_url": PAGE_URL,
            "snapshot_date": date,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    raw = args.out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    if not args.offline:
        fetch(raw, dt.date.today().isoformat())
    rows = build(raw)

    path = args.out / "ncg_members_bronze.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    types = Counter(r["member_type"] for r in rows)
    print(f"{len(rows)} Indian members {dict(types)}; "
          f"{sum(1 for r in rows if r['pincode_clean'])} with a PIN; "
          f"{len({r['state_clean'] for r in rows if r['state_clean']})} states")
    bad = sorted({r["state_group"] for r in rows if not r["state_clean"] and not r["is_national_member"]})
    if bad:
        print(f"WARNING: unrecognised state groups: {bad}")
    if types.get("unknown"):
        print(f"WARNING: {types['unknown']} members not found in any type list")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
