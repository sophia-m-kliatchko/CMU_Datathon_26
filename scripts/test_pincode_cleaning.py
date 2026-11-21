"""
Local tests for notebooks/common/coordinate_parsing.py, plus a dry run of notebook 04's coordinate
cleaning and PIN centroid logic on data/raw/india_post_pincode_directory.csv (no Spark needed).

Usage:  python scripts/test_pincode_cleaning.py
"""
import csv
import importlib.util
import math
import os
import statistics
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("coordinate_parsing",
                                              os.path.join(ROOT, "notebooks", "common", "coordinate_parsing.py"))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

CASES = [
    ("19.3638689", (19.3638689, "plain")),
    ("18.856818°", (18.856818, "symbols_removed")),
    ("28.430354° N", (28.430354, "symbols_removed")),
    ("25.43 N", (25.43, "symbols_removed")),
    ("17°57'17.7", (17.954917, "dms_converted")),
    ("28.4 32628", (28.432628, "space_removed")),
    ("NA", (None, "missing")),
    ("abc", (None, "unparseable")),
]
PAIRS = [
    (("79.0", "17.0"), ("swapped_fixed", 17.0, 79.0)),
    (("28.4", "77.1"), ("ok", 28.4, 77.1)),
    (("0", "0"), ("zero", None, None)),
    (("39.5698", "120.1"), ("out_of_range", None, None)),
]


def haversine_km(a, b, c, d):
    p = math.pi / 180
    h = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))


def main():
    fails = 0
    for text, (val, how) in CASES:
        got = cp.parse_coordinate(text)
        ok = got[1] == how and (val is None and got[0] is None or got[0] is not None and abs(got[0] - val) < 1e-6)
        fails += not ok
        print("PASS" if ok else "FAIL", repr(text), "->", got)
    for (la, lo), (status, elat, elon) in PAIRS:
        r = cp.fix_pair(la, lo)
        ok = (r["coord_status"], r["latitude"], r["longitude"]) == (status, elat, elon)
        fails += not ok
        print("PASS" if ok else "FAIL", (la, lo), "->", r["coord_status"], r["latitude"], r["longitude"])

    path = os.path.join(ROOT, "data", "raw", "india_post_pincode_directory.csv")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    status, hows = Counter(), Counter()
    by_pin = defaultdict(list)
    for r in rows:
        x = cp.fix_pair(r["latitude"], r["longitude"])
        status[x["coord_status"]] += 1
        hows[x["lat_how"]] += 1
        if x["latitude"] is not None:
            by_pin[r["pincode"]].append((x["latitude"], x["longitude"]))
    n = len(rows)
    print(f"\n{n:,} offices. coord_status:", {k: f"{v:,} ({v / n:.1%})" for k, v in status.most_common()})
    print("latitude read as:", dict(hows.most_common()))

    far, spreads = 0, []
    for pin, pts in by_pin.items():
        mlat, mlon = statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)
        d = [haversine_km(mlat, mlon, a, b) for a, b in pts]
        far += sum(x > 50 for x in d)
        spreads.append(max(d))
    pins = len({r["pincode"] for r in rows})
    print(f"PINs: {pins:,}; with a centroid: {len(by_pin):,} ({len(by_pin) / pins:.1%})")
    print(f"offices > 50 km from their PIN's median point (flagged, left out of the centroid): {far:,}")
    print(f"PIN max spread (km): median {statistics.median(spreads):.1f}, 90th pct {sorted(spreads)[int(.9 * len(spreads))]:.1f}")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
