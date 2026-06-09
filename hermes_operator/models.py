"""Shared models for the operator layer."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class OperatorTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str
    status: TaskStatus = TaskStatus.queued
    project: str | None = None
    repo: str | None = None
    result: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    key: str
    value: str
    project: str | None = None
    source: str = "operator"
    metadata: dict[str, Any] = Field(default_factory=dict)
