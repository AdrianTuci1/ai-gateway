# 03.1 — Schema Postgres

**Status:** `[x]` DDL de referință
**Owns:** tabele, coloane, indexuri, constrângeri.
**Depends on:** [`README.md`](README.md)

Convenții: `snake_case`, UUID v7 pentru id-uri (sortabile), `timestamptz` peste tot, enums ca `text` + `check` (migrații simple), `jsonb` doar pentru date care nu se interoghează relațional.

```sql
create extension if not exists pgcrypto;
create extension if not exists pg_trgm;

-- ─── tenancy & oameni ────────────────────────────────────────────────
create table workspace (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,
  name        text not null,
  created_at  timestamptz not null default now(),
  deleted_at  timestamptz
);

create table app_user (
  id            uuid primary key default gen_random_uuid(),
  idp_subject   text not null unique,
  email         text not null,
  display_name  text,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz
);

-- ─── roluri & membership ─────────────────────────────────────────────
create table role_definition (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid references workspace(id) on delete cascade,  -- null = builtin
  name         text not null,
  permissions  text[] not null,
  is_builtin   boolean not null default false,
  unique (workspace_id, name)
);

create table membership (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   uuid not null references workspace(id) on delete cascade,
  principal_type text not null check (principal_type in ('user','agent')),
  principal_id   uuid not null,
  role_id        uuid not null references role_definition(id),
  created_at     timestamptz not null default now(),
  unique (workspace_id, principal_type, principal_id)
);
create index on membership (principal_type, principal_id);

-- ─── agenți & credențiale ────────────────────────────────────────────
create table agent (
  id           uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references workspace(id) on delete cascade,
  slug         text not null,
  name         text not null,
  kind         text not null default 'interactive'
               check (kind in ('interactive','autonomous','service')),
  status       text not null default 'active'
               check (status in ('active','suspended','revoked')),
  ceiling      jsonb not null default '{}'::jsonb,   -- plafon de capabilități
  created_by   uuid,
  created_at   timestamptz not null default now(),
  unique (workspace_id, slug)
);

create table agent_credential (
  id              uuid primary key default gen_random_uuid(),
  agent_id        uuid not null references agent(id) on delete cascade,
  type            text not null check (type in ('api_key','client_cert')),
  prefix          text,                -- primele 8 caractere, pentru UI
  secret_hash     bytea,               -- argon2id, doar pentru api_key
  cert_fingerprint text,               -- sha256, doar pentru client_cert
  cert_pem        text,                -- certificat public, fără cheie
  serial_number   text,
  issuer          text,                -- internal | acm_pca | external:<name>
  spiffe_id       text,
  expires_at      timestamptz,
  last_used_at    timestamptz,
  revoked_at      timestamptz,
  created_at      timestamptz not null default now()
);
create index on agent_credential (agent_id) where revoked_at is null;

-- ─── bootstrap și înrolare ───────────────────────────────────────────
create table bootstrap_state (
  id            boolean primary key default true check (id),
  completed_at  timestamptz,
  completed_by  uuid references app_user(id),
  method        text check (method in ('cli','http_token')),
  created_at    timestamptz not null default now()
);

create table enrollment_token (
  id            uuid primary key default gen_random_uuid(),
  workspace_id  uuid not null references workspace(id) on delete cascade,
  agent_id      uuid references agent(id) on delete cascade,  -- null = se creează la consum
  agent_slug    text not null,
  role_id       uuid not null references role_definition(id),
  ceiling       jsonb not null default '{}'::jsonb,
  prefix        text not null,
  secret_hash   bytea not null,                                -- argon2id
  state         text not null default 'active'
                check (state in ('active','reserved','consumed','failed')),
  enrollment_id uuid,                                          -- idempotență pentru CA extern
  reserved_at   timestamptz,
  expires_at    timestamptz not null,
  consumed_at   timestamptz,
  created_by    uuid not null,
  created_at    timestamptz not null default now()
);
create index on enrollment_token (workspace_id, expires_at) where consumed_at is null;

create table enrollment_device_code (
  id               uuid primary key default gen_random_uuid(),
  device_code_hash bytea not null,
  user_code        text not null unique,
  status           text not null default 'pending'
                   check (status in ('pending','approved','consumed','denied','expired')),
  workspace_id     uuid references workspace(id) on delete cascade,  -- ales la aprobare
  agent_name       text not null,
  requested_role   text,
  approved_agent   uuid references agent(id),
  approved_by      uuid references app_user(id),
  attempts         int not null default 0 check (attempts <= 5),
  expires_at       timestamptz not null,
  interval_seconds int not null default 5,
  last_polled_at   timestamptz,
  created_at       timestamptz not null default now()
);
create index on enrollment_device_code (status, expires_at);

-- ─── servicii upstream ───────────────────────────────────────────────
create table upstream_service (
  id                uuid primary key default gen_random_uuid(),
  workspace_id      uuid not null references workspace(id) on delete cascade,
  name              text not null,
  kind              text not null
                    check (kind in ('mcp_http','mcp_stdio','http','a2a')),
  endpoint          text,
  auth_type         text not null default 'none'
                    check (auth_type in ('none','oauth2','api_key','mtls')),
  auth_config       jsonb not null default '{}'::jsonb,  -- client_id, scopes, nu secrete
  credential_policy text not null default 'per_agent'
                    check (credential_policy in ('per_agent','per_user','workspace')),
  manifest_hash     text,
  manifest_synced_at timestamptz,
  runtime_requirements jsonb not null default '{}'::jsonb,  -- streaming, session, stdio, push
  status            text not null default 'active'
                    check (status in ('active','disabled')),
  created_by        uuid,
  created_at        timestamptz not null default now(),
  unique (workspace_id, name)
);

create table service_tool (
  id              uuid primary key default gen_random_uuid(),
  service_id      uuid not null references upstream_service(id) on delete cascade,
  name            text not null,
  description     text,
  input_schema    jsonb not null default '{}'::jsonb,
  annotations     jsonb not null default '{}'::jsonb,  -- readOnlyHint etc.
  definition_hash text not null,                        -- detectează rug-pull
  search_tsv      tsvector generated always as (
                    to_tsvector('simple', coalesce(name,'') || ' ' || coalesce(description,''))
                  ) stored,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  unique (service_id, name)
);
create index on service_tool using gin (search_tsv);
create index on service_tool using gin (name gin_trgm_ops);

create table service_resource (
  id            uuid primary key default gen_random_uuid(),
  service_id    uuid not null references upstream_service(id) on delete cascade,
  uri_template  text not null,
  name          text,
  mime_type     text,
  unique (service_id, uri_template)
);

create table service_prompt (
  id           uuid primary key default gen_random_uuid(),
  service_id   uuid not null references upstream_service(id) on delete cascade,
  name         text not null,
  description  text,
  arguments    jsonb not null default '[]'::jsonb,
  unique (service_id, name)
);

-- ─── grants ──────────────────────────────────────────────────────────
create table agent_grant (
  id              uuid primary key default gen_random_uuid(),
  workspace_id    uuid not null references workspace(id) on delete cascade,
  agent_id        uuid not null references agent(id) on delete cascade,
  service_id      uuid not null references upstream_service(id) on delete cascade,
  tools           text[] not null default '{}',   -- vid = niciun tool
  resources       text[] not null default '{}',
  arg_constraints jsonb not null default '{}'::jsonb,
  status          text not null default 'pending'
                  check (status in ('pending','active','suspended','stale','denied','revoked')),
  reason          text,
  created_by_type text not null check (created_by_type in ('user','agent','system')),
  created_by_id   uuid,
  approved_by_id  uuid,
  approved_at     timestamptz,
  expires_at      timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (agent_id, service_id)
);
create index on agent_grant (agent_id, status);
create index on agent_grant (service_id, status);

-- ─── conexiuni & vault ───────────────────────────────────────────────
create table service_connection (
  id                  uuid primary key default gen_random_uuid(),
  workspace_id        uuid not null references workspace(id) on delete cascade,
  service_id          uuid not null references upstream_service(id) on delete cascade,
  user_id             uuid references app_user(id) on delete cascade,
  agent_id            uuid references agent(id) on delete cascade,
  binding             text not null default 'per_agent'
                      check (binding in ('per_agent','per_user','workspace')),
  scopes              text[] not null default '{}',
  access_token_enc    bytea,
  refresh_token_enc   bytea,
  token_type          text,
  expires_at          timestamptz,
  status              text not null default 'active'
                      check (status in ('active','needs_reauth','revoked')),
  created_at          timestamptz not null default now(),
  last_used_at        timestamptz,
  -- subiecții trebuie să corespundă binding-ului: triadă, per user, sau service account
  check (
    (binding = 'per_agent' and user_id is not null and agent_id is not null) or
    (binding = 'per_user'  and user_id is not null and agent_id is null)     or
    (binding = 'workspace' and user_id is null     and agent_id is null)
  )
);
-- o singură conexiune per combinație, cu NULL normalizat
create unique index on service_connection (
  service_id,
  coalesce(user_id,  '00000000-0000-0000-0000-000000000000'::uuid),
  coalesce(agent_id, '00000000-0000-0000-0000-000000000000'::uuid)
);
create index on service_connection (workspace_id, status);

create table oauth_state (
  id                uuid primary key default gen_random_uuid(),
  workspace_id      uuid not null references workspace(id) on delete cascade,
  agent_id          uuid not null references agent(id) on delete cascade,
  service_id        uuid not null references upstream_service(id) on delete cascade,
  user_id           uuid not null references app_user(id) on delete cascade,
  code_verifier_enc bytea not null,
  redirect_uri      text not null,
  requested_scopes  text[] not null default '{}',
  return_url        text,
  created_at        timestamptz not null default now(),
  expires_at        timestamptz not null,
  consumed_at       timestamptz
);
create index on oauth_state (expires_at) where consumed_at is null;

-- ─── cereri de identitate ────────────────────────────────────────────
create table identity_request (
  id                 uuid primary key default gen_random_uuid(),
  workspace_id       uuid not null references workspace(id) on delete cascade,
  kind               text not null
                     check (kind in ('delegation','agent_credential','service_account')),
  requested_by_type  text not null check (requested_by_type in ('user','agent')),
  requested_by_id    uuid not null,
  agent_id           uuid not null references agent(id) on delete cascade,
  service_id         uuid references upstream_service(id) on delete cascade,
  user_id            uuid references app_user(id) on delete cascade,
  requested_scopes   text[] not null default '{}',
  purpose            text,
  status             text not null default 'pending'
                     check (status in ('pending','approved','denied','fulfilled','expired','revoked')),
  approved_by_type   text check (approved_by_type in ('user','agent')),
  approved_by_id     uuid,
  approved_at        timestamptz,
  fulfilled_connection_id uuid references service_connection(id),
  fulfilled_credential_id uuid references agent_credential(id),
  expires_at         timestamptz,
  created_at         timestamptz not null default now(),
  -- un agent nu își aprobă propria cerere; un om își poate auto-aproba propria delegare
  check (approved_by_id is null or requested_by_type = 'user' or approved_by_id <> requested_by_id),
  -- forma subiecților depinde de tipul cererii
  check (
    (kind = 'delegation'       and user_id is not null and service_id is not null) or
    (kind = 'service_account'  and user_id is null     and service_id is not null) or
    (kind = 'agent_credential' and service_id is null)
  )
);
create index on identity_request (workspace_id, status);
create index on identity_request (agent_id, status);

-- ─── approvals ───────────────────────────────────────────────────────
create table approval_request (
  id               uuid primary key default gen_random_uuid(),
  workspace_id     uuid not null references workspace(id) on delete cascade,
  kind             text not null check (kind in ('grant','connection','role_change')),
  subject          jsonb not null,        -- ce se cere, suficient pentru a rejuca
  requested_by_type text not null check (requested_by_type in ('user','agent')),
  requested_by_id  uuid not null,
  status           text not null default 'pending'
                   check (status in ('pending','approved','denied','expired')),
  decided_by_id    uuid,
  decided_at       timestamptz,
  note             text,
  created_at       timestamptz not null default now(),
  expires_at       timestamptz
);
create index on approval_request (workspace_id, status);

-- ─── audit & metering ────────────────────────────────────────────────
create table audit_event (
  id            bigserial,
  workspace_id  uuid not null,
  ts            timestamptz not null default now(),
  actor_type    text not null check (actor_type in ('user','agent','system')),
  actor_id      uuid,
  action        text not null,             -- grant.update, tool.call, connection.revoke
  resource_type text,
  resource_id   uuid,
  decision      text check (decision in ('allow','deny','n/a')),
  trace_id      text not null,
  meta          jsonb not null default '{}'::jsonb,
  primary key (id, ts)
) partition by range (ts);

create index on audit_event (workspace_id, ts desc);
create index on audit_event (actor_type, actor_id, ts desc);

create table usage_counter (
  workspace_id uuid not null,
  agent_id     uuid not null,
  bucket       timestamptz not null,       -- trunchiat la minut
  requests     bigint not null default 0,
  cost_micros  bigint not null default 0,   -- 0 dacă serviciul nu are preț declarat
  primary key (workspace_id, agent_id, bucket)
);

-- ─── suport ──────────────────────────────────────────────────────────
create table idempotency_record (
  workspace_id uuid not null,
  key          text not null,
  request_hash text not null,
  status_code  int not null,
  response     jsonb not null,
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null,
  primary key (workspace_id, key)
);

create table a2a_task (
  id             uuid primary key default gen_random_uuid(),
  workspace_id   uuid not null references workspace(id) on delete cascade,
  agent_id       uuid not null references agent(id) on delete cascade,
  service_id     uuid not null references upstream_service(id) on delete cascade,
  remote_task_id text,
  state          text not null,
  context_id     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table mcp_session (
  id            text primary key,          -- Mcp-Session-Id
  workspace_id  uuid not null,
  agent_id      uuid not null references agent(id) on delete cascade,
  service_id    uuid not null references upstream_service(id) on delete cascade,
  upstream_state jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null
);
```

