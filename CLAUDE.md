# CLAUDE.md

## Project
CMU Datathon Fall 2026, "Find the right care": given a medical service and a location in India, recommend facilities from the Virtue Foundation dataset with cited, evidence-based explanations and honest uncertainty. Must run on Databricks Free Edition. Team of 4.

## Branches
- Claude's work for Sophia goes on the **`sophia-wip`** branch (tracking `origin/sophia-wip`).
- Claude's work for William goes on the **`Will_branch`** branch.
- Don't commit to `main` unless asked.

## Layout
- `notebooks/`: Databricks notebooks (source `.py` format). `01_bronze_to_silver.py` builds the bronze/silver tables.
- `docs/`: dataset notes (`dataset-notes.md`) and the silver-table reference with filtering watch-outs (`silver-tables.md`).

## Change logging (required)
After every change to this project (code, notebooks, data or cleaning rules, scoring logic, environment or setup, or a design decision), add an entry at the top of the "Entries" section in `DEVLOG.md`, using the template in that file. Each entry records:
- **When:** date and local time (`Get-Date -Format "yyyy-MM-dd HH:mm"`)
- **Who:** the person, or "Claude (for <name>)"
- **What:** the exact files, tables or settings changed
- **How:** commands, tools or approach used
- **Why:** the reason, including any tradeoffs considered

Log the change in the same piece of work as the change itself, not afterward in a batch.
