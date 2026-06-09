# Deploy Hermes Operator on Choreo

This deployment treats Choreo as compute only. Supabase stores state and the vector index. GitHub stores long-term memory and project files. Memory search uses Supabase semantic search when indexed and falls back to GitHub-backed lexical search.

## 1. Supabase

1. Open your Supabase project.
2. Enable `pgvector`.
3. Run `supabase/migrations/001_hermes_operator.sql`.
4. Copy the service-role key for Choreo secrets only.

## 2. GitHub

Create a fine-grained GitHub token with access only to the memory repo and repos in `ALLOWED_REPOS`.

Create or choose a memory repo. Hermes will write:

```text
memory/raw/
memory/wiki/
memory/projects/
memory/archive/
memory/prompts/
memory/tasks/
memory/snapshots/
memory/decisions/
memory/context/
memory/executions/
memory/goals/
memory/graphify-out/
```

## 3. Choreo

1. Create a Service component.
2. Connect this repository.
3. Use `Dockerfile.choreo`.
4. Expose port `8642`.
5. Add the environment variables below.
6. Deploy to Development.

```text
SUPABASE_URL=<your-supabase-url>
SUPABASE_ANON_KEY=<your-supabase-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<secret>

OPENROUTER_API_KEY=<secret>
OPENROUTER_MODEL=qwen/qwen3.6-plus-preview
GOOGLE_API_KEY=<optional-secret>

GITHUB_TOKEN=<secret>
GITHUB_USERNAME=kirawebdesigner
MEMORY_REPO=<owner/repo>
ALLOWED_REPOS=<owner/repo,owner/repo>

TELEGRAM_BOT_TOKEN=<secret>
TELEGRAM_ALLOWED_USER_IDS=<your-telegram-user-id>

HERMES_MODE=operator
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_PORT=8642
API_SERVER_KEY=<secret>

KIRZKIT_REPO=https://github.com/kirawebdesigner/KirzKit
KIRZKIT_LOCAL_PATH=C:\Users\kirub\kirzkit_openclaw\kirzkit
RUFLO_REPO=https://github.com/ruvnet/ruflo

GRAPHIFY_ENABLED=true
GRAPHIFY_COMMAND=graphify
GRAPHIFY_TIMEOUT_SECONDS=180

OPERATOR_WORKER_ENABLED=false
OPERATOR_WORKER_INTERVAL_SECONDS=30

ALLOW_DELETE=false
ALLOW_FORCE_PUSH=false
ALLOW_REPO_CREATE=false
ALLOW_TIER_1_5_AUTO=true
REQUIRE_CONFIRMATION_FOR_DANGEROUS_ACTIONS=true
```

Do not commit real keys. Keep all real values in Choreo environment variables or secrets.

## 4. Verify

Check health:

```bash
curl https://<choreo-url>/health
```

Bootstrap the memory OS:

```bash
curl -X POST https://<choreo-url>/operator/bootstrap \
  -H "x-api-key: <API_SERVER_KEY>"
```

Create a task:

```bash
curl -X POST https://<choreo-url>/operator/tasks \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"Continue BrandBlueprint\",\"project\":\"BrandBlueprint\"}"
```

Rebuild the Graphify knowledge graph:

```bash
curl -X POST https://<choreo-url>/operator/graphify/rebuild \
  -H "x-api-key: <API_SERVER_KEY>"
```

Inspect skill sources:

```bash
curl https://<choreo-url>/operator/skills/sources \
  -H "x-api-key: <API_SERVER_KEY>"
```

Search skills:

```bash
curl "https://<choreo-url>/operator/skills/search?q=supabase" \
  -H "x-api-key: <API_SERVER_KEY>"
```

Build a project context packet:

```bash
curl https://<choreo-url>/operator/projects/BrandBlueprint/context \
  -H "x-api-key: <API_SERVER_KEY>"
```

Process raw memory into wiki/archive:

```bash
curl -X POST https://<choreo-url>/operator/memory/process \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"limit\":20}"
```

Search GitHub-backed memory:

```bash
curl -X POST https://<choreo-url>/operator/memory/search \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"query\":\"BrandBlueprint SEO\",\"limit\":10}"
```

Rebuild the semantic memory index:

```bash
curl -X POST https://<choreo-url>/operator/memory/index \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"limit\":200}"
```

Create a goal plan:

```bash
curl -X POST https://<choreo-url>/operator/goals/plan \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"Earn first $1k online\",\"projects\":[\"BrandBlueprint\"]}"
```

List goals:

```bash
curl https://<choreo-url>/operator/goals \
  -H "x-api-key: <API_SERVER_KEY>"
```

Create a KirzKit-first implementation plan:

```bash
curl -X POST https://<choreo-url>/operator/kirzkit/plan \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"Build a SaaS landing page\",\"project\":\"BrandBlueprint\"}"
```

