"""
App settings, all from environment variables (set in app.yaml on Databricks, or in your shell locally).

  EVIDENCE_PROVIDER  evidence_confidence | placeholder
                     evidence_confidence = Alice's package does tiers AND ranking (backend/engine.py; default)
                     placeholder         = the app's own provisional tiers + ranker (fallback for demos)
  DATA_MODE          live | mock   live = query Databricks; mock = canned demo data (always uses the placeholder)
"""

import os


def _env(name, default):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


CATALOG = _env("APP_CATALOG", "workspace")
SCHEMA = _env("APP_SCHEMA", "datathon")
WAREHOUSE_ID = _env("DATABRICKS_WAREHOUSE_ID", "")

DATA_MODE = _env("DATA_MODE", "live")                     # live | mock
EVIDENCE_PROVIDER = _env("EVIDENCE_PROVIDER", "evidence_confidence")  # evidence_confidence | placeholder
RANKER = _env("RANKER", "placeholder")  # only used with EVIDENCE_PROVIDER=placeholder

# Optional AI explainer (Databricks Foundation Model API). Empty = explainer off.
LLM_ENDPOINT = _env("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
EXPLAINER_ENABLED = _env("EXPLAINER_ENABLED", "true").lower() == "true"

DEFAULT_RADIUS_KM = float(_env("DEFAULT_RADIUS_KM", "50"))
MAX_RADIUS_KM = float(_env("MAX_RADIUS_KM", "300"))
TOP_N = int(_env("TOP_N", "5"))              # recommendations shown
ALTERNATIVES_N = int(_env("ALTERNATIVES_N", "5"))
MAX_CANDIDATES = int(_env("MAX_CANDIDATES", "5000"))  # safety cap; evidence is added to ALL candidates up to this


def t(name):
    """Fully qualified table name."""
    return f"`{CATALOG}`.`{SCHEMA}`.`{name}`"
