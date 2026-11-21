"""
Dry run (no Spark) of the coordinate/address cross-checks in notebooks 01, 02 and 04, on the raw CSVs:
  * PIN offices: coordinates more than 50 km from their PIN's median point are set to NULL (notebook 04)
  * Facilities: coordinates must be within 25 km (+ the PIN's spread) of the PIN centre and inside the
    state's padded box, else set to NULL (notebook 01)
  * NQAS: district must exist in the state per the India Post directory (notebook 02, flag only)
Numbers are estimates: the notebooks also merge duplicate IDs and standardize more carefully.

Usage:  python scripts/dryrun_coordinate_checks.py
"""
import csv
import importlib.util
import math
import os
import re
import statistics
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


cp = load("cp", "notebooks/common/coordinate_parsing.py")
ap = load("ap", "notebooks/common/address_parsing.py")

PIN_MATCH_KM, PAD, FAR_KM = 25.0, 0.25, 50.0
STATES = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
          "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
          "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
          "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
          "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"]
KEY = {re.sub(r"[^a-z]", "", s.lower()): s for s in STATES}
KEY.update({"orissa": "Odisha", "pondicherry": "Puducherry", "newdelhi": "Delhi", "nctofdelhi": "Delhi",
            "uttaranchal": "Uttarakhand", "jammukashmir": "Jammu and Kashmir"})


def state_of(text):
    k = re.sub(r"[^a-z]", "", (text or "").lower().replace("&", " and "))
    if k in KEY:
        return KEY[k]
    for kk in sorted((x for x in KEY if len(x) >= 5), key=len, reverse=True):
        if kk in k:
            return KEY[kk]
    return None


def km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))


# ---- PIN directory (notebook 04) ----
offices = []
with open(os.path.join(ROOT, "data/raw/india_post_pincode_directory.csv"), encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        x = cp.fix_pair(r["latitude"], r["longitude"])
        offices.append((r["pincode"], x["latitude"], x["longitude"], state_of(r["statename"]),
                        re.sub(r"[^a-z0-9]", "", (r["district"] or "").lower())))
by_pin = defaultdict(list)
for pin, la, lo, st, dk in offices:
    if la is not None:
        by_pin[pin].append((la, lo))
med = {p: (statistics.median(a for a, _ in v), statistics.median(b for _, b in v)) for p, v in by_pin.items()}
kept = defaultdict(list)
nulled_offices = 0
for pin, la, lo, st, dk in offices:
    if la is None:
        continue
    if km(la, lo, *med[pin]) > FAR_KM:
        nulled_offices += 1
    else:
        kept[pin].append((la, lo, st))
cent = {}
for pin, v in kept.items():
    c = (statistics.median(a for a, _, _ in v), statistics.median(b for _, b, _ in v))
    cent[pin] = (c, max(km(a, b, *c) for a, b, _ in v))
pin_states = defaultdict(set)
box = {}
for pin, la, lo, st, dk in offices:
    if st:
        pin_states[pin].add(st)
for pin, v in kept.items():
    for la, lo, st in v:
        if st:
            b = box.setdefault(st, [la, la, lo, lo])
            b[0], b[1], b[2], b[3] = min(b[0], la), max(b[1], la), min(b[2], lo), max(b[3], lo)
district_pairs = {(st, dk) for _, _, _, st, dk in offices if st and dk}
print(f"PIN offices: {len(offices):,}; coordinates set to NULL for being > {FAR_KM:.0f} km from their PIN: {nulled_offices:,}")
print(f"PINs with a centroid: {len(cent):,}")

# ---- Facilities (notebook 01) ----
csv.field_size_limit(10 ** 9)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
res = Counter()
examples = defaultdict(list)
with open(os.path.join(ROOT, "data/raw/facilities.csv"), encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f, escapechar="\\", doublequote=False):
        if not UUID.match(r["unique_id"].strip()):
            continue
        x = cp.fix_pair(r["latitude"], r["longitude"])
        if x["latitude"] is None:
            res["no usable coordinates"] += 1
            continue
        zip_txt = re.sub(r"(?<=\d)[\s-](?=\d)", "", r["address_zipOrPostcode"] or "")
        m = re.search(r"(?<!\d)([1-9]\d{5})(?!\d)", zip_txt)
        pin = m.group(1) if m else ap.parse_address(r["address_line1"], r["address_line2"], r["address_line3"],
                                                    r["address_city"], r["address_stateOrRegion"], "")["pin_from_text"]
        st = state_of(r["address_stateOrRegion"])
        la, lo = x["latitude"], x["longitude"]
        if pin in cent:
            (cla, clo), spread = cent[pin]
            d = km(la, lo, cla, clo)
            if d > PIN_MATCH_KM + spread:
                res["NULLED: too far from PIN centre"] += 1
                examples["pin"].append(f'{r["name"][:40]} | PIN {pin} | {d:.0f} km away')
                continue
        if st in box:
            b = box[st]
            if not (b[0] - PAD <= la <= b[1] + PAD and b[2] - PAD <= lo <= b[3] + PAD):
                res["NULLED: outside state"] += 1
                examples["state"].append(f'{r["name"][:40]} | {st} | ({la:.3f}, {lo:.3f})')
                continue
        res["kept"] += 1
        if pin and pin not in cent and pin not in pin_states:
            res["  (kept, but PIN not in directory)"] += 1
        if pin and st and pin_states.get(pin) and st not in pin_states[pin]:
            res["  (kept, but state not served by PIN)"] += 1
print("\nFacilities with valid IDs, coordinate check:")
for k, v in res.most_common():
    print(f"  {k}: {v:,}")
for k in ["pin", "state"]:
    print(f"  examples ({k}):", examples[k][:4])

# ---- NQAS (notebook 02) ----
rows = list(csv.DictReader(open(os.path.join(ROOT, "data/external/nqas_certified_facilities.csv"), encoding="utf-8")))
ok = sum((state_of(r["state"]), re.sub(r"[^a-z0-9]", "", r["district"].lower())) in district_pairs for r in rows)
print(f"\nNQAS listings whose district is found in that state (India Post): {ok:,} / {len(rows):,} "
      f"-> {len(rows) - ok:,} flagged DISTRICT_NOT_IN_STATE")
