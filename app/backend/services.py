"""
Services a user can search for. `tag` is the shared vocabulary used by the registry tables
(registry_services_silver.service). `synonyms` are regexes used by the PLACEHOLDER evidence provider to
find the facility's own claims in silver_facility_claims.claim_norm. Replace or extend once the
evidence engine defines its service list.
"""

SERVICES = [
    {"tag": "dialysis", "label": "Dialysis",
     "synonyms": [r"\bdialysis\b", r"\bha?emodialysis\b", r"renal replacement"]},
    {"tag": "emergency_c_section", "label": "Emergency C-section",
     "synonyms": [r"c\s?-?\s?section", r"ca?esarean", r"\blscs\b"]},
    {"tag": "nicu", "label": "Newborn intensive care (NICU / SNCU)",
     "synonyms": [r"\bnicu\b", r"\bsncu\b", r"neonatal intensive", r"newborn intensive", r"neonatology"]},
    {"tag": "trauma", "label": "Trauma care",
     "synonyms": [r"\btrauma\b", r"polytrauma", r"accident"]},
    {"tag": "emergency", "label": "Emergency care",
     "synonyms": [r"\bemergency\b", r"\bcasualty\b", r"24\s?x\s?7"]},
    {"tag": "icu", "label": "Intensive care (ICU)",
     "synonyms": [r"\bicu\b", r"intensive care", r"critical care"]},
    {"tag": "cancer_care", "label": "Cancer care",
     "synonyms": [r"oncolog", r"chemotherapy", r"radiotherapy", r"\bcancer\b"]},
    {"tag": "cardiac_care", "label": "Cardiac care",
     "synonyms": [r"cardiolog", r"\bcardiac\b", r"angioplasty", r"cath\s?lab"]},
    {"tag": "stroke_care", "label": "Stroke care",
     "synonyms": [r"\bstroke\b", r"thrombolysis"]},
    {"tag": "blood_bank", "label": "Blood bank",
     "synonyms": [r"blood bank", r"blood centre", r"blood center", r"transfusion"]},
    {"tag": "obstetrics", "label": "Maternity / delivery care",
     "synonyms": [r"obstetric", r"maternity", r"\bdelivery\b", r"labou?r room"]},
    {"tag": "eye_care", "label": "Eye care",
     "synonyms": [r"ophthalm", r"\beye\b", r"cataract"]},
]

BY_TAG = {s["tag"]: s for s in SERVICES}


def public_list():
    return [{"tag": s["tag"], "label": s["label"]} for s in SERVICES]
