"""Memory processing pipeline for raw notes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from hermes_operator.memory_os import MemoryOS, slugify


@dataclass
class MemoryPipeline:
    memory: MemoryOS

    async def process_raw(self, *, limit: int = 20) -> dict[str, Any]:
        paths = [
            path
            for path in await self.memory.memory_file_paths()
            if path.startswith("memory/raw/") and path.endswith(".md") and not path.endswith(".gitkeep")
        ][:limit]

        processed: list[str] = []
        wiki_paths: list[str] = []
        archive_paths: list[str] = []
        for path in paths:
            content = await self.memory.read_memory_file(path)
            if not content:
                continue
            filename = PurePosixPath(path).name
            title = self._title_from_content(filename, content)
            wiki_path = f"memory/wiki/{slugify(title)}.md"
            archive_path = f"memory/archive/{filename}"
            marker_path = f"memory/archive/.processed/{filename}.marker"
            if await self.memory.read_memory_file(marker_path):
                continue
            wiki_content = self._wiki_content(title, path, content)

            await self.memory.github.put_file(
                self.memory.memory_repo,
                wiki_path,
                wiki_content,
                f"chore(memory): process raw note {title}",
                enforce_allowlist=False,
            )
            await self.memory.github.put_file(
                self.memory.memory_repo,
                archive_path,
                content,
                f"chore(memory): archive raw note {title}",
                enforce_allowlist=False,
            )
            await self.memory.github.put_file(
                self.memory.memory_repo,
                marker_path,
                f"Processed from `{path}` into `{wiki_path}` and `{archive_path}`.\n",
                f"chore(memory): mark raw note processed {title}",
                enforce_allowlist=False,
            )
            processed.append(path)
            wiki_paths.append(wiki_path)
            archive_paths.append(archive_path)

        return {"processed": processed, "wiki_paths": wiki_paths, "archive_paths": archive_paths}

    @staticmethod
    def _title_from_content(filename: str, content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or filename
        return PurePosixPath(filename).stem

    @staticmethod
    def _wiki_content(title: str, source_path: str, content: str) -> str:
        excerpt = content.strip()
        if len(excerpt) > 2000:
            excerpt = excerpt[:2000].rstrip() + "\n\n[truncated]"
        return (
            f"# {title}\n\n"
            f"Source: `{source_path}`\n\n"
            "## Summary\n\n"
            f"{excerpt}\n\n"
            "## Status\n\n"
            "Processed from raw memory. Review and refine when this becomes active project knowledge.\n"
        )
