"""Model helpers for planning small operator tasks."""

from __future__ import annotations

import httpx

from hermes_operator.config import OperatorConfig


class LLMPlanner:
    def __init__(self, config: OperatorConfig) -> None:
        self.config = config

    async def summarize_intent(self, user_text: str) -> str:
        if not self.config.openrouter_api_key:
            return user_text.strip()
        prompt = (
            "Convert this user request into a concise execution goal for a cautious AI operator. "
            "Do not invent credentials or unsafe actions. Prefer KirzKit for UI work.\n\n"
            f"User request: {user_text}"
        )
        payload = {
            "model": "openrouter/auto",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 160,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://console.choreo.dev/",
                    "X-Title": "Hermes Operator",
                },
                json=payload,
            )
            if response.status_code >= 400:
                return user_text.strip()
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError):
                return user_text.strip()
