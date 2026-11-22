# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Service registries: `*_bronze` → `registry_sites_silver`, `registry_services_silver`
# MAGIC
# MAGIC Brings the outside **service-evidence registries** (scraped by `scrapers/`, cited in `docs/data-sources.md` §6–10) to silver, in one shared shape that later joins to `facilities_silver` on `facility_id` (matching is notebook 06).
# MAGIC
# MAGIC | Output table | One row per | What it's for |
# MAGIC |---|---|---|
# MAGIC | `<source>_bronze` (one per CSV) | source row | Raw copy of each uploaded CSV, all text, plus load metadata |
# MAGIC | `registry_sites_silver` | place listed by a registry | **Matching:** name, type, ownership, state, district, city, PIN, PIN location, citation |
# MAGIC | `registry_services_silver` | place × service | **Evidence:** which service, what to quote, evidence type, dates, whether still valid, citation |
# MAGIC
# MAGIC **Sources** (a source is skipped, with a warning, if its CSV/table isn't there):
# MAGIC
# MAGIC | `source` | Registry | Evidence type | Site grain |
# MAGIC |---|---|---|---|
# MAGIC | `laqshya` | LaQshya certified labour rooms / maternity OTs (NHSRC, 2026-04-08) | `government_certification` | facility |
# MAGIC | `trauma` | Trauma Care Facilities, NPPMT&BI (Rajya Sabha Q. 2048, 2026-03-10) | `government_designation` | facility |
# MAGIC | `nmc` | NMC medical colleges and their MBBS/PG courses (2026-11-21) | `government_training_approval` | college |
# MAGIC | `dnb` | NBEMS/DNB-accredited hospitals and specialties (ANBAI, 2026-11-21) | `government_training_approval` | hospital listing |
# MAGIC | `ncg` | National Cancer Grid member cancer centres (2026-11-21) | `network_membership` | member |
# MAGIC | `nabh` | NABH accredited / certified / empanelled organisations (2026-11-21) | `independent_accreditation`, `government_scheme_empanelment` | listing |
# MAGIC
# MAGIC **What "silver" means here**
# MAGIC * Same columns for every source; states standardized with `common/reference_data`; `name_norm` / `name_core` recomputed with the **shared** functions so both sides of a match are normalized the same way.
# MAGIC * Services use one shared vocabulary (`SERVICES` below), the same tags in every source.
# MAGIC * **No scores.** Each evidence row is *described* (`evidence_type`, `service_specific`, `is_current`, `status`), and points/levels are applied later in gold.
# MAGIC * Problems are flagged in `dq_flags`, never silently dropped. Every row has citation columns and a `row_citation`.
# MAGIC
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("external_path", "/Volumes/workspace/datathon/external", "3. Folder holding the *_bronze.csv files")
dbutils.widgets.dropdown("reload_bronze", "yes", ["yes", "no"], "4. Reload bronze tables from the CSVs")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
EXT = dbutils.widgets.get("external_path").strip().rstrip("/")
RELOAD = dbutils.widgets.get("reload_bronze") == "yes"
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

from functools import reduce
from pyspark.sql import Window
PRODUCED_BY_NB = "notebooks/05_registries_bronze_to_silver.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0 · Reference: sources and the service vocabulary

# COMMAND ----------

SOURCES = {
    "laqshya": dict(
        name="LaQshya Master Data (certified labour rooms and maternity OTs), 08-04-2026",
        publisher="National Health Systems Resource Centre (NHSRC), Ministry of Health and Family Welfare, Government of India",
        url="https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf",
        retrieved="2026-11-21",
        license="Government publication. No explicit open-data licence found; cite NHSRC/MoHFW.",
        scraper="scrapers/nhsrc_laqshya.py"),
    "trauma": dict(
        name="Trauma Care Facilities under NPPMT&BI (Rajya Sabha Unstarred Q. 2048, Annexure-I, 10 Mar 2026)",
        publisher="Ministry of Health and Family Welfare, Government of India (answer to the Rajya Sabha)",
        url="https://sansad.in/getFile/annex/270/AU2048_OvVj2M.pdf?source=pqars",
        retrieved="2026-11-21",
        license="Public parliamentary record. No explicit licence; cite the Rajya Sabha answer.",
        scraper="scrapers/mohfw_trauma_centres.py"),
    "nmc": dict(
        name="NMC lists of colleges teaching MBBS and PG courses",
        publisher="National Medical Commission (NMC), Government of India",
        url="https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-pg-courses",
        retrieved="2026-11-21",
        license="Public government website. No explicit open-data licence found; cite NMC.",
        scraper="scrapers/nmc_colleges.py"),
    "dnb": dict(
        name="DNB Accredited Institutions (NBEMS accreditation, listed by ANBAI)",
        publisher="Association of National Board Accredited Institutions (ANBAI); accreditation by NBEMS, MoHFW",
        url="https://anbai.org/DNB_accredited_institutions.php",
        retrieved="2026-11-21",
        license="Association website. No licence found; cite ANBAI and NBEMS.",
        scraper="scrapers/anbai_dnb.py"),
    "ncg": dict(
        name="National Cancer Grid member list",
        publisher="National Cancer Grid (Department of Atomic Energy; Tata Memorial Centre, Mumbai)",
        url="https://www.ncgindia.org/hospitals-and-institutions/members",
        retrieved="2026-11-21",
        license="Website (c) NCG, all rights reserved. Factual member list used for non-commercial research with citation.",
        scraper="scrapers/ncg_members.py"),
    "nabh": dict(
        name="NABH directory of accredited, certified and empanelled healthcare organisations",
        publisher="National Accreditation Board for Hospitals & Healthcare Providers (NABH), Quality Council of India",
        url="https://nabh.co/find-a-healthcare-organisation/",
        retrieved="2026-11-21",
        license="Public website directory. No open-data licence found; cite NABH / Quality Council of India.",
        scraper="scrapers/nabh_organisations.py"),
}

