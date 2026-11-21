"""
Convert a Kayakalp award-winners PDF (MoHFW / NHSRC) into a clean CSV for upload to Databricks.

Expected PDF layout: one table per page with the columns
    S.No. | Incentive | Type of Health Facility | Name of the facility | District | State
(as in "KAYAKALP WINNER FACILITIES 21-22.pdf"). The PDF may be locked against editing;
pdfplumber can still read it as long as it opens without a password.

Output columns:
    s_no, financial_year, award_raw, award_rank, award_category, facility_type,
    facility_name, district, state, source_file, source_page

Requires:  python -m pip install pdfplumber

Usage:
    python scripts/kayakalp_pdf_to_csv.py "C:/path/KAYAKALP WINNER FACILITIES 21-22.pdf"
    python scripts/kayakalp_pdf_to_csv.py in.pdf --out data/external/kayakalp_2021_22.csv --fy 2021-22
"""
import argparse
import csv
import os
import re
import sys

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is missing: run  python -m pip install pdfplumber")

FIELDS = ["s_no", "financial_year", "award_raw", "award_rank", "award_category", "facility_type",
          "facility_name", "district", "state", "state_raw", "district_repaired", "source_file", "source_page"]

STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
STATE_ALIASES = {"dnh&dd": "Dadra and Nagar Haveli and Daman and Diu", "dnhdd": "Dadra and Nagar Haveli and Daman and Diu",
                 "orissa": "Odisha", "pondicherry": "Puducherry", "j&k": "Jammu and Kashmir"}


def _key(s):
    return re.sub(r"[^a-z&]", "", s.lower().replace(" and ", "&"))


STATE_KEYS = {_key(s): s for s in STATES}
STATE_KEYS.update(STATE_ALIASES)


def subsequence_remainder(text, target):
    """If target's letters appear in order inside text (ignoring case and spaces), return the leftover characters."""
    t = [c for c in target.lower() if c != " "]
    i, leftover = 0, []
    for ch in text:
        if i < len(t) and ch.lower() == t[i]:
            i += 1
        elif ch != " ":
            leftover.append(ch)
    return "".join(leftover) if i == len(t) else None


def fix_state(state_raw, district):
    """
    Return (state, district, repaired). Long district names in this PDF spill into the State column,
    and their last letters get interleaved with the state's letters
    (e.g. district 'Porband' + state 'AGrUJARAT' -> 'Porbandar' + 'Gujarat').
    The state's letters stay in order, so we find which state fits and move the leftover letters back to the district.
    """
    k = _key(state_raw)
    if k in STATE_KEYS:
        return STATE_KEYS[k], district, False
    best = None
    for s in STATES:
        rem = subsequence_remainder(state_raw, s)
        if rem is not None and (best is None or len(s) > len(best[0])):
            best = (s, rem)
    if best:
        state, rem = best
        return state, (district + rem.lower()).strip(), True
    return state_raw.title(), district, False


def clean(cell):
    """Join wrapped lines and collapse whitespace."""
    if cell is None:
        return ""
    s = " ".join(str(cell).split())
    return re.sub(r"\s*-\s*$", "-", s)


def split_award(raw):
    """'JOINT WINNER- Kayakalp' -> ('Joint Winner', 'Kayakalp'); 'WINNER-Eco friendly' -> ('Winner', 'Eco-friendly')."""
    s = raw.lower()
    if "eco" in s:
        category = "Eco-friendly"
    else:
        category = "Kayakalp"  # plain "Winner" rows (PHC, UPHC, HWC) are the main Kayakalp award
    for pattern, label in [
        (r"\bbest\b", "Best"),
        (r"joint\s+runner", "Joint Runner Up"),
        (r"runner", "Runner Up"),
        (r"joint\s+winner", "Joint Winner"),
        (r"commend", "Commendation"),
        (r"winner", "Winner"),
    ]:
        if re.search(pattern, s):
            return label, category
    return raw, category


def fy_from_filename(path):
    m = re.search(r"(20)?(\d{2})\s*[-_]\s*(\d{2})(?!\d)", os.path.basename(path))
    return f"20{m.group(2)}-{m.group(3)}" if m else ""


def parse(pdf_path, fy):
    rows, warnings = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for raw in table:
                    cells = [clean(c) for c in raw]
                    if len(cells) < 6:
                        cells += [""] * (6 - len(cells))
                    s_no = cells[0]
                    if s_no.isdigit():
                        rows.append({
                            "s_no": int(s_no), "financial_year": fy, "award_raw": cells[1],
                            "facility_type": cells[2], "facility_name": cells[3],
                            "district": cells[4], "state": cells[5],
                            "source_file": os.path.basename(pdf_path), "source_page": page_no,
                        })
                    elif any(cells[1:]) and not s_no and rows and not cells[0].lower().startswith("s.no"):
                        # Continuation of a row that wrapped onto a new line or page: append the text
                        prev = rows[-1]
                        for key, val in zip(["award_raw", "facility_type", "facility_name", "district", "state"], cells[1:6]):
                            if val:
                                prev[key] = f"{prev[key]} {val}".strip()
                        warnings.append(f"page {page_no}: merged a continuation line into S.No {prev['s_no']}")
    for r in rows:
        r["award_rank"], r["award_category"] = split_award(r["award_raw"])
        r["state_raw"] = r["state"]
        r["state"], district, r["district_repaired"] = fix_state(r["state"], r["district"])
        r["district"] = district.title() if district.isupper() else district
        if r["district_repaired"]:
            warnings.append(f"S.No {r['s_no']}: state '{r['state_raw']}' -> '{r['state']}', district -> '{r['district']}'")
        elif r["state"] not in STATES:
            warnings.append(f"S.No {r['s_no']}: unrecognized state '{r['state_raw']}'")
    return rows, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--out", help="output CSV (default: data/external/kayakalp_<fy>.csv)")
    ap.add_argument("--fy", help="financial year label, e.g. 2021-22 (default: read from the file name)")
    args = ap.parse_args()

    fy = args.fy or fy_from_filename(args.pdf)
    out = args.out or os.path.join("data", "external", f"kayakalp_{(fy or 'unknown').replace('-', '_')}.csv")
    rows, warnings = parse(args.pdf, fy)

    # Sanity checks: S.No should run 1..N with no gaps or repeats
    nums = [r["s_no"] for r in rows]
    missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
    repeats = sorted({n for n in nums if nums.count(n) > 1})
    for w in warnings:
        print("note:", w)
    if missing:
        print(f"WARNING: S.No missing: {missing[:20]}{' ...' if len(missing) > 20 else ''}")
    if repeats:
        print(f"WARNING: S.No repeated: {repeats[:20]}")
    blank = [r["s_no"] for r in rows if not (r["facility_name"] and r["state"])]
    if blank:
        print(f"WARNING: rows with no facility name or state: {blank[:20]}")

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["s_no"]))
    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
