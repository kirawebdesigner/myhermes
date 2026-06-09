"""Skill source discovery for KirzKit, Ruflo, and native operator skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes_operator.config import OperatorConfig


@dataclass(frozen=True)
class SkillSourceSummary:
    name: str
    kind: str
    path_or_url: str
    available: bool
    agents: list[str]
    skills: list[str]
    workflows: list[str]
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path_or_url": self.path_or_url,
            "available": self.available,
            "agents_count": len(self.agents),
            "skills_count": len(self.skills),
            "workflows_count": len(self.workflows),
            "agents_sample": self.agents[:30],
            "skills_sample": self.skills[:50],
            "workflows": self.workflows,
            "notes": self.notes,
        }


class SkillSourceRegistry:
    def __init__(self, config: OperatorConfig) -> None:
        self.config = config

    def summarize(self) -> list[SkillSourceSummary]:
        return [self._kirzkit_summary(), self._ruflo_summary(), self._native_summary()]

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        results: list[dict[str, Any]] = []
        for source in self.summarize():
            for kind, names in (("agent", source.agents), ("skill", source.skills), ("workflow", source.workflows)):
                for name in names:
                    if not needle or needle in name.lower():
                        results.append({"source": source.name, "kind": kind, "name": name})
        return results

    def _kirzkit_summary(self) -> SkillSourceSummary:
        root = Path(self.config.kirzkit_local_path)
        agents = self._names(root / "agents", files=True, directories=True)
        skills = self._names(root / "skills", directories=True)
        workflows = self._names(root / "workflows", files=True)
        return SkillSourceSummary(
            name="KirzKit",
            kind="local-ai-operating-layer",
            path_or_url=str(root),
            available=root.exists(),
            agents=agents,
            skills=skills,
            workflows=workflows,
            notes=(
                "Primary skill source. Before creating UI/web/product/build skills, inspect KirzKit agents, "
                "skills, workflows, references, and activation docs."
            ),
        )

    def _ruflo_summary(self) -> SkillSourceSummary:
        return SkillSourceSummary(
            name="Ruflo",
            kind="optional-multi-agent-orchestration-layer",
            path_or_url=self.config.ruflo_repo,
            available=True,
            agents=["100+ specialized agents advertised by Ruflo"],
            skills=[
                "ruflo-core",
                "ruflo-swarm",
                "ruflo-autopilot",
                "ruflo-workflows",
                "ruflo-goals",
                "ruflo-rag-memory",
                "ruflo-knowledge-graph",
                "ruflo-docs",
                "ruflo-testgen",
                "ruflo-security-audit",
                "ruflo-adr",
                "ruflo-observability",
                "ruflo-cost-tracker",
            ],
            workflows=["npx ruflo@latest init wizard", "npx ruflo@latest mcp start"],
            notes=(
                "Optional future source for swarms, goals, RAG memory, knowledge graph traversal, docs, testing, "
                "security, and workflow orchestration. Do not make Choreo deployment depend on it until tested."
            ),
        )

    def _native_summary(self) -> SkillSourceSummary:
        return SkillSourceSummary(
            name="Hermes Operator Native",
            kind="built-in",
            path_or_url="hermes_operator",
            available=True,
            agents=[],
            skills=[
                "memory_save",
                "task_create",
                "project_continue",
                "graphify_rebuild",
                "github_memory_write",
                "supabase_persist",
                "telegram_dispatch",
            ],
            workflows=["bootstrap_memory_os", "continue_project", "rebuild_graph"],
            notes="Current built-in Hermes Operator capabilities.",
        )

    @staticmethod
    def _names(path: Path, *, files: bool = False, directories: bool = False) -> list[str]:
        if not path.exists():
            return []
        names: list[str] = []
        if directories:
            names.extend(child.name for child in path.iterdir() if child.is_dir())
        if files:
            names.extend(child.stem for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".md")
        return sorted(set(names), key=str.lower)