# Shared service vocabulary: tag -> display label. The same tags are used by every scraper.
SERVICES = {
    "dialysis": "Dialysis", "kidney_care": "Kidney care (nephrology)", "urology": "Urology",
    "obstetrics": "Obstetrics / delivery care", "emergency_c_section": "Emergency C-section",
    "normal_delivery": "Normal delivery (labour room)", "high_risk_pregnancy": "High-risk pregnancy", "gynaecology": "Gynaecology",
    "nicu": "Newborn intensive care (NICU/SNCU)", "neonatal_care": "Neonatal care", "paediatrics": "Paediatrics",
    "picu": "Paediatric intensive care", "paediatric_surgery": "Paediatric surgery",
    "emergency": "Emergency care", "trauma": "Trauma care", "icu": "Intensive care (ICU)", "burns": "Burns care",
    "cardiac_care": "Cardiac care", "cath_lab": "Cardiac catheterisation", "cardiac_surgery": "Cardiac surgery",
    "vascular_surgery": "Vascular surgery", "thoracic_surgery": "Thoracic surgery",
    "cancer_care": "Cancer care", "chemotherapy": "Chemotherapy", "radiotherapy": "Radiotherapy", "cancer_surgery": "Cancer surgery",
    "neurology": "Neurology", "stroke_care": "Stroke care", "neurosurgery": "Neurosurgery", "spine": "Spine surgery",
    "orthopaedics": "Orthopaedics", "joint_replacement": "Joint replacement",
    "general_surgery": "General surgery", "laparoscopy": "Laparoscopic surgery", "general_medicine": "General medicine",
    "primary_care": "Primary / family care", "gastro_liver": "Gastroenterology and liver", "endoscopy": "Endoscopy",
    "transplant": "Organ transplant", "respiratory": "Respiratory / chest medicine", "infectious_disease": "Infectious diseases",
    "diabetes_endocrine": "Diabetes and endocrinology", "blood_disorders": "Blood disorders (haematology)",
    "blood_bank": "Blood bank / transfusion", "rheumatology": "Rheumatology", "dermatology": "Dermatology",
    "eye_care": "Eye care", "dental": "Dental care", "ent": "ENT", "mental_health": "Mental health", "geriatrics": "Geriatrics",
    "rehabilitation": "Rehabilitation", "palliative_care": "Palliative care", "plastic_reconstructive": "Plastic and reconstructive surgery",
    "fertility": "Fertility / reproductive medicine", "genetics": "Medical genetics",
    "imaging": "Imaging (radiology)", "ct_mri": "CT / MRI", "interventional_radiology": "Interventional radiology",
    "nuclear_medicine": "Nuclear medicine", "lab_services": "Laboratory services",
}
DROPPED_TAGS = {"surgery_support"}  # from anaesthesiology: supports surgery, not a service a patient searches for
SERVICE_LABEL = F.create_map(*[x for k, v in SERVICES.items() for x in (F.lit(k), F.lit(v))])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Bronze: load each CSV as a raw table
# MAGIC Upload the `*_bronze.csv` files (from `datasets/external/*/`) into the Volume folder in widget 3. Each becomes a table with the same name, all columns as text. With `reload_bronze = no`, existing tables are used as they are.

# COMMAND ----------

BRONZE_FILES = {
    "laqshya": ["laqshya_facilities_bronze", "laqshya_certifications_bronze"],
    "trauma": ["trauma_care_facilities_bronze"],
    "nmc": ["nmc_colleges_bronze", "nmc_college_courses_bronze"],
    "dnb": ["dnb_hospitals_bronze", "dnb_hospital_specialties_bronze"],
    "ncg": ["ncg_members_bronze"],
    "nabh": ["nabh_organisations_bronze"],
}


def _file_exists(path):
    try:
        dbutils.fs.ls(path)
        return True
    except Exception:
        return False


def load_bronze(stem):
    """Return the bronze table for a CSV stem, (re)loading it from the Volume if asked. None if unavailable."""
    path = f"{EXT}/{stem}.csv"
    if RELOAD and _file_exists(path):
        df = (spark.read.option("header", True).option("inferSchema", False).option("multiLine", True)
              .option("escape", '"').csv(path))
        df = df.select([F.col(f"`{c}`").cast("string").alias(c.strip()) for c in df.columns])
        (df.withColumn("_ingested_at", F.current_timestamp()).withColumn("_source_file", F.lit(path))
           .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(stem))
    if spark.catalog.tableExists(stem):
        return spark.table(stem)
    return None


