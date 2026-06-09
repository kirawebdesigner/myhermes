"""Safety boundaries for repository operations."""

from __future__ import annotations

from dataclasses import dataclass

from hermes_operator.config import OperatorConfig


class SafetyError(RuntimeError):
    """Raised when an operation violates operator safety boundaries."""


@dataclass(frozen=True)
class SafetyPolicy:
    config: OperatorConfig

    def require_allowed_repo(self, repo: str) -> None:
        if not self.config.is_repo_allowed(repo):
            raise SafetyError(f"Repository '{repo}' is not in ALLOWED_REPOS.")

    def require_delete_allowed(self) -> None:
        if not self.config.allow_delete:
            raise SafetyError("Delete operations are disabled. Set ALLOW_DELETE=true to enable them.")

    def require_force_push_allowed(self) -> None:
        if not self.config.allow_force_push:
            raise SafetyError("Force push is disabled. Set ALLOW_FORCE_PUSH=true to enable it.")

    def require_repo_create_allowed(self) -> None:
        if not self.config.allow_repo_create:
            raise SafetyError("Repository creation is disabled. Set ALLOW_REPO_CREATE=true to enable it.")
