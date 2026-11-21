# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Kayakalp: `kayakalp_bronze` → `kayakalp_silver`
# MAGIC
# MAGIC **Input:** `kayakalp_bronze`, made by uploading `data/external/kayakalp_2021_22.csv` (from `scripts/kayakalp_pdf_to_csv.py`) as a table.
# MAGIC **Output:** `kayakalp_silver`, with **one row per award** (a facility can win both a Kayakalp award and an Eco-friendly award).
# MAGIC
# MAGIC | What happens | Why |
# MAGIC |---|---|
# MAGIC | Types fixed (`s_no`, `source_page` → int; `district_repaired` → boolean) | The CSV upload may read everything as text |
# MAGIC | `award_rank_order` (1 = Best … 6 = Commendation) | To sort and compare awards |
# MAGIC | District field split: the **last** comma-separated part becomes `district_clean`; the rest becomes `locality` | Some states wrote "village, block, district" in the district column |
# MAGIC | State standardized (`state_clean`) | To join with `silver_facilities` |
# MAGIC | Facility type kept as reported (`SDH/CHC`, `PHC`…), plus a type guessed from the name and a level (primary/secondary) | For filtering and like-for-like matching |
# MAGIC | `name_norm`, `name_core` | For fuzzy matching to Virtue Foundation facilities |
# MAGIC | `dq_flags` | Problems are flagged, never silently dropped |
# MAGIC | **Citation columns** (`source_*`, `row_citation` with PDF page and S.No) | Every row can be cited back to the exact line of the PDF (see `docs/data-sources.md`) |
# MAGIC
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("bronze_table", "kayakalp_bronze", "3. Bronze table")
dbutils.widgets.text("silver_table", "kayakalp_silver", "4. Silver table")
# TODO: fill in where the PDF was downloaded from (see docs/data-sources.md)
dbutils.widgets.text("source_url", "", "5. URL the PDF was downloaded from")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
BRONZE = dbutils.widgets.get("bronze_table").strip()
SILVER = dbutils.widgets.get("silver_table").strip()
SOURCE_URL = dbutils.widgets.get("source_url").strip() or None
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

SOURCE_NAME = "Kayakalp Winner Facilities of FY 2021-22 (PDF)"
SOURCE_PUBLISHER = "Ministry of Health and Family Welfare (MoHFW), Government of India, Kayakalp Award Scheme (administered with NHSRC)"
SOURCE_LICENSE = "Government publication. No explicit open-data licence found; cite MoHFW/NHSRC as the source."
PRODUCED_BY = "scripts/kayakalp_pdf_to_csv.py -> notebooks/03_kayakalp_bronze_to_silver.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)"
RETRIEVED_ON = "2026-11-21"  # date the PDF was converted; update if you re-download it

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Read bronze and check the columns

# COMMAND ----------

bronze = spark.table(BRONZE)
cols = {c.lower().strip(): c for c in bronze.columns}
REQUIRED = ["s_no", "financial_year", "award_raw", "award_rank", "award_category", "facility_type",
            "facility_name", "district", "state", "source_file", "source_page"]
missing = [c for c in REQUIRED if c not in cols]
assert not missing, f"{BRONZE} is missing columns {missing}. Found: {bronze.columns}"

def col(name, default=None):
    if name in cols:
        t = F.trim(F.col(f"`{cols[name]}`").cast("string"))
        return F.when(t == "", F.lit(None).cast("string")).otherwise(t)
    return F.lit(default).cast("string")

def to_int(name):
    return F.expr(f"try_cast(`{cols[name]}` AS INT)") if name in cols else F.lit(None).cast("int")

