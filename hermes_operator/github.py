"""GitHub REST helpers for memory files and safe repo updates."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from hermes_operator.config import OperatorConfig
from hermes_operator.safety import SafetyPolicy


@dataclass
class GitHubClient:
    config: OperatorConfig
    safety: SafetyPolicy

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_file(self, repo: str, path: str, *, ref: str | None = None) -> dict[str, Any] | None:
        query = f"?ref={quote(ref)}" if ref else ""
        url = f"https://api.github.com/repos/{repo}/contents/{quote(path, safe='/')}{query}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

    async def put_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str,
        *,
        branch: str | None = None,
        enforce_allowlist: bool = True,
    ) -> dict[str, Any]:
        if enforce_allowlist:
            self.safety.require_allowed_repo(repo)

        existing = await self.get_file(repo, path, ref=branch)
        if existing and existing.get("content"):
            existing_content = base64.b64decode(existing["content"].encode("ascii")).decode("utf-8")
            if existing_content == content:
                return {"content": {"path": path, "sha": existing.get("sha")}, "unchanged": True}
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if branch:
            payload["branch"] = branch
        if existing and existing.get("sha"):
            payload["sha"] = existing["sha"]

        url = f"https://api.github.com/repos/{repo}/contents/{quote(path, safe='/')}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def list_repo_root(self, repo: str) -> list[dict[str, Any]]:
        self.safety.require_allowed_repo(repo)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"https://api.github.com/repos/{repo}/contents", headers=self.headers)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    async def get_repo(self, repo: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"https://api.github.com/repos/{repo}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def create_branch(self, repo: str, branch: str, *, from_ref: str | None = None) -> dict[str, Any]:
        self.safety.require_allowed_repo(repo)
        repo_info = await self.get_repo(repo)
        default_branch = from_ref or repo_info.get("default_branch") or "main"
        async with httpx.AsyncClient(timeout=20) as client:
            base_response = await client.get(
                f"https://api.github.com/repos/{repo}/git/ref/heads/{quote(default_branch)}",
                headers=self.headers,
            )
            base_response.raise_for_status()
            sha = base_response.json()["object"]["sha"]
            create_response = await client.post(
                f"https://api.github.com/repos/{repo}/git/refs",
                headers=self.headers,
                json={"ref": f"refs/heads/{branch}", "sha": sha},
            )
            if create_response.status_code == 422:
                return {"ref": f"refs/heads/{branch}", "exists": True, "sha": sha}
            create_response.raise_for_status()
            return create_response.json()

    async def list_tree(self, repo: str, *, ref: str | None = None, prefix: str = "") -> list[dict[str, Any]]:
        repo_info = await self.get_repo(repo)
        tree_ref = ref or repo_info.get("default_branch") or "main"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"https://api.github.com/repos/{repo}/git/trees/{quote(tree_ref)}?recursive=1",
                headers=self.headers,
            )
            response.raise_for_status()
            tree = response.json().get("tree", [])
        files = [item for item in tree if item.get("type") == "blob"]
        if prefix:
            return [item for item in files if str(item.get("path", "")).startswith(prefix)]
        return files

    async def latest_commit(self, repo: str, *, ref: str | None = None) -> dict[str, Any] | None:
        self.safety.require_allowed_repo(repo)
        params = {"sha": ref, "per_page": "1"} if ref else {"per_page": "1"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"https://api.github.com/repos/{repo}/commits", headers=self.headers, params=params)
            response.raise_for_status()
            commits = response.json()
        if not commits:
            return None
        commit = commits[0]
        return {
            "sha": str(commit.get("sha", ""))[:12],
            "message": (commit.get("commit") or {}).get("message", "").splitlines()[0],
            "author": ((commit.get("commit") or {}).get("author") or {}).get("name"),
            "date": ((commit.get("commit") or {}).get("author") or {}).get("date"),
            "html_url": commit.get("html_url"),
        }

    async def get_text_file(self, repo: str, path: str, *, ref: str | None = None) -> str | None:
        data = await self.get_file(repo, path, ref=ref)
        if not data or not data.get("content"):
            return None
        return base64.b64decode(data["content"].encode("ascii")).decode("utf-8", errors="replace")

    async def create_pull_request(
        self,
        repo: str,
        branch: str,
        title: str,
        body: str,
        *,
        draft: bool = True,
        base: str | None = None,
    ) -> dict[str, Any]:
        self.safety.require_allowed_repo(repo)
        repo_info = await self.get_repo(repo)
        base_branch = base or repo_info.get("default_branch") or "main"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=self.headers,
                json={"title": title, "head": branch, "base": base_branch, "body": body, "draft": draft},
            )
            response.raise_for_status()
            return response.json()

    async def create_issue(self, repo: str, title: str, body: str = "") -> dict[str, Any]:
        self.safety.require_allowed_repo(repo)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers=self.headers,
                json={"title": title, "body": body},
            )
            response.raise_for_status()
            return response.json()

    async def comment_issue(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        self.safety.require_allowed_repo(repo)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
                headers=self.headers,
                json={"body": body},
            )
            response.raise_for_status()
            return response.json()
