"""SQL through the Databricks SQL warehouse, so the same code runs in jobs and in the app."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

_NUMERIC_INT = {"INT", "LONG", "BIGINT", "SHORT", "SMALLINT", "TINYINT", "BYTE"}
_NUMERIC_FLOAT = {"DOUBLE", "FLOAT", "DECIMAL"}


def _param(name: str, value: Any) -> StatementParameterListItem:
    if value is None:
        return StatementParameterListItem(name=name, type="STRING")
    if isinstance(value, bool):
        return StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN")
    if isinstance(value, int):
        return StatementParameterListItem(name=name, value=str(value), type="INT")
    if isinstance(value, float):
        return StatementParameterListItem(name=name, value=repr(value), type="DOUBLE")
    if isinstance(value, datetime):
        return StatementParameterListItem(name=name, value=value.isoformat(sep=" "), type="TIMESTAMP")
    if isinstance(value, date):
        return StatementParameterListItem(name=name, value=value.isoformat(), type="DATE")
    return StatementParameterListItem(name=name, value=str(value), type="STRING")


def _convert(value: str | None, type_name: str) -> Any:
    if value is None:
        return None
    if type_name in _NUMERIC_INT:
        return int(value)
    if type_name in _NUMERIC_FLOAT:
        return float(value)
    if type_name == "BOOLEAN":
        return value.lower() == "true"
    return value


class Warehouse:
    def __init__(self, w: WorkspaceClient, warehouse_id: str):
        self.w = w
        self.warehouse_id = warehouse_id

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        stmt = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id,
            statement=sql,
            parameters=[_param(k, v) for k, v in (params or {}).items()],
            wait_timeout="50s",
        )
        while stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            stmt = self.w.statement_execution.get_statement(stmt.statement_id)
        if stmt.status.state != StatementState.SUCCEEDED:
            message = stmt.status.error.message if stmt.status.error else stmt.status.state
            raise RuntimeError(f"SQL failed: {message}")
        if not stmt.manifest or not stmt.result:
            return []
        columns = [(c.name, c.type_name.value if c.type_name else "STRING")
                   for c in stmt.manifest.schema.columns]
        return [{name: _convert(v, t) for (name, t), v in zip(columns, row)}
                for row in (stmt.result.data_array or [])]

    def insert(self, table: str, rows: list[dict[str, Any]], batch: int = 8) -> None:
        """Insert dict rows with bound parameters (safe for LLM-written text)."""
        if not rows:
            return
        columns = list(rows[0])
        for start in range(0, len(rows), batch):
            chunk = rows[start:start + batch]
            params, values = {}, []
            for i, row in enumerate(chunk):
                names = []
                for c in columns:
                    if row.get(c) is None:
                        names.append("NULL")
                        continue
                    key = f"{c}_{i}"
                    params[key] = row[c]
                    names.append(f":{key}")
                values.append(f"({', '.join(names)})")
            self.query(f"INSERT INTO {table} ({', '.join(columns)}) VALUES {', '.join(values)}", params)
