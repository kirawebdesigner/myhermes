"""Query Graphify output stored in the memory repo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hermes_operator.memory_os import MemoryOS


@dataclass
class GraphQueryEngine:
    memory: MemoryOS

    async def query(self, term: str, *, limit: int = 20) -> dict[str, Any]:
        graph_text = await self.memory.read_memory_file("memory/graphify-out/graph.json")
        report = await self.memory.read_memory_file("memory/graphify-out/GRAPH_REPORT.md")
        if not graph_text:
            return self._result("missing_graph", term, [], [], report)
        try:
            graph = json.loads(graph_text)
        except json.JSONDecodeError as exc:
            return self._result("malformed_graph", term, [], [], report, detail=str(exc))

        nodes, edges = self._normalize_graph(graph)
        needle = term.lower().strip()
        matched_nodes = [node for node in nodes if self._matches(node, needle)][:limit]
        matched_edges = [edge for edge in edges if self._matches(edge, needle)][:limit]
        return self._result("ok", term, matched_nodes, matched_edges, report)

    @staticmethod
    def _normalize_graph(graph: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if isinstance(graph, dict):
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", graph.get("links", []))
            if not isinstance(nodes, list):
                nodes = []
            if not isinstance(edges, list):
                edges = []
            return [GraphQueryEngine._as_dict(item) for item in nodes], [GraphQueryEngine._as_dict(item) for item in edges]
        if isinstance(graph, list):
            return [GraphQueryEngine._as_dict(item) for item in graph], []
        return [{"value": graph}], []

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return {"value": value}

    @staticmethod
    def _matches(value: dict[str, Any], needle: str) -> bool:
        if not needle:
            return True
        return needle in json.dumps(value, ensure_ascii=False).lower()

    @staticmethod
    def _report_excerpt(report: str | None, term: str, *, max_chars: int = 1200) -> str | None:
        if not report:
            return None
        if not term:
            return report[:max_chars]
        lower = report.lower()
        index = lower.find(term.lower())
        if index < 0:
            return report[:max_chars]
        start = max(0, index - 300)
        return report[start : start + max_chars]

    @classmethod
    def _result(
        cls,
        status: str,
        term: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        report: str | None,
        *,
        detail: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "term": term,
            "matched_nodes": nodes,
            "matched_edges": edges,
            "report_excerpt": cls._report_excerpt(report, term),
            "detail": detail,
        }
