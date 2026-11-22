"""
Build a dataset of LaQshya-certified labour rooms and maternity operating theatres.

LaQshya ("Labour Room Quality Improvement Initiative") is MoHFW's quality certification for
labour rooms and maternity OTs in public health facilities, run by NHSRC. A certified
MATERNITY OT is direct government evidence that a facility performs caesarean sections;
a certified LABOUR ROOM is evidence of facility-based delivery care.

Source: NHSRC Quality & Patient Safety portal, "LaQshya Master data" PDF dated 08-04-2026
  https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf
One download. The table is read with pdfplumber, which follows the PDF's grid lines; this is
needed because "Certified" and "Conditionality" are two separate Yes/blank columns and only
the cell position tells them apart.

Outputs (default: datasets/external/laqshya_bronze/):
  raw/LaQshya_Master_data-08-04-2026.pdf       the source PDF (git-ignored)
  laqshya_certifications_bronze.csv            one row per certification (facility x department)
  laqshya_facilities_bronze.csv                one row per facility, certifications rolled up

Usage:
  python scrapers/nhsrc_laqshya.py              # download and build
  python scrapers/nhsrc_laqshya.py --pdf FILE   # build from a saved copy
Needs: requests, pdfplumber
"""

import argparse
import csv
import datetime as dt
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber
import requests

SOURCE_URL = "https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf"
LIST_DATE = "2026-04-08"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "datasets" / "external" / "laqshya_bronze"

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
    "orissa": "Odisha", "uttaranchal": "Uttarakhand", "pondicherry": "Puducherry", "chattisgarh": "Chhattisgarh",
    "jammukashmir": "Jammu and Kashmir", "andamannicobar": "Andaman and Nicobar Islands",
    "andamanandnicobar": "Andaman and Nicobar Islands", "dadraandnagarhaveli": "Dadra and Nagar Haveli and Daman and Diu",
    "damananddiu": "Dadra and Nagar Haveli and Daman and Diu", "dnhanddd": "Dadra and Nagar Haveli and Daman and Diu",
    "dnhdd": "Dadra and Nagar Haveli and Daman and Diu", "nctofdelhi": "Delhi", "newdelhi": "Delhi",
    "arunachalprades": "Arunachal Pradesh", "dnhdandd": "Dadra and Nagar Haveli and Daman and Diu",
})

# Rows where a long facility name overflowed into the Department cell in the PDF, so the two
# texts' letters interleave (e.g. "TraiLnaibnog uCre Rnotroem" = "Training Centre" + "Labour
# Room"). The department is recovered by the subsequence rule in department(); the full name
# is restored here (letter counts checked by hand). Flagged with name_repaired = 1.
NAME_REPAIRS = {
    92: "Bakin Pertin General Hospital & Training Centre",
    93: "Bakin Pertin General Hospital & Training Centre",
    414: "Rukshamaniben General Hospital Khokhra",
    # Name cells that received the overflow of the district / type columns
    1346: "DH Nawanshahr", 1347: "DH Nawanshahr",                     # "aDgaHr" = DH + "agar"
    1950: "District Combined Hospital GB Nagar",                      # stray "r"
    1951: "District Combined Hospital GB Nagar",
    2158: "CH Barwah", 2167: "CH Barwah",                              # "eC)H" = CH + "e)"
}

# Districts the generic overflow repair leaves slightly off
DISTRICT_FIXES = {
    "Sahid Bhagat Singh n": "Shaheed Bhagat Singh Nagar",
    "Gautam Buddha naga": "Gautam Buddha Nagar",
    "Pathanamthittta": "Pathanamthitta",
    "West Nimar (Khargon": "West Nimar (Khargone)",
}

TYPE_CODES = ["SDH", "CHC", "PHC", "DH", "MC"]  # longest first


def split_type_cell(cell):
    """
    The Type cell often holds a type code interleaved with the cut-off end of the district
    name, e.g. "PDUHRAM" = "DH" + "puram", "NMACS" = "MC" + "nas". Find the longest known code
    that is a subsequence, matching it as LATE as possible (the district overflow comes first),
    and return (code, leftover_text). Returns (cell, "") if the cell is already a clean code.
    """
    c = ws(cell).upper()
    if c in TYPE_CODES or not c:
        return c, ""
    for code in TYPE_CODES:
        idx, pos = [], len(c)
        for ch in reversed(code):
            pos = c.rfind(ch, 0, pos)
            if pos < 0:
                break
            idx.append(pos)
        else:
            keep = set(idx)
            return code, "".join(ch for i, ch in enumerate(cell.strip()) if i not in keep)
    return c, ""