## Interogarea de politică

Cea mai fierbinte interogare. Trebuie să întoarcă tot ce e nevoie pentru o decizie, într-un singur round-trip:

```sql
select g.id            as grant_id,
       g.tools,
       g.arg_constraints,
       g.status       as grant_status,
       s.kind         as service_kind,
       s.endpoint,
       s.auth_type,
       c.id           as connection_id,
       c.status       as connection_status,
       c.expires_at   as connection_expires_at,
       c.scopes       as connection_scopes
from agent_grant g
join upstream_service s on s.id = g.service_id
left join service_connection c
       on c.service_id = s.id
      and c.status = 'active'
      and c.user_id  = :user_id
      and (c.agent_id = :agent_id or c.binding <> 'per_agent')
where g.agent_id = :agent_id
  and g.service_id = :service_id
  and g.workspace_id = :workspace_id;
```

Un index compus pe `agent_grant(agent_id, service_id)` și unul pe `service_connection(service_id, user_id, agent_id)` acoperă cazul.

## Migrații

- Alembic, un director `app/db/migrations`.
- Fiecare migrație are `upgrade` și `downgrade` testat.
- Schimbările de enum se fac prin `check` constraints noi + backfill, nu prin `alter type`.
- Migrațiile rulează ca job separat în pipeline, înainte de rollout.
