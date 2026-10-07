"""Measure: simulate outcomes for new retention actions and compare agent vs generic vs holdout."""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser()
    for name in ("--catalog", "--schema", "--warehouse-id", "--src-dir"):
        p.add_argument(name, required=True)
    args = p.parse_args()
    sys.path.insert(0, args.src_dir)

    from databricks.sdk import WorkspaceClient
    from chiro_agent.db import Warehouse
    from chiro_agent.measure import measure_unmeasured_runs

    results = measure_unmeasured_runs(Warehouse(WorkspaceClient(), args.warehouse_id),
                                      f"{args.catalog}.{args.schema}")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