bronze, available = {}, []
for src, stems in BRONZE_FILES.items():
    tables = {s: load_bronze(s) for s in stems}
    if all(t is not None for t in tables.values()):
        bronze.update(tables)
        available.append(src)
        print(f"{src:8s} " + ", ".join(f"{s}: {t.count():,}" for s, t in tables.items()))
    else:
        print(f"{src:8s} SKIPPED: missing {[s for s, t in tables.items() if t is None]} (no CSV in {EXT} and no table)")
assert available, f"No registry sources found in {EXT}. Upload the *_bronze.csv files first."

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Map each source into the shared shape
# MAGIC Each `*_parts()` function returns `(sites, services)` with exactly the columns in `SITE_COLS` / `SERVICE_COLS`.

# COMMAND ----------

def t(df, c):
    """Trimmed text column, NULL if blank."""
    x = F.trim(F.col(f"`{c}`"))
    return F.when(x != "", x)


def lit_s(v=None):
    return F.lit(v).cast("string")


def to_date_col(c):
    return F.to_date(F.expr(f"try_to_timestamp(`{c}`, 'yyyy-MM-dd')"))


SITE_COLS = ["site_id", "source", "source_record_id", "name", "facility_type_code", "ownership",
             "state", "district", "city", "pincode", "address", "website", "latitude", "longitude",
             "listing_type", "listing_category", "listing_status", "listing_current", "source_flags"]
# Columns most sources don't have: added as typed NULLs by conform_sites()
SITE_OPTIONAL = {"latitude": "double", "longitude": "double", "listing_type": "string", "listing_category": "string",
                 "listing_status": "string", "listing_current": "boolean"}
# What being listed means, for sources where it's the same for every site
LISTING_DEFAULT = {
    "laqshya": ("LaQshya-certified public facility (labour room / maternity OT)", "service_certification"),
    "trauma": ("Trauma Care Facility sanctioned under NPPMT&BI", "government_designation"),
    "nmc": ("NMC-recognised medical college (teaching hospital)", "teaching_institution"),
    "dnb": ("NBEMS/DNB-accredited teaching hospital", "teaching_institution"),
    "ncg": ("National Cancer Grid member cancer centre", "network_membership"),
}


def conform_sites(df):
    for c, typ in SITE_OPTIONAL.items():
        if c not in df.columns:
            df = df.withColumn(c, F.lit(None).cast(typ))
    return df.select(*SITE_COLS)
SERVICE_COLS = ["site_id", "source", "evidence_key", "service", "evidence_type", "service_specific", "evidence_subtype",
                "evidence_detail", "approved_seats", "status", "evidence_date", "valid_until", "is_current", "evidence_flags"]


def explode_tags(df, tags_col):
    """One row per tag in a ';'-separated column, minus dropped tags."""
    out = df.withColumn("service", F.explode(F.split(F.coalesce(F.col(tags_col), F.lit("")), ";")))
    return out.where((F.col("service") != "") & ~F.col("service").isin(*DROPPED_TAGS))


def flags(*pairs):
    return F.filter(F.array(*[F.when(F.coalesce(c, F.lit(False)), F.lit(code)) for code, c in pairs]),
                    lambda x: x.isNotNull())


# ---- LaQshya ------------------------------------------------------------------------------------
def laqshya_parts():
    fac, cert = bronze["laqshya_facilities_bronze"], bronze["laqshya_certifications_bronze"]
    repaired = (cert.groupBy("laqshya_facility_id")
                .agg(F.max(F.col("name_repaired").cast("int")).alias("_nr"),
                     F.max(F.col("cells_repaired").cast("int")).alias("_cr")))
    sites = (fac.join(repaired, "laqshya_facility_id", "left").select(
        F.concat(F.lit("laqshya:"), "laqshya_facility_id").alias("site_id"), F.lit("laqshya").alias("source"),
        F.col("laqshya_facility_id").alias("source_record_id"), t(fac, "facility_name_raw").alias("name"),
        t(fac, "facility_type_code").alias("facility_type_code"), F.lit("government").alias("ownership"),
        t(fac, "state_clean").alias("state"), F.initcap(t(fac, "district")).alias("district"), lit_s().alias("city"),
        lit_s().alias("pincode"), lit_s().alias("address"), lit_s().alias("website"),
        flags(("NAME_REPAIRED_FROM_PDF", F.col("_nr") == 1), ("CELLS_REPAIRED_FROM_PDF", F.col("_cr") == 1),
              ("NO_PINCODE", F.lit(True))).alias("source_flags")))
    c = explode_tags(cert, "related_services")
    valid_until = to_date_col("validity_date")
    services = c.select(
        F.concat(F.lit("laqshya:"), "laqshya_facility_id").alias("site_id"), F.lit("laqshya").alias("source"),
        F.col("cert_row_id").alias("evidence_key"), "service",
        F.lit("government_certification").alias("evidence_type"), F.lit(True).alias("service_specific"),
        F.concat(F.lit("LaQshya "), F.lower("department"), F.lit(" certification")).alias("evidence_subtype"),
        F.concat(F.lit("LaQshya-certified "), F.col("department"), F.lit(" ("), F.col("certification_status"),
                 F.lit("), certified "), F.coalesce(F.col("result_date"), F.lit("?")),
                 F.lit(", valid until "), F.coalesce(F.col("validity_date"), F.lit("?"))).alias("evidence_detail"),
        F.lit(None).cast("int").alias("approved_seats"), F.col("certification_status").alias("status"),
        to_date_col("result_date").alias("evidence_date"), valid_until.alias("valid_until"),
        (valid_until >= F.current_date()).alias("is_current"),
        flags(("CERTIFICATION_EXPIRED", valid_until < F.current_date()),
              ("CONDITIONAL_CERTIFICATION", F.col("certification_status") == "conditional"),
              ("DEPARTMENT_NOT_STATED", F.col("department") == "Not stated")).alias("evidence_flags"))
    return sites, services


