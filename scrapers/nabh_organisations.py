"""
Scrape NABH's public "Find an Accredited Healthcare Organisation" directory.

NABH (National Accreditation Board for Hospitals & Healthcare Providers, part of the Quality
Council of India) accredits or certifies healthcare organisations after an on-site
assessment against published standards. Programmes include full hospital accreditation,
small hospitals, entry-level certification, eye care, blood banks, medical imaging,
emergency departments, stroke centres, Ayush hospitals, and CGHS/ECHS empanelment.

Source page: https://nabh.co/find-a-healthcare-organisation/
The page loads results by POSTing its search form to WordPress admin-ajax
(action=get_hospitals); robots.txt explicitly allows /wp-admin/admin-ajax.php.
Results come 25 per page (~865 pages). Requests are 1.5 s apart, each page is cached in
raw/pages/, and a re-run only fetches pages that are missing.

Personal data: the listing shows a contact phone number per organisation. It isn't needed
and isn't saved. Only institutional fields are kept (name, address, website, coordinates,
accreditation number and status, certificate link).

Outputs (default: datasets/external/nabh_bronze/):
  raw/pages/page_NNNN.json          API responses (git-ignored)
  nabh_organisations_bronze.csv     one row per listed organisation / accreditation

Usage:
  python scrapers/nabh_organisations.py            # fetch (resumes) and build
  python scrapers/nabh_organisations.py --offline  # rebuild from raw/pages
Needs: requests, beautifulsoup4
"""

import argparse
import hashlib
import csv
import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

AJAX = "https://nabh.co/wp-admin/admin-ajax.php"
PAGE_URL = "https://nabh.co/find-a-healthcare-organisation/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; datathon-research-scraper/1.0)"}
DELAY_S = 1.5
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "nabh_bronze"

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
STATE_ALIASES = {"orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
                 "newdelhi": "Delhi", "nctofdelhi": "Delhi", "chattisgarh": "Chhattisgarh",
                 "jammukashmir": "Jammu and Kashmir", "andamanandnicobar": "Andaman and Nicobar Islands",
                 "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
                 "damananddiu": "Dadra and Nagar Haveli and Daman and Diu"}

