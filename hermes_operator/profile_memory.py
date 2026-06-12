"""GitHub-backed user profile memory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hermes_operator.memory_os import MemoryOS


PROFILE_PATH = "memory/profile.json"


@dataclass
class ProfileMemory:
    memory: MemoryOS

    async def get(self) -> dict[str, Any]:
        content = await self.memory.github.get_text_file(self.memory.memory_repo, PROFILE_PATH)
        if not content:
            return {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def update(self, updates: dict[str, Any], *, source: str = "telegram") -> dict[str, Any]:
        profile = await self.get()
        profile.update({key: value for key, value in updates.items() if value not in {None, ""}})
        profile["updated"] = datetime.now(timezone.utc).date().isoformat()
        profile["source"] = source
        await self.memory.github.put_file(
            self.memory.memory_repo,
            PROFILE_PATH,
            json.dumps(profile, indent=2, sort_keys=True),
            "chore(memory): update user profile",
            enforce_allowlist=False,
        )
        return profile

    @staticmethod
    def parse_update(message: str) -> dict[str, Any]:
        text = message.strip()
        lower = text.lower()
        updates: dict[str, Any] = {}

        age_match = re.search(r"\b(?:i am|i'm|im|my age is|age is|turned)\s+(\d{1,3})\b", lower)
        if age_match:
            updates["age"] = int(age_match.group(1))

        name_match = re.search(r"\bmy name is\s+([a-zA-Z][a-zA-Z .'-]{1,80})", text, re.IGNORECASE)
        if name_match:
            updates["name"] = name_match.group(1).strip(" .")

        nickname_match = re.search(r"\b(?:call me|people call me|nickname is)\s+([a-zA-Z][a-zA-Z .'-]{1,40})", text, re.IGNORECASE)
        if nickname_match:
            updates["nickname"] = nickname_match.group(1).strip(" .")

        location_match = re.search(r"\b(?:i live in|location is|from)\s+([a-zA-Z][a-zA-Z ,.'-]{1,80})", text, re.IGNORECASE)
        if location_match:
            updates["location"] = location_match.group(1).strip(" .")

        school_match = re.search(r"\b(?:school is|i study at|i go to)\s+([a-zA-Z0-9][a-zA-Z0-9 .'-]{1,100})", text, re.IGNORECASE)
        if school_match:
            updates["school"] = school_match.group(1).strip(" .")

        return updates
