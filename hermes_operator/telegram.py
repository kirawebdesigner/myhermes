"""Telegram polling/webhook adapter for Hermes Operator."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from hermes_operator.config import OperatorConfig
from hermes_operator.task_engine import TaskEngine

log = logging.getLogger(__name__)


@dataclass
class TelegramAdapter:
    config: OperatorConfig
    engine: TaskEngine

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.config.telegram_bot_token}"

    def is_allowed(self, user_id: int | str | None) -> bool:
        if not self.config.telegram_allowed_user_ids:
            return False
        return str(user_id) in set(self.config.telegram_allowed_user_ids)

    async def send_message(self, chat_id: int | str, text: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.base_url}/sendMessage", json={"chat_id": chat_id, "text": text})
            response.raise_for_status()

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        text = (message.get("text") or "").strip()
        if not chat_id or not text:
            return
        if not self.is_allowed(user_id):
            await self.send_message(chat_id, "This Hermes Operator is private.")
            return
        reply = await self.dispatch_text(text)
        await self.send_message(chat_id, reply)

    async def dispatch_text(self, text: str) -> str:
        if text == "/start":
            return "Hermes Operator is online. Use /status, /dashboard, /projects, /goals, /memory, /task, /continue, /index, or /worker."
        if text == "/status":
            return "Hermes Operator is running. Choreo is compute; Supabase and GitHub hold state."
        if text == "/dashboard":
            summary = await self.engine.dashboard_summary()
            tasks = summary["tasks"]
            return (
                "Dashboard: "
                f"{summary['projects']} project(s), {summary['goals']} goal(s), "
                f"tasks queued={tasks['queued']} running={tasks['running']} completed={tasks['completed']} failed={tasks['failed']}, "
                f"pending approvals={summary['pending_approvals']}."
            )
        if text.startswith("/memory "):
            payload = text.removeprefix("/memory ").strip()
            if "=" in payload:
                key, value = payload.split("=", 1)
            else:
                key, value = "note", payload
            path = await self.engine.save_memory(key.strip(), value.strip())
            return f"Memory saved to {path}."
        if text.startswith("/search "):
            query = text.removeprefix("/search ").strip()
            result = await self.engine.search_memory(query)
            if not result["results"]:
                return f"No memory matches for '{query}'."
            return "Memory matches:\n" + "\n".join(
                f"- {item['path']} (score {item['score']})" for item in result["results"][:5]
            )
        if text == "/index":
            result = await self.engine.rebuild_memory_index()
            return f"Semantic memory index rebuilt: {result['count']} document(s)."
        if text.startswith("/goal "):
            goal = text.removeprefix("/goal ").strip()
            result = await self.engine.plan_goal_records(goal)
            return f"Goal planned: {result['goal'].get('title', goal)} with {len(result['tasks'])} task(s)."
        if text.startswith("/kirzkit "):
            goal = text.removeprefix("/kirzkit ").strip()
            result = self.engine.plan_with_kirzkit(goal)
            return (
                f"KirzKit plan: {len(result['recommended_skills'])} skill(s), "
                f"{len(result['recommended_workflows'])} workflow(s)."
            )
        if text.startswith("/continue "):
            project = text.removeprefix("/continue ").strip()
            task = await self.engine.continue_project(project)
            return f"Project continuity ready for {project}. Task {task.id} completed."
        if text.startswith("/context "):
            project = text.removeprefix("/context ").strip()
            packet = await self.engine.build_project_context(project)
            return (
                f"Context packet for {project}: "
                f"{len(packet['next_tasks'])} open tasks, "
                f"{len(packet['recent_tasks'])} recent tasks."
            )
        if text == "/graph":
            result = await self.engine.rebuild_graph()
            if result.ok:
                return "Graphify knowledge graph rebuilt:\n" + "\n".join(result.uploaded or ["No output files uploaded."])
            return f"Graphify rebuild skipped: {result.status}. {result.detail or ''}".strip()
        if text.startswith("/graph "):
            query = text.removeprefix("/graph ").strip()
            result = await self.engine.query_graph(query)
            return (
                f"Graph query '{query}': "
                f"{len(result['matched_nodes'])} nodes, {len(result['matched_edges'])} edges, status={result['status']}."
            )
        if text == "/process":
            result = await self.engine.process_memory_pipeline()
            return f"Processed {len(result['processed'])} raw memories."
        if text == "/worker":
            result = await self.engine.run_queued_tasks_once()
            return f"Worker processed {result['count']} queued task(s)."
        if text.startswith("/skills"):
            return (
                "Skill sources: KirzKit first, Hermes Operator native skills second, Ruflo optional orchestration third. "
                "Use the HTTP API /operator/skills/sources for the full indexed list."
            )
        if text.startswith("/execute "):
            result = await self.engine.execute_goal(text.removeprefix("/execute ").strip())
            return f"Execution {result['status']}: {len(result['steps'])} step(s)."
        if text.startswith("/task "):
            task = await self.engine.create_task(text.removeprefix("/task ").strip())
            return f"Task queued: {task.id}\nGoal: {task.goal}"
        if text == "/projects":
            projects = await self.engine.list_projects()
            if not projects:
                return "No projects found yet."
            return "Projects:\n" + "\n".join(f"- {item['name']}" for item in projects[:20])
        if text.startswith("/project "):
            project = text.removeprefix("/project ").strip()
            status = await self.engine.project_status(project)
            return (
                f"{project}: {len(status['next_tasks'])} open task(s), "
                f"graph={status['graph_status']}, files={len(status['files_present'])} present."
            )
        if text == "/approvals":
            approvals = await self.engine.list_pending_approvals()
            if not approvals:
                return "No pending approvals."
            return "Pending approvals:\n" + "\n".join(
                f"- {item['id']} {item.get('skill')}: {item.get('reason')}" for item in approvals[:10]
            )
        if text.startswith("/approve "):
            approval_id = text.removeprefix("/approve ").strip()
            result = await self.engine.approve_and_continue(approval_id)
            return f"Approval continued: {result['status']} ({len(result['steps'])} step(s))."
        if text.startswith("/reject "):
            approval_id = text.removeprefix("/reject ").strip()
            await self.engine.reject_request(approval_id)
            return f"Approval rejected: {approval_id}."
        if text in {"/goals"}:
            goals = await self.engine.list_goals()
            if not goals:
                return "No goals found yet."
            return "Goals:\n" + "\n".join(f"- {item.get('title') or item.get('goal') or item.get('id')}" for item in goals[:10])

        task = await self.engine.create_task(text)
        return f"I captured this as task {task.id}.\nGoal: {task.goal}"

    async def poll_forever(self) -> None:
        if not self.config.telegram_bot_token:
            log.info("Telegram polling disabled: TELEGRAM_BOT_TOKEN is not set.")
            return
        offset: int | None = None
        while True:
            try:
                params: dict[str, Any] = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                async with httpx.AsyncClient(timeout=40) as client:
                    response = await client.get(f"{self.base_url}/getUpdates", params=params)
                    response.raise_for_status()
                    updates = response.json().get("result", [])
                for update in updates:
                    offset = update["update_id"] + 1
                    await self.handle_update(update)
            except Exception:
                log.exception("Telegram polling error")
                await asyncio.sleep(5)
