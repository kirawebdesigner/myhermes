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
        return await self._complete([{"role": "user", "content": prompt}], max_tokens=160, fallback=user_text.strip())

    async def chat_reply(self, user_text: str) -> str:
        if not self.config.openrouter_api_key:
            return (
                "I can hear you. Add OPENROUTER_API_KEY if you want natural AI chat. "
                "For actions, use /memory, /task, /continue, /projects, or /status."
            )
        system = (
            "You are Hermes Operator, Kirubel's phone-controlled project operator. "
            "Talk naturally and briefly. If the user only greets you, greet them back and ask what they want to work on. "
            "Do not claim you executed actions unless a slash command was used. "
            "When useful, suggest exact commands like /memory, /task, /continue, /goal, /kirzkit, /projects, or /execute."
        )
        return await self._complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            max_tokens=320,
            fallback="I am online. What do you want to work on? Use /memory, /task, /continue, /goal, or /projects when you want me to take action.",
        )

    async def _complete(self, messages: list[dict[str, str]], *, max_tokens: int, fallback: str) -> str:
        for model in self._candidate_models():
            payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
            data = await self._post_openrouter(payload)
            if not data:
                continue
            try:
                content = data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError, AttributeError):
                continue
            if content:
                return content
        return fallback

    async def _post_openrouter(self, payload: dict) -> dict | None:
        async with httpx.AsyncClient(timeout=45) as client:
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
                return None
            return response.json()

    def _candidate_models(self) -> list[str]:
        configured = self.config.openrouter_model.strip() or "openrouter/auto"
        candidates = [configured]
        if configured == "qwen/qwen3.6-plus-preview":
            candidates.append("qwen/qwen3.6-plus-preview:free")
        candidates.extend(["qwen/qwen3.6-plus:free", "openrouter/auto"])
        deduped: list[str] = []
        for model in candidates:
            if model not in deduped:
                deduped.append(model)
        return deduped
