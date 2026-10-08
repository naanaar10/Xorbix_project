"""Tool registry. Read tools are Unity Catalog functions, discovered from their UC metadata;
write tools are Python functions. Every call is an MLflow TOOL span."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import mlflow
from databricks.sdk import WorkspaceClient

from chiro_agent.db import Warehouse

MAX_ROWS_TO_LLM = 40
_JSON_TYPES = {"STRING": "string", "INT": "integer", "BIGINT": "integer", "DOUBLE": "number",
               "BOOLEAN": "boolean", "DATE": "string"}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], Any]

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.parameters}}


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def subset(self, names: list[str]) -> "ToolRegistry":
        return ToolRegistry({n: self.tools[n] for n in names})

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def fetch(self, name: str, args: dict) -> Any:
        """Run a tool for code (not the LLM): full results, still traced."""
        with mlflow.start_span(name=name, span_type="TOOL") as span:
            span.set_inputs(args)
            result = self.tools[name].run(args)
            span.set_outputs({"rows": len(result) if isinstance(result, list) else result})
        return result

    def call(self, name: str, args: dict) -> str:
        """Run a tool and return a compact JSON string for the LLM. Errors go back to the LLM."""
        with mlflow.start_span(name=name, span_type="TOOL") as span:
            span.set_inputs(args)
            try:
                if name not in self.tools:
                    raise ValueError(f"Unknown tool {name}. Available: {sorted(self.tools)}")
                result = self.tools[name].run(args)
            except Exception as e:  # noqa: BLE001 - the agent should see and recover from tool errors
                result = {"error": str(e)[:500]}
            span.set_outputs(result)
        return _to_llm_text(result)


def _to_llm_text(result: Any) -> str:
    if isinstance(result, list) and len(result) > MAX_ROWS_TO_LLM:
        result = {"rows": result[:MAX_ROWS_TO_LLM], "note": f"{len(result) - MAX_ROWS_TO_LLM} more rows omitted"}
    return json.dumps(result, default=str, separators=(",", ":"))


def uc_tool(w: WorkspaceClient, wh: Warehouse, full_name: str) -> Tool:
    """Build a tool from a Unity Catalog table function's own metadata."""
    fn = w.functions.get(full_name)
    properties, required = {}, []
    for p in (fn.input_params.parameters if fn.input_params else []):
        properties[p.name] = {"type": _JSON_TYPES.get(p.type_text.upper(), "string"),
                              "description": p.comment or ""}
        if p.parameter_default is None:
            required.append(p.name)
    param_names = list(properties)

    def run(args: dict) -> list[dict]:
        given = {k: v for k, v in args.items() if k in param_names and v is not None}
        call_args = ", ".join(f"{k} => :{k}" for k in given)
        return wh.query(f"SELECT * FROM {full_name}({call_args})", given)

    return Tool(name=fn.name, description=fn.comment or fn.name,
                parameters={"type": "object", "properties": properties, "required": required},
                run=run)


def load_uc_tools(w: WorkspaceClient, wh: Warehouse, fq: str, names: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.add(uc_tool(w, wh, f"{fq}.{name}"))
    return registry


UC_TOOL_NAMES = [
    "get_network_kpis", "compare_clinic_to_network", "get_dropoff_by_visit_number",
    "get_cancellation_reasons", "get_provider_breakdown", "get_lead_response_stats",
    "get_capacity_by_daypart", "find_at_risk_patients", "get_patient_history", "find_open_slots",
    "get_stale_leads", "find_reactivation_candidates", "get_intervention_performance",
    "get_marketing_channels", "price_budget_shift",
]
