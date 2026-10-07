"""Observe: create output tables, rebuild the clinic KPI snapshot, (re)install the agent tools in
Unity Catalog, and let the app's service principal read and write the schema."""
import argparse
import sys

from pyspark.sql import SparkSession


def main():
    p = argparse.ArgumentParser()
    for name in ("--catalog", "--schema", "--src-dir", "--app-name"):
        p.add_argument(name, required=True)
    args = p.parse_args()
    sys.path.insert(0, args.src_dir)
    from chiro_agent.sqlfiles import statements

    spark = SparkSession.builder.getOrCreate()
    fq = f"{args.catalog}.{args.schema}"
    for filename in ("output_tables.sql", "observe.sql", "tools.sql"):
        for sql in statements(filename, fq):
            spark.sql(sql)
        print(f"Ran {filename}")
    grant_app_access(spark, args.catalog, fq, args.app_name)


def grant_app_access(spark, catalog: str, fq: str, app_name: str):
    from databricks.sdk import WorkspaceClient
    try:
        sp = WorkspaceClient().apps.get(app_name).service_principal_client_id
    except Exception as e:  # noqa: BLE001 - the app may not be deployed yet
        print(f"Skipping app grants ({app_name} not found: {e})")
        return
    spark.sql(f"GRANT USE CATALOG ON CATALOG {catalog} TO `{sp}`")
    spark.sql(f"GRANT USE SCHEMA, SELECT, EXECUTE, MODIFY ON SCHEMA {fq} TO `{sp}`")
    print(f"Granted {app_name} access to {fq}")


if __name__ == "__main__":
    main()
