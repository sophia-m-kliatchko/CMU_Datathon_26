"""
Scrape the National Medical Commission (NMC) lists of medical colleges and their courses.

Source pages:
  https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs
  https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-pg-courses
Both pages load their tables from JSON endpoints, which this script calls directly:
  /college-courses/list?page=&per_page=        MBBS: one row per college (~840)
  /college-courses/pg-list?page=&per_page=     PG: one row per college x course (~10,700)
  /college-courses/detail/<college_id>         address, city, PIN, website for one college
robots.txt allows all paths (checked 2026-11-21).

Why: a medical college runs a teaching hospital. NMC only permits a PG course (MD/MS,
DM, M.Ch.) in a specialty when the hospital has that department with enough patients,
faculty and equipment, so a course with approved seats is strong outside evidence that the
specialty is practised there (e.g. D.M. Nephrology -> dialysis; D.M. Neonatology -> NICU).
A match is evidence FOR a facility; no match is NOT evidence against it.

Personal data: the detail endpoint also returns named staff contacts. These are NOT kept.
Only institutional fields (address, city, PIN, website) are saved.

Outputs (default: datasets/external/nmc/):
  raw/mbbs_list_<date>.json, raw/pg_list_<date>_p<N>.json   list responses as fetched
  raw/details/<college_id>.json                             detail responses (contacts removed);
                                                            cached, so re-runs resume
  nmc_colleges.csv               one row per college
  nmc_college_courses.csv        one row per college x course (MBBS + PG)
  nmc_specialty_reference.csv    one row per specialty: course levels, n_colleges, related services
  nmc_colleges.sqlite            the three tables plus the view v_service_evidence

Usage:
  python scrapers/nmc_colleges.py                 # fetch everything (details take ~15-20 min)
  python scrapers/nmc_colleges.py --skip-details  # lists only (no address / PIN), ~1 min
  python scrapers/nmc_colleges.py --offline       # rebuild outputs from raw/ without fetching
"""

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

BASE = "https://nmc.org.in"
MBBS_PAGE = BASE + "/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs"
PG_PAGE = BASE + "/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-pg-courses"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; datathon-research-scraper/1.0)",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}
PER_PAGE = 1000
DELAY_S = 0.5  # pause between requests, to be polite to a government server
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "nmc"

# Detail fields we keep (institutional only; 'contacts', 'mobile', 'email' etc. are dropped)
DETAIL_KEEP = ["id", "college_code", "college_name", "management_type", "state_name", "university_name",
               "address", "city", "pincode", "website", "inception_year", "no_of_seat", "remarks", "status"]

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Same official names as silver_facilities.state_clean (see notebooks/01_bronze_to_silver.py)
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
STATE_LOOKUP.update({
    "orissa": "Odisha", "chattisgarh": "Chhattisgarh", "chhatisgarh": "Chhattisgarh", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry",
    "nctofdelhi": "Delhi", "newdelhi": "Delhi", "jammukashmir": "Jammu and Kashmir",
    "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu",
})

# Course level, from the API's course_type
COURSE_LEVEL = {
    "M.B.B.S.": "MBBS",
    "MD": "PG degree", "MS": "PG degree",
    "Diploma": "PG diploma",
    "DM": "Super-specialty (DM)", "M.Ch.": "Super-specialty (M.Ch.)",
}

