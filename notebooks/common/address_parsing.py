# Databricks notebook source
# MAGIC %md
# MAGIC # common/address_parsing
# MAGIC Splits the messy `address_line1/2/3` fields into a standard shape:
# MAGIC
# MAGIC | Output | Meaning | Example |
# MAGIC |---|---|---|
# MAGIC | `street` | house/plot/building number and the street ("# street_name road/lane", plus building or floor details) | `#422, 1st Floor, 27th Main Road` |
# MAGIC | `region` | locality, neighbourhood, sector or area within the city | `Hsr Layout, Sector-1` |
# MAGIC | `landmark` | "near / opposite / behind …" directions | `Next To Icici Bank` |
# MAGIC | `pin_from_text` | a 6-digit PIN found inside the address lines (used when the PIN field is broken) | `400008` |
# MAGIC
# MAGIC City, state and PIN come from their own columns (see notebook 01).
# MAGIC This file is plain Python (no Spark needed), so it can be tested locally:
# MAGIC `python scripts/test_address_parsing.py`. In Databricks, load it with `%run ./common/address_parsing`.

# COMMAND ----------

import re

NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na", "-", "--", "[]", "{}", "india"}

# Segment starts with a direction word -> landmark
LANDMARK_RE = re.compile(
    r"^(near(by)?|nr\.?|opp\.?|opposite|beside[s]?|behind|above|below|next\s+to|adjacent(\s+to)?|adj\.?|"
    r"in\s*front\s+of|front\s+of|close\s+to|towards|off\.?|at\s+the|landmark|via)\b", re.I)

# Street-level words: roads, highways, lanes
STREET_RE = re.compile(
    r"\b(road|rd|street|st|lane|ln|marg|path|highway|hwy|expressway|bypass|avenue|ave|main|cross|"
    r"gali|galli|salai|veedhi|veethi|peth|n\.?h\.?[- ]?\d+[a-z]?|s\.?h\.?[- ]?\d+|nh|sh)\b", re.I)

# Building / unit details: also part of the street address
BUILDING_RE = re.compile(
    r"\b(floor|flr|plaza|complex|tower|towers|building|bldg|chambers|bhavan|bhawan|apartment[s]?|apts?|mall|"
    r"arcade|plot|shop|flat|wing|door|house|villa|residency|heights|hospital|clinic|centre|center|"
    r"survey|sy\.?\s*no|khasra|unit|suite|ground)\b", re.I)

# Leading house/plot number: "49", "#422", "No 84", "75/1", "4b/18", "Af-15", "D.No 12-3"
NUMBER_RE = re.compile(r"^(#|no\.?|d\.?\s*no\.?|h\.?\s*no\.?|plot\s*no\.?|door\s*no\.?)?\s*[a-z]{0,2}[-\s]?\d+[\w/\-]*\b", re.I)

# Locality-level words
REGION_RE = re.compile(
    r"\b(nagar|colony|sector|sec|layout|bazar|bazaar|market|mohalla|mohala|area|vihar|puram|khand|enclave|"
    r"extension|extn|phase|town|township|village|vill|post|p\.?\s?o|taluk|taluka|tehsil|mandal|district|dist|"
    r"cantt|cantonment|camp|park|garden[s]?|society|chowk|circle|block|ward|basti|pada|wadi|halli|palya|"
    r"pet|gram|ganj|abad|east|west|north|south|central|industrial|estate|city|nagara)\b", re.I)

PIN_RE = re.compile(r"(?<!\d)([1-9]\d{2}\s?\d{3})(?!\d)")


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _clean_segment(s):
    s = re.sub(r"\s+", " ", s).strip(" ,;-.")
    return s


def classify(segment, from_line):
    """Return 'landmark', 'street', 'region' or 'pin' for one comma-separated piece of an address line."""
    if LANDMARK_RE.match(segment):
        return "landmark"
    if re.fullmatch(r"[1-9]\d{2}\s?\d{3}", segment):
        return "pin"
    if STREET_RE.search(segment) or BUILDING_RE.search(segment) or NUMBER_RE.match(segment):
        # "Sector 9-10 Basai Road" is a street; "Sector 44" alone is a region
        if REGION_RE.search(segment) and not (STREET_RE.search(segment) or BUILDING_RE.search(segment)):
            return "region"
        return "street"
    if REGION_RE.search(segment):
        return "region"
    # Unclassified: line 1 is usually the building/street, later lines the locality
    return "street" if from_line == 1 else "region"


def parse_address(line1, line2, line3, city=None, state=None, pincode=None):
    """
    Split address lines into street / region / landmark. Drops pieces that only repeat the
    city, state, country or PIN, and pieces already seen (address lines often repeat each other).
    Returns a dict with keys street, region, landmark, pin_from_text (each None if empty).
    """
    skip = {_norm(x) for x in (city, state, pincode, "india") if x}
    seen = []           # normalized pieces already kept
    parts = {"street": [], "region": [], "landmark": []}
    pin_found = None

    for line_no, line in enumerate((line1, line2, line3), start=1):
        if line is None:
            continue
        line = str(line)
        if line.strip().lower() in NULL_TOKENS:
            continue
        m = PIN_RE.search(line)
        if m and not pin_found:
            pin_found = m.group(1).replace(" ", "")
        for raw in re.split(r",|;|\|", line):
            seg = _clean_segment(raw)
            n = _norm(seg)
            if not n or seg.lower() in NULL_TOKENS or n in skip:
                continue
            # Repeated piece (exact, or contained in a longer piece already kept)
            if any(n == s or (len(n) >= 4 and n in s) for s in seen):
                continue
            kind = classify(seg, line_no)
            if kind == "pin":
                pin_found = pin_found or seg.replace(" ", "")
                continue
            # Strip a trailing city/state/PIN from inside the piece ("Nagpada-mumbai Central" stays; "Kochi 682001" -> "Kochi")
            seg = PIN_RE.sub("", seg).strip(" ,-") or seg
            # A longer piece can replace a shorter one it contains
            for k in parts:
                parts[k] = [p for p in parts[k] if not (len(_norm(p)) >= 4 and _norm(p) in n)]
            seen = [s for s in seen if not (len(s) >= 4 and s in n)] + [n]
            parts[kind].append(seg)

    out = {k: (", ".join(v) if k != "landmark" else "; ".join(v)) or None for k, v in parts.items()}
    out["pin_from_text"] = pin_found
    return out


# COMMAND ----------

# Spark wrapper (only defined when running on Databricks / with PySpark available)
try:
    from pyspark.sql import functions as _F
    from pyspark.sql.types import StructType, StructField, StringType as _S

    ADDRESS_SCHEMA = StructType([StructField("street", _S()), StructField("region", _S()),
                                 StructField("landmark", _S()), StructField("pin_from_text", _S())])

    @_F.udf(ADDRESS_SCHEMA)
    def parse_address_udf(line1, line2, line3, city, state, pincode):
        return parse_address(line1, line2, line3, city, state, pincode)
except ImportError:
    pass