# ---- Trauma care facilities --------------------------------------------------------------------
TRAUMA_TYPE = {"medical_college": "MC", "district_hospital": "DH", "sub_district_or_taluk": "SDH", "chc_or_phc": "CHC"}
TRAUMA_TYPE_MAP = F.create_map(*[x for k, v in TRAUMA_TYPE.items() for x in (F.lit(k), F.lit(v))])


def trauma_parts():
    b = bronze["trauma_care_facilities_bronze"]
    sites = b.select(
        F.concat(F.lit("trauma:"), "tcf_id").alias("site_id"), F.lit("trauma").alias("source"),
        F.col("tcf_id").alias("source_record_id"), t(b, "facility_name_raw").alias("name"),
        F.coalesce(TRAUMA_TYPE_MAP[F.col("facility_type")], facility_type_from_text(F.col("facility_name_raw"))).alias("facility_type_code"),
        F.lit("government").alias("ownership"), t(b, "state_clean").alias("state"), lit_s().alias("district"),
        t(b, "place").alias("city"), lit_s().alias("pincode"), lit_s().alias("address"), lit_s().alias("website"),
        flags(("NO_PINCODE", F.lit(True)), ("PLACE_ADDED_BY_HAND", F.lit(True))).alias("source_flags"))
    s = explode_tags(b, "related_services")
    services = s.select(
        F.concat(F.lit("trauma:"), "tcf_id").alias("site_id"), F.lit("trauma").alias("source"),
        F.col("tcf_id").alias("evidence_key"), "service",
        F.lit("government_designation").alias("evidence_type"), F.lit(True).alias("service_specific"),
        F.concat(F.col("trauma_level_label"), F.lit(" Trauma Care Facility")).alias("evidence_subtype"),
        F.concat(F.lit("Designated "), F.col("trauma_level_label"),
                 F.lit(" Trauma Care Facility, sanctioned under the national trauma programme (NPPMT&BI, 2007-2017)")).alias("evidence_detail"),
        F.lit(None).cast("int").alias("approved_seats"), F.lit("sanctioned").alias("status"),
        to_date_col("as_of_date").alias("evidence_date"), F.lit(None).cast("date").alias("valid_until"),
        F.lit(None).cast("boolean").alias("is_current"),
        flags(("SANCTIONED_NOT_CONFIRMED_FUNCTIONAL", F.lit(True))).alias("evidence_flags"))
    return sites, services


# ---- NMC colleges and courses ------------------------------------------------------------------
def nmc_parts():
    col_, crs = bronze["nmc_colleges_bronze"], bronze["nmc_college_courses_bronze"]
    pin = t(col_, "pincode_clean")
    sites = col_.select(
        F.concat(F.lit("nmc:"), "college_id").alias("site_id"), F.lit("nmc").alias("source"),
        F.col("college_id").alias("source_record_id"), t(col_, "college_name").alias("name"),
        F.lit("MC").alias("facility_type_code"), F.lower(t(col_, "management_type")).alias("ownership"),
        t(col_, "state_clean").alias("state"), lit_s().alias("district"), t(col_, "city").alias("city"),
        F.when(pin.rlike(r"^[1-8][0-9]{5}$"), pin).alias("pincode"), t(col_, "address").alias("address"),
        t(col_, "website").alias("website"),
        flags(("NO_PINCODE", pin.isNull()), ("NO_DETAIL_RECORD", F.col("has_detail") == "0"),
              ("NEW_COLLEGE_LOP_ONLY", F.lower(F.coalesce(F.col("mbbs_status"), F.lit(""))).rlike(r"^lop|letter of permission"))
              ).alias("source_flags"))
    c = explode_tags(crs.where(F.col("active") == "1"), "related_services")
    seats = F.expr("try_cast(approved_seats AS INT)")
    services = c.select(
        F.concat(F.lit("nmc:"), "college_id").alias("site_id"), F.lit("nmc").alias("source"),
        F.col("course_row_id").alias("evidence_key"), "service",
        F.lit("government_training_approval").alias("evidence_type"), F.lit(False).alias("service_specific"),
        F.concat(F.col("course_level"), F.lit(" course")).alias("evidence_subtype"),
        F.concat(F.lit("NMC-approved "), F.col("course_name"),
                 F.when(seats.isNotNull(), F.concat(F.lit(", "), seats.cast("string"), F.lit(" approved seats"))).otherwise(F.lit("")),
                 F.lit(" ("), F.col("course_level"), F.lit(")")).alias("evidence_detail"),
        seats.alias("approved_seats"), F.lit("approved").alias("status"),
        F.coalesce(to_date_col("approval_date"), to_date_col("lop_date")).alias("evidence_date"),
        F.lit(None).cast("date").alias("valid_until"), F.lit(True).alias("is_current"),
        flags(("INDIRECT_VIA_SPECIALTY", F.lit(True)),
              ("RECENT_LOP_ONLY", F.lower(F.coalesce(F.col("recognition_status"), F.lit(""))).rlike(r"^lop|letter of permission"))
              ).alias("evidence_flags"))
    return sites, services


