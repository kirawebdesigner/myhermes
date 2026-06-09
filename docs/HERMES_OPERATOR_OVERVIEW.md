# Hermes Operator Overview

Hermes Operator is a Choreo-hosted extension layer for this Hermes fork. Its purpose is to turn Hermes into a phone-controlled project operator that can capture ideas, store durable memory, track goals and tasks, rebuild a knowledge graph, and write long-term state back to GitHub.

The current implementation is the foundation layer. It proves the core loop:

```text
Telegram / HTTP
    -> Hermes Operator API on Choreo
    -> Supabase state
    -> GitHub memory repo
    -> Graphify knowledge graph
```

It is not yet a full autonomous developer. The implemented system can receive requests, create tasks, save and search memory, initialize project continuity files, process raw notes into wiki/archive, query Graphify output, create goal plans, build KirzKit-first implementation plans, execute tier-gated skill plans, write branch-only GitHub changes, store execution replays, and expose the service through Choreo-safe HTTP endpoints.

## Current Maturity

Hermes Operator has successfully designed the platform foundation, not the full autonomous operator yet.

```text
Layer 0: Hosting                  done
Layer 1: Persistence              done
Layer 2: Memory OS                done
Layer 3: Knowledge Graph          done
Layer 4: Phone Interface          done
Layer 5: Safety Controls          done
Layer 6: Autonomous Skills        v1 done
Layer 7: Project Execution        partial, safe branch-only v1
Layer 8: Self-Improving Workflows not built
```

Status by capability:

| Layer | Status |
| --- | --- |
| Choreo Hosting | Done |
| Supabase Persistence | Done |
| GitHub Memory | Done |
| Graphify Knowledge Graph | Done |
| Telegram Control | Done |
| Safety System | Done |
| Project Continuity Files | Done |
| Planning Hook | Done, deterministic v1 |
| Skill Execution | Done, tier-gated v1 |
| Branch GitHub Workflows | Done, branch-only v1 |
| Autonomous Project Work | Partial, safe-loop v1 |
| Memory Search | Done, semantic v1 with lexical fallback |
| Goal Planning | Done, deterministic v1 |
| KirzKit Planning | Done, source-search v1 |
| Semantic Memory Index | Done, deterministic pgvector-backed v1 |
| Background Worker | Done, optional queued-task v1 |
| Approval Resume | Done, approve-and-continue v1 |
| Operator Dashboard API | Done, summary endpoint v1 |

If someone asks whether Hermes independently builds and ships software yet, the honest answer is: not fully. It can now prepare safe plans, write branch-only changes through registered skills, create draft PR artifacts, and stop at approval gates. If they ask whether Hermes has the infrastructure required to become a software-building operator, the answer is yes.

## Ultimate Goal

The target product is a personal project operating system that you can control from your phone.

Vision statement:

```text
Hermes Operator is a persistent project operating system that combines memory,
knowledge graphs, project state, and execution skills to help build and maintain
software projects from a phone.
```

It is not only a chatbot, second brain, or autonomous coding agent. Those are pieces. The real system connects:

```text
Projects
Goals
Tasks
Knowledge
Code
Decisions
Memory
Skills
```

Example future command:

```text
Continue BrandBlueprint. Review unfinished tasks. Build the next safe improvement. Update docs. Commit and push.
```

The intended behavior is:

1. Load project context.
2. Query Graphify first.
3. Read project memory, decisions, roadmap, and task state.
4. Plan the next useful action.
5. Execute safe skills.
6. Save new memory.
7. Update Supabase state.
8. Commit durable files to GitHub.
9. Report the result back through Telegram or API.

## Current Architecture

```text
Phone / Telegram
      |
      v
Hermes Operator FastAPI service
      |
      +-- Supabase
      |     - goals
      |     - projects
      |     - tasks
      |     - memories
      |     - decisions
      |     - documents
      |     - embeddings
      |     - execution_logs
      |     - graph_runs
      |     - execution_replays
      |     - approval_requests
      |     - goal_plans
      |
      +-- GitHub memory repo
      |     - memory/raw
      |     - memory/wiki
      |     - memory/projects
      |     - memory/archive
      |     - memory/prompts
      |     - memory/tasks
      |     - memory/snapshots
      |     - memory/decisions
      |     - memory/context
      |     - memory/executions
      |     - memory/goals
      |     - memory/graphify-out
      |
      +-- Graphify
      |     - graph.json
      |     - GRAPH_REPORT.md
      |     - graph.html
      |
      +-- OpenRouter
      |     - lightweight task intent planning
      |
      +-- KirzKit
      |     - primary skill/source-brain for project building
      |
      +-- Ruflo
      |     - optional future multi-agent orchestration layer
      |
      +-- GitHub project repos
            - only repos listed in ALLOWED_REPOS
```

