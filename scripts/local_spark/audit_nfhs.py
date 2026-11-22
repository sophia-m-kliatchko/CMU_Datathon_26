"""Spot-check nfhs_silver from a local run: value ranges per indicator, joins, quarantine."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nbrun import get_spark
from pyspark.sql import functions as F

s = get_spark()
s.sql("SET CATALOG spark_catalog")
s.sql("USE datathon")
n = s.table("nfhs_silver")
cols = ["households_surveyed", "women_15_49_interviewed", "men_15_54_interviewed", "sex_ratio_total_f_per_1000_m",
        "sex_ratio_at_birth_5y_f_per_1000_m", "female_population_age_6_years_and_above_ever_schooled_pct",
        "population_below_age_15_years_pct", "child_u5_whose_birth_was_civil_reg_pct"]
print(f"nfhs_silver: {n.count()} rows; states: {n.select('state').distinct().count()}")
n.select(*[F.concat_ws(" .. ", F.min(c).cast("string"), F.max(c).cast("string")).alias(c[:28]) for c in cols]).show(truncate=False)
n.select(F.count_if(F.col("district_in_pin_directory")).alias("district_in_pin_directory"),
         F.count_if(F.col("low_sample")).alias("low_sample"),
         F.count_if(F.col("has_estimate_values")).alias("has_estimates"),
         F.count_if(F.col("state_name") != F.col("state_ut")).alias("state_fixed"),
         F.count_if(F.col("district_std") != F.col("district_name")).alias("district_fixed")).show()
print("Example row (Manipur, Chandel) and the quarantined copy:")
n.where("district_name = 'Chandel'").select("state", "district_std", *cols[:4], "row_citation").show(truncate=60)
s.table("nfhs_quarantine").select("state_ut", "district_name", "quarantine_reason").show(truncate=80)
print("Districts not found in the India Post directory (sample):")
n.where("NOT district_in_pin_directory").select("state", "district_std").show(10)
