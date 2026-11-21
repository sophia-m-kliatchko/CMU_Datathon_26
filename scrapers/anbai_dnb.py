"""
Scrape the ANBAI list of DNB-accredited hospitals and their accredited specialties.

Source: https://anbai.org/DNB_accredited_institutions.php
(Association of National Board Accredited Institutions; mirrors the NBEMS accreditation list.)

Why: a hospital accredited by NBEMS to train DNB / DrNB / FNB doctors in a specialty
(e.g. Nephrology, Neonatology) must actually practise that specialty with enough patient
volume, faculty and equipment. That is outside evidence that backs up the Virtue Foundation
facility claims. A match is evidence FOR a facility; no match is NOT evidence against it.

The page is one static HTML file: one collapsible section per state, each holding a table
of  Hospital | City | Specialties (comma-separated). One HTTP request fetches everything.

Outputs (default: datasets/external/anbai_dnb_bronze/; "bronze" = not yet verified by the team):
  raw/anbai_dnb_<date>.html         snapshot of the page that was parsed (provenance)
  dnb_hospitals_bronze.csv          one row per hospital listing
  dnb_hospital_specialties_bronze.csv  one row per hospital x accredited specialty
  dnb_specialty_reference_bronze.csv  canonical specialties: category + related challenge services
  anbai_dnb_bronze.sqlite           the three tables above plus a view v_service_evidence

Usage:
  python scrapers/anbai_dnb.py                       # fetch live page
  python scrapers/anbai_dnb.py --html saved.html     # parse a saved copy instead
"""

import argparse
import csv
import datetime as dt
import hashlib
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://anbai.org/DNB_accredited_institutions.php"
USER_AGENT = "Mozilla/5.0 (compatible; datathon-research-scraper/1.0)"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "anbai_dnb_bronze"

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# State headings on the page -> official names used in silver_facilities.state_clean
STATE_FIXES = {
    "Orissa": "Odisha",
    "Uttaranchal": "Uttarakhand",
    "Jammu & Kashmir": "Jammu and Kashmir",
    "Pondicherry": "Puducherry",
}

# The list predates the 2014 Andhra Pradesh / Telangana split in places: these cities are
# listed under Andhra Pradesh but are in Telangana today.
TELANGANA_CITY_WORDS = [
    "hyderabad", "secunderabad", "warangal", "karimnagar", "nizamabad", "khammam",
    "nalgonda", "mahbubnagar", "mahabubnagar", "adilabad", "medak", "sangareddy",
    "rangareddy", "ranga reddy", "siddipet", "suryapet",
]