Choreo is treated only as compute. Important state must live in Supabase or GitHub so redeploys and restarts do not wipe memory.

## Implemented Components

### Operator API

Implemented in `hermes_operator/server.py`.

Current endpoints:

```text
GET  /health
GET  /operator/status
GET  /operator/dashboard
POST /operator/bootstrap
POST /operator/tasks
POST /operator/memory
POST /operator/memory/process
POST /operator/memory/search
POST /operator/memory/index
GET  /operator/goals
POST /operator/goals/plan
POST /operator/kirzkit/plan
POST /operator/projects/{project}/continue
GET  /operator/projects/{project}/context
GET  /operator/projects
GET  /operator/projects/{project}/status
POST /operator/graphify/rebuild
POST /operator/graphify/query
GET  /operator/skills/sources
GET  /operator/skills/search?q=<query>
GET  /operator/skills
POST /operator/execute
POST /operator/plan
POST /operator/execute-plan
POST /operator/autonomous-run
POST /operator/worker/run-once
GET  /operator/executions/{execution_id}
GET  /operator/approvals
POST /operator/approvals/approve
POST /operator/approvals/approve-and-continue
POST /operator/approvals/reject
POST /operator/github/branch
POST /operator/github/write
POST /operator/github/prepare-pr
POST /telegram/webhook
```

Protected operator endpoints require `x-api-key` when `API_SERVER_KEY` is set.

### Memory OS

Implemented in `hermes_operator/memory_os.py`.

The memory system writes durable Markdown files to the configured GitHub memory repo. Current memory structure:

```text
memory/
├── raw/
├── wiki/
├── projects/
├── archive/
├── prompts/
├── tasks/
├── snapshots/
├── decisions/
├── context/
├── executions/
├── goals/
└── graphify-out/
```

Each project gets continuity files:

```text
memory/projects/<project>/
├── README.md
├── roadmap.md
├── tasks.md
├── memory.md
├── decisions.md
└── status.md
```

### Supabase Persistence

Implemented through `hermes_operator/supabase.py` using Supabase REST APIs.

The migration is in:

```text
supabase/migrations/001_hermes_operator.sql
```

Current tables:

```text
goals
projects
tasks
memories
decisions
documents
embeddings
execution_logs
graph_runs
execution_replays
approval_requests
goal_plans
```

`pgvector` is enabled for future semantic memory search.

### Graphify Knowledge Layer

Implemented in `hermes_operator/graphify.py`.

Graphify is the relationship layer. The operator can rebuild the graph from GitHub-backed memory files and upload output back to:

```text
memory/graphify-out/
├── graph.json
├── GRAPH_REPORT.md
└── graph.html
```

When project understanding is required, the intended lookup order is:

1. Graphify output.
2. `memory/wiki/`.
3. `memory/projects/`.
4. `memory/raw/`.

`Dockerfile.choreo` installs the official `graphifyy` package, which provides the `graphify` command. If the command is unavailable, the graph rebuild returns `missing_cli` instead of crashing the service.

### Telegram Control

Implemented in `hermes_operator/telegram.py`.

Current commands:

```text
/start
/status
/memory key=value
/continue <project>
/context <project>
/task <goal>
/graph
/graph <query>
/search <query>
/index
/goal <goal>
/kirzkit <goal>
/process
/worker
/skills
/execute <goal>
/projects
/project <project>
/approvals
/approve <approval-id>
/reject <approval-id>
/goals
```

Telegram access is restricted by `TELEGRAM_ALLOWED_USER_IDS`.

### GitHub Integration

Implemented in `hermes_operator/github.py`.

Current capabilities:

```text
read file
write/update file
list repo tree
read text file
write memory files
write Graphify output files
create allowed-repo working branches
write files to non-default branches
create draft pull requests
```

Project repo modification is guarded by `ALLOWED_REPOS`. Memory repo writes intentionally bypass the allowlist because `MEMORY_REPO` is the operator's state store. Default-branch writes are rejected in v1; project code changes must go through a working branch.

### Autonomy Tiers

Implemented through skill metadata and the execution engine.

