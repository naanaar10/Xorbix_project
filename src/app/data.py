"""Reads and writes for the app, through the SQL warehouse as the app's service principal."""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chiro_agent.config import Settings  # noqa: E402
from chiro_agent.db import Warehouse  # noqa: E402
from databricks.sdk import WorkspaceClient  # noqa: E402


@st.cache_resource
def settings() -> Settings:
    return Settings.from_env()


@st.cache_resource
def workspace() -> WorkspaceClient:
    return WorkspaceClient()


@st.cache_resource
def warehouse() -> Warehouse:
    return Warehouse(workspace(), settings().warehouse_id)


def table(name: str) -> str:
    return f"{settings().fq}.{name}"


@st.cache_data(ttl=60, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.DataFrame(warehouse().query(sql, dict(params)))


def refresh() -> None:
    query.clear()


def runs() -> pd.DataFrame:
    return query(f"SELECT * FROM {table('agent_runs')} ORDER BY started_at DESC LIMIT 25")


def kpis() -> pd.DataFrame:
    return query(f"""SELECT location_id, location_name, city, state, annual_revenue, plan_completion_rate,
                       lead_conversion_rate, median_response_hours, no_show_rate, am_utilization,
                       pm_utilization, at_risk_patients, total_revenue_at_stake, largest_lever, stake_rank
                     FROM {table('clinic_kpis')} ORDER BY stake_rank""")


def diagnoses(run_id: str) -> pd.DataFrame:
    return query(f"""SELECT d.*, k.city FROM {table('clinic_diagnoses')} d
                     JOIN {table('clinic_kpis')} k ON d.location_id = k.location_id
                     WHERE d.run_id = :run_id ORDER BY d.revenue_at_stake DESC""", (("run_id", run_id),))


def actions(run_id: str) -> pd.DataFrame:
    return query(f"""SELECT * FROM {table('action_queue')} WHERE run_id = :run_id
                     ORDER BY location_id, arm, expected_value DESC""", (("run_id", run_id),))


def impact(run_id: str) -> pd.DataFrame:
    return query(f"SELECT * FROM {table('impact_summary')} WHERE run_id = :run_id",
                 (("run_id", run_id),))


def steps(run_id: str) -> pd.DataFrame:
    return query(f"SELECT * FROM {table('agent_steps')} WHERE run_id = :run_id ORDER BY step",
                 (("run_id", run_id),))


def save_decisions(rows: list[dict]) -> None:
    for r in rows:
        warehouse().query(
            f"""UPDATE {table('action_queue')}
                SET status = :status, message = :message, reviewed_at = current_timestamp()
                WHERE action_id = :action_id""",
            {"status": r["status"], "message": r["message"], "action_id": r["action_id"]})
    refresh()
