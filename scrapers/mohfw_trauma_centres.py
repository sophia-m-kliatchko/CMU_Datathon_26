"""
Build a dataset of the 196 Trauma Care Facilities (TCFs) sanctioned under MoHFW's
National Programme for Prevention & Management of Trauma and Burn Injuries (NPPMT&BI).

Source: Rajya Sabha Unstarred Question No. 2048, answered 10 March 2026,
"Establishment of Trauma Centres near National Highways", Annexure-I.
  https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars
The PDF is a public Parliament answer. One download; the table is read from the PDF text.

What it says: 196 TCFs were SANCTIONED in government hospitals / medical colleges during the
11th (2007-12) and 12th (2012-17) Five Year Plans, each designated Level I, II or III.
The answer does NOT confirm which are functional today, or their staff/beds.

Output (default: datasets/external/trauma_care_bronze/):
  raw/AU2048_2026-03-10.pdf                    the source PDF (git-ignored)
  trauma_care_facilities_bronze.csv            one row per facility

Usage:
  python scrapers/mohfw_trauma_centres.py              # download the PDF and build
  python scrapers/mohfw_trauma_centres.py --pdf FILE   # build from a saved copy
Needs: requests, pypdf
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import requests
from pypdf import PdfReader

SOURCE_URL = "https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars"
SOURCE_DOC = "Rajya Sabha Unstarred Q. 2048 (10 Mar 2026), Annexure-I"
ANSWER_DATE = "2026-03-10"
EXPECTED_ROWS = 196
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "trauma_care_bronze"

# State labels exactly as printed -> official names used in silver_facilities.state_clean
STATE_LABELS = {
    "Andhra Pradesh": "Andhra Pradesh", "Andaman & Nikobar": "Andaman and Nicobar Islands",
    "Arunachal Pradesh": "Arunachal Pradesh", "Assam": "Assam", "Bihar": "Bihar",
    "Chhattisgarh": "Chhattisgarh", "Dadar & Nagar Haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "Goa": "Goa", "Gujarat": "Gujarat", "Haryana": "Haryana", "Himachal Pradesh": "Himachal Pradesh",
    "Jammu and Kashmir": "Jammu and Kashmir", "Jharkhand": "Jharkhand", "Karnataka": "Karnataka",
    "Kerala": "Kerala", "Ladakh": "Ladakh", "Madhya Pradesh": "Madhya Pradesh", "Maharashtra": "Maharashtra",
    "Manipur": "Manipur", "Meghalaya": "Meghalaya", "Mizoram": "Mizoram", "Nagaland": "Nagaland",
    "Odisha": "Odisha", "Punjab": "Punjab", "Rajasthan": "Rajasthan", "Sikkim": "Sikkim",
    "Tamil Nadu": "Tamil Nadu", "Telangana": "Telangana", "Tripura": "Tripura",
    "Uttar Pradesh": "Uttar Pradesh", "Uttarakhand": "Uttarakhand", "West Bengal": "West Bengal",
}

# Programme levels. General descriptions of the NPPMT&BI tiers (not from this PDF).
LEVEL_INFO = {
    1: "Level I: highest tier, usually a medical college; definitive care for all injuries",
    2: "Level II: major hospital; emergency surgery, orthopaedics and anaesthesia for trauma",
    3: "Level III: district / sub-district hospital; stabilise the patient, basic surgery, refer on",
}

# Where each facility is. Derived by hand from the facility name (the PDF has no address
# column). Spelling corrected to the current official name; the PDF's own text stays in
# facility_name_raw. Keyed by S.No.
PLACE = {
    1: "Kurnool", 2: "Penukonda", 3: "Tekkali", 4: "Srikakulam", 5: "Visakhapatnam", 6: "Tuni",
    7: "Rajahmundry", 8: "Eluru", 9: "Guntur", 10: "Ongole", 11: "Nellore", 12: "Naidupeta",
    13: "Anantapur", 14: "Kakinada", 15: "Mayabunder", 16: "Bomdila", 17: "Roing", 18: "Tezu",
    19: "Khonsa", 20: "Silchar", 21: "Haflong", 22: "Diphu", 23: "Nagaon", 24: "Guwahati",
    25: "Nalbari", 26: "Bongaigaon", 27: "Kishanganj", 28: "Purnia", 29: "Madhepura",
    30: "Darbhanga", 31: "Muzaffarpur", 32: "Gopalganj", 33: "Jhanjharpur", 34: "Sasaram",
    35: "Gaya", 36: "Raipur", 37: "Bilaspur", 38: "Kanker", 39: "Raigarh", 40: "Jagdalpur",
    41: "Ambikapur", 42: "Khanvel", 43: "Goa (Bambolim)", 44: "Palanpur", 45: "Radhanpur",
    46: "Morbi", 47: "Rajkot", 48: "Jetpur", 49: "Porbandar", 50: "Valsad", 51: "Surat",
    52: "Bharuch", 53: "Vadodara", 54: "Himmatnagar", 55: "Bhachau", 56: "Jamnagar",
    57: "Bhavnagar", 58: "Veraval", 59: "Ambala", 60: "Rewari", 61: "Panipat", 62: "Chamba",
    63: "Hamirpur", 64: "Tanda (Kangra)", 65: "Mandi", 66: "Rampur (Shimla)", 67: "Shimla",
    68: "Anantnag", 69: "Ramban", 70: "Udhampur", 71: "Kupwara", 72: "Dhanbad", 73: "Koderma",
    74: "Daltonganj (Medininagar)", 75: "Gumla", 76: "Tumakuru", 77: "Sira", 78: "Chitradurga",
    79: "Davanagere", 80: "Hubballi", 81: "Haveri", 82: "Belagavi", 83: "Chikkaballapur",
    84: "Alappuzha", 85: "Ernakulam", 86: "Kannur", 87: "Palakkad", 88: "Kozhikode",
    89: "Thiruvananthapuram", 90: "Leh", 91: "Shivpuri", 92: "Gwalior", 93: "Narsinghpur",
    94: "Sagar", 95: "Seoni", 96: "Kolhapur", 97: "Satara", 98: "Pune", 99: "Vashi (Navi Mumbai)",
    100: "Dahanu", 101: "Hinganghat", 102: "Imphal", 103: "Churachandpur", 104: "Senapati",
    105: "Bishnupur", 106: "Thoubal", 107: "Chandel", 108: "Tura", 109: "Nongpoh", 110: "Shillong",
    111: "Aizawl", 112: "Lawngtlai", 113: "Siaha", 114: "Lunglei", 115: "Kolasib", 116: "Champhai",
    117: "Serchhip", 118: "Tuensang", 119: "Kiphire", 120: "Mon", 121: "Kohima", 122: "Dimapur",
    123: "Balasore", 124: "Bhadrak", 125: "Cuttack", 126: "Khurda", 127: "Berhampur", 128: "Puri",
    129: "Pathankot", 130: "Jalandhar", 131: "Khanna", 132: "Fazilka", 133: "Ferozepur",
    134: "Baran", 135: "Kota", 136: "Chittorgarh", 137: "Udaipur", 138: "Bhilwara", 139: "Ajmer",
    140: "Jaipur", 141: "Kotputli", 142: "Sirohi", 143: "Dungarpur", 144: "Namchi", 145: "Singtam",
    146: "Mangan", 147: "Gangtok", 148: "Chennai", 149: "Vellore", 150: "Krishnagiri", 151: "Karur",
    152: "Dindigul", 153: "Madurai", 154: "Kovilpatti", 155: "Tirunelveli",
    156: "Kanyakumari (Asaripallam)", 157: "Kallakurichi", 158: "Kumbakonam", 159: "Chengalpattu",
    160: "Coimbatore", 161: "Adilabad", 162: "Kamareddy", 163: "Mahabubnagar", 164: "Nizamabad",
    165: "Dharmanagar", 166: "Santirbazar", 167: "Udaipur (Gomati)", 168: "Agartala",
    169: "Ambassa (Dhalai)", 170: "Gorakhpur", 171: "Ayodhya (Faizabad)", 172: "Lucknow", 173: "Kanpur",
    174: "Orai (Jalaun)", 175: "Jhansi", 176: "Basti", 177: "Agra", 178: "Etawah", 179: "Fatehpur",
    180: "Prayagraj (Allahabad)", 181: "Meerut", 182: "Lalitpur", 183: "New Tehri", 184: "Haldwani",
    185: "Roorkee", 186: "Dehradun", 187: "Siliguri", 188: "Islampur", 189: "Asansol",
    190: "Bardhaman", 191: "Kharagpur", 192: "Alipurduar", 193: "Berhampore (Murshidabad)",
    194: "Ranaghat", 195: "Diamond Harbour", 196: "Raiganj",
}

FACILITY_TYPES = [  # first match wins
    ("medical_college", r"college|\bgmc\b|\bgmch\b|\bigmc\b|institute|inst\.|medical science"),
    ("district_hospital", r"district|dist\.?\b|\bdh\b|hqr|head ?quarters|sadar|naga hospital|stnm|s\.n\.m"),
    ("sub_district_or_taluk", r"sub.?district|sub.?divisional|\bsd\b|taluk|taluq|area hospital|community hospital"),
    ("chc_or_phc", r"\bchc\b|\bphc\b"),
    ("other_government_hospital", r"."),
]


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def name_norm(name):
    return ws(re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and ")))


def annexure_lines(pdf_path):
    reader = PdfReader(str(pdf_path))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    start = text.find("Annexure")
    if start < 0:
        sys.exit("Couldn't find 'Annexure' in the PDF text: the layout has changed.")
    lines = [ws(l) for l in text[start:].splitlines()]
    return [l for l in lines if l and not l.startswith(("Annexure", "S.", "No. Name of State"))]


def parse(lines):
    """Group lines into rows. A row starts with the next expected serial number."""
    rows, cur, expect = [], None, 1
    for line in lines:
        m = re.match(r"^(\d{1,3})\b\s*(.*)$", line)
        if m and int(m.group(1)) == expect:
            if cur:
                rows.append(cur)
            cur = {"sno": expect, "text": m.group(2)}
            expect += 1
        elif cur is not None:
            cur["text"] = ws(cur["text"] + " " + line)
    if cur:
        rows.append(cur)

    out, state_label = [], None
    labels = sorted(STATE_LABELS, key=len, reverse=True)
    for r in rows:
        text = r["text"]
        # A state label starts a row only when it is a NEW state. The state cell spans several
        # rows and is printed once, so "Chhattisgarh Institute of Medical Sciences" (under
        # Chhattisgarh) is a facility name, not a label.
        for lab in labels:
            if text.startswith(lab + " ") and lab != state_label:
                state_label, text = lab, text[len(lab):].strip()
                break
        m = re.search(r"\s*(III|II|I)\.?\s*$", text)
        if not m:
            sys.exit(f"Row {r['sno']}: no trauma level found in {text!r}")
        level = {"I": 1, "II": 2, "III": 3}[m.group(1)]
        name = ws(text[: m.start()]).rstrip(" ,.")
        out.append({"sno": r["sno"], "state_label": state_label, "name": name, "level": level})
    return out


def build(parsed):
    rows = []
    for p in parsed:
        ftype = next(t for t, pat in FACILITY_TYPES if re.search(pat, p["name"], re.I))
        rows.append({
            "tcf_id": f"tcf_{p['sno']:03d}",
            "sno_in_source": p["sno"],
            "facility_name_raw": p["name"],
            "name_norm": name_norm(p["name"]),
            "place": PLACE.get(p["sno"]),
            "state_listed": p["state_label"],
            "state_clean": STATE_LABELS.get(p["state_label"]),
            "trauma_level": p["level"],
            "trauma_level_label": ["", "Level I", "Level II", "Level III"][p["level"]],
            "trauma_level_meaning": LEVEL_INFO[p["level"]],
            "facility_type": ftype,
            "ownership": "Government",
            "programme": "NPPMT&BI (MoHFW), sanctioned 2007-2017",
            "status_in_source": "sanctioned",
            "related_services": "trauma;emergency",
            "source_doc": SOURCE_DOC,
            "source_url": SOURCE_URL,
            "as_of_date": ANSWER_DATE,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, help="use a saved copy of the PDF")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pdf = args.pdf
    if not pdf:
        raw = args.out / "raw"
        raw.mkdir(exist_ok=True)
        pdf = raw / f"AU2048_{ANSWER_DATE}.pdf"
        r = requests.get(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; datathon-research/1.0)"},
                         timeout=60)
        r.raise_for_status()
        pdf.write_bytes(r.content)
        print(f"Downloaded {SOURCE_URL} -> {pdf}")

    parsed = parse(annexure_lines(pdf))
    problems = []
    if len(parsed) != EXPECTED_ROWS:
        problems.append(f"expected {EXPECTED_ROWS} rows, got {len(parsed)}")
    problems += [f"row {p['sno']}: no state" for p in parsed if not p["state_label"]]
    problems += [f"row {p['sno']}: no place" for p in parsed if p["sno"] not in PLACE]
    if problems:
        sys.exit("Validation failed:\n  " + "\n  ".join(problems))

    rows = build(parsed)
    path = args.out / "trauma_care_facilities_bronze.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    print(f"{len(rows)} facilities, {len({r['state_clean'] for r in rows})} states/UTs; "
          f"levels {dict(sorted(Counter(r['trauma_level_label'] for r in rows).items()))}; "
          f"types {dict(Counter(r['facility_type'] for r in rows))}")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
