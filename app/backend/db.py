"""
Databricks SQL access.

On Databricks Apps the app's own service principal is used automatically (Config() reads the app's
environment). Locally, Config() uses your Databricks CLI profile: set DATABRICKS_CONFIG_PROFILE=datathon
and DATABRICKS_WAREHOUSE_ID. All queries use named parameters (never string-formatted user input).
"""

import json
import threading

from . import config


def as_list(value):
    """ARRAY columns come back as JSON text when pyarrow isn't installed; normalise to a Python list."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            return [value]
    return list(value)

_lock = threading.Lock()
_conn = None


def _connect():
    from databricks import sql
    from databricks.sdk.core import Config

    cfg = Config()
    if not config.WAREHOUSE_ID:
        raise RuntimeError("DATABRICKS_WAREHOUSE_ID is not set (the SQL warehouse the app queries).")
    host = cfg.host.replace("https://", "").rstrip("/")
    return sql.connect(server_hostname=host, http_path=f"/sql/1.0/warehouses/{config.WAREHOUSE_ID}",
                       credentials_provider=lambda: cfg.authenticate)


def query(statement, params=None):
    """Run a query and return a list of dicts. Reconnects once if the connection went stale."""
    global _conn
    for attempt in (1, 2):
        with _lock:
            if _conn is None:
                _conn = _connect()
            conn = _conn
        try:
            with conn.cursor() as cur:
                cur.execute(statement, params or {})
                cols = [d[0] for d in cur.description] if cur.description else []
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception:
            with _lock:
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
            if attempt == 2:
                raise
