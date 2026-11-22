"""
Geography: Elliot's search (notebook 07_pin_nearby_facilities, Part B) as app functions.

  B1  Is it an Indian PIN? 6 digits, first digit 1-9, and present in pincode_centroids_silver.
  B2  PIN -> centroid (median of its post offices), with warnings for ambiguous / spread-out PINs.
  B3  Bounding-box prefilter, then haversine (straight-line) distance to facility_geo_ready points.

Reads: pincode_centroids_silver (notebook 00), facility_geo_ready (notebook 07, Part A).
"""

import math
import re

from . import config, db

KM_PER_DEG_LAT = 111.0


class PinError(ValueError):
    """The PIN can't be used; the message is shown to the user."""


def normalise_pin(raw):
    pin = re.sub(r"[\s-]", "", raw or "")
    if not pin.isdigit() or len(pin) != 6:
        raise PinError(f"'{raw}' isn't an Indian PIN code: PIN codes are exactly 6 digits.")
    if pin[0] == "0":
        raise PinError(f"'{pin}' isn't an Indian PIN code: the first digit is 1-9.")
    return pin


def resolve_pin(raw):
    """Return the PIN's centre and any warnings. Raises PinError with a user-facing message."""
    pin = normalise_pin(raw)
    rows = db.query(
        f"""SELECT pincode, latitude, longitude, main_district, main_state, n_offices, centroid_quality,
                   pin_ambiguous, districts, states, max_office_distance_km
            FROM {config.t('pincode_centroids_silver')} WHERE pincode = :pin""", {"pin": pin})
    if not rows:
        raise PinError(f"'{pin}' has the right shape but isn't in the India Post directory. "
                       "It may be mistyped or very new.")
    c = rows[0]
    if c["latitude"] is None:
        raise PinError(f"PIN {pin} is valid, but none of its post offices has usable coordinates, "
                       "so there is no centre point to measure distance from.")
    warnings = []
    if c["pin_ambiguous"]:
        warnings.append(f"PIN {pin} covers more than one district or state; distances are measured from a "
                        "midpoint across them.")
    if c["centroid_quality"] == "spread_out":
        warnings.append(f"PIN {pin}'s post offices are up to {c['max_office_distance_km']} km apart, so its "
                        "centre point is approximate.")
    if c["centroid_quality"] == "single_office":
        warnings.append(f"PIN {pin}'s location comes from a single post office.")
    return {
        "pincode": pin,
        "latitude": float(c["latitude"]),
        "longitude": float(c["longitude"]),
        "district": c["main_district"],
        "state": c["main_state"],
        "n_post_offices": c["n_offices"],
        "centroid_quality": c["centroid_quality"],
        "warnings": warnings,
    }


_MAX_UNCERTAINTY = None


def max_uncertainty_km():
    """Largest location_uncertainty_km in facility_geo_ready (cached; widens the bounding box)."""
    global _MAX_UNCERTAINTY
    if _MAX_UNCERTAINTY is None:
        rows = db.query(f"SELECT max(coalesce(location_uncertainty_km, 0)) AS m FROM {config.t('facility_geo_ready')}")
        _MAX_UNCERTAINTY = float(rows[0]["m"] or 0) if rows else 0.0
    return _MAX_UNCERTAINTY


def nearby_facilities(lat0, lon0, radius_km, limit):
    """Facilities that may be within radius_km, nearest first (straight-line distance).

    Same radius rule as notebook 07 and Alice's pipeline: a facility is a candidate if its closest
    possible distance, distance_min_km = max(distance_km - location_uncertainty_km, 0), is within the
    radius. So a facility placed at its PIN centre just outside the radius is kept, with a warning.
    The bounding box is widened by the largest uncertainty so those facilities aren't cut early.
    """
    reach = radius_km + max_uncertainty_km()
    dlat = reach / KM_PER_DEG_LAT
    dlon = reach / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 0.01))
    return db.query(
        f"""
        WITH box AS (
          SELECT facility_id, name, city, state, pincode, address_full, geo_latitude, geo_longitude,
                 location_basis, location_uncertainty_km, geo_confidence
          FROM {config.t('facility_geo_ready')}
          WHERE geo_latitude BETWEEN :lat_lo AND :lat_hi AND geo_longitude BETWEEN :lon_lo AND :lon_hi
        )
        SELECT *, greatest(round(distance_km - coalesce(location_uncertainty_km, 0), 2), 0.0) AS distance_min_km
        FROM (
          SELECT *, round(2 * 6371.0 * asin(least(1.0, sqrt(
                      pow(sin(radians(geo_latitude - :lat0) / 2), 2) +
                      cos(radians(:lat0)) * cos(radians(geo_latitude)) *
                      pow(sin(radians(geo_longitude - :lon0) / 2), 2)))), 2) AS distance_km
          FROM box
        ) WHERE greatest(round(distance_km - coalesce(location_uncertainty_km, 0), 2), 0.0) <= :radius
        ORDER BY distance_km, facility_id
        LIMIT {int(limit)}
        """,
        {"lat0": lat0, "lon0": lon0, "radius": radius_km,
         "lat_lo": lat0 - dlat, "lat_hi": lat0 + dlat, "lon_lo": lon0 - dlon, "lon_hi": lon0 + dlon})