FACILITY_TYPES = {
    "MC": "Medical college hospital", "DH": "District hospital", "SDH": "Sub-district hospital",
    "CHC": "Community health centre", "PHC": "Primary health centre", "AH": "Area hospital",
    "DWH": "District women's hospital", "WH": "Women's hospital", "MCH": "Maternal and child health wing",
}

DEPARTMENT_SERVICES = {
    "Maternity OT": "obstetrics;emergency_c_section",
    "Labour Room": "obstetrics;normal_delivery",
    "Not stated": "obstetrics",
}


def ws(s):
    return re.sub(r"\s+", " ", str(s or "").replace("\x00", "")).strip()


def name_norm(s):
    return ws(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower().replace("&", " and ")))


def parse_date(s):
    s = ws(s)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _is_subsequence(needle, hay):
    it = iter(hay)
    return all(ch in it for ch in needle)


def department(s):
    s = ws(s).lower()
    if not s:
        return "Not stated"
    letters = re.sub(r"[^a-z]", "", s)
    if letters not in ("labourroom", "maternityot"):  # overflowed / interleaved cell
        if _is_subsequence("maternityot", letters):
            return "Maternity OT"
        if _is_subsequence("labourroom", letters):
            return "Labour Room"
    if "ot" in s.split() or "maternity" in s or "operation" in s:
        return "Maternity OT"
    if "labour" in s or "labor" in s or s == "lr":
        return "Labour Room"
    return ws(s).title()


def extract_rows(pdf_path):
    rows, header = [], None
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables():
                for cells in table:
                    cells = [ws(c) for c in cells]
                    if not cells or not cells[0]:
                        continue
                    if cells[0].upper().startswith("S.NO"):
                        header = cells
                        continue
                    if not re.fullmatch(r"\d+", cells[0]):
                        continue
                    if len(cells) != 10:
                        print(f"WARNING: page {pno}: row {cells[0]} has {len(cells)} cells: {cells}", file=sys.stderr)
                        continue
                    rows.append({"page": pno, "cells": cells})
    return rows, header


