"""
Local tests for notebooks/common/address_parsing.py, plus a dry run of notebook 01's row-removal rules
on data/raw/facilities.csv (no Spark needed).

Usage:  python scripts/test_address_parsing.py            # unit tests + summary
        python scripts/test_address_parsing.py --sample 30  # also print 30 parsed addresses
"""
import argparse
import csv
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("address_parsing", os.path.join(ROOT, "notebooks", "common", "address_parsing.py"))
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

CASES = [
    # (line1, line2, line3, city, state, pin) -> expected (street, region, landmark)
    (("#422, 1st Floor, 27th Main Road, Next To Icici Bank, Hsr Layout, Sector-1", "27th Main Road, Next To Icici Bank",
      "Hsr Layout, Sector-1", "Bengaluru", "Karnataka", "560102"),
     ("#422, 1st Floor, 27th Main Road", "Hsr Layout, Sector-1", "Next To Icici Bank")),
    (("49, Supari Bag", "Bhusawal Road", "Sector 18", "Jamner", "Maharashtra", "424206"),
     ("49, Supari Bag, Bhusawal Road", "Sector 18", None)),
    (("No 84, 1st Avenue", "Ashok Nagar", "Royapettah", "Chennai", "Tamil Nadu", "600083"),
     ("No 84, 1st Avenue", "Ashok Nagar, Royapettah", None)),
    (("Nh-7, Opp. Chitkara University, Rajpura Chandigarh Highway", "Opp - Chitkara University", "140401",
      "Rajpura", "Punjab", "140401"),
     ("Nh-7, Rajpura Chandigarh Highway", None, "Opp. Chitkara University")),
    (("Dm Road", "Near Omaxe City", "null", "Palwal", "Haryana", "121102"),
     ("Dm Road", None, "Near Omaxe City")),
]


def run_tests():
    failed = 0
    for args, (street, region, landmark) in CASES:
        got = ap.parse_address(*args)
        ok = (got["street"], got["region"], got["landmark"]) == (street, region, landmark)
        failed += not ok
        print(("PASS" if ok else "FAIL"), args[0][:50])
        if not ok:
            print("   expected:", (street, region, landmark))
            print("   got:     ", (got["street"], got["region"], got["landmark"]))
    return failed


UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
NULLS = {"", "null", "none", "nan", "n/a", "na", "-", "--", "[]", "{}", "not available", "unknown"}
DROP = {"source_types", "source_ids", "source_content_id", "organization_type", "content_table_id", "phone_numbers",
        "websites", "acceptsvolunteers", "facebooklink", "address_country", "address_countrycode", "countries",
        "affiliationtypeids", "area"}
KEEP_AFTER = {"coordinates", "latitude", "longitude"}


def dry_run(sample):
    csv.field_size_limit(10**9)
    with open(os.path.join(ROOT, "data", "raw", "facilities.csv"), encoding="utf-8", newline="") as f:
        r = csv.reader(f, escapechar="\\", doublequote=False)
        header = next(r)
        rows = [dict(zip(header, x)) for x in r]
    cut = header.index("recency_of_page_update")
    kept = [c for i, c in enumerate(header) if c.lower() not in DROP and (i <= cut or c.lower() in KEEP_AFTER)]
    print(f"\n{len(rows)} rows, {len(header)} columns -> keeping {len(kept)} columns:\n  {kept}")

    def filled(v):
        return v is not None and v.strip().lower() not in NULLS

    reasons = {"INVALID_ID": 0, "NAME_MISSING_OR_LIST": 0, "NO_COORDS_OR_ADDRESS": 0, "UNDER_30PCT_FILLED": 0}
    survivors = []
    for row in rows:
        if not UUID.match(row["unique_id"].strip()):
            reasons["INVALID_ID"] += 1; continue
        name = row["name"].strip()
        if not filled(name) or name.startswith("["):
            reasons["NAME_MISSING_OR_LIST"] += 1; continue
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            has_coords = 6 <= lat <= 37.5 and 68 <= lon <= 97.5 or 6 <= lon <= 37.5 and 68 <= lat <= 97.5
        except ValueError:
            has_coords = False
        addr = [row[c] for c in ["address_line1", "address_line2", "address_line3", "address_city",
                                 "address_stateOrRegion", "address_zipOrPostcode"]]
        if not has_coords and not any(filled(a) for a in addr):
            reasons["NO_COORDS_OR_ADDRESS"] += 1; continue
        share = sum(filled(row[c]) for c in kept) / len(kept)
        if share < 0.30:
            reasons["UNDER_30PCT_FILLED"] += 1; continue
        survivors.append(row)
    print("Rows removed by rule (applied in this order):", reasons, "-> kept", len(survivors))

    parsed = [ap.parse_address(r["address_line1"], r["address_line2"], r["address_line3"],
                               r["address_city"], r["address_stateOrRegion"], r["address_zipOrPostcode"]) for r in survivors]
    n = len(parsed)
    for k in ["street", "region", "landmark"]:
        print(f"  {k:9s} filled: {sum(p[k] is not None for p in parsed) / n:.0%}")
    bad_pin = [r for r, p in zip(survivors, parsed)
               if not re.fullmatch(r"[1-9]\d{5}", r["address_zipOrPostcode"].strip()) and p["pin_from_text"]]
    print(f"  PIN field invalid but a PIN found in the address text: {len(bad_pin)} rows")
    if sample:
        import random
        random.seed(1)
        for r, p in random.sample(list(zip(survivors, parsed)), sample):
            print("\nRAW :", " | ".join(r[c] for c in ["address_line1", "address_line2", "address_line3"]))
            print("  street:", p["street"], "\n  region:", p["region"], "\n  landmark:", p["landmark"])


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--sample", type=int, default=0)
    args = a.parse_args()
    fails = run_tests()
    dry_run(args.sample)
    sys.exit(1 if fails else 0)
