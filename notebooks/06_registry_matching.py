# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Match registry sites to facilities: `facility_registry_links_silver`
# MAGIC
# MAGIC Links each place in `registry_sites_silver` (notebook 05) to the Virtue Foundation facility it refers to in `facilities_silver` (notebook 01), so all registry evidence can be joined on `facility_id`.
# MAGIC
# MAGIC | Output table | One row per | What it's for |
# MAGIC |---|---|---|
# MAGIC | `facility_registry_links_silver` | facility ↔ registry site link | **The join table.** Match score, the evidence for the match (name, distance, PIN, place, type, ownership), and `needs_review` |
# MAGIC | `facility_registry_summary_silver` | facility (all of them) | Quick view: which registries list it, which services they evidence, how many links need review |
# MAGIC | `registry_match_review` | link needing review | Side-by-side names and places for a person to confirm or reject |
# MAGIC
# MAGIC **How a match is found**
# MAGIC 1. **Candidates:** same `state`, **and** at least one shared distinctive name word (words in more than `max_token_freq` names, e.g. "sri", "care", are ignored here), **and** close by: site coordinates within `max_distance_km`, or same PIN, or the site's PIN centroid within `max_pin_distance_km`, or the site's town/district named in the facility's address.
# MAGIC 2. **Distinctive-word check:** after removing common/generic words (medical, college, cardiac, eye…) and place names, if both names still have words and none match (typo-tolerant), the pair is rejected; if only one name has such words, the link goes to review. This stops "ESIC Medical College" matching "Osmania Medical College".
# MAGIC    **Kind-of-place check** (dental, eye, blood bank, diagnostics/lab, dialysis, fertility, physiotherapy, read from the full names):
# MAGIC    - both names name a kind and they share none (e.g. "Fertility Foundation" vs "Eye Foundation"): different places, rejected;
# MAGIC    - the **facility** names a kind the registry name doesn't (e.g. "Neo Dental Care" vs "Neo Hospital", "Blood Bank, Lal Bahadur Shastri Hospital" vs "Lal Bahadur Shastri Hospital"): review, never automatic. A department or specialist clinic shouldn't inherit a whole hospital's certificates without a person confirming;
# MAGIC    - the **registry** name adds a specialty (eye, dental, fertility, physiotherapy; e.g. "Manocha Hospital" vs "Manocha Eye Hospital"): review, since these are often separate places. A registry name that only adds a hospital department (blood bank, dialysis, diagnostics/lab, e.g. "Kasturba Hospital Blood Bank") is left to the normal score: the hospital runs it.
# MAGIC 3. **Score (0–100)** = name similarity (`rapidfuzz`: average of token-set and token-sort ratio on `name_core`, so being contained in a longer name isn't a perfect match) + location bonus (up to +20) + facility-type agreement (+5 / −10) + ownership agreement (government registry vs private facility −10, vs public +5) − 10 if a clinic/dentist is matched to a teaching-hospital, trauma, LaQshya or NCG listing.
# MAGIC    Registry names that are only a type plus a place (e.g. "DH Faridabad") need the facility type to agree, or the facility name to be just as generic.
# MAGIC 4. **Decide:** per site, the best candidate is linked if score ≥ `link_threshold`; `review_threshold` ≤ score < `link_threshold`, or a near-tie with a different facility, is linked **with `needs_review = true`**. A near-tie with a facility listed in the best one's `possible_duplicate_ids` is linked too (same place, two records). Name similarity below `min_name_score` is never linked.
# MAGIC
# MAGIC **Works with either naming of `facilities_silver`:** `state_clean`/`pincode_clean`/`city_clean`/`latitude_clean`/`longitude_clean` if present, otherwise `state`/`pincode`/`city`/`latitude`/`longitude` (printed at the start of section 1).
# MAGIC
# MAGIC **Silver, not gold:** this decides *which records are the same place*. It doesn't score services; that's done downstream from these links plus `registry_services_silver`.
# MAGIC Every change to this notebook must be logged in `DEVLOG.md`.

# COMMAND ----------

# MAGIC %pip install rapidfuzz --quiet

# COMMAND ----------