# Specialty keyword -> related challenge services. The tags match the ANBAI/DNB dataset
# (scrapers/anbai_dnb.py) so the two sources can be combined. These are HINTS we wrote:
# a teaching department is indirect evidence for a service, not a claim by the facility.
# Every matching rule adds its tags.
SERVICE_RULES = [
    (r"nephrolog", ["dialysis", "kidney_care"]),
    (r"neonat(?!al anaesth)", ["nicu", "neonatal_care"]),
    (r"^(?!.*oncolog).*(obstetric|gynaec|gynec|maternal)", ["obstetrics", "emergency_c_section"]),
    (r"critical care|intensive care", ["icu"]),
    (r"emergency", ["emergency", "trauma"]),
    (r"trauma", ["trauma"]),
    (r"cardiolog|cardiac|cardio", ["cardiac_care"]),
    (r"cardio.*surg|cardiac surg|thoracic", ["cardiac_surgery"]),
    (r"interventional cardiology", ["cath_lab"]),
    (r"onco|radio.?therapy", ["cancer_care"]),
    (r"medical oncology", ["chemotherapy"]),
    (r"radio.?therapy|radiation oncology", ["radiotherapy"]),
    (r"radiation medicine", ["nuclear_medicine"]),
    (r"neurosurg|neuro surg", ["neurosurgery"]),
    (r"neurolog", ["neurology", "stroke_care"]),
    (r"paediatric|pediatric|child health", ["paediatrics"]),
    (r"paediatric surg|pediatric surg", ["paediatric_surgery"]),
    (r"orthop", ["orthopaedics", "trauma"]),
    (r"\burolog|genito", ["urology", "kidney_care"]),
    (r"transfusion|immuno.?ha?ematology", ["blood_bank"]),
    (r"radio.?diagnosis|radiology|imaging", ["imaging"]),
    (r"interventional radiology", ["interventional_radiology"]),
    (r"anaesthe|anesthe", ["surgery_support"]),
    (r"psychiatr|mental health", ["mental_health"]),
    (r"ophthalm", ["eye_care"]),
    (r"otorhino|\bent\b|otology", ["ent"]),
    (r"gastro|hepat|g\.i\.", ["gastro_liver"]),
    (r"general surgery", ["general_surgery"]),
    (r"general medicine", ["general_medicine"]),
    (r"family medicine", ["primary_care"]),
    (r"pulmonary|respiratory|tuberculosis|chest", ["respiratory"]),
    (r"dermat", ["dermatology"]),
    (r"transplant", ["transplant"]),
    (r"plastic|burns", ["plastic_reconstructive", "burns"]),
    (r"hand surgery", ["plastic_reconstructive", "trauma"]),
    (r"head and neck", ["cancer_care", "ent"]),
    (r"palliative", ["palliative_care"]),
    (r"sports medicine", ["orthopaedics", "rehabilitation"]),
    (r"genetic", ["genetics"]),
    (r"endocrin|diabetolog", ["diabetes_endocrine"]),
    (r"ha?ematolog", ["blood_disorders"]),
    (r"rheumatolog", ["rheumatology"]),
    (r"infectious", ["infectious_disease"]),
    (r"physical medicine|rehabilitation", ["rehabilitation"]),
    (r"nuclear medicine", ["nuclear_medicine"]),
    (r"^vascular surg", ["vascular_surgery"]),
    (r"pathology|microbiology|biochemistry|laboratory medicine|virology", ["lab_services"]),
    (r"geriatric", ["geriatrics"]),
    (r"reproductive", ["fertility"]),
]

# Specialties that are lab / basic science / public health: say little about patient services
NON_CLINICAL = re.compile(
    r"anatomy|physiology|biochemistry|pharmacology|forensic|community medicine|preventive|public health|"
    r"hospital administration|health administration|health education|biophysics|tropical medicine|"
    r"aerospace|aviation|marine medicine|occupational health", re.I)

DEGREE_PREFIX = re.compile(
    r"^\s*(M\.?\s?D\.?|M\.?\s?S\.?|D\.?\s?M\.?|M\.?\s?Ch\.?|Diploma\s+in|Diploma)\s*[-:(]?\s*", re.I)


DIPLOMA_SUFFIX = re.compile(r"\s*\((?:D\.|Dip\.)[^)]*\)?\s*(?:/.*)?$")


def ws(text):
    return re.sub(r"\s+", " ", str(text or "").replace("\x00", "")).strip()


def name_norm(name):
    """Lower-case, '&'->'and', letters/digits/spaces only. For matching to other sources."""
    s = (name or "").lower().replace("&", " and ")
    return ws(re.sub(r"[^a-z0-9 ]+", " ", s))


def clean_state(s):
    return STATE_LOOKUP.get(_key(s), ws(s) or None)


def clean_pin(p):
    p = re.sub(r"\D", "", str(p or ""))
    return p if re.fullmatch(r"[1-8]\d{5}", p) else None


