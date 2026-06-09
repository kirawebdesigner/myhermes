"""Goal -> projects -> tasks planning helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hermes_operator.memory_os import MemoryOS, slugify
from hermes_operator.supabase import SupabaseClient


@dataclass
class GoalPlanner:
    supabase: SupabaseClient
    memory: MemoryOS

    async def create_plan(
        self,
        goal: str,
        *,
        projects: list[str] | None = None,
        tasks: list[str] | None = None,
    ) -> dict[str, Any]:
        project_names = projects or [self._project_from_goal(goal)]
        task_names = tasks or self._default_tasks(goal)
        goal_row = await self.supabase.insert(
            "goals",
            {"title": goal, "status": "active", "metadata": {"source": "goal_planner"}},
        )
        project_rows = []
        task_rows = []
        for project in project_names:
            await self.memory.ensure_project(project)
            project_rows.append(
                await self.supabase.insert(
                    "projects",
                    {
                        "goal_id": goal_row.get("id"),
                        "name": project,
                        "status": "active",
                        "metadata": {"goal": goal},
                    },
                )
            )
            for task in task_names:
                task_rows.append(
                    await self.supabase.insert(
                        "tasks",
                        {
                            "id": str(uuid4()),
                            "goal": task,
                            "status": "queued",
                            "project": project,
                            "metadata": {"parent_goal": goal},
                        },
                    )
                )
        path = await self._write_goal_memory(goal, project_names, task_names)
        await self.supabase.insert(
            "goal_plans",
            {
                "goal_id": goal_row.get("id"),
                "title": goal,
                "memory_path": path,
                "metadata": {"projects": project_names, "tasks": task_names},
            },
        )
        return {"goal": goal_row, "projects": project_rows, "tasks": task_rows, "memory_path": path}

    async def _write_goal_memory(self, goal: str, projects: list[str], tasks: list[str]) -> str:
        path = f"memory/goals/{slugify(goal)}.md"
        content = (
            f"# {goal}\n\n"
            "## Projects\n\n"
            + "\n".join(f"- {project}" for project in projects)
            + "\n\n## Tasks\n\n"
            + "\n".join(f"- [ ] {task}" for task in tasks)
            + "\n"
        )
        await self.memory.github.put_file(
            self.memory.memory_repo,
            path,
            content,
            f"chore(goal): plan {goal}",
            enforce_allowlist=False,
        )
        return path

    @staticmethod
    def _project_from_goal(goal: str) -> str:
        words = [word.strip(" .,:;") for word in goal.split() if word.strip(" .,:;")]
        return " ".join(words[:3]) or "Default Project"

    @staticmethod
    def _default_tasks(goal: str) -> list[str]:
        return [
            f"Define success criteria for {goal}",
            f"Build context packet for {goal}",
            f"Create first safe execution plan for {goal}",
        ]
