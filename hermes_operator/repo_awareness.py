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
    "ROADMAP.md",
    "roadmap.md",
    "TASKS.md",
    "tasks.md",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "pnpm-lock.yaml",
    "package-lock.json",
    "Dockerfile",
    "Dockerfile.choreo",
    "docker-compose.yml",
    "vercel.json",
    "netlify.toml",
    "render.yaml",
    ".choreo/component.yaml",
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
        recent_commits = await self._recent_commits(repo, ref=ref or repo_info.get("default_branch"))
        issues = await self._open_issues(repo)
        dependencies = self._dependencies(documents)
        roadmap = self._roadmap_items(documents)
        open_tasks = self._repo_tasks(documents, issues=issues)
        decisions = await self._decision_refs(repo, repo.rsplit("/", 1)[-1], documents)
        deployment = self._detect_deployment(paths, documents)
        deployment_status = self._deployment_status(deployment, paths)
        recommended = self._recommended_next_action(
            documents=documents,
            issues=issues,
            open_tasks=open_tasks,
            deployment=deployment,
            deployment_status=deployment_status,
        )
        last_activity_days = self._last_activity_days(recent_commits)
        health = self._repo_health(
            documents=documents,
            issues=issues,
            open_tasks=open_tasks,
            dependencies=dependencies,
            deployment=deployment,
            deployment_status=deployment_status,
            last_activity_days=last_activity_days,
        )
        context = {
            "repo": repo,
            "name": repo.rsplit("/", 1)[-1],
            "default_branch": repo_info.get("default_branch") or "main",
            "description": repo_info.get("description"),
            "visibility": repo_info.get("visibility"),
            "html_url": repo_info.get("html_url"),
            "last_commit": recent_commits[0] if recent_commits else None,
            "recent_commits": recent_commits,
            "issues": issues,
            "stack": self._detect_stack(paths),
            "dependencies": dependencies,
            "dependency_files": sorted(path for path in documents if self._is_dependency_file(path)),
            "deployment": deployment,
            "deployment_files": self._deployment_files(paths),
            "deployment_status": deployment_status,
            "related_goal": self._related_goal(repo, documents),
            "decisions": decisions,
            "readme": self._document_excerpt(documents, names={"readme.md", "readme.rst", "readme.txt"}),
            "roadmap": roadmap,
            "tasks": open_tasks,
            "open_tasks": open_tasks,
            "unfinished_tasks": len(open_tasks),
            "repo_health": health,
            "last_activity_days": last_activity_days,
            "recommended_next_action": recommended["action"],
            "recommendation_reason": recommended["reason"],
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

    async def _recent_commits(self, repo: str, *, ref: str | None = None) -> list[dict[str, Any]]:
        try:
            return await self.github.recent_commits(repo, ref=ref, limit=8)
        except Exception:
            return []

    async def _open_issues(self, repo: str) -> list[dict[str, Any]]:
        try:
            return await self.github.list_open_issues(repo, limit=20)
        except Exception:
            return []

    async def _decision_refs(self, repo: str, name: str, documents: dict[str, str]) -> list[dict[str, str]]:
        try:
            files = await self.memory.github.list_tree(self.memory.memory_repo, prefix="memory/decisions/")
        except Exception:
            return []
        haystack = self._cache_match_text(
            {
                "name": name,
                "repo": repo,
                "description": "\n".join(documents.values()),
                "related_goal": self._related_goal(repo, documents) or "",
                "open_tasks": self._repo_tasks(documents),
                "roadmap": self._roadmap_items(documents),
            }
        )
        refs: list[dict[str, str]] = []
        for item in files:
            path = str(item.get("path") or "")
            if not path.endswith(".md"):
                continue
            content = await self.memory.github.get_text_file(self.memory.memory_repo, path)
            if not content:
                continue
            match_text = slugify(f"{path} {content[:2000]}")
            if any(part and part in match_text for part in {slugify(name), slugify(repo), haystack[:80]}):
                refs.append({"path": path, "summary": self._first_heading_or_line(content)})
        return refs[:10]

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
    def _deployment_status(deployment: str, paths: list[str]) -> str:
        if deployment == "unknown":
            return "unknown"
        if deployment == "Choreo Docker service" and "Dockerfile.choreo" in paths:
            return "configured"
        if deployment.endswith("candidate"):
            return "candidate"
        return "configured"

    @staticmethod
    def _deployment_files(paths: list[str]) -> list[str]:
        lower_map = {path.lower(): path for path in paths}
        candidates = [
            "Dockerfile.choreo",
            ".choreo/component.yaml",
            "vercel.json",
            "netlify.toml",
            "render.yaml",
            "Dockerfile",
            "docker-compose.yml",
            "supabase/config.toml",
        ]
        return [lower_map[item.lower()] for item in candidates if item.lower() in lower_map]

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
    def _repo_tasks(documents: dict[str, str], *, issues: list[dict[str, Any]] | None = None) -> list[str]:
        tasks = RepoAwareness._checkbox_items(documents, names={"tasks.md", "roadmap.md", "readme.md"})[:20]
        for issue in issues or []:
            title = issue.get("title")
            if title:
                tasks.append(f"GitHub issue #{issue.get('number')}: {title}")
        return tasks[:30]

    @staticmethod
    def _roadmap_items(documents: dict[str, str]) -> list[str]:
        return RepoAwareness._checkbox_items(documents, names={"roadmap.md"})[:20]

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
    def _dependencies(documents: dict[str, str]) -> dict[str, Any]:
        deps: dict[str, Any] = {}
        package = documents.get("package.json")
        if package:
            try:
                parsed = json.loads(package)
                deps["package.json"] = {
                    "dependencies": sorted((parsed.get("dependencies") or {}).keys())[:80],
                    "devDependencies": sorted((parsed.get("devDependencies") or {}).keys())[:80],
                    "scripts": sorted((parsed.get("scripts") or {}).keys())[:40],
                }
            except json.JSONDecodeError:
                deps["package.json"] = {"error": "malformed package.json"}
        requirements = documents.get("requirements.txt")
        if requirements:
            deps["requirements.txt"] = [
                line.strip()
                for line in requirements.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ][:120]
        pyproject = documents.get("pyproject.toml")
        if pyproject:
            deps["pyproject.toml"] = RepoAwareness._pyproject_dependency_lines(pyproject)
        return deps

    @staticmethod
    def _repo_health(
        *,
        documents: dict[str, str],
        issues: list[dict[str, Any]],
        open_tasks: list[str],
        dependencies: dict[str, Any],
        deployment: str,
        deployment_status: str,
        last_activity_days: int | None,
    ) -> int:
        score = 50
        if any(PurePosixPath(path).name.lower().startswith("readme") for path in documents):
            score += 12
        if any(PurePosixPath(path).name.lower() == "roadmap.md" for path in documents):
            score += 8
        if any(PurePosixPath(path).name.lower() == "tasks.md" for path in documents):
            score += 8
        if dependencies:
            score += 8
        if deployment != "unknown":
            score += 10
        if deployment_status == "configured":
            score += 4
        if issues:
            score -= min(10, len(issues) * 2)
        if len(open_tasks) > 10:
            score -= 8
        elif len(open_tasks) > 5:
            score -= 4
        if last_activity_days is not None:
            if last_activity_days <= 7:
                score += 5
            elif last_activity_days > 30:
                score -= 10
        return max(0, min(100, score))

    @staticmethod
    def _last_activity_days(recent_commits: list[dict[str, Any]]) -> int | None:
        if not recent_commits:
            return None
        raw_date = recent_commits[0].get("date")
        if not raw_date:
            return None
        try:
            committed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        except ValueError:
            return None
        return max(0, (datetime.now(timezone.utc) - committed).days)

    @staticmethod
    def _recommended_next_action(
        *,
        documents: dict[str, str],
        issues: list[dict[str, Any]],
        open_tasks: list[str],
        deployment: str,
        deployment_status: str,
    ) -> dict[str, str]:
        if "README.md" not in documents and "README.rst" not in documents and "README.txt" not in documents:
            return {"action": "Add README project summary", "reason": "Hermes needs a readable project entry point."}
        if deployment == "unknown":
            return {"action": "Document deployment target", "reason": "Operator cannot verify or improve delivery without deployment context."}
        if deployment_status in {"candidate", "unknown"}:
            return {"action": "Confirm deployment status", "reason": "Deployment files exist but health is not proven from repo cache."}
        if issues:
            issue = issues[0]
            return {
                "action": f"Resolve issue #{issue.get('number')}: {issue.get('title')}",
                "reason": "Open GitHub issues are explicit unfinished work.",
            }
        if open_tasks:
            return {"action": open_tasks[0], "reason": "First unchecked roadmap/task item is the clearest next step."}
        return {"action": "Review recent commits and define next milestone", "reason": "No explicit open tasks were found."}

    @staticmethod
    def _pyproject_dependency_lines(content: str) -> list[str]:
        lines: list[str] = []
        in_dependencies = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("dependencies"):
                in_dependencies = True
            if in_dependencies and stripped:
                lines.append(stripped.strip('",'))
            if in_dependencies and stripped == "]":
                break
        return lines[:120]

    @staticmethod
    def _is_dependency_file(path: str) -> bool:
        return PurePosixPath(path).name.lower() in {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "uv.lock",
            "pnpm-lock.yaml",
            "package-lock.json",
        }

    @staticmethod
    def _document_excerpt(documents: dict[str, str], *, names: set[str], max_chars: int = 1200) -> str | None:
        for path, content in documents.items():
            if PurePosixPath(path).name.lower() in names:
                return content.strip()[:max_chars]
        return None

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
            f"- Repo health: {context.get('repo_health', 'unknown')}\n"
            f"- Deployment status: {context.get('deployment_status') or 'unknown'}\n"
            f"- Recommended next action: {context.get('recommended_next_action') or 'unknown'}\n"
            f"- Reason: {context.get('recommendation_reason') or 'unknown'}\n"
            f"- Last commit: {last_commit.get('sha', 'unknown')} {last_commit.get('message', '')}\n"
            f"- Open issues: {len(context.get('issues') or [])}\n"
            f"- Open tasks: {len(context.get('open_tasks') or [])}\n"
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
            "recent_commits": context.get("recent_commits", []),
            "issues": context.get("issues", []),
            "dependencies": context.get("dependencies", {}),
            "dependency_files": context.get("dependency_files", []),
            "open_tasks": context.get("open_tasks", []),
            "tasks": context.get("tasks", []),
            "unfinished_tasks": context.get("unfinished_tasks", 0),
            "roadmap": context.get("roadmap", []),
            "deployment": context.get("deployment"),
            "deployment_files": context.get("deployment_files", []),
            "deployment_status": context.get("deployment_status"),
            "related_goal": context.get("related_goal"),
            "decisions": context.get("decisions", []),
            "readme": context.get("readme"),
            "repo_health": context.get("repo_health"),
            "last_activity_days": context.get("last_activity_days"),
            "recommended_next_action": context.get("recommended_next_action"),
            "recommendation_reason": context.get("recommendation_reason"),
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

    @staticmethod
    def _first_heading_or_line(content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:160]
        return "Decision"