def specialty_of(course_name, course_type):
    if course_type == "M.B.B.S.":
        return "MBBS (undergraduate)"
    s = ws(DEGREE_PREFIX.sub("", ws(course_name))).strip(" -:")
    # Diplomas: "Paediatrics (D.C.H.)/Diploma in Child Health" -> "Paediatrics"
    s = ws(DIPLOMA_SUFFIX.sub("", s))
    return s or ws(course_name)


def services_for(specialty):
    if NON_CLINICAL.search(specialty):
        return []
    tags = []
    for pat, svc in SERVICE_RULES:
        if re.search(pat, specialty, re.I):
            tags += [t for t in svc if t not in tags]
    return tags


# ---------------------------------------------------------------------------
# Fetching (raw responses are saved so re-runs can work offline)
# ---------------------------------------------------------------------------

def get_json(session, path, params=None, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(BASE + path, params=params, headers=HEADERS, timeout=90)
            r.raise_for_status()
            data = r.json()
            if not data.get("success", True):
                raise ValueError(f"API returned success=false for {path}")
            return data
        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                raise
            wait = 5 * attempt
            print(f"  retry {attempt} for {path} in {wait}s ({e})", file=sys.stderr)
            time.sleep(wait)


def fetch_lists(session, raw, date):
    mbbs = get_json(session, "/college-courses/list", {"page": 1, "per_page": PER_PAGE})
    if mbbs["pagination"]["last_page"] > 1:
        sys.exit("MBBS list has more than one page at per_page=1000: add paging.")
    (raw / f"mbbs_list_{date}.json").write_text(json.dumps(mbbs), encoding="utf-8")
    print(f"MBBS list: {len(mbbs['data'])} rows")

    page, last = 1, 1
    while page <= last:
        time.sleep(DELAY_S)
        pg = get_json(session, "/college-courses/pg-list", {"page": page, "per_page": PER_PAGE})
        pg.pop("grouped", None)  # same rows as 'data', grouped by level
        (raw / f"pg_list_{date}_p{page:02d}.json").write_text(json.dumps(pg), encoding="utf-8")
        last = pg["pagination"]["last_page"]
        print(f"PG list: page {page}/{last}, {len(pg['data'])} rows")
        page += 1


def fetch_details(session, raw, college_ids):
    ddir = raw / "details"
    ddir.mkdir(exist_ok=True)
    todo = [c for c in sorted(college_ids) if not (ddir / f"{c}.json").exists()]
    print(f"Details: {len(college_ids) - len(todo)} cached, {len(todo)} to fetch")
    failed = []
    for n, cid in enumerate(todo, 1):
        time.sleep(DELAY_S)
        try:
            d = get_json(session, f"/college-courses/detail/{cid}")["data"]
        except Exception as e:  # keep going; a re-run retries the missing ones
            failed.append(cid)
            print(f"  detail {cid} failed: {e}", file=sys.stderr)
            continue
        keep = {k: d.get(k) for k in DETAIL_KEEP}
        (ddir / f"{cid}.json").write_text(json.dumps(keep), encoding="utf-8")
        if n % 50 == 0 or n == len(todo):
            print(f"  {n}/{len(todo)} details fetched")
    if failed:
        print(f"WARNING: {len(failed)} details failed; re-run to retry: {failed[:20]}", file=sys.stderr)


def latest(raw, pattern):
    files = sorted(raw.glob(pattern))
    if not files:
        sys.exit(f"No raw files matching {pattern} in {raw}; run without --offline first.")
    date = re.search(r"\d{4}-\d{2}-\d{2}", files[-1].name).group(0)
    return [f for f in files if date in f.name], date


# ---------------------------------------------------------------------------
# Build tables
# ---------------------------------------------------------------------------

def build(raw):
    mbbs_files, mbbs_date = latest(raw, "mbbs_list_*.json")
    pg_files, pg_date = latest(raw, "pg_list_*_p*.json")
    mbbs_rows = json.loads(mbbs_files[-1].read_text(encoding="utf-8"))["data"]
    pg_rows = [r for f in pg_files for r in json.loads(f.read_text(encoding="utf-8"))["data"]]

    details = {}
    for f in (raw / "details").glob("*.json") if (raw / "details").exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        details[d["id"]] = d

    courses, seen = [], set()
    for src, rows in (("mbbs_list", mbbs_rows), ("pg_list", pg_rows)):
        for r in rows:
            if r.get("id") in seen:  # the same course row can't be counted twice
                continue
            seen.add(r.get("id"))
            spec = specialty_of(r.get("course_name"), r.get("course_type"))
            svc = [] if r.get("course_type") == "M.B.B.S." else services_for(spec)
            courses.append({
                "college_id": r.get("college_id"),
                "course_row_id": r.get("id"),
                "course_level": COURSE_LEVEL.get(r.get("course_type"), r.get("course_type") or "unknown"),
                "course_type": r.get("course_type"),
                "course_name": ws(r.get("course_name")),
                "specialty": spec,
                "is_clinical": int(r.get("course_type") != "M.B.B.S." and not NON_CLINICAL.search(spec)),
                "related_services": ";".join(svc),
                "approved_seats": r.get("approved_seat"),
                "previous_approved_seats": r.get("previous_approved_seat"),
                "recognition_status": ws(r.get("recognition_status") or r.get("remark")),
                "lop_date": r.get("lop_date"),
                "approval_date": r.get("approval_date"),
                "active": int(r.get("status") == 1),
                "source_list": src,
            })

    # One row per college: list fields first, detail fields override where present
    colleges = {}
    for r in mbbs_rows + pg_rows:
        cid = r.get("college_id")
        c = colleges.setdefault(cid, {"college_id": cid})
        for k_out, k_in in (("college_code", "college_code"), ("college_name", "college_name"),
                            ("state_listed", "state_name"), ("university_name", "university_name"),
                            ("management_type", "management_type"), ("inception_year", "inception_year")):
            if r.get(k_in) and not c.get(k_out):
                c[k_out] = ws(r.get(k_in))

    by_college = defaultdict(list)
    for co in courses:
        by_college[co["college_id"]].append(co)

    out = []
    for cid, c in colleges.items():
        d = details.get(cid, {})
        cs = by_college[cid]
        mbbs = [x for x in cs if x["course_level"] == "MBBS"]
        pg = [x for x in cs if x["course_level"] != "MBBS"]
        ss = [x for x in pg if x["course_level"].startswith("Super-specialty")]
        name = ws(d.get("college_name")) or c.get("college_name")
        out.append({
            "college_id": cid,
            "college_code": c.get("college_code") or d.get("college_code"),
            "college_name": name,
            "name_norm": name_norm(name),
            "state_listed": c.get("state_listed") or d.get("state_name"),
            "state_clean": clean_state(c.get("state_listed") or d.get("state_name")),
            "city": ws(d.get("city")) or None,
            "pincode_clean": clean_pin(d.get("pincode")),
            "address": ws(d.get("address")) or None,
            "website": ws(d.get("website")) or None,
            "university_name": c.get("university_name"),
            "management_type": c.get("management_type") or d.get("management_type"),
            "inception_year": c.get("inception_year") or d.get("inception_year"),
            "has_mbbs": int(bool(mbbs)),
            "mbbs_seats": sum(x["approved_seats"] or 0 for x in mbbs) or None,
            "mbbs_status": mbbs[0]["recognition_status"] if mbbs else None,
            "n_pg_courses": len(pg),
            "n_pg_seats": sum(x["approved_seats"] or 0 for x in pg),
            "n_super_specialty_courses": len(ss),
            "super_specialties": "; ".join(sorted({x["specialty"] for x in ss})),
            "has_detail": int(bool(d)),
            "source_pages": MBBS_PAGE + " | " + PG_PAGE,
            "snapshot_date": max(mbbs_date, pg_date),
        })
    out.sort(key=lambda r: (r["state_clean"] or "", r["college_name"] or ""))

    ref = defaultdict(lambda: {"levels": set(), "colleges": set(), "seats": 0})
    for co in courses:
        if co["course_level"] == "MBBS":
            continue
        e = ref[co["specialty"]]
        e["levels"].add(co["course_level"])
        e["colleges"].add(co["college_id"])
        e["seats"] += co["approved_seats"] or 0
    reference = [{
        "specialty": s,
        "course_levels": "; ".join(sorted(e["levels"])),
        "is_clinical": int(not NON_CLINICAL.search(s)),
        "related_services": ";".join(services_for(s)),
        "n_colleges": len(e["colleges"]),
        "total_seats": e["seats"],
    } for s, e in sorted(ref.items())]

    return out, courses, reference


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_sqlite(path, tables):
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for name, rows in tables.items():
        cols = list(rows[0].keys())
        con.execute(f"CREATE TABLE {name} ({', '.join(cols)})")
        con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in cols)})",
                        [[r[c] for c in cols] for r in rows])
    con.executescript("""
        CREATE INDEX ix_course_college ON nmc_college_courses(college_id);
        CREATE INDEX ix_course_spec ON nmc_college_courses(specialty);
        CREATE INDEX ix_college_state ON nmc_colleges(state_clean);
        -- One row per college x challenge service that a clinical PG course points to
        CREATE VIEW v_service_evidence AS
        WITH RECURSIVE svc(college_id, course_name, course_level, approved_seats, rest, service) AS (
            SELECT college_id, course_name, course_level, approved_seats, related_services || ';', NULL
            FROM nmc_college_courses WHERE related_services <> '' AND active = 1
            UNION ALL
            SELECT college_id, course_name, course_level, approved_seats,
                   substr(rest, instr(rest, ';') + 1), substr(rest, 1, instr(rest, ';') - 1)
            FROM svc WHERE rest <> ''
        )
        SELECT c.college_id, c.college_name, c.city, c.pincode_clean, c.state_clean, c.management_type,
               s.service, group_concat(s.course_name, '; ') AS via_courses,
               max(s.course_level LIKE 'Super-specialty%') AS via_super_specialty,
               sum(s.approved_seats) AS seats
        FROM svc s JOIN nmc_colleges c USING (college_id)
        WHERE s.service IS NOT NULL
        GROUP BY c.college_id, s.service;
    """)
    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--offline", action="store_true", help="rebuild from raw/ without fetching")
    ap.add_argument("--skip-details", action="store_true", help="don't fetch per-college details")
    args = ap.parse_args()

    raw = args.out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    if not args.offline:
        date = dt.date.today().isoformat()
        with requests.Session() as session:
            fetch_lists(session, raw, date)
            if not args.skip_details:
                ids = set()
                for f in list(raw.glob(f"mbbs_list_{date}.json")) + list(raw.glob(f"pg_list_{date}_p*.json")):
                    ids |= {r["college_id"] for r in json.loads(f.read_text(encoding="utf-8"))["data"]}
                fetch_details(session, raw, ids)

    colleges, courses, reference = build(raw)
    write_csv(args.out / "nmc_colleges.csv", colleges)
    write_csv(args.out / "nmc_college_courses.csv", courses)
    write_csv(args.out / "nmc_specialty_reference.csv", reference)
    write_sqlite(args.out / "nmc_colleges.sqlite", {
        "nmc_colleges": colleges, "nmc_college_courses": courses, "nmc_specialty_reference": reference,
    })

    lv = Counter(c["course_level"] for c in courses)
    print(f"{len(colleges)} colleges ({sum(c['has_detail'] for c in colleges)} with detail, "
          f"{sum(1 for c in colleges if c['pincode_clean'])} with a valid PIN); "
          f"{len(courses)} course rows {dict(lv)}; {len(reference)} PG specialties")
    unmapped = [r["specialty"] for r in reference if r["is_clinical"] and not r["related_services"]]
    if unmapped:
        print(f"Clinical specialties with no service tag ({len(unmapped)}): {unmapped}")
    unknown_states = {c["state_listed"] for c in colleges if c["state_clean"] not in STATES}
    if unknown_states:
        print(f"WARNING: unrecognised states: {unknown_states}")
    print(f"Wrote outputs to {args.out}")


if __name__ == "__main__":
    main()
