"""Approval request helpers for gated execution steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hermes_operator.supabase import SupabaseClient


@dataclass
class ApprovalManager:
    supabase: SupabaseClient

    async def create_for_blocked_steps(
        self,
        *,
        execution_id: str,
        goal: str,
        project: str | None,
        plan: list[dict[str, Any]],
        steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        approvals: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            if not step.get("blocked_reason"):
                continue
            payload = {
                "id": str(uuid4()),
                "execution_id": execution_id,
                "goal": goal,
                "project": project,
                "skill": step.get("skill"),
                "status": "pending",
                "reason": step.get("blocked_reason"),
                "payload": {
                    "skill": step.get("skill"),
                    "inputs": step.get("inputs"),
                    "autonomy_tier": step.get("autonomy_tier"),
                    "plan": plan,
                    "step_index": index,
                },
            }
            approvals.append(await self.supabase.insert("approval_requests", payload))
        return approvals

    async def list_pending(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.supabase.list_rows("approval_requests", limit=limit)
        return [row for row in rows if row.get("status") == "pending"]

    async def approve(self, approval_id: str) -> dict[str, Any]:
        return await self.supabase.update("approval_requests", approval_id, {"status": "approved"})

    async def reject(self, approval_id: str) -> dict[str, Any]:
        return await self.supabase.update("approval_requests", approval_id, {"status": "rejected"})

    async def get(self, approval_id: str) -> dict[str, Any] | None:
        return await self.supabase.get_by_id("approval_requests", approval_id)
