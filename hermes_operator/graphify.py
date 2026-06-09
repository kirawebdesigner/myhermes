"""Graphify integration for GitHub-backed Hermes memory."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from hermes_operator.config import OperatorConfig
from hermes_operator.github import GitHubClient
from hermes_operator.memory_os import MemoryOS

GRAPHIFY_OUTPUT_FILES = ["graph.json", "GRAPH_REPORT.md", "graph.html"]


@dataclass
class GraphifyResult:
    ok: bool
    status: str
    uploaded: list[str]
    detail: str | None = None


class GraphifyRunner:
    def __init__(self, config: OperatorConfig, memory: MemoryOS, github: GitHubClient) -> None:
        self.config = config
        self.memory = memory
        self.github = github

    async def rebuild_memory_graph(self) -> GraphifyResult:
        if not self.config.graphify_enabled:
            return GraphifyResult(ok=False, status="disabled", uploaded=[], detail="GRAPHIFY_ENABLED=false")
        if not shutil.which(self.config.graphify_command):
            return GraphifyResult(
                ok=False,
                status="missing_cli",
                uploaded=[],
                detail=f"'{self.config.graphify_command}' is not installed on PATH.",
            )

        with tempfile.TemporaryDirectory(prefix="hermes-graphify-") as tmp:
            workspace = Path(tmp)
            paths = await self.memory.memory_file_paths()
            for path in paths:
                content = await self.memory.read_memory_file(path)
                if content is None:
                    continue
                target = workspace / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            process = await asyncio.create_subprocess_exec(
                self.config.graphify_command,
                ".",
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.graphify_timeout_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return GraphifyResult(ok=False, status="timeout", uploaded=[], detail="Graphify timed out.")

            if process.returncode != 0:
                detail = (stderr or stdout).decode("utf-8", errors="replace")[-2000:]
                return GraphifyResult(ok=False, status="failed", uploaded=[], detail=detail)

            uploaded: list[str] = []
            output_dir = workspace / "graphify-out"
            for filename in GRAPHIFY_OUTPUT_FILES:
                output_path = output_dir / filename
                if not output_path.exists():
                    continue
                repo_path = f"memory/graphify-out/{filename}"
                await self.github.put_file(
                    self.config.memory_repo,
                    repo_path,
                    output_path.read_text(encoding="utf-8", errors="replace"),
                    "chore(graphify): update memory knowledge graph",
                    enforce_allowlist=False,
                )
                uploaded.append(repo_path)

            return GraphifyResult(ok=True, status="completed", uploaded=uploaded)
