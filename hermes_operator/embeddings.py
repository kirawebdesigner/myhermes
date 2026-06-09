"""Deterministic embeddings for operator memory search.

The hosted v1 uses a local hashing embedder so semantic indexing works without
adding another paid API dependency. Supabase pgvector remains the storage layer,
and this class can be swapped for a model-backed embedder later.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from hermes_operator.memory_os import MemoryOS
from hermes_operator.supabase import SupabaseClient

EMBEDDING_DIMENSIONS = 1536


@dataclass
class SemanticMemoryIndex:
    memory: MemoryOS
    supabase: SupabaseClient
    dimensions: int = EMBEDDING_DIMENSIONS

    async def rebuild(self, *, limit: int = 200) -> dict[str, Any]:
        indexed: list[dict[str, Any]] = []
        for path in (await self.memory.memory_file_paths())[:limit]:
            if not path.endswith((".md", ".json", ".txt")):
                continue
            content = await self.memory.read_memory_file(path)
            if not content:
                continue
            document = await self.supabase.insert(
                "documents",
                {
                    "source": "github-memory",
                    "path": path,
                    "title": self._title_from_path(path),
                    "content": content,
                    "metadata": {"indexed_by": "hermes-operator"},
                },
            )
            embedding = self.embed(f"{path}\n{content}")
            await self.supabase.insert(
                "embeddings",
                {
                    "document_id": document.get("id"),
                    "content": self._preview(content),
                    "embedding": embedding,
                    "metadata": {"path": path, "source": "github-memory", "dimensions": self.dimensions},
                },
            )
            indexed.append({"path": path, "document_id": document.get("id")})
        return {"ok": True, "mode": "semantic-hash", "indexed": indexed, "count": len(indexed)}

    async def search(self, query: str, *, limit: int = 10, scan_limit: int = 500) -> dict[str, Any]:
        query_embedding = self.embed(query)
        rpc_results = await self._rpc_search(query, query_embedding, limit)
        if rpc_results is not None:
            return rpc_results
        rows = await self.supabase.list_rows("embeddings", limit=scan_limit)
        results: list[dict[str, Any]] = []
        for row in rows:
            embedding = self._parse_embedding(row.get("embedding"))
            if not embedding:
                continue
            score = self.cosine(query_embedding, embedding)
            metadata = row.get("metadata") or {}
            results.append(
                {
                    "path": metadata.get("path"),
                    "score": round(score, 6),
                    "excerpt": row.get("content") or "",
                    "metadata": metadata,
                }
            )
        results.sort(key=lambda item: (-item["score"], item.get("path") or ""))
        return {"query": query, "mode": "semantic-hash", "results": results[:limit]}

    async def _rpc_search(self, query: str, query_embedding: list[float], limit: int) -> dict[str, Any] | None:
        rpc = getattr(self.supabase, "rpc", None)
        if rpc is None:
            return None
        try:
            rows = await rpc(
                "match_operator_embeddings",
                {"query_embedding": query_embedding, "match_count": limit},
            )
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        results = []
        for row in rows:
            metadata = row.get("metadata") or {}
            results.append(
                {
                    "path": metadata.get("path"),
                    "score": round(float(row.get("similarity") or 0), 6),
                    "excerpt": row.get("content") or "",
                    "metadata": metadata,
                }
            )
        return {"query": query, "mode": "semantic", "results": results[:limit]}

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 8) for value in vector]

    @staticmethod
    def cosine(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right))

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [token for token in re.split(r"[^a-zA-Z0-9_-]+", text.lower()) if token]

    @staticmethod
    def _title_from_path(path: str) -> str:
        return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]

    @staticmethod
    def _preview(content: str, *, max_chars: int = 1000) -> str:
        return content.strip()[:max_chars]

    @staticmethod
    def _parse_embedding(value: Any) -> list[float]:
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            cleaned = value.strip().strip("[]")
            if not cleaned:
                return []
            return [float(part.strip()) for part in cleaned.split(",") if part.strip()]
        return []
