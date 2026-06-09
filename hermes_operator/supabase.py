"""Small Supabase REST client used by the operator layer."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from hermes_operator.config import OperatorConfig


class SupabaseClient:
    def __init__(self, config: OperatorConfig) -> None:
        self.config = config
        self.base_url = f"{config.supabase_url}/rest/v1"
        self.headers = {
            "apikey": config.supabase_service_role_key or config.supabase_anon_key,
            "Authorization": f"Bearer {config.supabase_service_role_key or config.supabase_anon_key}",
            "Content-Type": "application/json",
        }

    async def health(self) -> bool:
        if not self.config.supabase_url or not (self.config.supabase_service_role_key or self.config.supabase_anon_key):
            return False
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/tasks?select=id&limit=1", headers=self.headers)
            return response.status_code < 500

    async def insert(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/{quote(table)}",
                headers={**self.headers, "Prefer": "return=representation"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if isinstance(data, list) and data else payload

    async def update(self, table: str, row_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(
                f"{self.base_url}/{quote(table)}?id=eq.{quote(row_id)}",
                headers={**self.headers, "Prefer": "return=representation"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if isinstance(data, list) and data else payload

    async def list_rows(self, table: str, *, limit: int = 20, order: str = "created_at.desc") -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.base_url}/{quote(table)}?select=*&order={quote(order)}&limit={limit}",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []

    async def get_by_id(self, table: str, row_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.base_url}/{quote(table)}?id=eq.{quote(row_id)}&select=*&limit=1",
                headers=self.headers,
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if isinstance(data, list) and data else None

    async def rpc(self, name: str, payload: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/rpc/{quote(name)}",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()
