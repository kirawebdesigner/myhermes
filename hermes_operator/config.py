"""Runtime configuration for Hermes Operator mode."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class OperatorConfig:
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", "").rstrip("/"))
    supabase_anon_key: str = field(default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", ""))
    supabase_service_role_key: str = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_username: str = field(default_factory=lambda: os.getenv("GITHUB_USERNAME", "kirawebdesigner"))
    memory_repo: str = field(default_factory=lambda: os.getenv("MEMORY_REPO", ""))
    allowed_repos: list[str] = field(default_factory=lambda: _csv_env("ALLOWED_REPOS"))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_allowed_user_ids: list[str] = field(default_factory=lambda: _csv_env("TELEGRAM_ALLOWED_USER_IDS"))
    api_server_key: str = field(default_factory=lambda: os.getenv("API_SERVER_KEY", ""))
    host: str = field(default_factory=lambda: os.getenv("API_SERVER_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("API_SERVER_PORT", "8642")))
    kirzkit_repo: str = field(
        default_factory=lambda: os.getenv("KIRZKIT_REPO", "https://github.com/kirawebdesigner/KirzKit")
    )
    allow_delete: bool = field(default_factory=lambda: _bool_env("ALLOW_DELETE", False))
    allow_force_push: bool = field(default_factory=lambda: _bool_env("ALLOW_FORCE_PUSH", False))
    allow_repo_create: bool = field(default_factory=lambda: _bool_env("ALLOW_REPO_CREATE", False))
    allow_tier_1_5_auto: bool = field(default_factory=lambda: _bool_env("ALLOW_TIER_1_5_AUTO", True))
    require_confirmation_for_dangerous_actions: bool = field(
        default_factory=lambda: _bool_env("REQUIRE_CONFIRMATION_FOR_DANGEROUS_ACTIONS", True)
    )
    graphify_enabled: bool = field(default_factory=lambda: _bool_env("GRAPHIFY_ENABLED", True))
    graphify_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("GRAPHIFY_TIMEOUT_SECONDS", "180")))
    graphify_command: str = field(default_factory=lambda: os.getenv("GRAPHIFY_COMMAND", "graphify"))
    operator_worker_enabled: bool = field(default_factory=lambda: _bool_env("OPERATOR_WORKER_ENABLED", False))
    operator_worker_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("OPERATOR_WORKER_INTERVAL_SECONDS", "30"))
    )
    kirzkit_local_path: str = field(
        default_factory=lambda: os.getenv("KIRZKIT_LOCAL_PATH", r"C:\Users\kirub\kirzkit_openclaw\kirzkit")
    )
    ruflo_repo: str = field(default_factory=lambda: os.getenv("RUFLO_REPO", "https://github.com/ruvnet/ruflo"))

    def missing_required(self) -> list[str]:
        required = {
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "GITHUB_TOKEN": self.github_token,
            "MEMORY_REPO": self.memory_repo,
            "ALLOWED_REPOS": ",".join(self.allowed_repos),
            "API_SERVER_KEY": self.api_server_key,
        }
        return [name for name, value in required.items() if not value]

    def is_repo_allowed(self, repo: str) -> bool:
        normalized = repo.strip().lower()
        return normalized in {item.lower() for item in self.allowed_repos}


def load_config() -> OperatorConfig:
    return OperatorConfig()