# ---- DNB / NBEMS accredited hospitals -----------------------------------------------------------
def dnb_parts():
    h, sp = bronze["dnb_hospitals_bronze"], bronze["dnb_hospital_specialties_bronze"]
    sites = h.select(
        F.concat(F.lit("dnb:"), "hospital_id").alias("site_id"), F.lit("dnb").alias("source"),
        F.col("hospital_id").alias("source_record_id"), t(h, "hospital_name").alias("name"),
        facility_type_from_text(F.col("hospital_name")).alias("facility_type_code"), lit_s().alias("ownership"),
        t(h, "state_clean").alias("state"), lit_s().alias("district"), t(h, "city_raw").alias("city"),
        lit_s().alias("pincode"), lit_s().alias("address"), lit_s().alias("website"),
        flags(("NO_PINCODE", F.lit(True)), ("STATE_REASSIGNED", t(h, "state_note").isNotNull()),
              ("DUPLICATE_NAME_IN_CITY", F.col("duplicate_name_city") == "1"),
              ("LIST_UNDATED", F.lit(True))).alias("source_flags"))
    s = explode_tags(sp.where(F.col("category") != "public_health_admin"), "related_services")
    note = t(sp, "course_note")
    services = s.select(
        F.concat(F.lit("dnb:"), "hospital_id").alias("site_id"), F.lit("dnb").alias("source"),
        F.concat_ws("|", "hospital_id", "specialty", F.coalesce(note, F.lit(""))).alias("evidence_key"), "service",
        F.lit("government_training_approval").alias("evidence_type"), F.lit(False).alias("service_specific"),
        F.lit("DNB accredited specialty").alias("evidence_subtype"),
        F.concat(F.lit("Accredited by NBEMS to train DNB specialists in "), F.col("specialty"),
                 F.when(note.isNotNull(), F.concat(F.lit(" ("), note, F.lit(")"))).otherwise(F.lit(""))).alias("evidence_detail"),
        F.lit(None).cast("int").alias("approved_seats"), F.lit("accredited").alias("status"),
        F.lit(None).cast("date").alias("evidence_date"), F.lit(None).cast("date").alias("valid_until"),
        F.lit(None).cast("boolean").alias("is_current"),
        flags(("INDIRECT_VIA_SPECIALTY", F.lit(True)), ("NO_ACCREDITATION_DATE", F.lit(True))).alias("evidence_flags"))
    return sites, services


# ---- National Cancer Grid ---------------------------------------------------------------------
def ncg_parts():
    b = bronze["ncg_members_bronze"].where(F.col("member_type") == "cancer_centre")  # NGOs/societies/research aren't care sites
    pin = t(b, "pincode_clean")
    sites = b.select(
        F.concat(F.lit("ncg:"), "ncg_member_id").alias("site_id"), F.lit("ncg").alias("source"),
        F.col("ncg_member_id").alias("source_record_id"), t(b, "member_name").alias("name"),
        facility_type_from_text(F.col("member_name")).alias("facility_type_code"), lit_s().alias("ownership"),
        t(b, "state_clean").alias("state"), lit_s().alias("district"), lit_s().alias("city"),
        F.when(pin.rlike(r"^[1-8][0-9]{5}$"), pin).alias("pincode"), t(b, "address").alias("address"),
        t(b, "website").alias("website"),
        flags(("NO_PINCODE", pin.isNull()),
              ("MAY_BE_GROUP_OR_HEAD_OFFICE", F.lower(F.concat_ws(" ", "member_name", "address"))
               .rlike(r"regd\.? office|registered office|enterprise|\bgroup\b"))).alias("source_flags"))
    s = explode_tags(b, "related_services")
    services = s.select(
        F.concat(F.lit("ncg:"), "ncg_member_id").alias("site_id"), F.lit("ncg").alias("source"),
        F.col("ncg_member_id").alias("evidence_key"), "service",
        F.lit("network_membership").alias("evidence_type"), F.lit(True).alias("service_specific"),
        F.lit("National Cancer Grid member cancer centre").alias("evidence_subtype"),
        F.lit("Member cancer centre of the National Cancer Grid (Tata Memorial Centre network)").alias("evidence_detail"),
        F.lit(None).cast("int").alias("approved_seats"), F.lit("member").alias("status"),
        to_date_col("snapshot_date").alias("evidence_date"), F.lit(None).cast("date").alias("valid_until"),
        F.lit(True).alias("is_current"),
        flags(("MEMBERSHIP_NOT_INSPECTION", F.lit(True))).alias("evidence_flags"))
    return sites, services