# Canonical specialty -> (category, related services in our challenge)
#   category: clinical | diagnostic | lab_basic_science | public_health_admin
#   services: short tags for the services a user might search for. These are HINTS:
#   a specialty is indirect evidence (Nephrology training implies a dialysis unit almost
#   always, but it is still not the same as a "dialysis" claim). See docs/anbai-dnb.md.
SPECIALTIES = {
    "Anaesthesiology": ("clinical", ["surgery_support", "icu"]),
    "Arthroplasty": ("clinical", ["joint_replacement", "orthopaedics"]),
    "Biochemistry": ("lab_basic_science", ["lab_services"]),
    "Breast Imaging": ("diagnostic", ["imaging", "cancer_care"]),
    "Cardiac Anaesthesia": ("clinical", ["cardiac_surgery"]),
    "Cardio Thoracic Surgery": ("clinical", ["cardiac_surgery", "cardiac_care"]),
    "Cardiology": ("clinical", ["cardiac_care", "cath_lab"]),
    "Critical Care Medicine": ("clinical", ["icu"]),
    "Cross Sectional Body Imaging": ("diagnostic", ["imaging", "ct_mri"]),
    "Dermatology, Venereology and Leprosy": ("clinical", ["dermatology"]),
    "Emergency Medicine": ("clinical", ["emergency", "trauma"]),
    "Endocrinology": ("clinical", ["diabetes_endocrine"]),
    "Endovascular and Interventional Radiology": ("diagnostic", ["interventional_radiology", "imaging"]),
    "Family Medicine": ("clinical", ["primary_care"]),
    "Forensic Medicine": ("lab_basic_science", []),
    "Gastroenterology": ("clinical", ["gastro_liver", "endoscopy"]),
    "General Medicine": ("clinical", ["general_medicine"]),
    "General Surgery": ("clinical", ["general_surgery"]),
    "Genito Urinary Surgery (Urology)": ("clinical", ["urology", "kidney_care"]),
    "Gynaecologic Oncology": ("clinical", ["cancer_care", "gynaecology"]),
    "Hand and Micro Surgery": ("clinical", ["plastic_reconstructive", "trauma"]),
    "Health Administration including Hospital Administration": ("public_health_admin", []),
    "Hematology": ("clinical", ["blood_disorders"]),
    "High Risk Pregnancy and Perinatology": ("clinical", ["obstetrics", "high_risk_pregnancy", "emergency_c_section"]),
    "Immuno Hematology and Blood Transfusion": ("lab_basic_science", ["blood_bank"]),
    "Infectious Diseases": ("clinical", ["infectious_disease"]),
    "Interventional Cardiology": ("clinical", ["cath_lab", "cardiac_care"]),
    "Liver Transplantation": ("clinical", ["transplant", "gastro_liver"]),
    "Medical Genetics": ("clinical", ["genetics"]),
    "Medical Oncology": ("clinical", ["cancer_care", "chemotherapy"]),
    "Microbiology": ("lab_basic_science", ["lab_services"]),
    "Minimal Access Surgery": ("clinical", ["general_surgery", "laparoscopy"]),
    "Neonatology": ("clinical", ["nicu", "neonatal_care"]),
    "Nephrology": ("clinical", ["dialysis", "kidney_care"]),
    "Neuro Anaesthesia and Critical Care": ("clinical", ["neurosurgery", "icu"]),
    "Neuro Surgery": ("clinical", ["neurosurgery", "trauma"]),
    "Neurology": ("clinical", ["neurology", "stroke_care"]),
    "Neurovascular Intervention": ("clinical", ["stroke_care", "interventional_radiology"]),
    "Nuclear Medicine": ("diagnostic", ["nuclear_medicine", "cancer_care"]),
    "Obstetrics and Gynaecology": ("clinical", ["obstetrics", "emergency_c_section", "gynaecology"]),
    "Ophthalmology": ("clinical", ["eye_care"]),
    "Orthopaedic Surgery": ("clinical", ["orthopaedics", "trauma"]),
    "Otorhinolaryngology (ENT)": ("clinical", ["ent"]),
    "Paediatric Gastroenterology": ("clinical", ["paediatrics", "gastro_liver"]),
    "Paediatric Nephrology": ("clinical", ["paediatrics", "dialysis", "kidney_care"]),
    "Paediatric Surgery": ("clinical", ["paediatrics", "paediatric_surgery"]),
    "Paediatrics": ("clinical", ["paediatrics"]),
    "Pathology": ("lab_basic_science", ["lab_services"]),
    "Pediatric Cardiology": ("clinical", ["paediatrics", "cardiac_care"]),
    "Pediatric Hemato Oncology": ("clinical", ["paediatrics", "cancer_care", "blood_disorders"]),
    "Pediatric Intensive Care": ("clinical", ["paediatrics", "picu", "icu"]),
    "Pharmacology": ("lab_basic_science", []),
    "Physical Medicine and Rehabilitation": ("clinical", ["rehabilitation"]),
    "Physiology": ("lab_basic_science", []),
    "Plastic Surgery": ("clinical", ["plastic_reconstructive", "burns"]),
    "Psychiatry": ("clinical", ["mental_health"]),
    "Radio Diagnosis": ("diagnostic", ["imaging", "ct_mri"]),
    "Radio Therapy": ("clinical", ["cancer_care", "radiotherapy"]),
    "Reproductive Medicine": ("clinical", ["fertility"]),
    "Respiratory Medicine": ("clinical", ["respiratory"]),
    "Rheumatology": ("clinical", ["rheumatology"]),
    "Rural Surgery": ("clinical", ["general_surgery"]),
    "Social and Preventive Medicine / Community Medicine": ("public_health_admin", []),
    "Spine Surgery": ("clinical", ["spine", "orthopaedics", "neurosurgery"]),
    "Sports Medicine": ("clinical", ["orthopaedics", "rehabilitation"]),
    "Surgical Gastroenterology": ("clinical", ["gastro_liver", "general_surgery"]),
    "Surgical Oncology": ("clinical", ["cancer_care", "cancer_surgery"]),
    "Thoracic Surgery": ("clinical", ["thoracic_surgery"]),
    "Trauma Care": ("clinical", ["trauma", "emergency"]),
    "Vascular Surgery": ("clinical", ["vascular_surgery"]),
    "Vitreo Retinal Surgery": ("clinical", ["eye_care"]),
}

