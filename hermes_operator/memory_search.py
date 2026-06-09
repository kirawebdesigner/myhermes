"""Memory search over GitHub-backed memory files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from hermes_operator.memory_os import MemoryOS


@dataclass
class MemorySearchEngine:
    memory: MemoryOS

    async def search(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        terms = self._terms(query)
        results: list[dict[str, Any]] = []
        for path in await self.memory.memory_file_paths():
            if not path.endswith(".md") and not path.endswith(".json"):
                continue
            content = await self.memory.read_memory_file(path)
            if not content:
                continue
            score = self._score(path, content, terms)
            if score <= 0 and terms:
                continue
            results.append(
                {
                    "path": path,
                    "score": score,
                    "excerpt": self._excerpt(content, terms),
                }
            )
        results.sort(key=lambda item: (-item["score"], item["path"]))
        return {"query": query, "results": results[:limit], "mode": "lexical"}

    @staticmethod
    def _terms(query: str) -> list[str]:
        return [term for term in re.split(r"[^a-zA-Z0-9_-]+", query.lower()) if term]

    @staticmethod
    def _score(path: str, content: str, terms: list[str]) -> int:
        haystack = f"{path}\n{content}".lower()
        return sum(haystack.count(term) for term in terms)

    @staticmethod
    def _excerpt(content: str, terms: list[str], *, max_chars: int = 500) -> str:
        if not content:
            return ""
        lower = content.lower()
        indexes = [lower.find(term) for term in terms if term and lower.find(term) >= 0]
        start = max(0, min(indexes) - 120) if indexes else 0
        return content[start : start + max_chars].strip()
