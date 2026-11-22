"""
Services a user can search for. `tag` is the shared vocabulary used by the registry tables
(registry_services_silver.service). `synonyms` are regexes used by the PLACEHOLDER evidence provider to
find the facility's own claims in silver_facility_claims.claim_norm.

`best_tier` is the strongest tier the evidence engine can give the service with today's sources
(from Alice's tier rules): T1 needs a current LaQshya certificate or a service-specific NABH
accreditation. Services that only NMC/DNB training, NCG membership or the trauma list cover top out
at T3. Shown on the page so users don't read T3 as "poor" where nothing stronger exists.
"""

BEST_SOURCE = {"laqshya": "a current LaQshya certificate", "nabh": "a service-specific NABH accreditation",
               None: "training approvals, network membership or the trauma-centre list"}
BEST = {"emergency_c_section": ("T1", "laqshya"), "obstetrics": ("T1", "laqshya"),
        "dialysis": ("T1", "nabh"), "blood_bank": ("T1", "nabh"), "emergency": ("T1", "nabh"),
        "stroke_care": ("T1", "nabh"), "eye_care": ("T1", "nabh")}

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
     "synonyms": [r"\bemergency\b", r"\bcasualty\b"]},  # not "24x7": it matched labs, pharmacies, a hair salon
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


def best(tag):
    tier, source = BEST.get(tag, ("T3", None))
    return {"best_tier": tier, "best_source": BEST_SOURCE[source]}


def public_list():
    return [{"tag": s["tag"], "label": s["label"], **best(s["tag"])} for s in SERVICES]
