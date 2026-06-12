"""Telegram polling/webhook adapter for Hermes Operator."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from hermes_operator.config import OperatorConfig
from hermes_operator.document_ingest import extract_document_text
from hermes_operator.profile_memory import ProfileMemory
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
        if not chat_id:
            return
        if not self.is_allowed(user_id):
            await self.send_message(chat_id, "This Hermes Operator is private.")
            return
        if message.get("document"):
            reply = await self.handle_document(message["document"], caption=(message.get("caption") or "").strip())
        elif text:
            reply = await self.dispatch_text(text)
        else:
            reply = "Send text, a slash command, or a document/PDF for me to read."
        await self.send_message(chat_id, reply)

    async def dispatch_text(self, text: str) -> str:
        if text in {"/start", "/help"}:
            return self._help_text()
        if text == "/status":
            return "Hermes Operator is running. Choreo is compute; Supabase and GitHub hold state."
        if text == "/model":
            status = self.engine.model_status()
            return (
                f"Model: {status['configured_model']}\n"
                f"Provider: {status['provider']}\n"
                f"Fallbacks: {', '.join(status['candidate_models'])}\n"
                f"API key: {'set' if status['has_api_key'] else 'missing'}"
            )
        if text == "/selfcheck":
            return self._format_self_check(self.engine.self_check())
        if text == "/profile":
            return self._format_profile(await self.engine.profile_summary())
        if text == "/brief":
            review = await self.engine.daily_review()
            return (
                f"Daily Brief\n\n"
                f"{review['headline']}\n\n"
                f"Goals: {len(review['goals'])}\n"
                f"Projects: {len(review['projects'])}\n"
                f"Queued tasks: {review['tasks']['queued_count']}\n"
                f"Failed tasks: {review['tasks']['failed_count']}\n"
                f"Approvals: {len(review['approvals'])}\n\n"
                f"Focus: {review['suggested_focus']}"
            )
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
        if text.startswith("/website "):
            brief = text.removeprefix("/website ").strip()
            result = await self.engine.website_plan(brief)
            plan = result["kirzkit_plan"]
            return (
                f"Website plan created.\n"
                f"Task: {result['task_id']}\n"
                f"Memory: {result['memory_path']}\n"
                f"KirzKit skills: {len(plan['recommended_skills'])}\n"
                f"Workflows: {len(plan['recommended_workflows'])}"
            )
        if text.startswith("/repo "):
            return await self._dispatch_repo(text.removeprefix("/repo ").strip())
        if text.startswith("/branch "):
            return await self._dispatch_branch(text.removeprefix("/branch ").strip())
        if text.startswith("/write "):
            return await self._dispatch_write(text.removeprefix("/write ").strip())
        if text.startswith("/draftpr "):
            return await self._dispatch_draft_pr(text.removeprefix("/draftpr ").strip())
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
        if text.startswith("/next "):
            project = text.removeprefix("/next ").strip()
            result = await self.engine.project_next_action(project)
            return (
                f"Next for {project}\n"
                f"Recommended: {result['recommended_next_action']}\n"
                f"Open tasks: {len(result['open_tasks'])}\n"
                f"Memory matches: {len(result['memory_matches'])}\n"
                f"Graph: {result['graph_status']}"
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

        natural_reply = await self._dispatch_natural_text(text)
        if natural_reply:
            return natural_reply
        return await self.engine.chat_reply(text)

    @staticmethod
    def _help_text() -> str:
        return (
            "Hermes Operator commands:\n"
            "/status - health\n"
            "/selfcheck - config + capability smoke test\n"
            "/profile - what Hermes knows about you\n"
            "/brief - daily review\n"
            "/model - model/fallback status\n"
            "/memory key=value - save memory\n"
            "/search query - search memory\n"
            "/goal goal - create goal plan\n"
            "/continue project - load project\n"
            "/next project - recommended next action\n"
            "/projects - list projects\n"
            "/repo index owner/repo - cache repo context\n"
            "/repo status owner/repo - repo summary\n"
            "/repo context owner/repo - repo details\n"
            "/repo refresh owner/repo - rebuild repo cache\n"
            "/repo cache [project] - list repo awareness cache\n"
            "/branch owner/repo branch - create safe branch\n"
            "/write owner/repo branch path content - write branch file\n"
            "/draftpr owner/repo branch title - create draft PR\n"
            "/website brief - KirzKit website plan\n"
            "/kirzkit brief - KirzKit skill plan\n"
            "Natural text also works: remember ..., continue Project, build a landing page.\n"
            "Send PDF/DOCX/TXT/MD files and I will read + save them."
        )

    @staticmethod
    def _identity_text() -> str:
        return (
            "I am Hermes, your phone-controlled project operator.\n\n"
            "I help manage goals, projects, memories, repositories, tasks, and safe GitHub workflows.\n\n"
            "Current systems:\n"
            "- Telegram control\n"
            "- GitHub memory\n"
            "- Supabase state\n"
            "- Repository awareness\n"
            "- KirzKit-first build planning\n\n"
            "Try:\n"
            "- continue BrandBlueprint\n"
            "- what should I work on next\n"
            "- search memory for SEO\n"
            "- /repo status kirawebdesigner/myhermes"
        )

    @staticmethod
    def _greeting_text() -> str:
        return (
            "Hi Kirubel. I am here.\n\n"
            "You can talk normally or ask me to act:\n"
            "- remember I am 16\n"
            "- continue BrandBlueprint\n"
            "- what do you know about me\n"
            "- /repo status kirawebdesigner/myhermes"
        )

    @staticmethod
    def _format_profile(summary: dict[str, Any]) -> str:
        profile = summary.get("profile") or {}
        projects = summary.get("projects") or []
        goals = summary.get("goals") or []
        lines = ["What I know about you:"]
        for key in ["name", "nickname", "age", "school", "location"]:
            if profile.get(key) is not None:
                lines.append(f"- {key.replace('_', ' ').title()}: {profile[key]}")
        if profile.get("note"):
            lines.append(f"- Note: {profile['note']}")
        if projects:
            lines.append("Projects:")
            lines.extend(f"- {item.get('name')}" for item in projects[:5] if item.get("name"))
        if goals:
            lines.append("Goals:")
            lines.extend(f"- {item.get('title') or item.get('goal') or item.get('id')}" for item in goals[:5])
        if len(lines) == 1:
            lines.append("- I do not have profile facts yet. Say: my name is Kirubel, my age is 16.")
        return "\n".join(lines)

    @staticmethod
    def _format_self_check(check: dict[str, Any]) -> str:
        model = check["model"]
        capabilities = check["capabilities"]
        safety = check["safety"]
        missing = ", ".join(check["missing"]) if check["missing"] else "none"
        tests = "\n".join(f"- {item}" for item in check["smoke_tests"][:6])
        return (
            "Hermes Self Check\n"
            f"OK: {check['ok']}\n"
            f"Missing: {missing}\n"
            f"Model: {model['configured_model']}\n"
            f"Memory repo: {check['memory_repo']}\n"
            f"Allowed repos: {', '.join(check['allowed_repos']) or 'none'}\n"
            f"Natural actions: {len(capabilities['natural_safe_actions'])}\n"
            f"Documents: {', '.join(capabilities['documents'][:8])}...\n"
            f"Delete allowed: {safety['allow_delete']}\n"
            f"Force push allowed: {safety['allow_force_push']}\n\n"
            f"Try:\n{tests}"
        )

    async def _dispatch_natural_text(self, text: str) -> str | None:
        lower = text.strip().lower()
        if not lower:
            return None

        if lower in {"hi", "hello", "hey", "yo", "sup", "hey hermes", "hi hermes"}:
            return self._greeting_text()

        if lower.rstrip("?") in {"who are you", "what are you", "what can you do", "help me"}:
            return self._identity_text()

        if lower.rstrip("?") in {"what do you know about me", "who am i", "profile", "show my profile"}:
            return self._format_profile(await self.engine.profile_summary())

        profile_updates = ProfileMemory.parse_update(text)
        if profile_updates and (
            lower.startswith(("update that ", "remember ", "save that "))
            or re.search(r"\b(?:i am|i'm|im|my age is|age is|turned|my name is|call me|nickname is|i live in|i study at|i go to)\b", lower)
        ):
            profile = await self.engine.update_profile(profile_updates)
            changed = ", ".join(f"{key}={value}" for key, value in profile_updates.items())
            age_line = f"\nAge: {profile['age']}" if profile.get("age") is not None else ""
            return f"Got it. I updated your profile: {changed}.{age_line}"

        memory_prefixes = (
            "remember ",
            "save memory ",
            "save this memory ",
            "note ",
            "capture ",
        )
        for prefix in memory_prefixes:
            if lower.startswith(prefix):
                value = text[len(prefix) :].strip()
                if not value:
                    return None
                path = await self.engine.save_memory("note", value)
                return f"I remembered that.\nMemory: {path}"

        continue_prefixes = ("continue ", "resume ")
        for prefix in continue_prefixes:
            if lower.startswith(prefix):
                project = text[len(prefix) :].strip(" .")
                if not project:
                    return None
                task = await self.engine.continue_project(project)
                return f"Loaded {project} and prepared continuity. Task {task.id} completed."

        next_prefixes = ("next for ", "what next for ", "next action for ")
        for prefix in next_prefixes:
            if lower.startswith(prefix):
                project = text[len(prefix) :].strip(" .?")
                if not project:
                    return None
                result = await self.engine.project_next_action(project)
                return (
                    f"Next for {project}\n"
                    f"Recommended: {result['recommended_next_action']}\n"
                    f"Open tasks: {len(result['open_tasks'])}\n"
                    f"Memory matches: {len(result['memory_matches'])}\n"
                    f"Graph: {result['graph_status']}"
                )

        task_prefixes = ("create task ", "add task ", "task ")
        for prefix in task_prefixes:
            if lower.startswith(prefix):
                goal = text[len(prefix) :].strip()
                if not goal:
                    return None
                task = await self.engine.create_task(goal)
                return f"Task queued: {task.id}\nGoal: {task.goal}"

        if lower.startswith(("search memory for ", "find memory ")):
            query = text.split(" ", 3)[-1].strip()
            if not query:
                return None
            result = await self.engine.search_memory(query)
            if not result["results"]:
                return f"No memory matches for '{query}'."
            return "Memory matches:\n" + "\n".join(
                f"- {item['path']} (score {item['score']})" for item in result["results"][:5]
            )

        project_build_terms = ("website", "landing page", "dashboard", "frontend", "ui", "component")
        build_terms = ("build", "create", "design", "make")
        if any(term in lower for term in project_build_terms) and any(term in lower for term in build_terms):
            result = await self.engine.website_plan(text)
            plan = result["kirzkit_plan"]
            return (
                "I created a KirzKit-first build plan.\n"
                f"Task: {result['task_id']}\n"
                f"Memory: {result['memory_path']}\n"
                f"KirzKit skills: {len(plan['recommended_skills'])}\n"
                f"Workflows: {len(plan['recommended_workflows'])}"
            )

        if lower in {"status", "are you online", "are you running"}:
            return "Hermes Operator is running. Choreo is compute; Supabase and GitHub hold state."
        if lower in {"daily brief", "brief me", "today brief"}:
            review = await self.engine.daily_review()
            return (
                f"Daily Brief\n\n"
                f"{review['headline']}\n\n"
                f"Goals: {len(review['goals'])}\n"
                f"Projects: {len(review['projects'])}\n"
                f"Queued tasks: {review['tasks']['queued_count']}\n"
                f"Failed tasks: {review['tasks']['failed_count']}\n"
                f"Approvals: {len(review['approvals'])}\n\n"
                f"Focus: {review['suggested_focus']}"
            )
        if lower in {"self check", "selfcheck", "check yourself", "what can you do"}:
            return self._format_self_check(self.engine.self_check())
        return None

    async def _dispatch_repo(self, payload: str) -> str:
        parts = payload.split()
        if parts and parts[0] == "cache":
            project = parts[1] if len(parts) > 1 else None
            result = await self.engine.repo_cache(project=project)
            if not result["repos"]:
                return "Repo cache is empty. Use /repo index owner/repo first."
            lines = []
            for item in result["repos"][:10]:
                lines.append(
                    f"- {item.get('repo')}: {', '.join(item.get('stack') or ['Unknown'])}; "
                    f"deploy={item.get('deployment') or 'unknown'}"
                )
            return f"Repo cache ({result['count']}):\n" + "\n".join(lines)
        if len(parts) < 2 or parts[0] not in {"index", "status", "context", "refresh"}:
            return "Use /repo index owner/name, /repo status owner/name, /repo context owner/name, /repo refresh owner/name, or /repo cache [project]."
        mode, repo = parts[0], parts[1]
        cache = mode in {"index", "context", "refresh"}
        context = await self.engine.repo_context(repo, cache=cache)
        if mode == "status":
            return self._format_repo_status(context)
        if mode in {"context", "index", "refresh"}:
            return self._format_repo_context(mode, context)

        return self._format_repo_status(context)

    @staticmethod
    def _format_repo_status(context: dict[str, Any]) -> str:
        stack = ", ".join(context["stack"])
        next_action = context["next_actions"][0] if context["next_actions"] else "Review repo context."
        last_commit = context.get("last_commit") or {}
        return (
            f"Repo status: {context['repo']}\n"
            f"Health: {context.get('repo_health', 'unknown')}/100\n"
            f"Stack: {stack}\n"
            f"Deployment: {context.get('deployment') or 'unknown'}\n"
            f"Deployment status: {context.get('deployment_status') or 'unknown'}\n"
            f"Dependencies: {', '.join(context.get('dependency_files') or []) or 'none'}\n"
            f"Issues: {len(context.get('issues') or [])}\n"
            f"Unfinished tasks: {context.get('unfinished_tasks', len(context.get('open_tasks') or []))}\n"
            f"Decisions: {len(context.get('decisions') or [])}\n"
            f"Last commit: {last_commit.get('sha', 'unknown')} {last_commit.get('message', '')}\n"
            f"Recommended: {context.get('recommended_next_action') or next_action}\n"
            f"Reason: {context.get('recommendation_reason') or 'Repo cache analysis.'}"
        )

    @staticmethod
    def _format_repo_context(mode: str, context: dict[str, Any]) -> str:
        stack = ", ".join(context["stack"])
        next_action = context["next_actions"][0] if context["next_actions"] else "Review repo context."
        memory_line = f"\nCached: {context['memory_path']}" if context.get("memory_path") else ""
        cache_line = f"\nRepo cache: {context['cache_path']}" if context.get("cache_path") else ""
        dependency_count = sum(len(value) if isinstance(value, list) else len(value.get("dependencies", [])) for value in (context.get("dependencies") or {}).values())
        return (
            f"Repo {mode}: {context['repo']}\n"
            f"Stack: {stack}\n"
            f"Health: {context.get('repo_health', 'unknown')}/100\n"
            f"Deployment: {context.get('deployment') or 'unknown'}\n"
            f"Deployment status: {context.get('deployment_status') or 'unknown'}\n"
            f"Related goal: {context.get('related_goal') or 'unknown'}\n"
            f"Issues: {len(context.get('issues') or [])}\n"
            f"Recent commits: {len(context.get('recent_commits') or [])}\n"
            f"Dependencies: {dependency_count}\n"
            f"Unfinished tasks: {context.get('unfinished_tasks', len(context.get('open_tasks') or []))}\n"
            f"Decisions: {len(context.get('decisions') or [])}\n"
            f"Files: {context['file_count']}\n"
            f"Important: {', '.join(context['important_files'][:5]) or 'none'}\n"
            f"Recommended: {context.get('recommended_next_action') or next_action}\n"
            f"Reason: {context.get('recommendation_reason') or 'Repo cache analysis.'}"
            f"{memory_line}"
            f"{cache_line}"
        )

    async def _dispatch_branch(self, payload: str) -> str:
        parts = payload.split()
        if len(parts) != 2:
            return "Use /branch owner/repo branch-name"
        repo, branch = parts
        result = await self.engine.github.create_branch(repo, branch)
        return f"Branch ready: {repo} {branch} ({result.get('ref', 'ok')})"

    async def _dispatch_write(self, payload: str) -> str:
        parts = payload.split(maxsplit=3)
        if len(parts) < 4:
            return "Use /write owner/repo branch path content"
        repo, branch, path, content = parts
        result = await self.engine._github_write_branch_file(
            repo,
            branch,
            path,
            content,
            message=f"chore: update {path} from Hermes Operator",
        )
        status = "unchanged" if result.get("unchanged") else "written"
        return f"File {status}: {repo}@{branch}:{path}"

    async def _dispatch_draft_pr(self, payload: str) -> str:
        parts = payload.split(maxsplit=2)
        if len(parts) < 3:
            return "Use /draftpr owner/repo branch title"
        repo, branch, title = parts
        result = await self.engine._github_create_draft_pr(repo, branch, title, body="Prepared by Hermes Operator.")
        url = result.get("html_url") or result.get("url") or "draft PR created"
        return f"Draft PR: {url}"

    async def handle_document(self, document: dict[str, Any], *, caption: str = "") -> str:
        file_id = document.get("file_id")
        filename = document.get("file_name") or "telegram-document"
        mime_type = document.get("mime_type")
        if not file_id:
            return "I could not read that file because Telegram did not send a file id."
        content = await self._download_file(file_id)
        extracted = extract_document_text(filename, content, mime_type=mime_type)
        result = await self.engine.save_document_memory(extracted)
        caption_line = f"\nCaption: {caption}" if caption else ""
        if extracted.status != "ok":
            return f"Document saved, but text extraction is {extracted.status}: {extracted.detail}\nPath: {result['path']}{caption_line}"
        return f"Document understood and saved: {filename}\nPath: {result['path']}\nSummary: {result['summary']}{caption_line}"

    async def _download_file(self, file_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            file_response = await client.get(f"{self.base_url}/getFile", params={"file_id": file_id})
            file_response.raise_for_status()
            file_path = file_response.json()["result"]["file_path"]
            download_response = await client.get(f"https://api.telegram.org/file/bot{self.config.telegram_bot_token}/{file_path}")
            download_response.raise_for_status()
            return download_response.content

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
