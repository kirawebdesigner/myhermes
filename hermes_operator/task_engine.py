"""Small end-to-end task engine for the first Choreo operator loop."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hermes_operator.approvals import ApprovalManager
from hermes_operator.context import ProjectContextEngine
from hermes_operator.embeddings import SemanticMemoryIndex
from hermes_operator.execution import ExecutionEngine
from hermes_operator.goal_planner import GoalPlanner
from hermes_operator.github import GitHubClient
from hermes_operator.graphify import GraphifyRunner, GraphifyResult
from hermes_operator.graph_query import GraphQueryEngine
from hermes_operator.llm import LLMPlanner
from hermes_operator.kirzkit import KirzKitPlanner
from hermes_operator.memory_pipeline import MemoryPipeline
from hermes_operator.memory_search import MemorySearchEngine
from hermes_operator.memory_os import MemoryOS
from hermes_operator.models import MemoryRecord, OperatorTask, TaskStatus
from hermes_operator.projects import ProjectRegistry
from hermes_operator.replay import ReplayStore, json_safe
from hermes_operator.skill_sources import SkillSourceRegistry
from hermes_operator.skills import SkillDefinition, SkillRegistry, default_skill_definitions
from hermes_operator.supabase import SupabaseClient


class TaskEngine:
    def __init__(
        self,
        supabase: SupabaseClient,
        github: GitHubClient,
        memory: MemoryOS,
        planner: LLMPlanner,
        graphify: GraphifyRunner | None = None,
        skill_sources: SkillSourceRegistry | None = None,
    ) -> None:
        self.supabase = supabase
        self.github = github
        self.memory = memory
        self.planner = planner
        self.graphify = graphify
        self.context = ProjectContextEngine(memory, supabase)
        self.projects = ProjectRegistry(memory, supabase, self.context)
        self.memory_pipeline = MemoryPipeline(memory)
        self.memory_search = MemorySearchEngine(memory)
        self.semantic_memory = SemanticMemoryIndex(memory, supabase)
        self.graph_query = GraphQueryEngine(memory)
        self.skill_sources = skill_sources
        self.goal_planner = GoalPlanner(supabase, memory)
        self.kirzkit_planner = KirzKitPlanner(skill_sources) if skill_sources is not None else None
        self.replay_store = ReplayStore(memory)
        self.approvals = ApprovalManager(supabase)
        self.skill_registry = self._build_skill_registry()
        self.execution = ExecutionEngine(self.skill_registry, allow_tier_1_5_auto=github.config.allow_tier_1_5_auto)

    async def create_task(self, goal: str, *, project: str | None = None, repo: str | None = None) -> OperatorTask:
        planned_goal = await self.planner.summarize_intent(goal)
        task = OperatorTask(goal=planned_goal, project=project, repo=repo)
        await self.supabase.insert("tasks", task.model_dump())
        await self.memory.save_task_snapshot(task)
        return task

    async def chat_reply(self, message: str) -> str:
        return await self.planner.chat_reply(message)

    async def complete_task(self, task: OperatorTask, result: str) -> OperatorTask:
        task.status = TaskStatus.completed
        task.result = result
        task.updated_at = datetime.now(timezone.utc).isoformat()
        await self.supabase.update("tasks", task.id, task.model_dump())
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": task.id,
                "level": "info",
                "message": result,
                "metadata": task.metadata,
            },
        )
        await self.memory.save_task_snapshot(task)
        return task

    async def save_memory(self, key: str, value: str, *, project: str | None = None) -> str:
        record = MemoryRecord(key=key, value=value, project=project)
        path = await self.memory.save_memory(record)
        await self.supabase.insert(
            "memories",
            {
                "key": key,
                "value": value,
                "project": project,
                "source": "operator",
                "metadata": {"github_path": path},
            },
        )
        await self._index_memory_file_best_effort(path)
        return path

    async def continue_project(self, project: str) -> OperatorTask:
        await self.memory.ensure_project(project)
        graph_summary = await self.query_graph(project)
        context_packet = await self.build_project_context(project, graph_summary=graph_summary)
        task = await self.create_task(
            (
                f"Continue {project}: query Graphify first when graphify-out exists, then review README, roadmap, "
                "tasks, memory, decisions, and status before acting."
            ),
            project=project,
        )
        return await self.complete_task(
            task,
            (
                f"Project continuity files for {project} are initialized. "
                "Next implementation pass should query Graphify first, then load README, roadmap, tasks, "
                f"memory, decisions, and status. Open tasks found: {len(context_packet['next_tasks'])}."
            ),
        )

    async def rebuild_graph(self) -> GraphifyResult:
        if self.graphify is None:
            return GraphifyResult(ok=False, status="unconfigured", uploaded=[], detail="Graphify runner is not configured.")
        result = await self.graphify.rebuild_memory_graph()
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": None,
                "level": "info" if result.ok else "warning",
                "message": f"Graphify rebuild {result.status}",
                "metadata": {"uploaded": result.uploaded, "detail": result.detail},
            },
        )
        await self.supabase.insert(
            "graph_runs",
            {
                "status": result.status,
                "uploaded": result.uploaded,
                "detail": result.detail,
                "metadata": {"ok": result.ok},
            },
        )
        return result

    async def build_project_context(
        self, project: str, *, graph_summary: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        await self.memory.ensure_project(project)
        return await self.context.build_packet(project, graph_summary=graph_summary)

    async def process_memory_pipeline(self, *, limit: int = 20) -> dict[str, Any]:
        result = await self.memory_pipeline.process_raw(limit=limit)
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": None,
                "level": "info",
                "message": f"Memory pipeline processed {len(result['processed'])} raw notes",
                "metadata": result,
            },
        )
        if result["processed"] and self.graphify is not None:
            await self.rebuild_graph()
        for item in result["processed"]:
            wiki_path = item.get("wiki_path")
            if wiki_path:
                await self._index_memory_file_best_effort(wiki_path)
        return result

    async def query_graph(self, term: str, *, limit: int = 20) -> dict[str, Any]:
        return await self.graph_query.query(term, limit=limit)

    async def search_memory(self, query: str, *, limit: int = 10) -> dict[str, Any]:
        semantic = await self.semantic_memory.search(query, limit=limit)
        if semantic["results"]:
            return semantic
        lexical = await self.memory_search.search(query, limit=limit)
        lexical["fallback_reason"] = "semantic index is empty"
        return lexical

    async def rebuild_memory_index(self, *, limit: int = 200) -> dict[str, Any]:
        result = await self.semantic_memory.rebuild(limit=limit)
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": None,
                "level": "info",
                "message": f"Semantic memory index rebuilt: {result['count']} document(s)",
                "metadata": result,
            },
        )
        return result

    async def plan_goal_records(
        self, goal: str, *, projects: list[str] | None = None, tasks: list[str] | None = None
    ) -> dict[str, Any]:
        return await self.goal_planner.create_plan(goal, projects=projects, tasks=tasks)

    async def list_goals(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return await self.supabase.list_rows("goals", limit=limit)

    async def run_queued_tasks_once(self, *, limit: int = 3) -> dict[str, Any]:
        rows = await self.supabase.list_rows("tasks", limit=50)
        queued = [row for row in rows if row.get("status") == "queued"][:limit]
        results: list[dict[str, Any]] = []
        for row in queued:
            task_id = row["id"]
            await self.supabase.update("tasks", task_id, {"status": "running"})
            try:
                execution = await self.execute_goal(row["goal"], project=row.get("project"), repo=row.get("repo"))
                await self.supabase.update(
                    "tasks",
                    task_id,
                    {
                        "status": "completed" if execution["status"] == "completed" else "failed",
                        "result": execution["status"],
                        "metadata": {"execution_id": execution["execution_id"]},
                    },
                )
                results.append({"task_id": task_id, "status": execution["status"], "execution_id": execution["execution_id"]})
            except Exception as exc:
                await self.supabase.update("tasks", task_id, {"status": "failed", "error": str(exc)})
                results.append({"task_id": task_id, "status": "failed", "error": str(exc)})
        return {"ok": True, "processed": results, "count": len(results)}

    async def dashboard_summary(self) -> dict[str, Any]:
        projects = await self.list_projects()
        goals = await self.list_goals(limit=20)
        tasks = await self.supabase.list_rows("tasks", limit=100)
        approvals = await self.list_pending_approvals(limit=20)
        replays = await self.supabase.list_rows("execution_replays", limit=20)
        return {
            "projects": len(projects),
            "goals": len(goals),
            "tasks": {
                "queued": len([task for task in tasks if task.get("status") == "queued"]),
                "running": len([task for task in tasks if task.get("status") == "running"]),
                "completed": len([task for task in tasks if task.get("status") == "completed"]),
                "failed": len([task for task in tasks if task.get("status") == "failed"]),
            },
            "pending_approvals": len(approvals),
            "recent_executions": len(replays),
            "latest_execution": replays[0] if replays else None,
        }

    def plan_with_kirzkit(self, goal: str, *, project: str | None = None) -> dict[str, Any]:
        if self.kirzkit_planner is None:
            return {"goal": goal, "project": project, "queries": [], "recommended_workflows": [], "recommended_skills": [], "recommended_agents": [], "implementation_sequence": []}
        return self.kirzkit_planner.plan(goal, project=project)

    async def plan_goal(self, goal: str, *, project: str | None = None, repo: str | None = None) -> dict[str, Any]:
        project_name = project or self.execution._project_from_goal(goal)
        graph_summary = await self.query_graph(project_name)
        context_packet = await self.build_project_context(project_name, graph_summary=graph_summary)
        kirzkit_query = self._kirzkit_query_for_goal(goal)
        kirzkit_results = self._search_skill_sources(kirzkit_query)
        kirzkit_plan = self.plan_with_kirzkit(goal, project=project_name)
        memory_search = await self.search_memory(goal, limit=5)
        plan = self.execution.plan_from_goal(goal, project=project_name, repo=repo)
        return {
            "goal": goal,
            "project": project_name,
            "repo": repo,
            "context_packet": context_packet,
            "graph_query": graph_summary,
            "kirzkit_query": kirzkit_query,
            "kirzkit_results": kirzkit_results,
            "kirzkit_plan": kirzkit_plan,
            "memory_search": memory_search,
            "plan": plan,
        }

    async def execute_goal(
        self,
        goal: str,
        *,
        project: str | None = None,
        repo: str | None = None,
        approved_skills: set[str] | None = None,
    ) -> dict[str, Any]:
        preflight = await self.plan_goal(goal, project=project, repo=repo)
        result = await self.execution.execute_plan(preflight["plan"], approved_skills=approved_skills)
        return await self._persist_execution_result(goal, preflight, result)

    async def execute_custom_plan(
        self,
        goal: str,
        plan: list[dict[str, Any]],
        *,
        project: str | None = None,
        approved_skills: set[str] | None = None,
    ) -> dict[str, Any]:
        preflight = await self.plan_goal(goal, project=project)
        preflight["plan"] = plan
        result = await self.execution.execute_plan(plan, approved_skills=approved_skills)
        return await self._persist_execution_result(goal, preflight, result)

    async def _persist_execution_result(
        self, goal: str, preflight: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        result["goal"] = goal
        result["project"] = preflight["project"]
        result["preflight"] = preflight
        result["plan"] = preflight["plan"]
        replay = {
            "execution_id": result["execution_id"],
            "goal": goal,
            "project": preflight["project"],
            "status": result["status"],
            "context_packet": preflight["context_packet"],
            "graph_query": preflight["graph_query"],
            "kirzkit_search": preflight["kirzkit_results"],
            "kirzkit_plan": preflight["kirzkit_plan"],
            "memory_search": preflight["memory_search"],
            "plan": preflight["plan"],
            "steps": result["steps"],
            "final_result": result["status"],
        }
        replay_paths = await self.replay_store.save(replay)
        result["replay"] = replay_paths
        approvals = await self.approvals.create_for_blocked_steps(
            execution_id=result["execution_id"],
            goal=goal,
            project=preflight["project"],
            plan=preflight["plan"],
            steps=result["steps"],
        )
        result["approvals"] = approvals
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": None,
                "level": "info" if result["status"] == "completed" else "warning",
                "message": f"Execution {result['status']}: {goal}",
                "metadata": json_safe(result),
            },
        )
        await self.supabase.insert(
            "execution_replays",
            {
                "id": result["execution_id"],
                "goal": goal,
                "project": preflight["project"],
                "status": result["status"],
                "replay_paths": replay_paths,
                "metadata": json_safe({"plan": preflight["plan"], "steps": result["steps"]}),
            },
        )
        if self.graphify is not None:
            graph_result = await self.rebuild_graph()
            result["graph_update"] = {
                "ok": graph_result.ok,
                "status": graph_result.status,
                "uploaded": graph_result.uploaded,
                "detail": graph_result.detail,
            }
        return result

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self.projects.list_projects()

    async def project_status(self, project: str) -> dict[str, Any]:
        graph_summary = await self.query_graph(project)
        return await self.projects.status(project, graph_summary=graph_summary)

    async def list_pending_approvals(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return await self.approvals.list_pending(limit=limit)

    async def approve_request(self, approval_id: str) -> dict[str, Any]:
        return await self.approvals.approve(approval_id)

    async def reject_request(self, approval_id: str) -> dict[str, Any]:
        return await self.approvals.reject(approval_id)

    async def approve_and_continue(self, approval_id: str) -> dict[str, Any]:
        approval = await self.approvals.get(approval_id)
        if not approval:
            raise ValueError(f"Approval not found: {approval_id}")
        if approval.get("status") == "rejected":
            raise ValueError(f"Approval is rejected: {approval_id}")
        await self.approvals.approve(approval_id)
        payload = approval.get("payload") or {}
        skill = payload.get("skill") or approval.get("skill")
        step = {"skill": skill, "inputs": payload.get("inputs") or {}}
        result = await self.execution.execute_plan([step], approved_skills={skill})
        replay = {
            "execution_id": result["execution_id"],
            "goal": approval.get("goal", ""),
            "project": approval.get("project"),
            "status": result["status"],
            "approval_id": approval_id,
            "approved_step": step,
            "steps": result["steps"],
            "final_result": result["status"],
        }
        replay_paths = await self.replay_store.save(replay)
        result["approval_id"] = approval_id
        result["replay"] = replay_paths
        await self.supabase.insert(
            "execution_replays",
            {
                "id": result["execution_id"],
                "goal": approval.get("goal", ""),
                "project": approval.get("project"),
                "status": result["status"],
                "replay_paths": replay_paths,
                "metadata": json_safe({"approval_id": approval_id, "step": step, "steps": result["steps"]}),
            },
        )
        await self.supabase.insert(
            "execution_logs",
            {
                "task_id": None,
                "level": "info" if result["status"] == "completed" else "warning",
                "message": f"Approval continued {result['status']}: {approval_id}",
                "metadata": json_safe(result),
            },
        )
        return result

    def list_skills(self) -> list[SkillDefinition]:
        return self.skill_registry.list()

    def search_skills(self, query: str) -> list[SkillDefinition]:
        return self.skill_registry.search(query)

    def _build_skill_registry(self) -> SkillRegistry:
        registry = SkillRegistry()
        handlers = {
            "memory_save": self.save_memory,
            "task_create": self.create_task,
            "project_context": self.build_project_context,
            "graph_query": self._execute_graph_query,
            "graphify_rebuild": self._execute_rebuild_graph,
            "skill_source_search": self._search_skill_sources,
            "memory_pipeline_process": self.process_memory_pipeline,
            "memory_index_rebuild": self.rebuild_memory_index,
            "memory_search": self._execute_memory_search,
            "goal_plan": self._execute_goal_plan,
            "kirzkit_generate_plan": self._execute_kirzkit_plan,
            "github_branch_create": self.github.create_branch,
            "github_read_file": self.github.get_text_file,
            "github_write_file": self._github_write_branch_file,
            "github_commit_file": self._github_commit_file,
            "github_list_tree": self.github.list_tree,
            "github_pr_draft": self._github_create_draft_pr,
            "github_pr_ready": self._github_create_ready_pr,
            "github_issue_create": self.github.create_issue,
            "github_issue_comment": self.github.comment_issue,
        }
        for definition in default_skill_definitions():
            registry.register(definition, handlers[definition.name])
        return registry

    async def _execute_graph_query(self, term: str | None = None, query: str | None = None, limit: int = 20) -> dict[str, Any]:
        return await self.query_graph(term or query or "", limit=limit)

    async def _execute_rebuild_graph(self, **_: Any) -> GraphifyResult:
        return await self.rebuild_graph()

    def _search_skill_sources(self, query: str) -> list[dict[str, Any]]:
        if self.skill_sources is None:
            return []
        return self.skill_sources.search(query)

    async def _execute_memory_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        return await self.search_memory(query, limit=limit)

    async def _execute_goal_plan(
        self, goal: str, projects: list[str] | None = None, tasks: list[str] | None = None
    ) -> dict[str, Any]:
        return await self.plan_goal_records(goal, projects=projects, tasks=tasks)

    def _execute_kirzkit_plan(self, goal: str, project: str | None = None) -> dict[str, Any]:
        return self.plan_with_kirzkit(goal, project=project)

    async def _github_write_branch_file(
        self,
        repo: str,
        branch: str,
        path: str,
        content: str,
        message: str = "chore: update from Hermes Operator",
    ) -> dict[str, Any]:
        await self._require_non_default_branch(repo, branch)
        return await self.github.put_file(repo, path, content, message, branch=branch)

    async def _github_commit_file(
        self,
        repo: str,
        branch: str,
        path: str,
        content: str,
        message: str,
    ) -> dict[str, Any]:
        await self._require_non_default_branch(repo, branch)
        return await self.github.put_file(repo, path, content, message, branch=branch)

    async def _github_create_draft_pr(self, repo: str, branch: str, title: str, body: str = "") -> dict[str, Any]:
        return await self.github.create_pull_request(repo, branch, title, body, draft=True)

    async def _github_create_ready_pr(self, repo: str, branch: str, title: str, body: str = "") -> dict[str, Any]:
        return await self.github.create_pull_request(repo, branch, title, body, draft=False)

    async def _index_memory_file_best_effort(self, path: str) -> None:
        try:
            content = await self.memory.read_memory_file(path)
            if not content:
                return
            document = await self.supabase.insert(
                "documents",
                {
                    "source": "github-memory",
                    "path": path,
                    "title": path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                    "content": content,
                    "metadata": {"indexed_by": "hermes-operator", "best_effort": True},
                },
            )
            await self.supabase.insert(
                "embeddings",
                {
                    "document_id": document.get("id"),
                    "content": content.strip()[:1000],
                    "embedding": self.semantic_memory.embed(f"{path}\n{content}"),
                    "metadata": {"path": path, "source": "github-memory", "dimensions": self.semantic_memory.dimensions},
                },
            )
        except Exception:
            return

    async def _require_non_default_branch(self, repo: str, branch: str) -> None:
        repo_info = await self.github.get_repo(repo)
        default_branch = repo_info.get("default_branch") or "main"
        if branch == default_branch:
            raise ValueError("Default-branch writes are disabled. Use a Hermes working branch.")

    @staticmethod
    def _kirzkit_query_for_goal(goal: str) -> str:
        lower = goal.lower()
        project_building_terms = ["ui", "frontend", "saas", "supabase", "docs", "documentation", "deploy", "deployment"]
        if any(term in lower for term in project_building_terms):
            return goal
        return "project-planner"
