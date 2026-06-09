"""KirzKit-first implementation planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes_operator.skill_sources import SkillSourceRegistry


@dataclass
class KirzKitPlanner:
    sources: SkillSourceRegistry

    def plan(self, goal: str, *, project: str | None = None) -> dict[str, Any]:
        queries = self._queries(goal)
        matches: list[dict[str, Any]] = []
        for query in queries:
            matches.extend(self.sources.search(query))
        deduped = self._dedupe(matches)
        workflows = [item for item in deduped if item["kind"] == "workflow"]
        skills = [item for item in deduped if item["kind"] == "skill"]
        agents = [item for item in deduped if item["kind"] == "agent"]
        return {
            "goal": goal,
            "project": project,
            "queries": queries,
            "recommended_workflows": workflows[:8],
            "recommended_skills": skills[:12],
            "recommended_agents": agents[:8],
            "implementation_sequence": self._sequence(goal),
        }

    @staticmethod
    def _queries(goal: str) -> list[str]:
        lower = goal.lower()
        queries = ["plan", "project"]
        if any(term in lower for term in ["ui", "frontend", "landing", "website", "dashboard"]):
            queries.extend(["frontend", "ui", "web-design", "tailwind"])
        if "supabase" in lower or "database" in lower:
            queries.extend(["supabase", "database"])
        if "deploy" in lower or "deployment" in lower:
            queries.extend(["deploy", "deployment"])
        if "docs" in lower or "documentation" in lower:
            queries.extend(["documentation", "docs"])
        if "test" in lower or "qa" in lower:
            queries.extend(["test", "playwright"])
        return list(dict.fromkeys(queries))

    @staticmethod
    def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            key = (item.get("source", ""), item.get("kind", ""), item.get("name", ""))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _sequence(goal: str) -> list[str]:
        return [
            "Load project context packet.",
            "Query Graphify for related decisions, tasks, and memories.",
            "Use KirzKit recommended workflows and skills before inventing patterns.",
            f"Draft implementation steps for: {goal}",
            "Execute only safe or approved skills.",
            "Save replay, memory update, and graph update.",
        ]