# Programme, from the accreditation-number prefix (worked out from the 2026-11-21 data: each prefix
# checked against its status text and certificate folder). prefix -> (label, category, related services).
# Categories:
#   service_accreditation      accredits/certifies a specific service -> service evidence
#   hospital_accreditation     full NABH accreditation of a hospital / small hospital -> general quality
#   entry_level_certification  NABH entry-level certification -> general quality (lighter standard)
#   empanelment                NABH-assessed empanelment for government schemes (CGHS/ECHS) -> general quality
#   quality_certification     nursing excellence, digital health, clinics -> general quality
#   ayush                      Ayush (traditional medicine) programmes -> no allopathic service evidence
#   non_facility               not a care site (travel facilitators, ethics committees) -> excluded downstream
PROGRAMMES = {
    "H": ("Hospital accreditation", "hospital_accreditation", ""),
    "SHCO": ("Small healthcare organisation accreditation", "hospital_accreditation", ""),
    "PEH": ("Entry-level hospital certification", "entry_level_certification", ""),
    "PESHCO": ("Entry-level small healthcare organisation certification", "entry_level_certification", ""),
    "ELCP": ("Entry-level certification programme (2nd edition)", "entry_level_certification", ""),
    "BB": ("Blood bank / blood centre accreditation", "service_accreditation", "blood_bank"),
    "CD": ("Allopathic clinic accreditation: dialysis centre", "service_accreditation", "dialysis;kidney_care"),
    "E": ("Emergency department certification", "service_accreditation", "emergency"),
    "ST": ("Advanced stroke centre certification", "service_accreditation", "stroke_care;neurology"),
    "MANYATA": ("Manyata maternity care certification", "service_accreditation", "obstetrics;normal_delivery"),
    "MIS": ("Medical imaging services accreditation", "service_accreditation", "imaging"),
    "MLP": ("Medical laboratory certification", "service_accreditation", "lab_services"),
    "ECO": ("Eye care organisation accreditation", "service_accreditation", "eye_care"),
    "D": ("Dental facility accreditation", "service_accreditation", "dental"),
    "ELDC": ("Entry-level dental clinic certification", "service_accreditation", "dental"),
    "DE": ("Allopathic clinic accreditation: dermatology clinic", "service_accreditation", "dermatology"),
    "CH": ("Care home accreditation", "service_accreditation", "geriatrics"),
    "C": ("Allopathic clinic accreditation", "quality_certification", ""),
    "N": ("Nursing excellence certification", "quality_certification", ""),
    "DH": ("Digital health accreditation (hospital)", "quality_certification", ""),
    "DHC": ("Entry-level digital health certification", "quality_certification", ""),
    "HOS": ("Hospital empanelment (CGHS/ECHS, NABH-assessed)", "empanelment", ""),
    "EYE": ("Eye care empanelment (CGHS/ECHS, NABH-assessed)", "empanelment", "eye_care"),
    "ECE": ("Eye care empanelment (NABH-assessed)", "empanelment", "eye_care"),
    "DEN": ("Dental empanelment (CGHS/ECHS, NABH-assessed)", "empanelment", "dental"),
    "LAB": ("Laboratory empanelment (CGHS/ECHS, NABH-assessed)", "empanelment", "lab_services"),
    "CGHS": ("CGHS empanelment (NABH-assessed)", "empanelment", ""),
    "ECHS": ("ECHS empanelment (NABH-assessed)", "empanelment", ""),
    None: ("CGHS/ECHS empanelment (NABH-assessed; number without prefix)", "empanelment", ""),
    "AH": ("Ayush hospital accreditation", "ayush", ""),
    "EAH": ("Entry-level Ayush hospital certification", "ayush", ""),
    "EAC": ("Entry-level Ayush centre certification", "ayush", ""),
    "PC": ("Panchakarma clinic accreditation", "ayush", ""),
    "MT": ("Medical value travel facilitator empanelment", "non_facility", ""),
    "EC": ("Ethics committee accreditation (clinical trials)", "non_facility", ""),
}
# Status text that means the accreditation is no longer in force
NOT_CURRENT = re.compile(r"withdraw|suspen|expired|closed|cancel", re.I)


def _key(s):
    return re.sub(r"[^a-z]", "", (s or "").lower().replace("&", " and "))


STATE_LOOKUP = {_key(s): s for s in STATES}
STATE_LOOKUP.update(STATE_ALIASES)
# Whole-word patterns for finding a state name inside free text (official names plus common old names)
STATE_TEXT_PATTERNS = [(re.compile(r"\b" + re.escape(s).replace(r"\ ", r"\s+") + r"\b", re.I), s) for s in STATES] + [
    (re.compile(r"\b" + p + r"\b", re.I), s) for p, s in [
        (r"orissa", "Odisha"), (r"pondicherry", "Puducherry"), (r"uttaranchal", "Uttarakhand"),
        (r"new\s+delhi", "Delhi"), (r"chattisgarh", "Chhattisgarh"), (r"jammu\s*(?:&|and)\s*kashmir", "Jammu and Kashmir")]]


def ws(s):
    return re.sub(r"\s+", " ", (s or "").replace("\x00", "")).strip()


def name_norm(s):
    return ws(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower().replace("&", " and ")))


def acc_prefix(acc_no):
    m = re.match(r"^([A-Za-z]+)", acc_no or "")
    return m.group(1).upper() if m else None


def cert_folder(url):
    """'.../Documents/AccreditedList/SHCO/SHCO-2023-0928_...pdf' -> 'SHCO'."""
    if not url:
        return None
    parts = [unquote(p) for p in urlparse(url).path.split("/") if p]
    try:
        i = [p.lower() for p in parts].index("accreditedlist")
        return parts[i + 1] if i + 1 < len(parts) - 1 else None
    except ValueError:
        return None


