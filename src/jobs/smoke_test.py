"""Smoke test: proves each platform feature the agent relies on works in this workspace.

Checks: UC SQL table function, UC Python function, SQL warehouse statement execution,
LLM tool calling through the serving endpoint, and MLflow tracing.
"""
import argparse
import json

import mlflow
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--warehouse-id", required=True)
    p.add_argument("--llm-endpoint", required=True)
    p.add_argument("--experiment-id", required=True)
    return p.parse_args()


def main():
    args = parse_args()
    fq = f"{args.catalog}.{args.schema}"
    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    results = {}

    # 1. UC SQL table function, created and called from Spark.
    spark.sql(f"""
        CREATE OR REPLACE FUNCTION {fq}.smoke_kpis(clinic STRING)
        RETURNS TABLE (location_id STRING, completion_rate DOUBLE)
        COMMENT 'Smoke-test table function'
        RETURN SELECT clinic AS location_id, 0.42 AS completion_rate
    """)
    rows = spark.sql(f"SELECT * FROM {fq}.smoke_kpis('LOC007')").collect()
    results["uc_sql_table_function"] = rows[0].asDict()

    # 2. UC Python function (optional: we fall back to SQL if unsupported).
    try:
        spark.sql(f"""
            CREATE OR REPLACE FUNCTION {fq}.smoke_py(x DOUBLE) RETURNS DOUBLE
            LANGUAGE PYTHON AS $$ return x * 2 $$
        """)
        results["uc_python_function"] = spark.sql(f"SELECT {fq}.smoke_py(21.0) AS v").collect()[0]["v"]
    except Exception as e:  # noqa: BLE001
        results["uc_python_function"] = f"UNSUPPORTED: {str(e)[:200]}"

    # 3. Same table function through the SQL warehouse (the path the app and agents use).
    stmt = w.statement_execution.execute_statement(
        warehouse_id=args.warehouse_id,
        statement=f"SELECT * FROM {fq}.smoke_kpis('LOC012')",
        wait_timeout="50s",
    )
    results["warehouse_statement"] = {
        "state": str(stmt.status.state),
        "rows": stmt.result.data_array if stmt.result else None,
    }

    # 4 + 5. LLM tool call, traced to MLflow.
    mlflow.set_experiment(experiment_id=args.experiment_id)
    mlflow.openai.autolog()
    client = w.serving_endpoints.get_open_ai_client()
    tools = [{
        "type": "function",
        "function": {
            "name": "smoke_kpis",
            "description": "Return care-plan completion rate for a clinic.",
            "parameters": {
                "type": "object",
                "properties": {"clinic": {"type": "string"}},
                "required": ["clinic"],
            },
        },
    }]

    @mlflow.trace(span_type="AGENT", name="smoke_agent")
    def ask():
        return client.chat.completions.create(
            model=args.llm_endpoint,
            messages=[{"role": "user", "content": "What is the completion rate at LOC007?"}],
            tools=tools,
            max_tokens=300,
        )

    resp = ask()
    msg = resp.choices[0].message
    results["llm_tool_call"] = (
        [{"name": t.function.name, "args": t.function.arguments} for t in msg.tool_calls]
        if msg.tool_calls else f"NO TOOL CALL: {msg.content}"
    )
    results["mlflow_trace_id"] = mlflow.get_last_active_trace_id()

    print("SMOKE TEST RESULTS")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
