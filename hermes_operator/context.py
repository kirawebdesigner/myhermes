"""Project context packet generation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from hermes_operator.memory_os import MemoryOS, slugify
from hermes_operator.supabase import SupabaseClient

PROJECT_CONTEXT_FILES = ["README.md", "roadmap.md", "tasks.md", "memory.md", "decisions.md", "status.md"]


@dataclass
class ProjectContextEngine:
    memory: MemoryOS
    supabase: SupabaseClient

    async def build_packet(self, project: str, *, graph_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        project_slug = slugify(project)
        files: dict[str, str | None] = {}
        for filename in PROJECT_CONTEXT_FILES:
            path = f"memory/projects/{project_slug}/{filename}"
            files[filename] = await self.memory.read_memory_file(path)

        recent_tasks = await self._safe_list_rows("tasks", limit=10)
        recent_logs = await self._safe_list_rows("execution_logs", limit=10)
        next_tasks = self._extract_next_tasks(files)
        repo_cache = await self._repo_cache_for_project(project)

        return {
            "project": project,
            "project_slug": project_slug,
            "files": files,
            "graph_summary": graph_summary or {"status": "not_queried", "matched_nodes": [], "matched_edges": []},
            "repo_cache": repo_cache,
            "recent_tasks": self._filter_project_rows(recent_tasks, project),
            "recent_execution_logs": recent_logs,
            "next_tasks": next_tasks,
        }

    async def _repo_cache_for_project(self, project: str) -> list[dict[str, Any]]:
        try:
            tree = await self.memory.github.list_tree(self.memory.memory_repo, prefix="memory/repo_cache/")
        except Exception:
            return []
        project_slug = slugify(project)
        matches: list[dict[str, Any]] = []
        for item in tree:
            path = item.get("path")
            if not path or not str(path).endswith(".json"):
                continue
            try:
                content = await self.memory.github.get_text_file(self.memory.memory_repo, str(path))
                data = json.loads(content or "{}")
            except Exception:
                continue
            if project_slug in self._repo_cache_match_text(data):
                matches.append(data)
        return matches[:10]

    async def _safe_list_rows(self, table: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            return await self.supabase.list_rows(table, limit=limit)
        except Exception:
            return []

    @staticmethod
    def _filter_project_rows(rows: list[dict[str, Any]], project: str) -> list[dict[str, Any]]:
        project_lower = project.lower()
        filtered = [
            row
            for row in rows
            if str(row.get("project", "")).lower() == project_lower
            or project_lower in str(row.get("goal", "")).lower()
            or project_lower in str(row.get("message", "")).lower()
        ]
        return filtered

    @staticmethod
    def _extract_next_tasks(files: dict[str, str | None]) -> list[str]:
        candidates = "\n".join(value or "" for key, value in files.items() if key in {"tasks.md", "roadmap.md", "status.md"})
        tasks: list[str] = []
        for line in candidates.splitlines():
            match = re.match(r"\s*[-*]\s+\[\s\]\s+(.+?)\s*$", line)
            if match:
                tasks.append(match.group(1).strip())
        return tasks

    @staticmethod
    def _repo_cache_match_text(data: dict[str, Any]) -> str:
        values = [
            str(data.get("name", "")),
            str(data.get("repo", "")),
            str(data.get("description", "")),
            str(data.get("related_goal", "")),
            " ".join(map(str, data.get("open_tasks", []))),
            " ".join(map(str, data.get("roadmap", []))),
        ]
        return slugify(" ".join(values))