# ---- NABH --------------------------------------------------------------------------------------
def nabh_parts():
    # Travel facilitators and ethics committees aren't care sites
    b = bronze["nabh_organisations_bronze"].where(F.col("programme_category") != "non_facility")
    pin = t(b, "pincode_clean")
    current = F.col("listing_current") == "1"
    year = F.regexp_extract(F.col("accreditation_no"), r"((?:19|20)\d\d)", 1)
    sites = b.select(
        F.concat(F.lit("nabh:"), "nabh_row_id").alias("site_id"), F.lit("nabh").alias("source"),
        F.col("nabh_row_id").alias("source_record_id"), t(b, "organisation_name").alias("name"),
        facility_type_from_text(F.col("organisation_name")).alias("facility_type_code"), lit_s().alias("ownership"),
        t(b, "state_clean").alias("state"), lit_s().alias("district"), lit_s().alias("city"),
        F.when(pin.rlike(r"^[1-8][0-9]{5}$"), pin).alias("pincode"), t(b, "address").alias("address"),
        t(b, "website").alias("website"),
        F.expr("try_cast(latitude AS DOUBLE)").alias("latitude"), F.expr("try_cast(longitude AS DOUBLE)").alias("longitude"),
        t(b, "programme").alias("listing_type"), t(b, "programme_category").alias("listing_category"),
        t(b, "status_text").alias("listing_status"), current.alias("listing_current"),
        flags(("NO_PINCODE", pin.isNull()), ("LISTING_NOT_CURRENT", ~current),
              ("NO_COORDINATES", F.col("latitude").isNull() | (t(b, "latitude").isNull()))).alias("source_flags"))
    s = explode_tags(b, "related_services")
    services = s.select(
        F.concat(F.lit("nabh:"), "nabh_row_id").alias("site_id"), F.lit("nabh").alias("source"),
        F.col("nabh_row_id").alias("evidence_key"), "service",
        F.when(F.col("programme_category") == "empanelment", "government_scheme_empanelment")
         .otherwise("independent_accreditation").alias("evidence_type"),
        F.lit(True).alias("service_specific"),
        F.col("programme").alias("evidence_subtype"),
        F.concat(F.lit("NABH "), F.col("programme"), F.lit(": "), F.coalesce(F.col("status_text"), F.lit("?")),
                 F.lit(" (no. "), F.coalesce(F.col("accreditation_no"), F.lit("?")), F.lit(")")).alias("evidence_detail"),
        F.lit(None).cast("int").alias("approved_seats"),
        F.when(~current, "not_current").when(F.col("programme_category") == "empanelment", "empaneled")
         .otherwise("accredited").alias("status"),
        F.when(year != "", F.to_date(F.concat(year, F.lit("-01-01")))).alias("evidence_date"),
        F.lit(None).cast("date").alias("valid_until"), current.alias("is_current"),
        flags(("LISTING_NOT_CURRENT", ~current), ("DATE_IS_YEAR_ONLY", year != "")).alias("evidence_flags"))
    return sites, services


BUILDERS = {"laqshya": laqshya_parts, "trauma": trauma_parts, "nmc": nmc_parts, "dnb": dnb_parts, "ncg": ncg_parts,
            "nabh": nabh_parts}
parts = [BUILDERS[s]() for s in available]
# lambda (not DataFrame.unionByName): the classic DataFrame class isn't available on serverless (Spark Connect)
sites = reduce(lambda a, b: a.unionByName(b), [conform_sites(p[0]) for p in parts])
_ld_type = F.create_map(*[x for k, v in LISTING_DEFAULT.items() for x in (F.lit(k), F.lit(v[0]))])
_ld_cat = F.create_map(*[x for k, v in LISTING_DEFAULT.items() for x in (F.lit(k), F.lit(v[1]))])
sites = (sites.withColumn("listing_type", F.coalesce("listing_type", _ld_type[F.col("source")]))
              .withColumn("listing_category", F.coalesce("listing_category", _ld_cat[F.col("source")])))
services = reduce(lambda a, b: a.unionByName(b), [p[1].select(*SERVICE_COLS) for p in parts])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · `registry_sites_silver`
# MAGIC States re-standardized with the shared lookup; names normalized with the shared `name_norm` / `name_core`. If `pincode_centroids_silver` (notebook 04) exists, sites with a PIN get that PIN's location and a state cross-check.

# COMMAND ----------

src_map = lambda key: F.create_map(*[x for k, v in SOURCES.items() for x in (F.lit(k), F.lit(v[key]))])

sites = (sites
    .withColumn("state", state_from_text(F.col("state")))
    .withColumn("state_listed", F.col("state"))
    .withColumn("name_norm", name_norm(F.col("name")))
    .withColumn("name_core", name_core(F.col("name")))
    .withColumn("facility_level", facility_level(F.col("facility_type_code"))))

HAS_PIN_CENTROIDS = spark.catalog.tableExists("pincode_centroids_silver")
if HAS_PIN_CENTROIDS:
    cent = spark.table("pincode_centroids_silver").select(
        "pincode", F.col("latitude").alias("pin_latitude"), F.col("longitude").alias("pin_longitude"),
        F.col("states").alias("_pin_states"), F.col("main_district").alias("pin_main_district"))
    sites = sites.join(cent, "pincode", "left")
else:
    print("pincode_centroids_silver not found: run notebook 04 first to add PIN locations. Continuing without them.")
    sites = (sites.withColumn("pin_latitude", F.lit(None).cast("double")).withColumn("pin_longitude", F.lit(None).cast("double"))
                  .withColumn("_pin_states", F.lit(None).cast("array<string>")).withColumn("pin_main_district", lit_s()))

# NABH's address ends with a "City, State" pair that is often wrong (e.g. an Agra hospital filed under
# "South Delhi, Delhi"; Hyderabad under Andhra Pradesh), while its PIN is right. For NABH only, when the
# PIN belongs to exactly one state and disagrees, take the PIN's state (original kept in state_listed).
_mismatch = (F.col("_pin_states").isNotNull() & F.col("state").isNotNull() &
             ~F.array_contains(F.coalesce(F.col("_pin_states"), F.array().cast("array<string>")), F.col("state")))
