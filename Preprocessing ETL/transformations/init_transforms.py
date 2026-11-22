# Linked to the DAIS 2026 Virtue Foundation dataset catalog.
# Source: databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset

from pyspark import pipelines as dp

SOURCE = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"


@dp.materialized_view(
    name="facilities",
    comment="Linked from databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities",
)
def facilities():
    return spark.read.table(f"{SOURCE}.facilities")


@dp.materialized_view(
    name="india_post_pincode_directory",
    comment="Linked from databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory",
)
def india_post_pincode_directory():
    return spark.read.table(f"{SOURCE}.india_post_pincode_directory")


@dp.materialized_view(
    name="nfhs_5_district_health_indicators",
    comment="Linked from databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators",
)
def nfhs_5_district_health_indicators():
    return spark.read.table(f"{SOURCE}.nfhs_5_district_health_indicators")