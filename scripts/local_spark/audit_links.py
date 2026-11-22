"""Deeper look at notebook 06's facility <-> registry links (local run)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nbrun import get_spark
from pyspark.sql import functions as F

s = get_spark()
s.sql("SET CATALOG spark_catalog")
s.sql("USE datathon")
L = s.table("facility_registry_links_silver")
print("links by needs_review / match_method:")
L.groupBy("needs_review", "match_method").agg(F.count("*").alias("n"), F.round(F.avg("match_score"), 1).alias("avg_score"),
                                               F.min("match_score").alias("min_score")).orderBy("needs_review", "match_method").show(truncate=False)
acc = L.where("NOT needs_review")
print(f"accepted (no review): {acc.count():,}; of which > 25 km apart: {acc.where('distance_km > 25').count():,}; "
      f"name_score < 75: {acc.where('name_score < 75').count():,}")
print("Accepted links that are far apart:")
acc.where("distance_km > 25").orderBy(F.desc("distance_km")).select(
    "facility_name", "site_name", "source", "match_score", "name_score", "distance_km", "distance_basis", "facility_city", "site_city"
).show(12, truncate=35)
print("Accepted links with the lowest name similarity:")
acc.orderBy("name_score").select("facility_name", "site_name", "source", "match_score", "name_score", "distance_km",
                                 "pin_match", "type_match").show(12, truncate=35)
print("Review links: reasons")
L.where("needs_review").groupBy("review_reason").count().orderBy(F.desc("count")).show(12, truncate=80)
print("Facilities linked to more than one site of the same source:")
L.groupBy("facility_id", "source").count().where("count > 1").groupBy("source").count().show()
