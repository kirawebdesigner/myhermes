"""Execution replay persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hermes_operator.memory_os import MemoryOS, slugify


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if hasattr(value, "__dict__"):
        return json_safe(value.__dict__)
    return str(value)


@dataclass
class ReplayStore:
    memory: MemoryOS

    async def save(self, replay: dict[str, Any]) -> dict[str, str]:
        safe = json_safe(replay)
        execution_id = safe["execution_id"]
        goal_slug = slugify(str(safe.get("goal", execution_id)))[:80]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        base_path = f"memory/executions/{timestamp}-{goal_slug}-{execution_id}"
        json_path = f"{base_path}.json"
        markdown_path = f"{base_path}.md"

        await self.memory.github.put_file(
            self.memory.memory_repo,
            json_path,
            json.dumps(safe, indent=2, ensure_ascii=False),
            f"chore(execution): save replay {execution_id}",
            enforce_allowlist=False,
        )
        await self.memory.github.put_file(
            self.memory.memory_repo,
            markdown_path,
            self._markdown(safe),
            f"chore(execution): summarize replay {execution_id}",
            enforce_allowlist=False,
        )
        return {"json_path": json_path, "markdown_path": markdown_path}

    @staticmethod
    def _markdown(replay: dict[str, Any]) -> str:
        lines = [
            f"# Execution Replay: {replay.get('goal', replay.get('execution_id'))}",
            "",
            f"- Execution ID: `{replay.get('execution_id')}`",
            f"- Status: `{replay.get('status')}`",
            f"- Project: `{replay.get('project') or 'none'}`",
            "",
            "## Plan",
            "",
        ]
        for step in replay.get("plan", []):
            lines.append(f"- `{step.get('skill')}`")
        lines.extend(["", "## Steps", ""])
        for step in replay.get("steps", []):
            status = "ok" if step.get("ok") else "failed"
            lines.append(f"- `{step.get('skill')}`: {status}")
            if step.get("blocked_reason"):
                lines.append(f"  - Blocked: {step['blocked_reason']}")
            if step.get("error"):
                lines.append(f"  - Error: {step['error']}")
        lines.extend(["", "## Final Result", "", str(replay.get("final_result", ""))])
        return "\n".join(lines) + "\n"
