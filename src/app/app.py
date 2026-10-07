"""Smoke-test app: confirms the app can reach the SQL warehouse, our schema and the LLM."""
import os

import streamlit as st
from databricks.sdk import WorkspaceClient

st.set_page_config(page_title="Chiro Growth Director", layout="wide")
st.title("Chiro Growth Director: smoke test")

w = WorkspaceClient()
warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
fq = f"{os.environ['CHIRO_CATALOG']}.{os.environ['CHIRO_SCHEMA']}"


def run_sql(sql: str):
    stmt = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout="50s"
    )
    if stmt.status.error:
        return f"ERROR: {stmt.status.error.message}"
    return stmt.result.data_array if stmt.result else []


st.subheader("Warehouse")
st.write(run_sql("SELECT current_user(), current_catalog()"))

st.subheader(f"Schema {fq}")
st.write(run_sql(f"SELECT * FROM {fq}.smoke_kpis('LOC003')"))

st.subheader("LLM")
try:
    client = w.serving_endpoints.get_open_ai_client()
    resp = client.chat.completions.create(
        model=os.environ["LLM_ENDPOINT"],
        messages=[{"role": "user", "content": "Reply with exactly: app can reach the LLM"}],
        max_tokens=50,
    )
    st.write(resp.choices[0].message.content)
except Exception as e:  # noqa: BLE001
    st.error(f"LLM call failed: {e}")
