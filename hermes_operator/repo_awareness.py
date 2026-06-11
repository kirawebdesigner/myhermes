"""Repository awareness helpers for Hermes Operator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
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
            "name": repo.rsplit("/", 1)[-1],
            "default_branch": repo_info.get("default_branch") or "main",
            "description": repo_info.get("description"),
            "visibility": repo_info.get("visibility"),
            "html_url": repo_info.get("html_url"),
            "last_commit": await self._last_commit(repo, ref=ref or repo_info.get("default_branch")),
            "stack": self._detect_stack(paths),
            "deployment": self._detect_deployment(paths, documents),
            "related_goal": self._related_goal(repo, documents),
            "open_tasks": self._repo_tasks(documents),
            "roadmap": self._roadmap_items(documents),
            "important_files": sorted(documents),
            "file_count": len(paths),
            "top_level": self._top_level(paths),
            "documents": documents,
            "next_actions": self._next_actions(paths, documents),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        if cache:
            cached = await self.cache_context(context)
            context["memory_path"] = cached["markdown_path"]
            context["cache_path"] = cached["json_path"]
        return context

    async def cache_context(self, context: dict[str, Any]) -> dict[str, str]:
        repo_slug = slugify(context["repo"].replace("/", "-"))
        path = str(PurePosixPath("memory/context/repos") / f"{repo_slug}.md")
        json_path = str(PurePosixPath("memory/repo_cache") / f"{repo_slug}.json")
        content = self._render_context(context)
        cache = self._cache_payload(context)
        await self.memory.github.put_file(
            self.memory.memory_repo,
            path,
            content,
            f"chore(memory): cache repo context for {context['repo']}",
            enforce_allowlist=False,
        )
        await self.memory.github.put_file(
            self.memory.memory_repo,
            json_path,
            json.dumps(cache, indent=2, sort_keys=True),
            f"chore(memory): cache repo awareness for {context['repo']}",
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
        await self.supabase.insert(
            "documents",
            {
                "source": "github-repo-cache",
                "path": json_path,
                "title": f"Repo cache: {context['repo']}",
                "content": json.dumps(cache, indent=2, sort_keys=True),
                "metadata": {"repo": context["repo"], "stack": context["stack"], "deployment": context["deployment"]},
            },
        )
        return {"markdown_path": path, "json_path": json_path}

    async def cached_contexts(self, project: str | None = None) -> list[dict[str, Any]]:
        files = await self.memory.github.list_tree(self.memory.memory_repo, prefix="memory/repo_cache/")
        contexts: list[dict[str, Any]] = []
        project_slug = slugify(project) if project else ""
        for item in files:
            path = item.get("path")
            if not path or not str(path).endswith(".json"):
                continue
            content = await self.memory.github.get_text_file(self.memory.memory_repo, str(path))
            if not content:
                continue
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                continue
            if project_slug and project_slug not in self._cache_match_text(data):
                continue
            contexts.append(data)
        return contexts

    async def _last_commit(self, repo: str, *, ref: str | None = None) -> dict[str, Any] | None:
        try:
            return await self.github.latest_commit(repo, ref=ref)
        except Exception:
            return None

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
    def _detect_deployment(paths: list[str], documents: dict[str, str]) -> str:
        lower = {path.lower() for path in paths}
        joined = "\n".join(lower)
        if "dockerfile.choreo" in lower or ".choreo/component.yaml" in lower:
            return "Choreo Docker service"
        if "vercel.json" in lower or "next.config.js" in lower or "next.config.ts" in lower:
            return "Vercel/Next.js candidate"
        if "netlify.toml" in lower:
            return "Netlify candidate"
        if "render.yaml" in lower:
            return "Render candidate"
        if "dockerfile" in lower or "docker-compose.yml" in lower:
            return "Docker candidate"
        if any("supabase" in text.lower() for text in documents.values()) or "supabase/" in joined:
            return "Supabase-backed app"
        return "unknown"

    @staticmethod
    def _related_goal(repo: str, documents: dict[str, str]) -> str | None:
        haystack = f"{repo}\n" + "\n".join(documents.values())
        lower = haystack.lower()
        if "first $1k" in lower or "first 1k" in lower or "online income" in lower:
            return "Earn first $1k online"
        if "brandblueprint" in lower or "brand blueprint" in lower:
            return "Build BrandBlueprint into a useful product"
        return None

    @staticmethod
    def _repo_tasks(documents: dict[str, str]) -> list[str]:
        return RepoAwareness._checkbox_items(documents, names={"tasks.md", "roadmap.md", "readme.md"})[:20]

    @staticmethod
    def _roadmap_items(documents: dict[str, str]) -> list[str]:
        return RepoAwareness._checkbox_items(documents, names={"roadmap.md", "readme.md"})[:20]

    @staticmethod
    def _checkbox_items(documents: dict[str, str], *, names: set[str]) -> list[str]:
        items: list[str] = []
        for path, content in documents.items():
            if PurePosixPath(path).name.lower() not in names:
                continue
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith(("- [ ]", "* [ ]")):
                    items.append(stripped[5:].strip())
        return items

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
        last_commit = context.get("last_commit") or {}
        return (
            f"# Repo Context: {context['repo']}\n\n"
            f"- URL: {context.get('html_url') or 'unknown'}\n"
            f"- Default branch: {context['default_branch']}\n"
            f"- Visibility: {context.get('visibility') or 'unknown'}\n"
            f"- Stack: {', '.join(context['stack'])}\n"
            f"- Deployment: {context.get('deployment') or 'unknown'}\n"
            f"- Related goal: {context.get('related_goal') or 'unknown'}\n"
            f"- Last commit: {last_commit.get('sha', 'unknown')} {last_commit.get('message', '')}\n"
            f"- File count: {context['file_count']}\n\n"
            "## Important Files\n\n"
            f"{docs}\n\n"
            "## Top Level\n\n"
            f"{top_level}\n\n"
            "## Next Actions\n\n"
            f"{actions}\n"
        )

    @staticmethod
    def _cache_payload(context: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": context["name"],
            "repo": context["repo"],
            "default_branch": context["default_branch"],
            "description": context.get("description"),
            "stack": context["stack"],
            "last_commit": context.get("last_commit"),
            "open_tasks": context.get("open_tasks", []),
            "roadmap": context.get("roadmap", []),
            "deployment": context.get("deployment"),
            "related_goal": context.get("related_goal"),
            "important_files": context["important_files"],
            "top_level": context["top_level"],
            "next_actions": context["next_actions"],
            "indexed_at": context["indexed_at"],
        }

    @staticmethod
    def _cache_match_text(data: dict[str, Any]) -> str:
        text = " ".join(
            [
                str(data.get("name", "")),
                str(data.get("repo", "")),
                str(data.get("description", "")),
                str(data.get("related_goal", "")),
                " ".join(map(str, data.get("open_tasks", []))),
                " ".join(map(str, data.get("roadmap", []))),
            ]
        )
        return slugify(text)
