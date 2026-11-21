# scripts/

Local Python scripts that fetch or convert **outside datasets** into CSVs under `data/external/`, ready to upload to Databricks.

| Script | Input | Output | Needs |
|---|---|---|---|
| `scrape_nqas.py` | NHSRC NQAS certified facilities website ([qps.nhsrcindia.org/nqas-facility-list](https://qps.nhsrcindia.org/nqas-facility-list)) | `data/external/nqas_certified_facilities.csv` | Standard library only |
| `kayakalp_pdf_to_csv.py` | A Kayakalp award-winners PDF, e.g. `KAYAKALP WINNER FACILITIES 21-22.pdf` | `data/external/kayakalp_<fy>.csv` | `python -m pip install pdfplumber` |

Run them from the repo root:

```powershell
python scripts/scrape_nqas.py
python scripts/kayakalp_pdf_to_csv.py "C:\path\to\KAYAKALP WINNER FACILITIES 21-22.pdf"
```

## Uploading a CSV to Databricks (Free Edition)
1. In the workspace, open **Catalog**, then `workspace` → your schema (e.g. `datathon`) → **Create → Volume**, named for example `external`.
2. Open the volume → **Upload to this volume** → pick the CSV.
3. In a notebook:
   ```python
   df = spark.read.option("header", True).csv("/Volumes/workspace/datathon/external/kayakalp_2021_22.csv")
   df.write.mode("overwrite").saveAsTable("workspace.datathon.ext_kayakalp_2021_22")
   ```
   Or skip the volume: **New → Add or upload data → Create or modify table** and drop in the CSV.

## Known issues per source
- **NQAS website:** the list pages have an unstable sort order. Walking pages 0, 1, 2… repeats some facilities and skips others. The script avoids this by querying state by state and district by district, then checks its row count against the site's total.
- **Kayakalp 2021-22 PDF:**
  - Long district names spill into the State column, so their letters get mixed with the state's. The script repairs this and marks those rows `district_repaired = true` (17 rows). Small leftovers are possible (e.g. "North Garohills").
  - In Gujarat, the "district" field is really "village, block, district".
