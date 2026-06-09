"""GitHub-backed memory operating system."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from re import sub

from hermes_operator.github import GitHubClient
from hermes_operator.models import MemoryRecord, OperatorTask

MEMORY_DIRS = [
    "memory/raw",
    "memory/wiki",
    "memory/projects",
    "memory/archive",
    "memory/prompts",
    "memory/tasks",
    "memory/snapshots",
    "memory/decisions",
    "memory/context",
    "memory/executions",
    "memory/goals",
    "memory/graphify-out",
]

PROJECT_FILES = {
    "README.md": "# {project}\n\nProject overview and current purpose.\n",
    "roadmap.md": "# Roadmap\n\n- [ ] Define next milestone.\n",
    "tasks.md": "# Tasks\n\n- [ ] Capture next actionable task.\n",
    "memory.md": "# Memory\n\nImportant project facts live here.\n",
    "decisions.md": "# Decisions\n\nMajor project decisions and reasons live here.\n",
    "status.md": "# Status\n\nCurrent status: active\n",
}


def slugify(value: str) -> str:
    cleaned = sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    return cleaned or "untitled"


class MemoryOS:
    def __init__(self, github: GitHubClient, memory_repo: str) -> None:
        self.github = github
        self.memory_repo = memory_repo

    async def bootstrap(self) -> None:
        readme = (
            "# Hermes Operator Memory\n\n"
            "This repository stores long-term memory for Hermes Operator.\n\n"
            "GitHub is the source of truth. Supabase is the task queue and vector index.\n"
        )
        await self.github.put_file(
            self.memory_repo,
            "memory/README.md",
            readme,
            "chore(memory): initialize Hermes memory OS",
            enforce_allowlist=False,
        )
        for directory in MEMORY_DIRS:
            await self.github.put_file(
                self.memory_repo,
                f"{directory}/.gitkeep",
                "\n",
                f"chore(memory): ensure {directory}",
                enforce_allowlist=False,
            )

    async def ensure_project(self, project: str) -> None:
        project_slug = slugify(project)
        for filename, template in PROJECT_FILES.items():
            path = str(PurePosixPath("memory/projects") / project_slug / filename)
            existing = await self.github.get_file(self.memory_repo, path)
            if existing:
                continue
            await self.github.put_file(
                self.memory_repo,
                path,
                template.format(project=project),
                f"chore(memory): initialize {project} project continuity",
                enforce_allowlist=False,
            )

    async def save_memory(self, record: MemoryRecord) -> str:
        now = datetime.now(timezone.utc)
        project_part = f"\nProject: {record.project}\n" if record.project else ""
        body = (
            f"# {record.key}\n\n"
            f"Created: {now.isoformat()}\n"
            f"Source: {record.source}\n"
            f"{project_part}\n"
            f"{record.value}\n"
        )
        folder = "memory/raw" if not record.project else f"memory/projects/{slugify(record.project)}"
        path = str(PurePosixPath(folder) / f"{now.strftime('%Y%m%d%H%M%S')}-{slugify(record.key)}.md")
        await self.github.put_file(
            self.memory_repo,
            path,
            body,
            f"chore(memory): save {record.key}",
            enforce_allowlist=False,
        )
        return path

    async def save_task_snapshot(self, task: OperatorTask) -> str:
        now = datetime.now(timezone.utc)
        path = f"memory/tasks/{now.strftime('%Y%m%d%H%M%S')}-{slugify(task.goal)}.md"
        content = (
            f"# Task: {task.goal}\n\n"
            f"- ID: {task.id}\n"
            f"- Status: {task.status.value}\n"
            f"- Project: {task.project or 'none'}\n"
            f"- Repo: {task.repo or 'none'}\n\n"
            f"## Result\n\n{task.result or task.error or 'Pending'}\n"
        )
        await self.github.put_file(
            self.memory_repo,
            path,
            content,
            f"chore(memory): record task {task.id}",
            enforce_allowlist=False,
        )
        return path

    async def memory_file_paths(self) -> list[str]:
        files = await self.github.list_tree(self.memory_repo, prefix="memory/")
        return [
            item["path"]
            for item in files
            if item.get("path")
            and not str(item["path"]).startswith("memory/graphify-out/")
            and not str(item["path"]).endswith(".gitkeep")
        ]

    async def read_memory_file(self, path: str) -> str | None:
        return await self.github.get_text_file(self.memory_repo, path)
