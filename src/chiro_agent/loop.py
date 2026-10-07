"""A plain tool-calling loop over any OpenAI-compatible chat endpoint, traced with MLflow."""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

import mlflow

from chiro_agent.tools import ToolRegistry

# gpt-oss returns reasoning blocks in `content`; the OpenAI SDK's pydantic models warn about it.
warnings.filterwarnings("ignore", message=".*PydanticSerializationUnexpectedValue.*")
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")


@dataclass
class AgentResult:
    final_text: str
    steps: list[dict] = field(default_factory=list)
    stopped_early: bool = False


def message_text(content: Any) -> str:
    """Endpoints may return plain text or a list of blocks (e.g. reasoning + text)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        block = block if isinstance(block, dict) else getattr(block, "__dict__", {})
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def run_agent(client, model: str, name: str, system: str, user: str, registry: ToolRegistry,
              max_steps: int = 20, on_step: Callable[[dict], None] | None = None,
              max_tokens: int = 2000, unfinished: Callable[[], str | None] | None = None,
              max_nudges: int = 2) -> AgentResult:
    """Call the model, run any tool calls it asks for, feed results back, repeat until it answers.

    `unfinished` can return a reminder when the agent tries to stop with work left; the reminder is
    sent back as a user message (at most `max_nudges` times)."""
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    result = AgentResult(final_text="")

    def record(step: dict):
        step = {"agent": name, "step": len(result.steps) + 1, **step}
        result.steps.append(step)
        if on_step:
            on_step(step)

    with mlflow.start_span(name=name, span_type="AGENT") as span:
        span.set_inputs({"task": user})
        for _ in range(max_steps):
            response = client.chat.completions.create(
                model=model, messages=messages, tools=registry.specs(), max_tokens=max_tokens,
                temperature=0.1)
            msg = response.choices[0].message
            text = message_text(msg.content)
            if not msg.tool_calls:
                reminder = unfinished() if unfinished and max_nudges > 0 else None
                if reminder:
                    max_nudges -= 1
                    messages.append({"role": "assistant", "content": text or "Done."})
                    messages.append({"role": "user", "content": reminder})
                    record({"kind": "nudge", "name": "reminder", "arguments": "", "result_preview": reminder})
                    continue
                result.final_text = text
                record({"kind": "answer", "name": "final", "arguments": "", "result_preview": text[:2000]})
                break
            messages.append({"role": "assistant", "content": text or None,
                             "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                output = registry.call(tc.function.name, args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
                record({"kind": "tool", "name": tc.function.name,
                        "arguments": json.dumps(args, default=str), "result_preview": output[:1500]})
        else:
            result.stopped_early = True
            result.final_text = "Stopped after reaching the step limit."
        span.set_outputs({"final": result.final_text, "tool_calls": len(result.steps)})
    return result