# MAGIC %run ./common/reference_data

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "1. Catalog")
dbutils.widgets.text("schema", "datathon", "2. Schema")
dbutils.widgets.text("link_threshold", "85", "3. Score to link")
dbutils.widgets.text("review_threshold", "70", "4. Score to link with review")
dbutils.widgets.text("min_name_score", "60", "5. Minimum name similarity")
dbutils.widgets.text("max_distance_km", "3", "6. Max distance, site coordinates (km)")
dbutils.widgets.text("max_pin_distance_km", "5", "7. Max distance, site PIN centroid (km)")
dbutils.widgets.text("max_token_freq", "250", "8. Ignore name words in more than this many names (candidate step)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
LINK_T = float(dbutils.widgets.get("link_threshold"))
REVIEW_T = float(dbutils.widgets.get("review_threshold"))
MIN_NAME = float(dbutils.widgets.get("min_name_score"))
MAX_D = float(dbutils.widgets.get("max_distance_km"))
MAX_PIN_D = float(dbutils.widgets.get("max_pin_distance_km"))
MAX_TOKEN_FREQ = int(dbutils.widgets.get("max_token_freq"))
TIE_MARGIN = 5.0  # a second facility within this many points of the best = ambiguous
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")

import pandas as pd
from pyspark.sql import Window
from pyspark.sql.functions import pandas_udf

for t_ in ["facilities_silver", "registry_sites_silver", "registry_services_silver"]:
    assert spark.catalog.tableExists(t_), f"{t_} not found: run notebooks 01 and 05 first."

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1 · Prepare both sides

# COMMAND ----------

# Words that say what kind of place it is, not which place: ignored when comparing distinctive name words
GENERIC_NAME_WORDS = [
    "medical", "college", "hospital", "hospitals", "institute", "research", "centre", "center", "sciences", "science",
    "health", "healthcare", "care", "clinic", "clinics", "multi", "speciality", "specialty", "specialities", "superspeciality",
    "superspecialty", "super", "multispeciality", "multispecialty", "nursing", "home", "maternity", "eye", "dental", "cardiac",
    "heart", "cancer", "oncology", "ortho", "orthopaedic", "orthopedic", "neuro", "kidney", "children", "child", "women",
    "mother", "trust", "foundation", "memorial", "charitable", "government", "govt", "unit", "private", "limited", "pvt",
    "ltd", "diagnostic", "diagnostics", "imaging", "scan", "lab", "laboratory", "pathology", "the", "and", "for", "sri",
    "shri", "shree", "saint", "new", "city", "general", "district", "civil", "sub", "divisional", "community", "primary",
    "referral", "taluk", "area", "rural", "urban", "teaching", "mission", "society", "global", "life", "speciality",
    "surgical", "surgery", "trauma", "emergency", "fertility", "ivf", "laser", "vision", "nethralaya", "hosp", "medicity",
    "institution", "national", "regional", "state", "academy", "university", "society", "group", "enterprise", "enterprises"]
# Kinds of place a name can name. Compared between facility and registry names (see the "Kind-of-place check" at the
# top): disjoint kinds = different places; a kind only the facility names = review (a dental clinic or a hospital's
# blood bank shouldn't silently inherit the hospital's registry evidence).
KIND_PATTERNS = {
    "dental": r"\bdent(al|ist|istry|o)",
    "eye": r"\b(eye\w*|netra\w*|nethra\w*|ophthalm\w*|lasik|retina\w*)",
    "blood bank": r"\bblood\s*(bank|centre|center)\b",
    "diagnostics/lab": r"\b(diagnostics?|imaging|scans?|mri|radiology|pathology|laborator(y|ies)|labs?)\b",
    "dialysis": r"\bdialysis\b",
    "fertility": r"\b(ivf|(in)?fertility|test\s*tube)\b",
    "physiotherapy": r"\bphysiother",
}


# Hospital departments: a registry entry naming one (e.g. "X Hospital Blood Bank") still belongs to hospital X.
DEPARTMENT_KINDS = ["blood bank", "dialysis", "diagnostics/lab"]


def kinds(col):
    """Sorted list of the kinds of place a name mentions (see KIND_PATTERNS)."""
    low = F.lower(col)
    return F.filter(F.array(*[F.when(low.rlike(p), F.lit(k)) for k, p in sorted(KIND_PATTERNS.items())]),
                    lambda x: x.isNotNull())


GENERIC_PLACE_WORDS = ["district", "dist", "nagar", "city", "road", "rural", "urban", "east", "west", "north", "south",
                       "new", "old", "taluk", "block", "sector", "india"]


def tokens(col):
    """Lower-case word tokens (letters/digits), 3+ characters."""
    return F.filter(F.split(F.regexp_replace(F.lower(col), r"[^a-z0-9]+", " "), " "), lambda x: F.length(x) >= 3)


def place_tokens(*cols):
    """Distinctive place words (4+ letters, not generic words like 'district' or 'nagar')."""
    raw = F.split(F.regexp_replace(F.lower(F.concat_ws(" ", *cols)), r"[^a-z]+", " "), " ")
    return F.array_distinct(F.filter(raw, lambda x: (F.length(x) >= 4) & ~x.isin(*GENERIC_PLACE_WORDS)))


# facilities_silver has used two naming styles: plain names (state, pincode, latitude…) and *_clean names
# (state_clean, pincode_clean, latitude_clean…). Accept either: if a *_clean column exists it's the cleaned
# value, so it wins; otherwise the plain name is used. Columns that don't exist at all become NULL.
FAC_COLS = set(spark.table("facilities_silver").columns)


def fcol(name, cast=None):
    for c in (f"{name}_clean", name):
        if c in FAC_COLS:
            col = F.col(f"`{c}`")
            return col.cast(cast) if cast else col
    print(f"NOTE: facilities_silver has no '{name}' or '{name}_clean' column; using NULL")
    return F.lit(None).cast(cast or "string")


print("facilities_silver columns used:",
      {n: next((c for c in (f"{n}_clean", n) if c in FAC_COLS), None)
       for n in ["name", "state", "pincode", "city", "latitude", "longitude"]})

fac = (spark.table("facilities_silver")
    .select("facility_id", fcol("name").alias("f_name"), fcol("state").alias("state"), fcol("pincode").alias("f_pin"),
            fcol("city").alias("f_city"), fcol("address_region").alias("address_region"),
            fcol("address_full").alias("address_full"),
            fcol("latitude", "double").alias("f_lat"), fcol("longitude", "double").alias("f_lon"),
            F.lower(fcol("operatorTypeId")).alias("f_operator"), F.lower(fcol("facilityTypeId")).alias("f_kind"),
            F.coalesce(fcol("possible_duplicate_ids", "array<string>"), F.array().cast("array<string>")).alias("f_dups"))
    .where(F.col("state").isNotNull() & F.col("f_name").isNotNull())
    .withColumn("f_norm", name_norm(F.col("f_name")))
    .withColumn("f_core", name_core(F.col("f_name")))
    .withColumn("f_core_tokens", F.array_distinct(tokens(F.col("f_core"))))
    .withColumn("f_type", facility_type_from_text(F.col("f_name")))
    .withColumn("f_text_tokens", F.array_distinct(tokens(F.concat_ws(" ", "f_name", "f_city", "address_region", "address_full"))))
    .withColumn("f_place_tokens", place_tokens(F.col("f_city"), F.col("address_region"), F.col("state")))
    .withColumn("f_generic", F.size(F.array_except("f_core_tokens", "f_place_tokens")) == 0))

site = (spark.table("registry_sites_silver")
    .where(F.col("state").isNotNull() & F.col("name").isNotNull())
    .select("site_id", "source", F.col("name").alias("s_name"), "name_norm", "name_core", "state",
            F.col("district").alias("s_district"), F.col("city").alias("s_city"), F.col("pincode").alias("s_pin"),
            F.col("latitude").alias("s_lat"), F.col("longitude").alias("s_lon"), "pin_latitude", "pin_longitude",
            F.col("facility_type_code").alias("s_type"), F.col("ownership").alias("s_owner"), "listing_category")
    .withColumn("s_core_tokens", F.array_distinct(tokens(F.col("name_core"))))
    .withColumn("s_place_tokens", place_tokens(F.col("s_city"), F.col("s_district")))
    .withColumn("s_generic", F.size(F.array_except("s_core_tokens",
                F.array_union("s_place_tokens", place_tokens(F.col("state"))))) == 0))

n_fac, n_site = fac.count(), site.count()
print(f"facilities with state and name: {n_fac:,} | registry sites with state and name: {n_site:,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2 · Candidate pairs
# MAGIC Pairs share a state and a distinctive name word (a join on `(state, word)`, which avoids comparing every facility with every site), then must also be close by.

# COMMAND ----------

f_tok = fac.select("facility_id", "state", F.explode("f_core_tokens").alias("tok"))
s_tok = site.select("site_id", "state", F.explode("s_core_tokens").alias("tok"))
freq = (f_tok.select(F.col("facility_id").alias("id"), "tok").unionByName(s_tok.select(F.col("site_id").alias("id"), "tok"))
        .groupBy("tok").agg(F.countDistinct("id").alias("n")))
common = freq.where(F.col("n") > MAX_TOKEN_FREQ).select("tok")
print("Name words ignored for candidates (too common):",
      sorted(r["tok"] for r in common.collect())[:60])

common_words = [r["tok"] for r in common.collect()]
NOT_DISTINCT = F.array(*[F.lit(x) for x in sorted(set(GENERIC_NAME_WORDS) | set(common_words))])

pairs = (f_tok.join(common, "tok", "left_anti")
         .join(s_tok, ["state", "tok"])
         .select("facility_id", "site_id").distinct())


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km; NULL if any coordinate is missing.
    (F.least() skips NULLs, so without the guard a missing coordinate gives least(1.0, NULL) = 1.0, i.e. 20,015 km.)"""
    p = 3.141592653589793 / 180
    a = (F.pow(F.sin((lat2 - lat1) * p / 2), 2) +
         F.cos(lat1 * p) * F.cos(lat2 * p) * F.pow(F.sin((lon2 - lon1) * p / 2), 2))
    return F.when(a.isNotNull(), 2 * 6371.0 * F.asin(F.least(F.lit(1.0), F.sqrt(a))))


cand = (pairs.join(fac, "facility_id").join(site.drop("state"), "site_id")
    .withColumn("d_site", haversine_km(F.col("f_lat"), F.col("f_lon"), F.col("s_lat"), F.col("s_lon")))
    .withColumn("d_pin", haversine_km(F.col("f_lat"), F.col("f_lon"), F.col("pin_latitude"), F.col("pin_longitude")))
    .withColumn("pin_match", F.coalesce(F.col("f_pin") == F.col("s_pin"), F.lit(False)))
    .withColumn("place_match", F.size(F.array_intersect("s_place_tokens", "f_text_tokens")) > 0)
    .where((F.col("d_site") <= MAX_D) | F.col("pin_match") | (F.col("d_pin") <= MAX_PIN_D) | F.col("place_match"))
    # Distinctive name words: what's left after removing common/generic words and place names
    .withColumn("f_distinct", F.array_except(F.array_except("f_core_tokens", NOT_DISTINCT),
                                             F.array_union("f_place_tokens", place_tokens(F.col("state")))))
    .withColumn("s_distinct", F.array_except(F.array_except("s_core_tokens", NOT_DISTINCT),
                                             F.array_union(F.array_union("s_place_tokens", place_tokens(F.col("state"))),
                                                           F.col("f_place_tokens")))))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3 · Score each candidate pair

# COMMAND ----------

@pandas_udf("double")
def name_similarity(a: pd.Series, b: pd.Series) -> pd.Series:
    from rapidfuzz import fuzz
    out = []
    for x, y in zip(a.fillna(""), b.fillna("")):
        out.append(0.5 * fuzz.token_set_ratio(x, y) + 0.5 * fuzz.token_sort_ratio(x, y) if x and y else 0.0)
    return pd.Series(out, dtype="float64")


@pandas_udf("int")
def distinct_overlap(a: pd.Series, b: pd.Series) -> pd.Series:
    """How many of the site's distinctive words have a close match (typo-tolerant) among the facility's."""
    from rapidfuzz import fuzz
    out = []
    for x, y in zip(a, b):
        x = [] if x is None else list(x)
        y = [] if y is None else list(y)
        out.append(sum(1 for t in y if any(fuzz.ratio(t, u) >= 85 for u in x)))
    return pd.Series(out, dtype="int32")


loc_bonus = F.least(F.lit(20.0),
    F.when(F.col("d_site") <= 0.3, 20).when(F.col("d_site") <= 1, 15).when(F.col("d_site") <= MAX_D, 8)
     .when(F.col("pin_match"), 10).when(F.col("d_pin") <= 3, 5).otherwise(0)
    + F.when(F.col("place_match"), 5).otherwise(0))
type_known = F.col("f_type").isNotNull() & F.col("s_type").isNotNull()
type_adj = F.when(type_known & (F.col("f_type") == F.col("s_type")), 5).when(type_known, -10).otherwise(0)
gov_site = F.col("s_owner") == "government"
own_adj = (F.when(gov_site & (F.col("f_operator") == "private"), -10)
            .when(gov_site & F.col("f_operator").isin("public", "government"), 5).otherwise(0))
# A clinic / dentist / doctor's practice isn't a teaching hospital, trauma centre or certified public facility
kind_adj = F.when(F.col("f_kind").isin("clinic", "dentist", "doctor", "farmacy", "pharmacy") &
                  F.col("source").isin("nmc", "dnb", "trauma", "laqshya", "ncg"), -10).otherwise(0)

scored = (cand
    .withColumn("name_score", F.round(F.greatest(name_similarity(F.col("f_core"), F.col("name_core")),
                                                 name_similarity(F.col("f_norm"), F.col("name_norm")) - 10), 1))
    .withColumn("type_match", F.when(type_known, F.col("f_type") == F.col("s_type")))
    .withColumn("generic_ok", ~F.col("s_generic") | F.coalesce(F.col("type_match"), F.lit(False)) | F.col("f_generic"))
    .withColumn("n_f_distinct", F.size("f_distinct")).withColumn("n_s_distinct", F.size("s_distinct"))
    .withColumn("distinct_overlap", distinct_overlap(F.col("f_distinct"), F.col("s_distinct")))
    # Both names have distinctive words and none match: different places (e.g. "ESIC Medical College" vs "Osmania Medical College")
    .withColumn("distinct_conflict", (F.col("n_f_distinct") > 0) & (F.col("n_s_distinct") > 0) & (F.col("distinct_overlap") == 0))
    # Only one name has distinctive words (e.g. "ESI Medical College, Coimbatore" vs "Coimbatore Medical College"): review
    .withColumn("distinct_one_sided", (F.col("n_f_distinct") > 0) != (F.col("n_s_distinct") > 0))
    # Different kinds of place in the two full names (e.g. "Neo Dental Care" vs "Neo Hospital"): review, never automatic
    .withColumn("f_kinds", kinds(F.col("f_name"))).withColumn("s_kinds", kinds(F.col("s_name")))
    .withColumn("kind_conflict", (F.size("f_kinds") > 0) & (F.size("s_kinds") > 0) &
                                 (F.size(F.array_intersect("f_kinds", "s_kinds")) == 0))
    .withColumn("kind_mismatch", (F.size(F.array_except("f_kinds", "s_kinds")) > 0) |
                (F.size(F.array_except(F.array_except("s_kinds", "f_kinds"),
                                       F.array(*[F.lit(k) for k in DEPARTMENT_KINDS]))) > 0))
    .withColumn("match_score", F.round(F.least(F.lit(100.0), F.greatest(F.lit(0.0),
                F.col("name_score") + loc_bonus + type_adj + own_adj + kind_adj)), 1))
    .withColumn("match_score", F.when(F.col("distinct_one_sided") | F.col("kind_mismatch"),
                                      F.least(F.col("match_score"), F.lit(LINK_T - 0.1)))
                                .otherwise(F.col("match_score")))
    .withColumn("distance_km", F.round(F.coalesce("d_site", "d_pin"), 2))
    .withColumn("distance_basis", F.when(F.col("d_site").isNotNull(), "site_coordinates")
                                   .when(F.col("d_pin").isNotNull(), "site_pin_centroid"))
    .where((F.col("name_score") >= MIN_NAME) & F.col("generic_ok") & ~F.col("distinct_conflict") & ~F.col("kind_conflict") &
           (F.col("match_score") >= REVIEW_T)))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4 · Decide links

# COMMAND ----------

w = Window.partitionBy("site_id").orderBy(F.desc("match_score"), F.asc_nulls_last("distance_km"), "facility_id")
ranked = scored.withColumn("match_rank", F.row_number().over(w))  # no .cache(): not supported on serverless
best = ranked.where("match_rank = 1").select("site_id", F.col("facility_id").alias("best_fid"),
                                              F.col("match_score").alias("best_score"), F.col("f_dups").alias("best_dups"))
second = (ranked.where("match_rank > 1").join(best, "site_id")
          .withColumn("is_dup_of_best", F.array_contains("best_dups", F.col("facility_id")) |
                                        F.array_contains("f_dups", F.col("best_fid")))
          .withColumn("near_tie", F.col("match_score") >= F.col("best_score") - TIE_MARGIN))
ambiguous = (second.where(F.col("near_tie") & ~F.col("is_dup_of_best"))
             .groupBy("site_id").agg(F.count(F.lit(1)).alias("n_rivals")))
dup_links = second.where(F.col("near_tie") & F.col("is_dup_of_best")).select("site_id", "facility_id")

links = (ranked.join(best.select("site_id"), "site_id")
    .join(dup_links.withColumn("_dup", F.lit(True)), ["site_id", "facility_id"], "left")
    .where((F.col("match_rank") == 1) | F.coalesce(F.col("_dup"), F.lit(False)))
    .join(ambiguous, "site_id", "left")
    .withColumn("review_reason", F.concat_ws("; ", F.filter(F.array(
        F.when(F.col("distinct_one_sided"), F.lit("distinctive name words on one side only")),
        F.when(F.col("kind_mismatch"), F.concat(F.lit("different kind of place in the names (facility: "),
               F.coalesce(F.nullif(F.array_join("f_kinds", ", "), F.lit("")), F.lit("general")), F.lit("; registry: "),
               F.coalesce(F.nullif(F.array_join("s_kinds", ", "), F.lit("")), F.lit("general")), F.lit(")"))),
        F.when((F.col("match_score") < LINK_T) & ~F.col("distinct_one_sided") & ~F.col("kind_mismatch"),
               F.lit("score below link threshold")),
        F.when(F.col("n_rivals") > 0, F.concat(F.lit("near-tie with "), F.col("n_rivals").cast("string"), F.lit(" other facility(ies)"))),
        F.when(F.col("s_generic") & ~F.coalesce(F.col("type_match"), F.lit(False)),
               F.lit("registry name is generic (type + place) and the type isn't confirmed")),
        F.when(F.col("distance_km") > 10, F.lit("more than 10 km apart"))), lambda x: x.isNotNull())))
    .withColumn("needs_review", F.col("review_reason") != "")
    .withColumn("match_method", F.concat_ws("+", F.filter(F.array(
        F.lit("name"),
        F.when(F.col("d_site") <= MAX_D, F.lit("coordinates")),
        F.when(F.col("pin_match"), F.lit("pin")),
        F.when(F.col("d_pin") <= MAX_PIN_D, F.lit("pin_area")),
        F.when(F.col("place_match"), F.lit("place_name")),
        F.when(F.col("type_match"), F.lit("type")),
        F.when(F.col("_dup"), F.lit("duplicate_of_best"))), lambda x: x.isNotNull())))
    .withColumn("link_id", F.substring(F.sha2(F.concat_ws("|", "facility_id", "site_id"), 256), 1, 16)))

LINK_ORDER = ["link_id", "facility_id", "site_id", "source", "match_score", "needs_review", "review_reason", "match_method",
              "name_score", "distinct_overlap", "distance_km", "distance_basis", "pin_match", "place_match", "type_match", "match_rank",
              "f_name", "s_name", "f_city", "s_city", "s_district", "state", "f_pin", "s_pin", "f_operator", "s_owner",
              "f_type", "s_type", "listing_category"]
RENAME = {"f_name": "facility_name", "s_name": "site_name", "f_city": "facility_city", "s_city": "site_city",
          "s_district": "site_district", "f_pin": "facility_pincode", "s_pin": "site_pincode",
          "f_operator": "facility_operator", "s_owner": "site_ownership", "f_type": "facility_type_guess",
          "s_type": "site_type_code"}
links_out = (links.select(*[F.col(c).alias(RENAME.get(c, c)) for c in LINK_ORDER])
             .withColumn("matched_on", F.current_date())
             .withColumn("produced_by", F.lit("notebooks/06_registry_matching.py (github.com/sophia-m-kliatchko/CMU_Datathon_26)")))
write_table(links_out, "facility_registry_links_silver",
            "Links between facilities_silver.facility_id and registry_sites_silver.site_id, with match score and the "
            "evidence for the match. needs_review = true means a person should confirm. Built by notebooks/06_registry_matching.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5 · Per-facility summary and the review list

# COMMAND ----------

L = spark.table("facility_registry_links_silver")
svc = spark.table("registry_services_silver").select("site_id", "service", "is_current")
per_fac = (L.join(svc, "site_id", "left")
    .groupBy("facility_id").agg(
        F.countDistinct("site_id").alias("n_registry_links"),
        F.sort_array(F.collect_set("source")).alias("registry_sources"),
        F.sort_array(F.collect_set("listing_category")).alias("listing_categories"),
        F.sort_array(F.collect_set(F.when(~F.col("needs_review"), F.col("service")))).alias("services_evidenced"),
        F.sort_array(F.collect_set(F.when(F.col("needs_review"), F.col("service")))).alias("services_evidenced_pending_review"),
        F.countDistinct(F.when(F.col("needs_review"), F.col("site_id"))).alias("n_links_needing_review"),
        F.max("match_score").alias("best_match_score")))
summary = (spark.table("facilities_silver").select("facility_id", fcol("name").alias("facility_name"),
                                                   fcol("state").alias("state"), fcol("city").alias("city"))
    .join(per_fac, "facility_id", "left")
    .withColumn("n_registry_links", F.coalesce("n_registry_links", F.lit(0)))
    .withColumn("n_links_needing_review", F.coalesce("n_links_needing_review", F.lit(0)))
    .withColumn("in_any_registry", F.col("n_registry_links") > 0))
write_table(summary, "facility_registry_summary_silver",
            "One row per facility: which outside registries list it and which services they evidence. Derived from "
            "facility_registry_links_silver + registry_services_silver. Built by notebooks/06_registry_matching.")

review = (L.where("needs_review")
          .select("link_id", "source", "match_score", "review_reason", "facility_name", "site_name",
                  "facility_city", F.coalesce("site_city", "site_district").alias("site_place"), "state",
                  "distance_km", "facility_operator", "site_ownership", "facility_id", "site_id")
          .withColumn("reviewer_decision", F.lit(None).cast("string")))
write_table(review, "registry_match_review",
            "Registry-to-facility links that need a person to confirm. Fill reviewer_decision with 'confirm' or 'reject'.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6 · Checks

# COMMAND ----------

assert L.count() == L.select("link_id").distinct().count(), "link_id not unique"
assert L.join(spark.table("facilities_silver"), "facility_id", "left_anti").count() == 0, "link to unknown facility"
display(spark.sql("""
  SELECT s.source, s.sites,
         count(DISTINCT l.site_id) AS sites_linked,
         round(100 * count(DISTINCT l.site_id) / s.sites, 1) AS pct_linked,
         count(DISTINCT CASE WHEN NOT l.needs_review THEN l.site_id END) AS linked_confident,
         count(DISTINCT CASE WHEN l.needs_review THEN l.site_id END) AS linked_needs_review,
         count(DISTINCT l.facility_id) AS facilities_reached
  FROM (SELECT source, count(*) AS sites FROM registry_sites_silver GROUP BY source) s
  LEFT JOIN facility_registry_links_silver l ON l.source = s.source
  GROUP BY s.source, s.sites ORDER BY s.sites DESC"""))

# COMMAND ----------

# MAGIC %sql
# MAGIC -- How many facilities now have outside evidence, and for the main demo services
# MAGIC SELECT count(*) AS facilities, count_if(in_any_registry) AS in_any_registry,
# MAGIC        count_if(array_contains(services_evidenced, 'dialysis')) AS dialysis,
# MAGIC        count_if(array_contains(services_evidenced, 'emergency_c_section')) AS c_section,
# MAGIC        count_if(array_contains(services_evidenced, 'nicu')) AS nicu,
# MAGIC        count_if(array_contains(services_evidenced, 'trauma')) AS trauma,
# MAGIC        count_if(array_contains(services_evidenced, 'cancer_care')) AS cancer_care,
# MAGIC        count_if(array_contains(services_evidenced, 'blood_bank')) AS blood_bank
# MAGIC FROM facility_registry_summary_silver

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Spot-check: random confident links (names should clearly be the same place)
# MAGIC SELECT source, match_score, match_method, facility_name, site_name, facility_city, site_city, distance_km
# MAGIC FROM facility_registry_links_silver WHERE NOT needs_review ORDER BY rand(42) LIMIT 25

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT source, match_score, review_reason, facility_name, site_name, facility_city, site_place, distance_km
# MAGIC FROM registry_match_review ORDER BY rand(7) LIMIT 25