_fix = (F.col("source") == "nabh") & (F.size(F.coalesce(F.col("_pin_states"), F.array().cast("array<string>"))) == 1) & \
       (_mismatch | F.col("state").isNull())
sites = (sites
    .withColumn("_state_fixed", _fix)
    .withColumn("state", F.when(_fix, F.element_at("_pin_states", 1)).otherwise(F.col("state"))))

# Same source, same listing type, same name and place = possible duplicate. (NABH lists one hospital
# under several programmes; those are different listing types, not duplicates.)
w_dup = Window.partitionBy("source", "listing_type", "state", "name_norm", F.coalesce("pincode", "district", "city"))
sites = (sites
    .withColumn("_n_same", F.count(F.lit(1)).over(w_dup))
    .withColumn("dq_flags", F.array_distinct(F.concat(F.col("source_flags"), flags(
        ("STATE_UNRECOGNIZED", F.col("state").isNull()),
        ("MISSING_NAME", F.col("name").isNull()),
        ("NO_LOCALITY", F.col("city").isNull() & F.col("district").isNull() & F.col("pincode").isNull() &
                        F.col("latitude").isNull() & F.col("address").isNull()),
        ("PIN_NOT_IN_DIRECTORY", F.col("pincode").isNotNull() & F.col("pin_latitude").isNull() & F.lit(HAS_PIN_CENTROIDS)),
        ("STATE_CORRECTED_FROM_PIN", F.col("_state_fixed")),
        ("PIN_STATE_MISMATCH", ~F.col("_state_fixed") & F.col("_pin_states").isNotNull() & F.col("state").isNotNull() &
                               ~F.array_contains(F.coalesce(F.col("_pin_states"), F.array().cast("array<string>")), F.col("state"))),
        ("POSSIBLE_DUPLICATE_IN_SOURCE", F.col("_n_same") > 1)))))
    .drop("source_flags", "_pin_states", "_n_same", "_state_fixed"))

sites = (sites
    .withColumn("source_name", src_map("name")[F.col("source")])
    .withColumn("source_publisher", src_map("publisher")[F.col("source")])
    .withColumn("source_url", src_map("url")[F.col("source")])
    .withColumn("retrieved_on", F.to_date(src_map("retrieved")[F.col("source")]))
    .withColumn("source_license", src_map("license")[F.col("source")])
    .withColumn("produced_by", F.concat(src_map("scraper")[F.col("source")], F.lit(" -> "), F.lit(PRODUCED_BY_NB)))
    .withColumn("row_citation", F.concat(
        F.col("source_publisher"), F.lit(". "), F.col("source_name"), F.lit(": "), F.coalesce(F.col("name"), F.lit("?")),
        F.lit(", "), F.coalesce(F.col("city"), F.col("district"), F.col("pin_main_district"), F.lit("?")), F.lit(", "),
        F.coalesce(F.col("state"), F.lit("?")), F.lit(" [record "), F.col("source_record_id"), F.lit("]. "), F.col("source_url"),
        F.lit(", retrieved "), F.col("retrieved_on").cast("string"), F.lit("."))))