def build(rows, build_date):
    certs = []
    for r in rows:
        sno, state, district, ftype, fname, dept, certified, conditional, result, validity = r["cells"]
        # Two columns that pdfplumber can occasionally merge with their neighbours: split
        # "VishakhapatnamSDH"-style district+type cells if the type cell is empty.
        if not ftype:
            m = re.match(r"^(.*?)(MC|DH|SDH|CHC|PHC)$", district)
            if m:
                district, ftype = m.group(1).strip(), m.group(2)
        res_d, val_d = parse_date(result), parse_date(validity)
        status = ("conditional" if conditional.lower().startswith("y")
                  else "certified" if certified.lower().startswith("y") else "unknown")
        dep = department(dept)
        repaired = int(sno) in NAME_REPAIRS
        if repaired:
            fname = NAME_REPAIRS[int(sno)]
        st = STATE_LOOKUP.get(_key(state), state)
        # Overflow repairs: the last letter(s) of a truncated state land at the start of the
        # district ("hEast Siang"); the end of a truncated district lands in the type cell.
        district_raw, type_raw = district, ftype
        district = re.sub(r"^[a-z]+(?=[A-Z])", "", district)
        code, leftover = split_type_cell(ftype)
        if leftover:
            district = district + leftover.lower()
        district = DISTRICT_FIXES.get(ws(district), district)
        cell_repaired = int(district != district_raw or code != ws(type_raw).upper())
        certs.append({
            "cert_row_id": f"laq_{int(sno):04d}",
            "sno_in_source": int(sno),
            "state_listed": state,
            "state_clean": st,
            "district": ws(district),
            "district_raw": district_raw,
            "facility_type_code": code,
            "facility_type_raw": type_raw,
            "facility_type": FACILITY_TYPES.get(code, code or None),
            "cells_repaired": cell_repaired,
            "facility_name_raw": fname,
            "name_norm": name_norm(fname),
            "name_repaired": int(repaired),
            "department_raw": dept,
            "department": dep,
            "certification_status": status,
            "result_date": res_d.isoformat() if res_d else None,
            "validity_date": val_d.isoformat() if val_d else None,
            "valid_on_list_date": int(bool(val_d and val_d.isoformat() >= LIST_DATE)),
            "valid_on_build_date": int(bool(val_d and val_d >= build_date)),
            "related_services": DEPARTMENT_SERVICES.get(dep, "obstetrics"),
            "source_page": r["page"],
            "source_url": SOURCE_URL,
            "list_date": LIST_DATE,
            "build_date": build_date.isoformat(),
        })

    # Facility roll-up: same state + normalised name + first 5 letters of the district
    # (district names are truncated inconsistently in the PDF, e.g. "Thiruvanantha")
    groups = defaultdict(list)
    for c in certs:
        groups[(c["state_clean"], _key(c["district"])[:5], c["name_norm"])].append(c)
    facilities = []
    for (st, dk, nn), cs in groups.items():
        first = max(cs, key=lambda c: len(c["district"]))  # least-truncated district
        fid = "laqf_" + hashlib.sha1(f"{st}|{dk}|{nn}".encode()).hexdigest()[:10]
        for c in cs:
            c["laqshya_facility_id"] = fid

        def best(dep):
            xs = [c for c in cs if c["department"] == dep]
            return max((c["validity_date"] or "" for c in xs), default="") or None

        mot, lr, ns = best("Maternity OT"), best("Labour Room"), best("Not stated")
        today = build_date.isoformat()
        facilities.append({
            "laqshya_facility_id": fid,
            "facility_name_raw": first["facility_name_raw"],
            "name_norm": nn,
            "state_clean": st,
            "district": first["district"],
            "facility_type_code": first["facility_type_code"],
            "facility_type": first["facility_type"],
            "has_maternity_ot_cert": int(mot is not None),
            "maternity_ot_valid_until": mot,
            "maternity_ot_valid_now": int(bool(mot and mot >= today)),
            "has_labour_room_cert": int(lr is not None),
            "labour_room_valid_until": lr,
            "labour_room_valid_now": int(bool(lr and lr >= today)),
            "has_dept_not_stated_cert": int(ns is not None),
            "any_conditional": int(any(c["certification_status"] == "conditional" for c in cs)),
            "n_certifications": len(cs),
            "related_services": ";".join(sorted({s for c in cs for s in c["related_services"].split(";")})),
            "cert_row_ids": ";".join(c["cert_row_id"] for c in cs),
            "source_url": SOURCE_URL,
            "list_date": LIST_DATE,
            "build_date": today,
        })
    facilities.sort(key=lambda f: (f["state_clean"] or "", f["district"] or "", f["name_norm"]))
    return certs, facilities


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pdf = args.pdf
    if not pdf:
        raw = args.out / "raw"
        raw.mkdir(exist_ok=True)
        pdf = raw / "LaQshya_Master_data-08-04-2026.pdf"
        r = requests.get(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; datathon-research/1.0)"},
                         timeout=120)
        r.raise_for_status()
        pdf.write_bytes(r.content)
        print(f"Downloaded {SOURCE_URL}")

    rows, _ = extract_rows(pdf)
    snos = [int(r["cells"][0]) for r in rows]
    problems = []
    missing = sorted(set(range(1, max(snos) + 1)) - set(snos))
    dups = [k for k, v in Counter(snos).items() if v > 1]
    if missing:
        problems.append(f"missing serial numbers: {missing[:30]}{'...' if len(missing) > 30 else ''}")
    if dups:
        problems.append(f"duplicate serial numbers: {dups[:30]}")

    certs, facilities = build(rows, dt.date.today())
    bad_dates = [c["sno_in_source"] for c in certs if not c["validity_date"] or not c["result_date"]]
    bad_states = sorted({c["state_listed"] for c in certs if c["state_clean"] not in STATES})
    if bad_dates:
        problems.append(f"rows with unparsed dates: {bad_dates[:30]}")
    if bad_states:
        problems.append(f"unrecognised states: {bad_states}")
    if problems:
        print("CHECK:\n  " + "\n  ".join(problems), file=sys.stderr)

    write_csv(args.out / "laqshya_certifications_bronze.csv", certs)
    write_csv(args.out / "laqshya_facilities_bronze.csv", facilities)

    dep = Counter(c["department"] for c in certs)
    st = Counter(c["certification_status"] for c in certs)
    print(f"{len(certs)} certifications (serials 1-{max(snos)}), {dict(dep)}, status {dict(st)}")
    print(f"{len(facilities)} facilities in {len({f['state_clean'] for f in facilities})} states; "
          f"{sum(f['has_maternity_ot_cert'] for f in facilities)} with a maternity OT certification "
          f"({sum(f['maternity_ot_valid_now'] for f in facilities)} still valid today)")
    print(f"Wrote outputs to {args.out}")


if __name__ == "__main__":
    main()
