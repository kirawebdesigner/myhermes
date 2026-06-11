"""Skill registry primitives."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "safe"
    autonomy_tier: float = 0
    requires_approval: bool = False


@dataclass
class SkillResult:
    ok: bool
    skill: str
    output: Any = None
    error: str | None = None


class SkillRegistry:
    def __init__(self, definitions: list[SkillDefinition] | None = None) -> None:
        self._definitions: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        for definition in default_skill_definitions():
            self.register_definition(definition)
        for definition in definitions or []:
            self.register_definition(definition)

    def register_definition(self, definition: SkillDefinition) -> None:
        self._definitions[definition.name] = definition

    def register(self, definition: SkillDefinition, handler: Callable[..., Any]) -> None:
        self.register_definition(definition)
        self._handlers[definition.name] = handler

    def register_handler(self, name: str, handler: Callable[..., Any]) -> None:
        if name not in self._definitions:
            raise KeyError(f"Unknown skill: {name}")
        self._handlers[name] = handler

    def list(self) -> list[SkillDefinition]:
        return sorted(self._definitions.values(), key=lambda item: item.name)

    def get(self, name: str) -> SkillDefinition | None:
        return self._definitions.get(name)

    def search(self, query: str) -> list[SkillDefinition]:
        needle = query.lower().strip()
        return [
            definition
            for definition in self.list()
            if not needle or needle in definition.name.lower() or needle in definition.description.lower()
        ]

    async def execute(self, name: str, inputs: dict[str, Any] | None = None) -> SkillResult:
        if name not in self._definitions:
            return SkillResult(ok=False, skill=name, error=f"Unknown skill: {name}")
        if name not in self._handlers:
            return SkillResult(ok=False, skill=name, error=f"No handler registered for skill: {name}")
        try:
            result = self._handlers[name](**(inputs or {}))
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, SkillResult):
                return result
            return SkillResult(ok=True, skill=name, output=result)
        except Exception as exc:
            return SkillResult(ok=False, skill=name, error=str(exc))


def default_skill_definitions() -> list[SkillDefinition]:
    return [
        SkillDefinition("memory_save", "Save a memory into GitHub and Supabase.", {"key": "string", "value": "string"}, autonomy_tier=0),
        SkillDefinition("task_create", "Create a tracked operator task.", {"goal": "string"}, autonomy_tier=0),
        SkillDefinition("project_context", "Build a project context packet.", {"project": "string"}, autonomy_tier=0),
        SkillDefinition("graph_query", "Query Graphify output.", {"term": "string"}, autonomy_tier=0),
        SkillDefinition("graphify_rebuild", "Rebuild Graphify output from memory files.", autonomy_tier=0),
        SkillDefinition("skill_source_search", "Search KirzKit, native, and Ruflo skill sources.", {"query": "string"}, autonomy_tier=0),
        SkillDefinition("memory_pipeline_process", "Process raw memory notes into wiki and archive.", autonomy_tier=0),
        SkillDefinition("memory_index_rebuild", "Rebuild the Supabase semantic memory index from GitHub memory files.", autonomy_tier=0),
        SkillDefinition("memory_search", "Search GitHub-backed memory files.", {"query": "string"}, autonomy_tier=0),
        SkillDefinition("goal_plan", "Create goal, project, and task records.", {"goal": "string"}, autonomy_tier=0),
        SkillDefinition("kirzkit_generate_plan", "Create a KirzKit-first implementation plan.", {"goal": "string"}, autonomy_tier=0),
        SkillDefinition("repo_context", "Build and cache repository awareness context.", {"repo": "string"}, autonomy_tier=0),
        SkillDefinition("github_branch_create", "Create a working branch in an allowed GitHub repo.", {"repo": "string", "branch": "string"}, risk_level="medium", autonomy_tier=1),
        SkillDefinition("github_read_file", "Read a file from an allowed GitHub repo.", {"repo": "string", "path": "string"}, autonomy_tier=0),
        SkillDefinition("github_write_file", "Write a file to a non-default branch in an allowed GitHub repo.", {"repo": "string", "branch": "string", "path": "string", "content": "string"}, risk_level="medium", autonomy_tier=1),
        SkillDefinition("github_commit_file", "Commit file content to a non-default branch.", {"repo": "string", "branch": "string", "path": "string", "content": "string", "message": "string"}, risk_level="medium", autonomy_tier=1),
        SkillDefinition("github_list_tree", "List files in an allowed GitHub repo.", {"repo": "string"}, autonomy_tier=0),
        SkillDefinition("github_pr_draft", "Open a draft pull request from a working branch.", {"repo": "string", "branch": "string", "title": "string"}, risk_level="medium", autonomy_tier=1.5),
        SkillDefinition("github_pr_ready", "Open a ready-for-review pull request.", {"repo": "string", "branch": "string", "title": "string"}, risk_level="approval_required", autonomy_tier=2, requires_approval=True),
        SkillDefinition("github_issue_create", "Create an issue in an allowed GitHub repo.", {"repo": "string", "title": "string"}, risk_level="medium", autonomy_tier=1.5),
        SkillDefinition("github_issue_comment", "Comment on an issue in an allowed GitHub repo.", {"repo": "string", "issue_number": "integer", "body": "string"}, risk_level="medium", autonomy_tier=1.5),
    ]