Query Graphify output:

```bash
curl -X POST https://<choreo-url>/operator/graphify/query \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"term\":\"BrandBlueprint\",\"limit\":20}"
```

Execute a safe deterministic goal plan:

```bash
curl -X POST https://<choreo-url>/operator/execute \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"continue BrandBlueprint\",\"project\":\"BrandBlueprint\"}"
```

List projects and project status:

```bash
curl https://<choreo-url>/operator/projects \
  -H "x-api-key: <API_SERVER_KEY>"

curl https://<choreo-url>/operator/projects/BrandBlueprint/status \
  -H "x-api-key: <API_SERVER_KEY>"
```

Check operator-wide status:

```bash
curl https://<choreo-url>/operator/status \
  -H "x-api-key: <API_SERVER_KEY>"
```

List and resolve pending approvals:

```bash
curl https://<choreo-url>/operator/approvals \
  -H "x-api-key: <API_SERVER_KEY>"

curl -X POST https://<choreo-url>/operator/approvals/approve \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"approval_id\":\"<approval-id>\"}"

curl -X POST https://<choreo-url>/operator/approvals/approve-and-continue \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"approval_id\":\"<approval-id>\"}"
```

Plan with mandatory preflight:

```bash
curl -X POST https://<choreo-url>/operator/plan \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"continue BrandBlueprint\",\"project\":\"BrandBlueprint\"}"
```

Run the autonomous v1 loop:

```bash
curl -X POST https://<choreo-url>/operator/autonomous-run \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"goal\":\"continue BrandBlueprint\",\"project\":\"BrandBlueprint\",\"repo\":\"owner/repo\"}"
```

Run one queued worker pass:

```bash
curl -X POST https://<choreo-url>/operator/worker/run-once \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"limit\":3}"
```

Create a branch-only GitHub working branch:

```bash
curl -X POST https://<choreo-url>/operator/github/branch \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"repo\":\"owner/repo\",\"branch\":\"hermes/brandblueprint\"}"
```

Write to a non-default branch:

```bash
curl -X POST https://<choreo-url>/operator/github/write \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"repo\":\"owner/repo\",\"branch\":\"hermes/brandblueprint\",\"path\":\"README.md\",\"content\":\"# Update\",\"message\":\"docs: update readme\"}"
```

Create a draft PR automatically:

```bash
curl -X POST https://<choreo-url>/operator/github/prepare-pr \
  -H "content-type: application/json" \
  -H "x-api-key: <API_SERVER_KEY>" \
  -d "{\"repo\":\"owner/repo\",\"branch\":\"hermes/brandblueprint\",\"title\":\"Hermes update\",\"body\":\"Prepared by Hermes Operator\"}"
```

Ready-for-review PRs require approval:

```json
{"ready_for_review": true, "approved": true}
```

From Telegram:

```text
/status
/memory style=KirzKit-first, clean, practical UI
/continue BrandBlueprint
/context BrandBlueprint
/graph
/graph BrandBlueprint
/search BrandBlueprint SEO
/index
/goal Earn first $1k online
/kirzkit Build a SaaS landing page
/process
/worker
/skills
/execute continue BrandBlueprint
/projects
/project BrandBlueprint
/approvals
/approve <approval-id>
/reject <approval-id>
```

Restart/redeploy the Choreo service and confirm the task and memory still exist in Supabase and GitHub.

## Graphify Behavior

Graphify is the knowledge layer. When project understanding is required, Hermes should prefer:

1. `memory/graphify-out/graph.json` and `GRAPH_REPORT.md`
2. `memory/wiki/`
3. `memory/projects/`
4. `memory/raw/`

`Dockerfile.choreo` installs the official PyPI package `graphifyy`, which provides the `graphify` CLI. If the CLI is unavailable, `/operator/graphify/rebuild` returns `missing_cli` instead of crashing the service.

## KirzKit and Ruflo Skill Sources

KirzKit is the primary project-building skill source. Before Hermes creates a new skill for UI, SaaS, Supabase, frontend, product, design, testing, deployment, or documentation work, it should inspect KirzKit first.

Local KirzKit path:

```text
C:\Users\kirub\kirzkit_openclaw\kirzkit
```

Current local KirzKit contains:

```text
agents/
skills/
workflows/
references/
assets/
scripts/
.claude/
.claude-flow/
CLAUDE.md
GEMINI.md
PROMPT.md
SKILL.md
README.md
```

The local source has 149 skill packs and 16 workflow guides. The README describes the toolkit as a local AI operating layer with specialist agents, modular skills, workflow guides, activation files, generated capability maps, and validation commands.

Ruflo is registered as an optional orchestration layer, not a required Choreo dependency. Use it later for swarms, goals, workflows, RAG memory, knowledge graphs, docs, testing, security, and multi-agent coordination after the basic Choreo loop is stable.
