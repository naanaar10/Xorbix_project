#!/usr/bin/env bash
# Run the Backbone app on this machine against a deployed bundle target (default: dev).
# Names and ids come from `databricks bundle summary`, and it uses your Databricks CLI login.
# Open http://localhost:8000 once uvicorn says it is running.
set -euo pipefail
target="${1:-dev}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
eval "$(databricks bundle summary -t "$target" -o json | python3 -c '
import json, shlex, sys
s = json.load(sys.stdin)
v, r = s["variables"], s["resources"]
env = {
    "DATABRICKS_CONFIG_PROFILE": s["workspace"].get("profile") or "DEFAULT",
    "CHIRO_CATALOG": r["schemas"]["chiro_growth"]["catalog_name"],
    "CHIRO_SCHEMA": r["schemas"]["chiro_growth"]["name"],
    "DATABRICKS_WAREHOUSE_ID": v["warehouse_id"]["value"],
    "LLM_ENDPOINT": v["llm_endpoint"]["value"],
    "MLFLOW_EXPERIMENT_ID": r["experiments"]["agent_traces"].get("id") or "",
}
for key, value in env.items():
    print(f"export {key}={shlex.quote(str(value))}")
')"
cd "$root/src"
exec uv run --project "$root" --group dev python -m app.server
