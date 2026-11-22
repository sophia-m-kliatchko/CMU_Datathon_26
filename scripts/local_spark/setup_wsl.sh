#!/bin/bash
# Local Spark for verifying the Databricks notebooks. Everything goes under ~/sparkcheck (no sudo).
set -e
BASE=~/sparkcheck
mkdir -p "$BASE"
cd "$BASE"

# 1) uv (Python manager) -> ~/.local/bin
if ! command -v uv >/dev/null 2>&1 && [ ! -x ~/.local/bin/uv ]; then
  curl -LsSf https://astral.sh/uv/install.sh -o uv-install.sh
  sh uv-install.sh -q
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

# 2) Java 17 (Eclipse Temurin) -> ~/sparkcheck/jdk
if [ ! -x "$BASE/jdk/bin/java" ]; then
  curl -LsSf -o jdk.tar.gz "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse"
  mkdir -p jdk && tar -xzf jdk.tar.gz -C jdk --strip-components=1 && rm jdk.tar.gz
fi
"$BASE/jdk/bin/java" -version 2>&1 | head -1

# 3) Python 3.12 venv with PySpark 4.0 + Delta
if [ ! -x "$BASE/venv/bin/python" ]; then
  uv venv --python 3.12 "$BASE/venv" -q
fi
uv pip install --python "$BASE/venv/bin/python" -q "pyspark==4.0.1" "delta-spark==4.0.0" pandas pyarrow
"$BASE/venv/bin/python" -c "import pyspark, delta; print('pyspark', pyspark.__version__)"
echo SETUP_OK