```text
Tier 0 Auto
- read
- search
- context packets
- planning
- Graphify query
- KirzKit search
- memory updates

Tier 1 Auto Execute
- create branch
- write/update files on a non-default branch
- generate docs
- commit file content to branch

Tier 1.5 Auto By Default
- create draft PR
- create GitHub issue
- comment on issue

Tier 2 Approval Required
- ready-for-review PR
- merge PR
- deploy
- runtime/config changes

Tier 3 Always Manual
- delete repos
- force push
- secrets
- security-sensitive changes
```

Draft PRs are treated as work artifacts. Ready-for-review PRs are team-facing and require approval.

### Execution Replay

Every `/operator/execute`, `/operator/execute-plan`, `/operator/autonomous-run`, and approval continuation stores a replay record containing:

```text
goal
context packet
Graphify query result
KirzKit search result
skill plan
skill outputs
final result
blocked approval reasons
```

Replay metadata is stored in Supabase `execution_replays`. Durable replay JSON and Markdown are written to:

```text
memory/executions/
```

### Approval Requests

Blocked Tier 2 and manual-gated execution steps create pending approval records in Supabase `approval_requests`.

Current approval endpoints:

```text
GET  /operator/approvals
POST /operator/approvals/approve
POST /operator/approvals/reject
```

Approving a request records approval state. `approve-and-continue` can resume the single blocked approved skill with the original inputs. It does not automatically merge, deploy, change secrets, or bypass Tier 3 manual-only rules.

### Semantic Memory Index

Implemented in `hermes_operator/embeddings.py`.

The v1 semantic index stores deterministic 1536-dimensional hash embeddings in Supabase `documents` and `embeddings`. It supports the `match_operator_embeddings` pgvector RPC from the migration when deployed, and falls back to scanning stored embeddings when RPC is unavailable. If the semantic index is empty, memory search falls back to GitHub-backed lexical search.

Current endpoints:

```text
POST /operator/memory/index
POST /operator/memory/search
```

Memory saves and processed wiki files are indexed best-effort, so a Supabase indexing issue does not block the GitHub memory write.

### Background Worker

Implemented as an optional Choreo-safe worker loop and one-shot endpoint.

```text
OPERATOR_WORKER_ENABLED=false
OPERATOR_WORKER_INTERVAL_SECONDS=30
```

Endpoint:

```text
POST /operator/worker/run-once
```

The worker claims queued tasks, marks them running, executes the safe v1 execution path, then marks them completed or failed. Keep the loop disabled until the hosted `/health`, Telegram, memory, graph, and approval paths are verified.

### Operator Dashboard API

Implemented as JSON status endpoints, not a web UI.

```text
GET /operator/status
GET /operator/dashboard
```

The payload reports project count, goal count, queue counts, pending approvals, recent execution count, latest execution, missing config keys, worker state, memory repo, and memory search mode.

### Project Registry

Project listing combines GitHub memory folders under `memory/projects/` with Supabase project rows.

Current project endpoints:

```text
GET /operator/projects
GET /operator/projects/{project}/status
```

Project status reports present/missing continuity files, open markdown tasks, recent execution counts, and Graphify match counts.

### Safety Boundaries

Implemented in `hermes_operator/safety.py`.

Current defaults:

```text
ALLOW_DELETE=false
ALLOW_FORCE_PUSH=false
ALLOW_REPO_CREATE=false
REQUIRE_CONFIRMATION_FOR_DANGEROUS_ACTIONS=true
```

The system should not delete files, force push, create repos, or modify repos outside `ALLOWED_REPOS` unless those controls are explicitly changed.

### Skill Sources

Implemented in `hermes_operator/skill_sources.py`.

Current endpoints:

```text
GET /operator/skills/sources
GET /operator/skills/search?q=<query>
```

Skill source priority:

1. KirzKit.
2. Hermes Operator native skills.
3. Ruflo optional orchestration.

KirzKit must be checked before creating or inventing skills for UI, websites, SaaS projects, Supabase apps, frontend design, product planning, testing, deployment, documentation, or project workflows.

Local KirzKit path:

```text
C:\Users\kirub\kirzkit_openclaw\kirzkit
```

Local KirzKit currently contains:

```text
.claude/
.claude-flow/
agents/
assets/
references/
scripts/
skills/
workflows/
.cursorrules
.mcp.json
CLAUDE.md
GEMINI.md
PROMPT.md
README.md
SKILL.md
```