# Spelling variants seen on the page -> canonical name (keys are lower-cased)
SPECIALTY_ALIASES = {
    "cardiac anesthesia": "Cardiac Anaesthesia",
    "critical care": "Critical Care Medicine",
    "pediatrics": "Paediatrics",
    "radiology": "Radio Diagnosis",
    "hospital administration": "Health Administration including Hospital Administration",
    "health administration": "Health Administration including Hospital Administration",
    "dermatology": "Dermatology, Venereology and Leprosy",
    "urology": "Genito Urinary Surgery (Urology)",
}

COURSE_NOTE_RE = re.compile(r"\(\s*direct\s*6\s*years?\s*course\s*\)", re.I)

_CANON_BY_KEY = {s.lower(): s for s in SPECIALTIES}
_CANON_BY_KEY.update(SPECIALTY_ALIASES)


def ws(text):
    return re.sub(r"\s+", " ", (text or "").replace("\x00", "")).strip()


def canonical(fragment):
    """Return (canonical_name, course_note) or (None, course_note) if unrecognised."""
    note = "Direct 6-year course" if COURSE_NOTE_RE.search(fragment) else ""
    base = ws(COURSE_NOTE_RE.sub("", fragment)).strip(" ,.;")
    return _CANON_BY_KEY.get(base.lower()), note


def split_specialties(cell):
    """
    Split a comma-separated specialty cell into canonical specialties, repairing the page's
    formatting problems:
      * names broken by a stray comma ("Genito Urinary, Surgery (Urology)",
        "Critical Care, Medicine", "Dermatology, Venereology and Leprosy")
      * missing commas ("Cardio Thoracic Surgery (Direct 6 Years Course) Cardiology")
      * the same specialty listed twice in one cell
    Returns a list of dicts: specialty, specialty_raw, course_note, recognized.
    """
    frags = [ws(f) for f in cell.split(",")]
    frags = [f for f in frags if f]
    out, i = [], 0
    while i < len(frags):
        f = frags[i]
        # 1) a name broken across a comma: try joining with the next fragment
        if i + 1 < len(frags):
            for joiner in (" ", ", "):
                joined = f + joiner + frags[i + 1]
                name, note = canonical(joined)
                # Only join when the first piece is not already a full name, or when the
                # joined form is the official name (e.g. Dermatology, Venereology and Leprosy)
                if name and (canonical(f)[0] is None or joined.lower() == name.lower()):
                    out.append((name, joined, note, True))
                    i += 2
                    break
            else:
                name = None
            if name:
                continue
        # 2) a known name on its own
        name, note = canonical(f)
        if name:
            out.append((name, f, note, True))
            i += 1
            continue
        # 3) two names with a missing comma: try every word boundary
        words = f.split(" ")
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:])
            (na, nota), (nb, notb) = canonical(a), canonical(b)
            if na and nb:
                out.append((na, a, nota, True))
                out.append((nb, b, notb, True))
                break
        else:
            out.append((ws(COURSE_NOTE_RE.sub("", f)), f, "", False))
        i += 1

    seen, result = set(), []
    for name, raw, note, ok in out:
        key = (name.lower(), note)
        if key in seen:
            continue
        seen.add(key)
        result.append({"specialty": name, "specialty_raw": raw, "course_note": note, "recognized": ok})
    return result


