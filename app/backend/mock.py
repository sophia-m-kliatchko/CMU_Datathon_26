"""
DATA_MODE=mock: canned data so the interface can be developed and demoed without Databricks.
Illustrative only. The facility names are made up and the page says so.
"""

from .geography import PinError, normalise_pin


def resolve_pin(raw):
    pin = normalise_pin(raw)
    if pin != "110001":
        raise PinError("Mock mode only knows PIN 110001 (New Delhi).")
    return {"pincode": pin, "latitude": 28.6198, "longitude": 77.2129, "district": "New Delhi", "state": "Delhi",
            "n_post_offices": 23, "centroid_quality": "good", "warnings": []}


_FAC = [
    ("mock-a", "Example Medical Center A", "New Delhi", 2.1, "high", 0.1),
    ("mock-b", "Example District Hospital B", "New Delhi", 4.8, "high", 0.1),
    ("mock-c", "Example Clinic C", "Noida", 9.6, "approximate_pin_centroid", 3.0),
    ("mock-d", "Example Hospital D", "Gurugram", 21.4, "medium_low_precision", 1.0),
    ("mock-e", "Example Nursing Home E", "New Delhi", 1.2, "high", 0.1),
]


def nearby_facilities(lat0, lon0, radius_km, limit):
    return [{"facility_id": f, "name": n, "city": c, "state": "Delhi", "pincode": "110001", "address_full": None,
             "location_basis": "pin_centroid" if g == "approximate_pin_centroid" else "facility_coordinates",
             "location_uncertainty_km": u, "geo_confidence": g, "distance_km": d}
            for f, n, c, d, g, u in _FAC if d <= radius_km][:limit]


class MockEvidence:
    name = "mock"

    def get_evidence(self, facility_ids, service):
        url = "https://example.org/registry"
        data = {
            "mock-a": ("T1", [], [("registry", "Example registry: certified for this service, valid until 2027-03-31", url),
                                  ("self_reported", "Facility lists: “Dialysis unit”", None)]),
            "mock-b": ("T2", ["CERTIFICATION_EXPIRED"], [("registry", "Example registry: certification expired 2024-02-01", url),
                                                         ("self_reported", "Facility lists the service", None)]),
            "mock-c": ("T3", [], [("self_reported", "Facility lists the service", None)]),
            "mock-d": ("R", ["MATCH_NEEDS_REVIEW"], [("registry", "Example registry lists this service (match needs review)", url)]),
        }
        out = {}
        for fid in facility_ids:
            if fid in data:
                tier, flags, items = data[fid]
                out[fid] = {"tier": tier, "flags": flags, "provider": "mock",
                            "items": [{"kind": k, "text": t, "source": "Example source", "url": u, "current": None}
                                      for k, t, u in items]}
        return out