Observed local KirzKit inventory:

```text
22 top-level agent categories
149 skill packs
16 workflow guides
5 reference docs
1 asset/template doc
```

Important workflow guides:

```text
accessibility-review
brainstorm
collect-inspiration
component-selection
create
debug
deploy
enhance
landing-page-teardown
orchestrate
plan
preview
status
test
ui-audit
ui-ux-pro-max
```

Important skill areas include:

```text
frontend-design
web-design-guidelines
modern-sleek-ui-ux
tailwind-patterns
shadcn-ui-master
nextjs-react-expert
supabase-expert
database-design
api-patterns
testing-patterns
playwright-e2e-pro
deployment-procedures
security-hardening
seo-fundamentals
project-planner
product-design-pro
skill-creator
```

Ruflo is registered as an optional future orchestration layer for swarms, goals, workflows, RAG memory, knowledge graphs, docs, testing, security, and multi-agent coordination. It should not be a hard Choreo dependency until it has been separately tested in the target runtime.

### KirzKit As A Project

KirzKit should also become a first-class project inside the Memory OS:

```text
memory/projects/KirzKit/
├── README.md
├── roadmap.md
├── tasks.md
├── memory.md
├── decisions.md
└── status.md
```

The operator should continuously index KirzKit's components, patterns, layouts, conventions, skills, agents, and workflows. Later, a command like:

```text
Build a SaaS dashboard
```

should work like:

```text
Search KirzKit
-> find matching agents, workflows, skills, and UI patterns
-> build an implementation plan
-> execute with KirzKit conventions
```

This prevents random UI generation and turns KirzKit into a reusable source brain for project execution.

### Choreo Deployment

Deployment files:

```text
Dockerfile.choreo
.choreo/component.yaml
.env.operator.example
DEPLOY_CHOREO.md
```

The Choreo service exposes port `8642`.

## Runtime Configuration

Real values must be configured in Choreo, not committed to the repo.

Required:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
GITHUB_TOKEN
MEMORY_REPO
ALLOWED_REPOS
API_SERVER_KEY
```

Usually required for phone use:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_ALLOWED_USER_IDS
```

Usually required for planning:

```text
OPENROUTER_API_KEY
```

Graphify:

```text
GRAPHIFY_ENABLED=true
GRAPHIFY_COMMAND=graphify
GRAPHIFY_TIMEOUT_SECONDS=180
```

KirzKit:

```text
KIRZKIT_REPO=https://github.com/kirawebdesigner/KirzKit
KIRZKIT_LOCAL_PATH=C:\Users\kirub\kirzkit_openclaw\kirzkit
RUFLO_REPO=https://github.com/ruvnet/ruflo
```

Autonomy controls:

```text
ALLOW_DELETE=false
ALLOW_FORCE_PUSH=false
ALLOW_REPO_CREATE=false
ALLOW_TIER_1_5_AUTO=true
REQUIRE_CONFIRMATION_FOR_DANGEROUS_ACTIONS=true
```

## Current User Flows

### Bootstrap Memory

```text
POST /operator/bootstrap
```

Creates the memory folder structure in the memory repo.

### Save Memory

```text
POST /operator/memory
```

Writes memory to GitHub and inserts a row into Supabase `memories`.

Telegram equivalent:

```text
/memory style=KirzKit-first, clean, practical UI
```

### Create Task

```text
POST /operator/tasks
```

Creates a Supabase task and writes a task snapshot to GitHub.

Telegram equivalent:

```text
/task Build a landing page idea for BrandBlueprint
```

### Continue Project

```text
POST /operator/projects/BrandBlueprint/continue
```

Initializes project continuity files and creates/completes a continuity task. This is currently a preparation step, not full autonomous project execution.

Telegram equivalent:

```text
/continue BrandBlueprint
```

### Rebuild Knowledge Graph

```text
POST /operator/graphify/rebuild
```

Builds `graphify-out` from memory files and uploads the graph output to GitHub.

Telegram equivalent:

```text
/graph
```

## What Is Not Built Yet

The following are part of the vision but not fully implemented:

```text
KirzKit component-level code generation
dangerous-action confirmation flow
web dashboard UI
ready PR / merge / deploy full approval UX
full code-generation planner
```

The current version stores state and creates the structure needed for those features.
The first versions of the Project Context Engine, Memory Pipeline, Graphify Query API, Skill Registry, Execution Engine, branch-only GitHub workflows, and replay records are implemented. They are intentionally conservative: they build packets, process raw notes deterministically, query graph output, run registered safe skills, write only to allowed repos, and block default-branch writes.

