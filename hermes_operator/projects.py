"""Project registry and status helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from hermes_operator.context import ProjectContextEngine
from hermes_operator.memory_os import MemoryOS, slugify
from hermes_operator.supabase import SupabaseClient


@dataclass
class ProjectRegistry:
    memory: MemoryOS
    supabase: SupabaseClient
    context: ProjectContextEngine

    async def list_projects(self) -> list[dict[str, Any]]:
        names: set[str] = set()
        for item in await self.memory.github.list_tree(self.memory.memory_repo, prefix="memory/projects/"):
            path = str(item.get("path", ""))
            parts = PurePosixPath(path).parts
            if len(parts) >= 3 and parts[0] == "memory" and parts[1] == "projects":
                names.add(parts[2])
        for row in await self._safe_rows("projects"):
            name = row.get("name")
            if name:
                names.add(slugify(str(name)))
        return [{"slug": name, "name": name, "status": "active"} for name in sorted(names)]

    async def status(self, project: str, *, graph_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        packet = await self.context.build_packet(project, graph_summary=graph_summary)
        files = packet["files"]
        executions = [
            row
            for row in await self._safe_rows("execution_replays", limit=10)
            if str(row.get("project", "")).lower() == project.lower()
        ]
        return {
            "project": project,
            "project_slug": packet["project_slug"],
            "files_present": sorted(name for name, content in files.items() if content),
            "files_missing": sorted(name for name, content in files.items() if not content),
            "next_tasks": packet["next_tasks"],
            "recent_tasks_count": len(packet["recent_tasks"]),
            "recent_execution_logs_count": len(packet["recent_execution_logs"]),
            "recent_executions": executions,
            "graph_status": (graph_summary or packet["graph_summary"]).get("status"),
            "graph_matches": {
                "nodes": len((graph_summary or packet["graph_summary"]).get("matched_nodes", [])),
                "edges": len((graph_summary or packet["graph_summary"]).get("matched_edges", [])),
            },
        }

    async def _safe_rows(self, table: str, *, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return await self.supabase.list_rows(table, limit=limit)
        except Exception:
            return []