def address_parts(address):
    """The address ends with ', City, State, PIN' (often repeated). Pull state and PIN."""
    pin = None
    pins = re.findall(r"(?<!\d)([1-8]\d{5})(?!\d)", address or "")
    if pins:
        pin = pins[-1]
    state = None
    for tok in reversed([t.strip() for t in (address or "").split(",")]):
        st = STATE_LOOKUP.get(_key(tok))
        if st:
            state = st
            break
    if state is None:
        # Some listings (mostly empanelment) end "... City State" with no comma: take the state name
        # that appears LAST in the address text.
        best = None
        for pattern, st in STATE_TEXT_PATTERNS:
            for m in pattern.finditer(address or ""):
                if best is None or m.end() > best[0] or (m.end() == best[0] and len(m.group(0)) > best[2]):
                    best = (m.end(), st, len(m.group(0)))
        state = best[1] if best else None
    return state, pin


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def get_page(session, page):
    data = {"action": "get_hospitals", "page": str(page), "q": "", "lat": "", "long": "", "selectedSpecText": ""}
    for attempt in range(1, 4):
        try:
            r = session.post(AJAX, data=data, headers=HEADERS, timeout=90)
            r.raise_for_status()
            d = r.json()
            if "html" not in d or "pagination" not in d:
                raise ValueError("unexpected response shape")
            return d
        except (requests.RequestException, ValueError) as e:
            if attempt == 3:
                raise
            print(f"  retry page {page} ({e})", file=sys.stderr)
            time.sleep(10 * attempt)


