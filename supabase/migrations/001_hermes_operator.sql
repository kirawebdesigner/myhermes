create extension if not exists vector;

create table if not exists goals (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid references goals(id) on delete set null,
  name text not null,
  repo text,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tasks (
  id uuid primary key,
  goal text not null,
  status text not null check (status in ('queued', 'running', 'completed', 'failed')),
  project text,
  repo text,
  result text,
  error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists memories (
  id uuid primary key default gen_random_uuid(),
  key text not null,
  value text not null,
  project text,
  source text not null default 'operator',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists decisions (
  id uuid primary key default gen_random_uuid(),
  project text,
  title text not null,
  rationale text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  path text not null,
  title text,
  content text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists embeddings (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references documents(id) on delete cascade,
  content text not null,
  embedding vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists execution_logs (
  id uuid primary key default gen_random_uuid(),
  task_id uuid references tasks(id) on delete set null,
  level text not null default 'info',
  message text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists graph_runs (
  id uuid primary key default gen_random_uuid(),
  status text not null,
  uploaded text[] not null default '{}'::text[],
  detail text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists execution_replays (
  id uuid primary key,
  goal text not null,
  project text,
  status text not null,
  replay_paths jsonb not null default '{}'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists approval_requests (
  id uuid primary key,
  execution_id uuid,
  goal text not null,
  project text,
  skill text not null,
  status text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  reason text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists goal_plans (
  id uuid primary key default gen_random_uuid(),
  goal_id uuid references goals(id) on delete set null,
  title text not null,
  memory_path text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists tasks_status_idx on tasks(status);
create index if not exists tasks_project_idx on tasks(project);
create index if not exists memories_project_idx on memories(project);
create index if not exists documents_path_idx on documents(path);
create index if not exists embeddings_vector_idx on embeddings using ivfflat (embedding vector_cosine_ops);
create index if not exists graph_runs_status_idx on graph_runs(status);
create index if not exists execution_replays_project_idx on execution_replays(project);
create index if not exists execution_replays_status_idx on execution_replays(status);
create index if not exists approval_requests_status_idx on approval_requests(status);
create index if not exists approval_requests_execution_idx on approval_requests(execution_id);
create index if not exists goal_plans_goal_idx on goal_plans(goal_id);

create or replace function match_operator_embeddings(
  query_embedding vector(1536),
  match_count int default 10
)
returns table (
  id uuid,
  document_id uuid,
  content text,
  metadata jsonb,
  similarity float
)
language sql
stable
as $$
  select
    embeddings.id,
    embeddings.document_id,
    embeddings.content,
    embeddings.metadata,
    1 - (embeddings.embedding <=> query_embedding) as similarity
  from embeddings
  where embeddings.embedding is not null
  order by embeddings.embedding <=> query_embedding
  limit match_count;
$$;
