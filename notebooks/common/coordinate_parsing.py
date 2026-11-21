# Databricks notebook source
# MAGIC %md
# MAGIC # common/coordinate_parsing
# MAGIC Turns messy latitude/longitude text into numbers, and records **how** each value was read so nothing is silently guessed.
# MAGIC
# MAGIC | Input example | Result | `how` |
# MAGIC |---|---|---|
# MAGIC | `19.3638689` | 19.3638689 | `plain` |
# MAGIC | `18.856818°`, `28.430354° N`, `25.43 N` | number without the symbol/letter | `symbols_removed` |
# MAGIC | `17°57'17.7` | 17 + 57/60 + 17.7/3600 = 17.954917 | `dms_converted` |
# MAGIC | `28.4 32628` | 28.432628 (the space was inside the decimals) | `space_removed` |
# MAGIC | `NA`, empty | NULL | `missing` |
# MAGIC | anything else | NULL | `unparseable` |
# MAGIC
# MAGIC `fix_pair()` then checks the pair against India's bounding box and swaps latitude/longitude when they were entered the wrong way round.
# MAGIC Plain Python, so it can be tested locally (`python scripts/test_pincode_cleaning.py`). In Databricks: `%run ./common/coordinate_parsing`.

# COMMAND ----------

import re

LAT_RANGE = (6.0, 37.5)
LON_RANGE = (68.0, 97.5)
_MISSING = {"", "na", "n/a", "null", "none", "nan", "-"}

_PLAIN = re.compile(r"^-?\d+(\.\d+)?$")
_SYMBOLS = re.compile(r"^(\d+(?:\.\d+)?)\s*[°º˚]?\s*[NnEeSsWw]?\.?$")
_DMS = re.compile(r"^(\d{1,3})\s*[°º˚:\s]\s*(\d{1,2})\s*['′:\s]\s*(\d{1,2}(?:\.\d+)?)?\s*(?:\"|″|'')?\s*[NnEe]?$")
_SPACED = re.compile(r"^(\d{1,3}\.\d+)\s+(\d+)\s*[NnEe]?$")


def parse_coordinate(text):
    """Return (value or None, how)."""
    if text is None:
        return None, "missing"
    s = str(text).strip()
    if s.lower() in _MISSING:
        return None, "missing"
    if _PLAIN.match(s):
        return float(s), "plain"
    m = _SYMBOLS.match(s)
    if m:
        return float(m.group(1)), "symbols_removed"
    m = _DMS.match(s)
    if m:
        deg, minutes, sec = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0)
        if minutes < 60 and sec < 60:
            return round(deg + minutes / 60 + sec / 3600, 7), "dms_converted"
    m = _SPACED.match(s)
    if m:
        return float(m.group(1) + m.group(2)), "space_removed"
    return None, "unparseable"


def _in(v, rng):
    return v is not None and rng[0] <= v <= rng[1]


def fix_pair(lat_text, lon_text):
    """
    Parse both values and check them together. Returns a dict:
      latitude, longitude  (None unless the pair is usable)
      coord_status         ok | swapped_fixed | missing | unparseable | zero | out_of_range
      lat_how, lon_how     how each text was read (see parse_coordinate)
    """
    lat, lat_how = parse_coordinate(lat_text)
    lon, lon_how = parse_coordinate(lon_text)
    out = {"latitude": None, "longitude": None, "lat_how": lat_how, "lon_how": lon_how}
    if lat_how == "missing" or lon_how == "missing":
        out["coord_status"] = "missing"
    elif lat is None or lon is None:
        out["coord_status"] = "unparseable"
    elif lat == 0 and lon == 0:
        out["coord_status"] = "zero"
    elif _in(lat, LAT_RANGE) and _in(lon, LON_RANGE):
        out.update(latitude=lat, longitude=lon, coord_status="ok")
    elif _in(lon, LAT_RANGE) and _in(lat, LON_RANGE):
        out.update(latitude=lon, longitude=lat, coord_status="swapped_fixed")
    else:
        out["coord_status"] = "out_of_range"
    return out


# COMMAND ----------

# Spark wrapper (only defined when PySpark is available)
try:
    from pyspark.sql import functions as _F
    from pyspark.sql.types import StructType, StructField, StringType as _S, DoubleType as _D

    COORD_SCHEMA = StructType([StructField("latitude", _D()), StructField("longitude", _D()),
                               StructField("coord_status", _S()), StructField("lat_how", _S()),
                               StructField("lon_how", _S())])

    @_F.udf(COORD_SCHEMA)
    def fix_pair_udf(lat_text, lon_text):
        return fix_pair(lat_text, lon_text)
except ImportError:
    pass