def fetch(pages_dir):
    pages_dir.mkdir(parents=True, exist_ok=True)
    with requests.Session() as s:
        first = pages_dir / "page_0001.json"
        if not first.exists():
            d = get_page(s, 1)
            first.write_text(json.dumps(d), encoding="utf-8")
        total = json.loads(first.read_text(encoding="utf-8"))["pagination"]["total_pages"]
        todo = [p for p in range(1, total + 1) if not (pages_dir / f"page_{p:04d}.json").exists()]
        print(f"{total} pages; {total - len(todo)} cached, {len(todo)} to fetch", flush=True)
        failed = []
        for n, p in enumerate(todo, 1):
            time.sleep(DELAY_S)
            try:
                d = get_page(s, p)
            except Exception as e:
                failed.append(p)
                print(f"  page {p} failed: {e}", file=sys.stderr, flush=True)
                continue
            (pages_dir / f"page_{p:04d}.json").write_text(json.dumps(d), encoding="utf-8")
            if n % 50 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)} pages fetched", flush=True)
        if failed:
            print(f"WARNING: {len(failed)} pages failed; re-run to retry: {failed[:20]}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_page(d, page):
    soup = BeautifulSoup(d["html"], "html.parser")
    coords = {}
    for m in d.get("mapData") or []:
        coords[(ws(m.get("name")), ws(m.get("address")))] = (m.get("lat"), m.get("lng"))
    for card in soup.select("div.hp-body-row"):
        cols = {c: card.select_one(f".hs-col-{c}") for c in range(1, 6)}
        a = cols[1].find("a", href=True) if cols[1] else None
        name = ws(cols[1].get_text(" ")) if cols[1] else ""
        address = ws(cols[2].get_text(" ")) if cols[2] else ""
        website = None
        if cols[3]:
            for link in cols[3].find_all("a", href=True):
                if "website" in link.get_text(" ").lower():
                    website = link["href"].strip()
                    break
        acc_no = ws(cols[4].get_text(" ")) if cols[4] else ""
        status = ws(cols[5].get_text(" ")) if cols[5] else ""
        lat, lng = coords.get((name, address), (None, None))
        yield {
            "name": name, "address": address, "website": website, "acc_no": acc_no, "status": status,
            "cert_url": a["href"].strip() if a else None, "lat": lat, "lng": lng, "page": page,
        }


def edition_of(status):
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+Edition", status or "", re.I)
    return int(m.group(1)) if m else None


def build(pages_dir):
    files = sorted(pages_dir.glob("page_*.json"))
    if not files:
        sys.exit(f"No pages in {pages_dir}; run without --offline first.")
    total = json.loads(files[0].read_text(encoding="utf-8"))["pagination"]
    rows, seen = [], Counter()
    for f in files:
        page = int(re.search(r"(\d+)", f.stem).group(1))
        for r in parse_page(json.loads(f.read_text(encoding="utf-8")), page):
            seen[(r["acc_no"], r["name"], r["address"])] += 1
            if seen[(r["acc_no"], r["name"], r["address"])] > 1:
                continue  # the same card can appear on two pages if the list shifts while paging
            state, pin = address_parts(r["address"])
            prefix = acc_prefix(r["acc_no"])
            folder = cert_folder(r["cert_url"])
            prog = PROGRAMMES.get(prefix) or ("Other / unknown", "unknown", "")
            # Empanelment numbers look like HOS/2025/E2674 or HOS/2025/C2655. NABH runs separate ECHS and
            # CGHS empanelment programmes; the E/C letter is taken to mean ECHS/CGHS (an inference, not
            # stated by the site). It separates two listings of one hospital that aren't duplicates.
            m = re.search(r"/\d{4}/([EC])\d", r["acc_no"] or "")
            if prog[1] == "empanelment" and m:
                scheme = {"E": "ECHS", "C": "CGHS"}[m.group(1)]
                prog = (re.sub(r"\(CGHS/ECHS, |\(", f"({scheme} track (inferred), ", prog[0], count=1), prog[1], prog[2])
            try:
                lat = float(r["lat"]) if r["lat"] not in (None, "") else None
                lng = float(r["lng"]) if r["lng"] not in (None, "") else None
            except (TypeError, ValueError):
                lat = lng = None
            if lat is not None and not (6 <= lat <= 37.5 and 68 <= (lng or 0) <= 97.5):
                lat = lng = None  # outside India: geocoding error
            key = f"{r['acc_no']}|{r['name']}|{r['address']}".lower()
            rows.append({
                "nabh_row_id": "nabh_" + hashlib.sha1(key.encode()).hexdigest()[:12],
                "organisation_name": r["name"],
                "name_norm": name_norm(r["name"]),
                "address": r["address"],
                "state_clean": state,
                "pincode_clean": pin,
                "latitude": lat,
                "longitude": lng,
                "website": r["website"],
                "accreditation_no": r["acc_no"],
                "acc_prefix": prefix,
                "cert_folder": folder,
                "programme": prog[0],
                "programme_category": prog[1],
                "status_text": r["status"],
                "listing_current": int(not NOT_CURRENT.search(r["status"] or "")),
                "standards_edition": edition_of(r["status"]),
                "related_services": prog[2],
                "certificate_url": r["cert_url"],
                "source_page": r["page"],
                "source_url": PAGE_URL,
            })
    return rows, total, len(files)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    pages_dir = args.out / "raw" / "pages"

    if not args.offline:
        fetch(pages_dir)
    rows, total, n_files = build(pages_dir)
    snap = dt.datetime.fromtimestamp(max(f.stat().st_mtime for f in pages_dir.glob("page_*.json"))).date()
    for r in rows:
        r["snapshot_date"] = snap.isoformat()

    path = args.out / "nabh_organisations_bronze.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"{n_files}/{total['total_pages']} pages; {len(rows)} rows (site says {total['total_results']})")
    print(f"with state {sum(1 for r in rows if r['state_clean'])}, PIN {sum(1 for r in rows if r['pincode_clean'])}, "
          f"coords {sum(1 for r in rows if r['latitude'] is not None)}")
    print("acc_prefix:", Counter(r["acc_prefix"] for r in rows).most_common(40))
    print("cert_folder:", Counter(r["cert_folder"] for r in rows).most_common(40))
    print("programme_category:", Counter(r["programme_category"] for r in rows).most_common())
    print("service rows by tag:", Counter(t for r in rows for t in r["related_services"].split(";") if t).most_common())
    print("not current:", sum(1 for r in rows if not r["listing_current"]),
          "| ids unique:", len({r["nabh_row_id"] for r in rows}) == len(rows))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