def name_norm(name):
    """Lower-case, '&'->'and', letters/digits/spaces only. For matching to other sources."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return ws(s)


def clean_state(listed, city):
    state = STATE_FIXES.get(listed, listed)
    note = ""
    if state == "Andhra Pradesh" and any(w in city.lower() for w in TELANGANA_CITY_WORDS):
        state, note = "Telangana", "Listed under Andhra Pradesh (pre-2014 split); city is in Telangana"
    return state, note


# ---------------------------------------------------------------------------
# Scrape and parse
# ---------------------------------------------------------------------------

def fetch(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    hospitals, specialties, unknown = [], [], Counter()
    id_counts = Counter()

    sections = soup.select("div.faqitem")
    if not sections:
        sys.exit("No state sections (div.faqitem) found: the page layout has changed.")

    for section in sections:
        heading = section.select_one(".acchead h4")
        state_listed = ws(heading.get_text(" ") if heading else "")
        for tr in section.select("table tr"):
            cells = [ws(td.get_text(" ")) for td in tr.find_all("td")]
            if not cells or "headingbg" in (tr.get("class") or []) or cells[:2] == ["Sl.No.", "Hospitals"]:
                continue
            if len(cells) != 4:
                print(f"WARNING: skipped row with {len(cells)} cells in {state_listed}: {cells}", file=sys.stderr)
                continue
            _, name, city, spec_cell = cells
            state_clean, state_note = clean_state(state_listed, city)

            base_id = "dnb_" + hashlib.sha1(f"{state_listed}|{name}|{city}".lower().encode()).hexdigest()[:10]
            id_counts[base_id] += 1
            hospital_id = base_id if id_counts[base_id] == 1 else f"{base_id}_{id_counts[base_id]}"

            specs = split_specialties(spec_cell)
            for s in specs:
                if not s["recognized"]:
                    unknown[s["specialty"]] += 1
                category, services = SPECIALTIES.get(s["specialty"], ("unknown", []))
                specialties.append({
                    "hospital_id": hospital_id,
                    "specialty": s["specialty"],
                    "course_note": s["course_note"],
                    "category": category,
                    "related_services": ";".join(services),
                    "specialty_raw": s["specialty_raw"],
                    "recognized": int(s["recognized"]),
                })

            hospitals.append({
                "hospital_id": hospital_id,
                "hospital_name": name,
                "name_norm": name_norm(name),
                "city_raw": city,
                "state_listed": state_listed,
                "state_clean": state_clean,
                "state_note": state_note,
                "n_specialties": len(specs),
                "specialties": "; ".join(s["specialty"] for s in specs),
                "specialties_raw": spec_cell,
            })

    # Same name + city listed more than once (e.g. two branches): kept, but flagged
    nc = Counter((h["name_norm"], h["city_raw"].lower()) for h in hospitals)
    for h in hospitals:
        h["duplicate_name_city"] = int(nc[(h["name_norm"], h["city_raw"].lower())] > 1)

    return hospitals, specialties, unknown


# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_sqlite(path, tables):
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    for name, (rows, fields) in tables.items():
        con.execute(f"CREATE TABLE {name} ({', '.join(f'{c} TEXT' for c in fields)})")
        con.executemany(
            f"INSERT INTO {name} VALUES ({', '.join('?' for _ in fields)})",
            [[r.get(c) for c in fields] for r in rows],
        )
    con.executescript("""
        CREATE INDEX ix_spec_hospital ON dnb_hospital_specialties(hospital_id);
        CREATE INDEX ix_spec_name ON dnb_hospital_specialties(specialty);
        CREATE INDEX ix_hosp_state ON dnb_hospitals(state_clean);
        -- One row per hospital x challenge service that an accredited specialty points to
        CREATE VIEW v_service_evidence AS
        WITH RECURSIVE svc(hospital_id, specialty, rest, service) AS (
            SELECT hospital_id, specialty, related_services || ';', NULL
            FROM dnb_hospital_specialties WHERE related_services <> ''
            UNION ALL
            SELECT hospital_id, specialty, substr(rest, instr(rest, ';') + 1),
                   substr(rest, 1, instr(rest, ';') - 1)
            FROM svc WHERE rest <> ''
        )
        SELECT h.hospital_id, h.hospital_name, h.city_raw, h.state_clean,
               s.service, group_concat(s.specialty, '; ') AS via_specialties
        FROM svc s JOIN dnb_hospitals h USING (hospital_id)
        WHERE s.service IS NOT NULL
        GROUP BY h.hospital_id, s.service;
    """)
    con.commit()
    con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", type=Path, help="parse this saved HTML file instead of fetching")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    args = ap.parse_args()

    scraped_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.mkdir(parents=True, exist_ok=True)

    if args.html:
        html = args.html.read_text(encoding="utf-8")
    else:
        print(f"Fetching {SOURCE_URL} ...")
        html = fetch(SOURCE_URL)
        raw_dir = args.out / "raw"
        raw_dir.mkdir(exist_ok=True)
        snap = raw_dir / f"anbai_dnb_{scraped_at[:10]}.html"
        snap.write_text(html, encoding="utf-8")
        print(f"Saved snapshot {snap.relative_to(REPO_ROOT) if snap.is_relative_to(REPO_ROOT) else snap}")

    hospitals, specialties, unknown = parse(html)
    for h in hospitals:
        h["source_url"] = SOURCE_URL
        h["scraped_at"] = scraped_at

    hosp_fields = ["hospital_id", "hospital_name", "name_norm", "city_raw", "state_listed", "state_clean",
                   "state_note", "n_specialties", "specialties", "specialties_raw", "duplicate_name_city",
                   "source_url", "scraped_at"]
    spec_fields = ["hospital_id", "specialty", "course_note", "category", "related_services",
                   "specialty_raw", "recognized"]
    ref_counts = Counter(s["specialty"] for s in specialties)
    reference = [{"specialty": k, "category": c, "related_services": ";".join(sv), "n_hospitals": ref_counts.get(k, 0)}
                 for k, (c, sv) in sorted(SPECIALTIES.items())]
    ref_fields = ["specialty", "category", "related_services", "n_hospitals"]

    write_csv(args.out / "dnb_hospitals_bronze.csv", hospitals, hosp_fields)
    write_csv(args.out / "dnb_hospital_specialties_bronze.csv", specialties, spec_fields)
    write_csv(args.out / "dnb_specialty_reference_bronze.csv", reference, ref_fields)
    write_sqlite(args.out / "anbai_dnb_bronze.sqlite", {
        "dnb_hospitals": (hospitals, hosp_fields),
        "dnb_hospital_specialties": (specialties, spec_fields),
        "dnb_specialty_reference": (reference, ref_fields),
    })

    print(f"{len(hospitals)} hospital listings, {len(specialties)} hospital-specialty rows, "
          f"{len({h['state_clean'] for h in hospitals})} states, {len(ref_counts)} distinct specialties")
    if unknown:
        print("WARNING: unrecognised specialties (add them to SPECIALTIES or SPECIALTY_ALIASES):")
        for k, v in unknown.most_common():
            print(f"  {v:4d}  {k}")
    print(f"Wrote outputs to {args.out}")


if __name__ == "__main__":
    main()
