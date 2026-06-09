"""Skill-based execution engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hermes_operator.skills import SkillRegistry


@dataclass
class ExecutionEngine:
    registry: SkillRegistry
    allow_tier_1_5_auto: bool = True

    def plan_from_goal(self, goal: str, *, project: str | None = None, repo: str | None = None) -> list[dict[str, Any]]:
        lower = goal.lower()
        if repo and any(word in lower for word in ("edit", "write", "update file", "change file")):
            branch = f"hermes/{self._project_from_goal(project or goal).lower()}"
            return [
                {"skill": "project_context", "inputs": {"project": project or self._project_from_goal(goal)}},
                {"skill": "github_branch_create", "inputs": {"repo": repo, "branch": branch}},
            ]
        if "graph" in lower and any(word in lower for word in ("rebuild", "update", "refresh", "regenerate")):
            return [{"skill": "graphify_rebuild", "inputs": {"goal": goal}}]
        if "graph" in lower:
            return [{"skill": "graph_query", "inputs": {"query": project or goal}}]
        if lower.startswith("plan goal") or "goal plan" in lower:
            return [{"skill": "goal_plan", "inputs": {"goal": goal}}]
        if "search memory" in lower or "find memory" in lower:
            return [{"skill": "memory_search", "inputs": {"query": goal}}]
        if "remember" in lower or "memory" in lower:
            return [{"skill": "memory_save", "inputs": {"key": project or "note", "value": goal, "project": project}}]
        if any(term in lower for term in ("kirzkit", "landing", "website", "dashboard", "frontend", "ui")):
            return [{"skill": "kirzkit_generate_plan", "inputs": {"goal": goal, "project": project}}]
        if "continue" in lower or project:
            return [{"skill": "project_context", "inputs": {"project": project or self._project_from_goal(goal)}}]
        return [{"skill": "task_create", "inputs": {"goal": goal, "project": project}}]

    async def execute_plan(
        self,
        plan: list[dict[str, Any]],
        *,
        stop_on_failure: bool = True,
        approved_skills: set[str] | None = None,
    ) -> dict[str, Any]:
        execution_id = str(uuid4())
        steps: list[dict[str, Any]] = []
        status = "completed"
        shared_context: dict[str, Any] = {}
        approved = approved_skills or set()
        for item in plan:
            skill = item.get("skill")
            inputs = self._resolve_inputs(item.get("inputs") or {}, shared_context)
            definition = self.registry.get(skill)
            blocked_reason = self._blocked_reason(skill, definition, approved)
            if blocked_reason:
                step = {
                    "skill": skill,
                    "inputs": inputs,
                    "ok": False,
                    "output": None,
                    "error": None,
                    "blocked_reason": blocked_reason,
                    "autonomy_tier": definition.autonomy_tier if definition else None,
                }
                steps.append(step)
                status = "blocked"
                if stop_on_failure:
                    break
                continue
            result = await self.registry.execute(skill, inputs)
            step = {
                "skill": skill,
                "inputs": inputs,
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
                "blocked_reason": None,
                "autonomy_tier": definition.autonomy_tier if definition else None,
            }
            steps.append(step)
            if result.ok:
                shared_context[skill] = result.output
            if not result.ok:
                if stop_on_failure:
                    status = "failed"
                    break
                status = "completed_with_errors"
        return {"execution_id": execution_id, "status": status, "steps": steps}

    async def execute_goal(self, goal: str, *, project: str | None = None, repo: str | None = None) -> dict[str, Any]:
        plan = self.plan_from_goal(goal, project=project, repo=repo)
        result = await self.execute_plan(plan)
        result["goal"] = goal
        result["plan"] = plan
        return result

    def _blocked_reason(self, skill: str, definition, approved: set[str]) -> str | None:
        if definition is None:
            return None
        if definition.autonomy_tier >= 3:
            return f"{skill} is Tier 3 manual-only."
        if definition.requires_approval and skill not in approved:
            return f"{skill} requires approval."
        if definition.autonomy_tier == 1.5 and not self.allow_tier_1_5_auto and skill not in approved:
            return f"{skill} is Tier 1.5 and optional auto execution is disabled."
        if definition.autonomy_tier >= 2 and skill not in approved:
            return f"{skill} is Tier {definition.autonomy_tier} and requires approval."
        return None

    @staticmethod
    def _resolve_inputs(inputs: dict[str, Any], shared_context: dict[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in inputs.items():
            if isinstance(value, str) and value.startswith("$steps."):
                resolved[key] = shared_context.get(value.removeprefix("$steps."))
            else:
                resolved[key] = value
        return resolved

    @staticmethod
    def _project_from_goal(goal: str) -> str:
        words = goal.split()
        if words and words[0].lower() == "continue" and len(words) > 1:
            return words[1].strip(" .,:;")
        return "default"