SITE_ORDER = ["site_id", "source", "source_record_id", "name", "name_norm", "name_core", "facility_type_code", "facility_level",
              "ownership", "state", "state_listed", "district", "city", "pincode", "latitude", "longitude",
              "pin_latitude", "pin_longitude", "pin_main_district", "address", "website",
              "listing_type", "listing_category", "listing_status", "listing_current", "dq_flags", "row_citation",
              "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
write_table(sites.select(*SITE_ORDER), "registry_sites_silver",
            "One row per place listed by an outside service registry (LaQshya, trauma, NMC, DNB, NCG, NABH), in one shared shape "
            "for matching to facilities_silver. Built by notebooks/05_registries_bronze_to_silver.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · `registry_services_silver`
# MAGIC One row per site × service × piece of evidence (e.g. a college with D.M. Nephrology and M.Ch. Urology has two `kidney_care` rows). Described, not scored.

# COMMAND ----------

unknown = [r["service"] for r in services.select("service").distinct().collect() if r["service"] not in SERVICES]
services = (services
    .withColumn("service_label", SERVICE_LABEL[F.col("service")])
    .withColumn("service_row_id", F.substring(F.sha2(F.concat_ws("|", "site_id", "evidence_key", "service"), 256), 1, 16))
    .withColumn("dq_flags", F.array_distinct(F.concat(F.col("evidence_flags"), flags(
        ("SERVICE_NOT_IN_VOCABULARY", F.col("service_label").isNull()))))).drop("evidence_flags")
    .join(spark.table("registry_sites_silver").select("site_id", "name", "state",
                                                      F.coalesce("city", "district", "pin_main_district").alias("_place")), "site_id", "left")
    .withColumn("source_name", src_map("name")[F.col("source")])
    .withColumn("source_publisher", src_map("publisher")[F.col("source")])
    .withColumn("source_url", src_map("url")[F.col("source")])
    .withColumn("retrieved_on", F.to_date(src_map("retrieved")[F.col("source")]))
    .withColumn("source_license", src_map("license")[F.col("source")])
    .withColumn("produced_by", F.concat(src_map("scraper")[F.col("source")], F.lit(" -> "), F.lit(PRODUCED_BY_NB)))
    .withColumn("row_citation", F.concat(
        F.col("source_publisher"), F.lit(". "), F.col("source_name"), F.lit(": "), F.coalesce(F.col("name"), F.lit("?")),
        F.lit(", "), F.coalesce(F.col("_place"), F.lit("?")), F.lit(", "), F.coalesce(F.col("state"), F.lit("?")), F.lit(" - "),
        F.col("evidence_detail"), F.lit(". "), F.col("source_url"), F.lit(", retrieved "), F.col("retrieved_on").cast("string"), F.lit("."))))

SERVICE_ORDER = ["service_row_id", "site_id", "source", "service", "service_label", "evidence_type", "service_specific",
                 "evidence_subtype", "evidence_detail", "approved_seats", "status", "evidence_date", "valid_until",
                 "is_current", "dq_flags", "row_citation", "evidence_key",
                 "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
write_table(services.select(*SERVICE_ORDER), "registry_services_silver",
            "One row per registry site x service x piece of evidence, with evidence type, validity and citation. "
            "Descriptive only (no scores). Join to registry_sites_silver on site_id. Built by notebooks/05_registries_bronze_to_silver.")
if unknown:
    print(f"WARNING: tags not in SERVICES (flagged SERVICE_NOT_IN_VOCABULARY): {unknown}")

COLUMN_COMMENTS = {
    "registry_sites_silver": {
        "site_id": "'<source>:<source_record_id>'. Unique across all registries.",
        "name_core": "Name with facility-type words removed (common/reference_data.name_core). Use for fuzzy matching.",
        "pin_latitude": "Median location of the post offices with this PIN (pincode_centroids_silver). Not the site's exact location.",
        "dq_flags": "Data-quality codes; see notebook 05 and docs/registries-silver.md.",
        "latitude": "Site coordinates as given by the source (NABH only so far). NULL if none or outside India.",
        "listing_category": "What being listed means: service_certification, government_designation, teaching_institution, "
                            "network_membership, or a NABH programme category (hospital_accreditation, entry_level_certification, "
                            "service_accreditation, empanelment, quality_certification, ayush).",
        "listing_current": "False if the source says the listing was withdrawn, suspended or expired (NABH); NULL if unknown.",
        "state_listed": "State as the source gave it (standardized). Differs from state only where corrected from the PIN (NABH).",
    },
    "registry_services_silver": {
        "evidence_type": "government_certification | government_designation | government_training_approval | "
                         "government_scheme_empanelment | independent_accreditation | network_membership",
        "service_specific": "True if the evidence certifies/designates this service itself; False if inferred from a specialty department or course.",
        "is_current": "True if still valid on the run date; False if expired; NULL if the source gives no validity information.",
        "evidence_detail": "Human-readable evidence to quote in an explanation.",
    },
}
for tbl, comments in COLUMN_COMMENTS.items():
    for c, txt in comments.items():
        spark.sql(f"ALTER TABLE {tbl} ALTER COLUMN `{c}` COMMENT '{txt.replace(chr(39), '')}'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Checks

# COMMAND ----------

s_tbl, v_tbl = spark.table("registry_sites_silver"), spark.table("registry_services_silver")
assert s_tbl.count() == s_tbl.select("site_id").distinct().count(), "site_id is not unique"
assert v_tbl.count() == v_tbl.select("service_row_id").distinct().count(), "service_row_id is not unique"
orphans = v_tbl.join(s_tbl, "site_id", "left_anti").count()
assert orphans == 0, f"{orphans} service rows have no site"
print(f"registry_sites_silver: {s_tbl.count():,} | registry_services_silver: {v_tbl.count():,}")

display(spark.sql("""
  SELECT s.source, s.sites, s.with_pin, s.with_pin_location, s.state_unrecognized, v.service_rows, v.services
  FROM (SELECT source, count(*) AS sites, count_if(pincode IS NOT NULL) AS with_pin,
               count_if(pin_latitude IS NOT NULL) AS with_pin_location, count_if(state IS NULL) AS state_unrecognized
        FROM registry_sites_silver GROUP BY source) s
  LEFT JOIN (SELECT source, count(*) AS service_rows, count(DISTINCT service) AS services
             FROM registry_services_silver GROUP BY source) v USING (source)
  ORDER BY s.sites DESC"""))

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Sites with evidence for the main demo services, by source and whether the evidence is current
# MAGIC SELECT service, source, evidence_type, service_specific,
# MAGIC        count(DISTINCT site_id) AS sites, count_if(is_current) AS rows_current, count_if(NOT is_current) AS rows_expired
# MAGIC FROM registry_services_silver
# MAGIC WHERE service IN ('dialysis', 'nicu', 'emergency_c_section', 'trauma', 'emergency', 'cancer_care', 'icu', 'blood_bank', 'stroke_care')
# MAGIC GROUP BY ALL ORDER BY service, sites DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT 'site' AS level, flag, count(*) AS n FROM (SELECT explode(dq_flags) AS flag FROM registry_sites_silver) GROUP BY flag
# MAGIC UNION ALL
# MAGIC SELECT 'service' AS level, flag, count(*) AS n FROM (SELECT explode(dq_flags) AS flag FROM registry_services_silver) GROUP BY flag
# MAGIC ORDER BY level, n DESC
