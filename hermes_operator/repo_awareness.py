"""Repository awareness helpers for Hermes Operator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from hermes_operator.github import GitHubClient
from hermes_operator.memory_os import MemoryOS, slugify
from hermes_operator.supabase import SupabaseClient


IMPORTANT_FILES = [
    "README.md",
    "README.rst",
    "README.txt",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "Dockerfile.choreo",
    "docker-compose.yml",
    "supabase/config.toml",
]


@dataclass
class RepoAwareness:
    github: GitHubClient
    memory: MemoryOS
    supabase: SupabaseClient

    async def build_context(self, repo: str, *, ref: str | None = None, cache: bool = True) -> dict[str, Any]:
        self.github.safety.require_allowed_repo(repo)
        repo_info = await self.github.get_repo(repo)
        tree = await self.github.list_tree(repo, ref=ref)
        paths = sorted(str(item.get("path", "")) for item in tree if item.get("path"))
        documents = await self._read_important_files(repo, paths, ref=ref)
        context = {
            "repo": repo,
            "default_branch": repo_info.get("default_branch") or "main",
            "description": repo_info.get("description"),
            "visibility": repo_info.get("visibility"),
            "html_url": repo_info.get("html_url"),
            "stack": self._detect_stack(paths),
            "important_files": sorted(documents),
            "file_count": len(paths),
            "top_level": self._top_level(paths),
            "documents": documents,
            "next_actions": self._next_actions(paths, documents),
        }
        if cache:
            context["memory_path"] = await self.cache_context(context)
        return context

    async def cache_context(self, context: dict[str, Any]) -> str:
        repo_slug = slugify(context["repo"].replace("/", "-"))
        path = str(PurePosixPath("memory/context/repos") / f"{repo_slug}.md")
        content = self._render_context(context)
        await self.memory.github.put_file(
            self.memory.memory_repo,
            path,
            content,
            f"chore(memory): cache repo context for {context['repo']}",
            enforce_allowlist=False,
        )
        await self.supabase.insert(
            "documents",
            {
                "source": "github-repo-context",
                "path": path,
                "title": f"Repo context: {context['repo']}",
                "content": content,
                "metadata": {"repo": context["repo"], "stack": context["stack"]},
            },
        )
        return path

    async def _read_important_files(self, repo: str, paths: list[str], *, ref: str | None = None) -> dict[str, str]:
        available = {path.lower(): path for path in paths}
        docs: dict[str, str] = {}
        for filename in IMPORTANT_FILES:
            path = available.get(filename.lower())
            if not path:
                continue
            content = await self.github.get_text_file(repo, path, ref=ref)
            if content:
                docs[path] = content[:4000]
        return docs

    @staticmethod
    def _detect_stack(paths: list[str]) -> list[str]:
        lower = {path.lower() for path in paths}
        stack: list[str] = []
        checks = [
            ("Python", ("pyproject.toml", "requirements.txt", "setup.py")),
            ("FastAPI", ("fastapi",)),
            ("Node.js", ("package.json", "pnpm-lock.yaml", "package-lock.json")),
            ("Docker", ("dockerfile", "dockerfile.choreo", "docker-compose.yml")),
            ("Supabase", ("supabase/config.toml", "supabase/migrations")),
            ("Choreo", ("dockerfile.choreo", ".choreo/component.yaml")),
            ("React", ("vite.config", "next.config", "src/app", "app/")),
        ]
        joined = "\n".join(lower)
        for name, needles in checks:
            if any(needle in lower or needle in joined for needle in needles):
                stack.append(name)
        return stack or ["Unknown"]

    @staticmethod
    def _top_level(paths: list[str]) -> list[str]:
        roots = sorted({path.split("/", 1)[0] for path in paths if path})
        return roots[:80]

    @staticmethod
    def _next_actions(paths: list[str], documents: dict[str, str]) -> list[str]:
        actions: list[str] = []
        if "README.md" not in documents:
            actions.append("Add or update README.md so Hermes can understand this repo faster.")
        if "Dockerfile.choreo" in paths:
            actions.append("Verify the Choreo endpoint and environment variables after each deploy.")
        if any(path.startswith("tests/") for path in paths):
            actions.append("Run focused tests before making repo changes.")
        if not actions:
            actions.append("Review README, file tree, and open project memory before planning changes.")
        return actions

    @staticmethod
    def _render_context(context: dict[str, Any]) -> str:
        docs = "\n".join(f"- {path}" for path in context["important_files"]) or "- none"
        top_level = "\n".join(f"- {path}" for path in context["top_level"]) or "- none"
        actions = "\n".join(f"- {item}" for item in context["next_actions"])
        return (
            f"# Repo Context: {context['repo']}\n\n"
            f"- URL: {context.get('html_url') or 'unknown'}\n"
            f"- Default branch: {context['default_branch']}\n"
            f"- Visibility: {context.get('visibility') or 'unknown'}\n"
            f"- Stack: {', '.join(context['stack'])}\n"
            f"- File count: {context['file_count']}\n\n"
            "## Important Files\n\n"
            f"{docs}\n\n"
            "## Top Level\n\n"
            f"{top_level}\n\n"
            "## Next Actions\n\n"
            f"{actions}\n"
        )
