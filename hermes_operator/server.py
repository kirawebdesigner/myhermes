"""FastAPI entry point for Choreo-hosted Hermes Operator mode."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from hermes_operator.config import OperatorConfig, load_config
from hermes_operator.github import GitHubClient
from hermes_operator.graphify import GraphifyRunner
from hermes_operator.llm import LLMPlanner
from hermes_operator.memory_os import MemoryOS
from hermes_operator.safety import SafetyPolicy
from hermes_operator.skill_sources import SkillSourceRegistry
from hermes_operator.supabase import SupabaseClient
from hermes_operator.task_engine import TaskEngine
from hermes_operator.telegram import TelegramAdapter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    goal: str
    project: str | None = None
    repo: str | None = None


class MemoryRequest(BaseModel):
    key: str
    value: str
    project: str | None = None


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 10


class MemoryIndexRequest(BaseModel):
    limit: int = 200


class GoalPlanRequest(BaseModel):
    goal: str
    project: str | None = None
    projects: list[str] | None = None
    tasks: list[str] | None = None


class KirzKitPlanRequest(BaseModel):
    goal: str
    project: str | None = None


class WebsitePlanRequest(BaseModel):
    brief: str
    project: str | None = None


class RepoContextRequest(BaseModel):
    repo: str
    ref: str | None = None
    cache: bool = True


class GraphQueryRequest(BaseModel):
    term: str
    limit: int = 20


class ExecuteRequest(BaseModel):
    goal: str
    project: str | None = None
    repo: str | None = None
    approved_skills: list[str] = []


class ExecutePlanRequest(BaseModel):
    goal: str
    project: str | None = None
    plan: list[dict[str, Any]]
    approved_skills: list[str] = []


class GitHubBranchRequest(BaseModel):
    repo: str
    branch: str
    from_ref: str | None = None


class GitHubWriteRequest(BaseModel):
    repo: str
    branch: str
    path: str
    content: str
    message: str = "chore: update from Hermes Operator"


class GitHubPullRequest(BaseModel):
    repo: str
    branch: str
    title: str
    body: str = ""
    ready_for_review: bool = False
    approved: bool = False


class PipelineRequest(BaseModel):
    limit: int = 20


class WorkerRunRequest(BaseModel):
    limit: int = 3


class ApprovalActionRequest(BaseModel):
    approval_id: str


class AppState:
    config: OperatorConfig
    supabase: SupabaseClient
    engine: TaskEngine
    telegram: TelegramAdapter
    skills: SkillSourceRegistry


state = AppState()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not state.config.api_server_key:
        raise HTTPException(status_code=503, detail="API_SERVER_KEY is not configured")
    if x_api_key != state.config.api_server_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    missing = config.missing_required()
    if missing:
        log.warning("Hermes Operator missing required configuration: %s", ", ".join(missing))
    safety = SafetyPolicy(config)
    supabase = SupabaseClient(config)
    github = GitHubClient(config, safety)
    memory = MemoryOS(github, config.memory_repo)
    graphify = GraphifyRunner(config, memory, github)
    planner = LLMPlanner(config)
    skills = SkillSourceRegistry(config)
    engine = TaskEngine(supabase, github, memory, planner, graphify, skills)
    telegram = TelegramAdapter(config, engine)

    state.config = config
    state.supabase = supabase
    state.engine = engine
    state.telegram = telegram
    state.skills = skills

    poll_task: asyncio.Task[Any] | None = None
    worker_task: asyncio.Task[Any] | None = None
    if config.telegram_bot_token:
        poll_task = asyncio.create_task(telegram.poll_forever())
    if config.operator_worker_enabled:
        worker_task = asyncio.create_task(_worker_loop(engine, config.operator_worker_interval_seconds))
    yield
    if poll_task:
        poll_task.cancel()
    if worker_task:
        worker_task.cancel()


app = FastAPI(title="Hermes Operator", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    missing = state.config.missing_required()
    return {
        "ok": not missing,
        "mode": "operator",
        "missing": missing,
        "memory_repo": state.config.memory_repo,
        "allowed_repos": state.config.allowed_repos,
        "graphify_enabled": state.config.graphify_enabled,
        "graphify_command": state.config.graphify_command,
        "kirzkit_local_path": state.config.kirzkit_local_path,
        "ruflo_repo": state.config.ruflo_repo,
        "worker_enabled": state.config.operator_worker_enabled,
        "model": state.engine.model_status(),
    }


@app.post("/operator/bootstrap", dependencies=[Depends(require_api_key)])
async def bootstrap() -> dict[str, Any]:
    await state.engine.memory.bootstrap()
    return {"ok": True}


@app.post("/operator/tasks", dependencies=[Depends(require_api_key)])
async def create_task(payload: TaskRequest) -> dict[str, Any]:
    task = await state.engine.create_task(payload.goal, project=payload.project, repo=payload.repo)
    return task.model_dump()


@app.post("/operator/memory", dependencies=[Depends(require_api_key)])
async def save_memory(payload: MemoryRequest) -> dict[str, Any]:
    path = await state.engine.save_memory(payload.key, payload.value, project=payload.project)
    return {"ok": True, "path": path}


@app.post("/operator/memory/search", dependencies=[Depends(require_api_key)])
async def search_memory(payload: MemorySearchRequest) -> dict[str, Any]:
    return await state.engine.search_memory(payload.query, limit=payload.limit)


@app.post("/operator/memory/index", dependencies=[Depends(require_api_key)])
async def index_memory(payload: MemoryIndexRequest | None = None) -> dict[str, Any]:
    return await state.engine.rebuild_memory_index(limit=payload.limit if payload else 200)


@app.post("/operator/goals/plan", dependencies=[Depends(require_api_key)])
async def plan_goal_records(payload: GoalPlanRequest) -> dict[str, Any]:
    projects = payload.projects or ([payload.project] if payload.project else None)
    return await state.engine.plan_goal_records(payload.goal, projects=projects, tasks=payload.tasks)


@app.get("/operator/goals", dependencies=[Depends(require_api_key)])
async def list_goals() -> dict[str, Any]:
    return {"goals": await state.engine.list_goals()}


@app.post("/operator/kirzkit/plan", dependencies=[Depends(require_api_key)])
async def kirzkit_plan(payload: KirzKitPlanRequest) -> dict[str, Any]:
    return state.engine.plan_with_kirzkit(payload.goal, project=payload.project)


@app.post("/operator/website/plan", dependencies=[Depends(require_api_key)])
async def website_plan(payload: WebsitePlanRequest) -> dict[str, Any]:
    return await state.engine.website_plan(payload.brief, project=payload.project)


@app.get("/operator/model", dependencies=[Depends(require_api_key)])
async def model_status() -> dict[str, Any]:
    return state.engine.model_status()


@app.post("/operator/repos/index", dependencies=[Depends(require_api_key)])
async def repo_index(payload: RepoContextRequest) -> dict[str, Any]:
    return await state.engine.repo_context(payload.repo, ref=payload.ref, cache=True)


@app.post("/operator/repos/context", dependencies=[Depends(require_api_key)])
async def repo_context(payload: RepoContextRequest) -> dict[str, Any]:
    return await state.engine.repo_context(payload.repo, ref=payload.ref, cache=payload.cache)


@app.get("/operator/repos/{owner}/{name}/status", dependencies=[Depends(require_api_key)])
async def repo_status(owner: str, name: str) -> dict[str, Any]:
    return await state.engine.repo_context(f"{owner}/{name}", cache=False)


@app.post("/operator/projects/{project}/continue", dependencies=[Depends(require_api_key)])
async def continue_project(project: str) -> dict[str, Any]:
    task = await state.engine.continue_project(project)
    return task.model_dump()


@app.get("/operator/projects/{project}/context", dependencies=[Depends(require_api_key)])
async def project_context(project: str) -> dict[str, Any]:
    graph_summary = await state.engine.query_graph(project)
    return await state.engine.build_project_context(project, graph_summary=graph_summary)


@app.get("/operator/projects", dependencies=[Depends(require_api_key)])
async def list_projects() -> dict[str, Any]:
    return {"projects": await state.engine.list_projects()}


@app.get("/operator/projects/{project}/status", dependencies=[Depends(require_api_key)])
async def project_status(project: str) -> dict[str, Any]:
    return await state.engine.project_status(project)


@app.get("/operator/dashboard", dependencies=[Depends(require_api_key)])
async def dashboard() -> dict[str, Any]:
    return await state.engine.dashboard_summary()


@app.get("/operator/status", dependencies=[Depends(require_api_key)])
async def operator_status() -> dict[str, Any]:
    summary = await state.engine.dashboard_summary()
    return {
        **summary,
        "ok": not state.config.missing_required(),
        "missing": state.config.missing_required(),
        "memory_repo": state.config.memory_repo,
        "allowed_repos": state.config.allowed_repos,
        "worker_enabled": state.config.operator_worker_enabled,
        "worker_interval_seconds": state.config.operator_worker_interval_seconds,
        "memory_search_mode": "semantic-hash-with-lexical-fallback",
        "model": state.engine.model_status(),
    }


@app.get("/operator/selfcheck", dependencies=[Depends(require_api_key)])
async def self_check() -> dict[str, Any]:
    return state.engine.self_check()


@app.get("/operator/brief", dependencies=[Depends(require_api_key)])
async def daily_brief() -> dict[str, Any]:
    return await state.engine.daily_review()


@app.get("/operator/projects/{project}/next", dependencies=[Depends(require_api_key)])
async def project_next(project: str) -> dict[str, Any]:
    return await state.engine.project_next_action(project)


@app.post("/operator/memory/process", dependencies=[Depends(require_api_key)])
async def process_memory(payload: PipelineRequest | None = None) -> dict[str, Any]:
    return await state.engine.process_memory_pipeline(limit=payload.limit if payload else 20)


@app.post("/operator/graphify/rebuild", dependencies=[Depends(require_api_key)])
async def rebuild_graph() -> dict[str, Any]:
    result = await state.engine.rebuild_graph()
    return {"ok": result.ok, "status": result.status, "uploaded": result.uploaded, "detail": result.detail}


@app.post("/operator/graphify/query", dependencies=[Depends(require_api_key)])
async def query_graph(payload: GraphQueryRequest) -> dict[str, Any]:
    return await state.engine.query_graph(payload.term, limit=payload.limit)


@app.get("/operator/skills/sources", dependencies=[Depends(require_api_key)])
async def skill_sources() -> dict[str, Any]:
    return {"sources": [source.as_dict() for source in state.skills.summarize()]}


@app.get("/operator/skills/search", dependencies=[Depends(require_api_key)])
async def skill_search(q: str = "") -> dict[str, Any]:
    return {"query": q, "results": state.skills.search(q)}


@app.get("/operator/skills", dependencies=[Depends(require_api_key)])
async def native_skills() -> dict[str, Any]:
    return {"skills": [definition.__dict__ for definition in state.engine.list_skills()]}


@app.post("/operator/execute", dependencies=[Depends(require_api_key)])
async def execute_goal(payload: ExecuteRequest) -> dict[str, Any]:
    return await state.engine.execute_goal(
        payload.goal,
        project=payload.project,
        repo=payload.repo,
        approved_skills=set(payload.approved_skills),
    )


@app.post("/operator/plan", dependencies=[Depends(require_api_key)])
async def plan_goal(payload: ExecuteRequest) -> dict[str, Any]:
    return await state.engine.plan_goal(payload.goal, project=payload.project, repo=payload.repo)


@app.post("/operator/execute-plan", dependencies=[Depends(require_api_key)])
async def execute_plan(payload: ExecutePlanRequest) -> dict[str, Any]:
    return await state.engine.execute_custom_plan(
        payload.goal,
        payload.plan,
        project=payload.project,
        approved_skills=set(payload.approved_skills),
    )


@app.post("/operator/autonomous-run", dependencies=[Depends(require_api_key)])
async def autonomous_run(payload: ExecuteRequest) -> dict[str, Any]:
    return await state.engine.execute_goal(
        payload.goal,
        project=payload.project,
        repo=payload.repo,
        approved_skills=set(payload.approved_skills),
    )


@app.post("/operator/worker/run-once", dependencies=[Depends(require_api_key)])
async def worker_run_once(payload: WorkerRunRequest | None = None) -> dict[str, Any]:
    return await state.engine.run_queued_tasks_once(limit=payload.limit if payload else 3)


@app.get("/operator/executions/{execution_id}", dependencies=[Depends(require_api_key)])
async def get_execution(execution_id: str) -> dict[str, Any]:
    row = await state.supabase.get_by_id("execution_replays", execution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Execution replay not found")
    return row


@app.get("/operator/approvals", dependencies=[Depends(require_api_key)])
async def list_approvals(limit: int = 20) -> dict[str, Any]:
    return {"approvals": await state.engine.list_pending_approvals(limit=limit)}


@app.post("/operator/approvals/approve", dependencies=[Depends(require_api_key)])
async def approve_request(payload: ApprovalActionRequest) -> dict[str, Any]:
    return await state.engine.approve_request(payload.approval_id)


@app.post("/operator/approvals/approve-and-continue", dependencies=[Depends(require_api_key)])
async def approve_and_continue(payload: ApprovalActionRequest) -> dict[str, Any]:
    return await state.engine.approve_and_continue(payload.approval_id)


@app.post("/operator/approvals/reject", dependencies=[Depends(require_api_key)])
async def reject_request(payload: ApprovalActionRequest) -> dict[str, Any]:
    return await state.engine.reject_request(payload.approval_id)


@app.post("/operator/github/branch", dependencies=[Depends(require_api_key)])
async def github_branch(payload: GitHubBranchRequest) -> dict[str, Any]:
    return await state.engine.github.create_branch(payload.repo, payload.branch, from_ref=payload.from_ref)


@app.post("/operator/github/write", dependencies=[Depends(require_api_key)])
async def github_write(payload: GitHubWriteRequest) -> dict[str, Any]:
    return await state.engine._github_write_branch_file(
        payload.repo,
        payload.branch,
        payload.path,
        payload.content,
        payload.message,
    )


@app.post("/operator/github/prepare-pr", dependencies=[Depends(require_api_key)])
async def github_prepare_pr(payload: GitHubPullRequest) -> dict[str, Any]:
    if payload.ready_for_review and not payload.approved:
        raise HTTPException(status_code=403, detail="Ready-for-review PRs require approval")
    if payload.ready_for_review:
        return await state.engine._github_create_ready_pr(payload.repo, payload.branch, payload.title, payload.body)
    return await state.engine._github_create_draft_pr(payload.repo, payload.branch, payload.title, payload.body)


@app.post("/telegram/webhook")
async def telegram_webhook(update: dict[str, Any]) -> dict[str, bool]:
    await state.telegram.handle_update(update)
    return {"ok": True}


async def _worker_loop(engine: TaskEngine, interval_seconds: int) -> None:
    while True:
        try:
            await engine.run_queued_tasks_once(limit=1)
        except Exception:
            log.exception("Hermes Operator worker loop failed")
        await asyncio.sleep(max(5, interval_seconds))


def main() -> None:
    config = load_config()
    uvicorn.run("hermes_operator.server:app", host=config.host, port=config.port, proxy_headers=True)


if __name__ == "__main__":
    main()