print(f"{BRONZE}: {bronze.count():,} rows; columns: {bronze.columns}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Clean and parse

# COMMAND ----------

RANK_ORDER = {"Best": 1, "Winner": 2, "Joint Winner": 3, "Runner Up": 4, "Joint Runner Up": 5, "Commendation": 6}
rank_map = F.create_map(*[x for k, v in RANK_ORDER.items() for x in (F.lit(k), F.lit(v))])

df = bronze.select(
    to_int("s_no").alias("s_no"),
    col("financial_year").alias("financial_year"),
    col("award_raw").alias("award_raw"),
    col("award_rank").alias("award_rank"),
    col("award_category").alias("award_category"),
    F.upper(F.regexp_replace(col("facility_type"), r"\s+", "")).alias("facility_type_reported"),
    F.regexp_replace(col("facility_name"), r"\s+", " ").alias("facility_name"),
    col("district").alias("district_raw"),
    col("state").alias("state_pdf"),
    col("state_raw").alias("state_raw"),
    F.lower(col("district_repaired", "false")).isin("true", "1", "yes").alias("district_repaired"),
    col("source_file").alias("source_file"),
    to_int("source_page").alias("source_page"),
)

# District column: "village, block, district" -> district = last part, locality = the rest
parts = F.filter(F.transform(F.split(F.col("district_raw"), ","), lambda x: F.trim(x)), lambda x: x != "")
last_part = F.element_at(parts, -1)
district = F.trim(F.regexp_replace(last_part, r"(?i)\s+health\s+district$", ""))

silver = (df
    .withColumn("award_id", F.concat_ws("-", F.lit("kayakalp"), F.col("financial_year"), F.col("s_no").cast("string")))
    .withColumn("award_rank_order", rank_map[F.col("award_rank")])
    .withColumn("district_clean", F.when(F.size(parts) > 0, F.initcap(district)))
    .withColumn("locality", F.when(F.size(parts) > 1, F.array_join(F.slice(parts, 1, F.size(parts) - 1), ", ")))
    .withColumn("state_clean", state_from_text(F.coalesce(F.col("state_pdf"), F.col("state_raw"))))
    .withColumn("facility_type_from_name", facility_type_from_text(F.col("facility_name")))
    .withColumn("facility_level", F.coalesce(facility_level(F.col("facility_type_reported")),
                                             facility_level(F.col("facility_type_from_name"))))
    .withColumn("name_norm", name_norm(F.col("facility_name")))
    .withColumn("name_core", name_core(F.col("facility_name")))
)

# Same facility listed twice for the same award category = likely a PDF duplicate (flagged, not removed)
from pyspark.sql import Window
w = Window.partitionBy("financial_year", "award_category", "name_norm", "district_clean", "state_clean")
silver = silver.withColumn("_n_same", F.count(F.lit(1)).over(w))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Data-quality flags and citations

# COMMAND ----------

FLAGS = [
    ("STATE_UNRECOGNIZED",           F.col("state_clean").isNull()),
    ("MISSING_DISTRICT",             F.col("district_clean").isNull()),
    ("MISSING_FACILITY_NAME",        F.col("facility_name").isNull()),
    ("DISTRICT_REPAIRED_FROM_PDF",   F.col("district_repaired")),
    ("DISTRICT_FIELD_HAD_LOCALITY",  F.col("locality").isNotNull()),
    ("AWARD_RANK_UNRECOGNIZED",      F.col("award_rank_order").isNull()),
    ("FACILITY_LEVEL_UNKNOWN",       F.col("facility_level").isNull()),
    ("POSSIBLE_DUPLICATE_AWARD",     F.col("_n_same") > 1),
]
silver = silver.withColumn(
    "dq_flags",
    F.filter(F.array(*[F.when(F.coalesce(c, F.lit(False)), F.lit(code)) for code, c in FLAGS]), lambda x: x.isNotNull()),
).drop("_n_same")

silver = add_provenance(silver, SOURCE_NAME, SOURCE_PUBLISHER,
                        F.lit(SOURCE_URL).cast("string"), F.lit(RETRIEVED_ON).cast("date"), SOURCE_LICENSE, PRODUCED_BY)
silver = silver.withColumn(
    "row_citation",
    F.concat(F.lit("MoHFW, Kayakalp Winner Facilities of FY "), F.coalesce(F.col("financial_year"), F.lit("?")),
             F.lit(", "), F.coalesce(F.col("source_file"), F.lit("PDF")),
             F.lit(", p. "), F.coalesce(F.col("source_page").cast("string"), F.lit("?")),
             F.lit(", S.No "), F.coalesce(F.col("s_no").cast("string"), F.lit("?")), F.lit(": "),
             F.coalesce(F.col("award_raw"), F.lit("?")), F.lit(", "), F.coalesce(F.col("facility_type_reported"), F.lit("?")),
             F.lit(", "), F.coalesce(F.col("facility_name"), F.lit("?")), F.lit(", "),
             F.coalesce(F.col("district_raw"), F.lit("?")), F.lit(", "), F.coalesce(F.col("state_raw"), F.col("state_pdf"), F.lit("?")),
             F.lit(".")),
)

ORDER = ["award_id", "financial_year", "facility_name", "facility_type_reported", "facility_type_from_name", "facility_level",
         "locality", "district_clean", "state_clean", "award_category", "award_rank", "award_rank_order",
         "name_norm", "name_core", "dq_flags", "row_citation", "s_no", "source_page", "award_raw", "district_raw",
         "state_pdf", "state_raw", "district_repaired", "source_file",
         "source_name", "source_publisher", "source_url", "retrieved_on", "source_license", "produced_by"]
silver = silver.select(*ORDER)

write_table(silver, SILVER,
            "Kayakalp award winners FY 2021-22 (MoHFW PDF), one row per award, with page and S.No citations. "
            "Public facilities only. Built by notebooks/03_kayakalp_bronze_to_silver.")
if SOURCE_URL is None:
    print("NOTE: source_url is empty. Fill in the PDF's download URL (widget 5) and docs/data-sources.md.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Checks

# COMMAND ----------

silver = spark.table(SILVER)
assert silver.count() == silver.select("award_id").distinct().count(), "award_id is not unique"
display(spark.sql(f"""
  SELECT award_category, award_rank, count(*) AS awards, count_if(state_clean IS NULL) AS state_unrecognized
  FROM {SILVER} GROUP BY ALL ORDER BY award_category, min(award_rank_order)"""))

# COMMAND ----------

display(spark.sql(f"""
  SELECT flag, count(*) AS awards
  FROM (SELECT explode(dq_flags) AS flag FROM {SILVER}) GROUP BY flag ORDER BY awards DESC"""))

# COMMAND ----------

display(spark.sql(f"""
  SELECT state_clean, facility_type_reported, count(*) AS awards
  FROM {SILVER} GROUP BY ALL ORDER BY state_clean, awards DESC"""))