The correct build order is:

```text
Project Context Engine
-> Memory Pipeline
-> Graphify Query API
-> Skill Registry
-> Execution Engine
```

Current implementation status:

```text
Project Context Engine  v1 implemented
Memory Pipeline         v1 implemented
Graphify Query API      v1 implemented
Skill Registry          v1 implemented
Execution Engine        v1 implemented
Branch GitHub Workflows v1 implemented
Execution Replay        v1 implemented
Semantic Memory Index   v1 implemented
Background Worker       v1 implemented
Approval Resume         v1 implemented
Dashboard API           v1 implemented
Full code autonomy      not built
```

### Phase A: Project Context Engine

V1 is implemented. When Hermes sees a project name like `BrandBlueprint`, it gathers:

```text
project README
roadmap
tasks
memory
decisions
graph relationships
recent execution logs
recent commits
```

and produce:

```json
{
  "project": "BrandBlueprint",
  "state": "active",
  "next_tasks": [],
  "relevant_memories": [],
  "graph_relationships": []
}
```

All future planning should use this packet instead of blindly reading the whole repo or memory tree.

### Phase B: Memory Pipeline

V1 is implemented. The pipeline automates:

```text
raw -> wiki -> archive
```

Example:

```text
User says: We should add AI competitor analysis.
Hermes saves raw note.
Hermes summarizes it.
Hermes updates project wiki.
Hermes archives the raw note.
Hermes rebuilds Graphify.
```

### Phase C: Graphify Query API

V1 is implemented. Rebuilding the graph is not enough; the operator can also query it.

Examples:

```text
What relates to BrandBlueprint?
What unfinished ideas connect to SEO?
What decisions mention KirzKit?
```

Without querying, Graphify is mostly a report. With querying, it becomes reasoning support.

### Phase D: Skill Registry

V1 is implemented. The skill registry has entries like:

```text
memory_save
memory_search
graph_query
github_branch_create
github_write_file
github_commit_file
github_pr_draft
kirzkit_generate_plan
```

Each skill exposes:

```text
name
description
inputs
risk_level / autonomy_tier
execute()
```

KirzKit must be searched before creating new project-building skills.

### Phase E: Execution Engine

V1 is implemented. Hermes has moved from:

```text
Goal -> Task
```

to:

```text
Goal -> Plan -> Skills -> Execution -> Memory Update
```

This is still a conservative execution engine, not a free-running coding agent. It plans deterministic skill sequences, executes safe tiers, blocks approval-gated work, and records replays.

## Recommended Next Milestone

Before adding more advanced autonomy, prove the hosted loop:

1. Run the Supabase migration.
2. Add secrets to Choreo.
3. Deploy with `Dockerfile.choreo`.
4. Confirm `/health`.
5. Run `/operator/bootstrap`.
6. Save a memory.
7. Create a task.
8. Run `/graph`.
9. Restart the Choreo service.
10. Confirm Supabase and GitHub still have the memory, task, and graph output.

After that works, build the next feature set:

```text
component-level KirzKit code generation
full approval UX for merge / deploy
web dashboard UI
full code-generation planner
```

## Verification Status

Current local verification:

```text
uv run --frozen --extra dev pytest tests/test_hermes_operator.py tests/test_execution_engine.py tests/test_context_memory_graph.py tests/test_real_execution_layer.py tests/test_memory_goal_kirzkit.py --timeout-method=thread
```

Result:

```text
34 passed
```

Compile check:

```text
uv run --frozen python -m compileall -q hermes_operator
```

Server import check:

```text
uv run --frozen python -c "from hermes_operator.server import app; print('\n'.join(sorted(route.path for route in app.routes)))"
```

Result:

```text
Routes include /operator/status, /operator/dashboard, /operator/memory/index,
/operator/worker/run-once, and /operator/approvals/approve-and-continue.
```

Docker build was not completed locally because Docker Desktop's Linux engine was not running in this environment.

## Mental Model

This project is not just a chatbot.

It is being built as:

```text
phone interface
+ task engine
+ memory operating system
+ knowledge graph
+ GitHub-backed second brain
+ future project execution skills
```

The current codebase is the foundation for that system. It gives Hermes a hosted API, durable state, memory files, Graphify output, Telegram commands, and safety boundaries. The next work should focus on turning stored knowledge into reliable execution.
