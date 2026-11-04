# 02 — Arhitectură

**Status:** `[x]` schelet stabilit
**Owns:** componente, layere, fluxuri de request, reguli de caching, moduri de eșec.
**Depends on:** [`../01-vision/README.md`](../01-vision/README.md), [`../11-decisions/README.md`](../11-decisions/README.md)

## Forma generală

```
                    ┌──────────────────────────────────────────┐
   CLI (agw) ──────►│  FastAPI                                 │
   Agent (API key)  │  ├─ edge: authn → workspace → rate limit │
   Agent (mTLS) ───►│  ├─ policy engine                        │
   Agent peer (A2A) │  ├─ credential broker (KMS + vault)      │
                    │  ├─ adapters: MCP | A2A | HTTP           │
                    │  └─ audit + metering                     │
                    └───────┬──────────────┬───────────────────┘
                            │              │
                     PostgreSQL        Upstreams
                     (stare + audit)   (MCP, API, agenți)
                            │
                          KMS (envelope encryption)
```

Un singur proces. Nu există serviciu separat de politică, de vault sau de audit în v1 — sunt module în același proces, cu granițe de cod clare, ca să poată fi extrase mai târziu. CLI-ul pornește procesul și rulează migrațiile; administrarea trece prin HTTP.

## Layere

| Layer | Modul Python | Responsabilitate | Nu face |
|---|---|---|---|
| **edge** | `app/api`, `app/core/authn` | autentifică principalul (user/agent), rezolvă workspace-ul, rate limit, `trace_id` | nu decide acces la tool |
| **runtime** | `app/core/runtime` | anvelopa `persistent` / `request_response`, capabilitățile, refuzul `409` | nu emulează funcții absente |
| **policy** | `app/policy` | încarcă granturile, evaluează allowlist + argumente, întoarce decizie cu motiv | nu ține credențiale, nu face I/O upstream |
| **vault** | `app/vault` | criptare/decriptare, token exchange, refresh, revocare | nu decide cine are voie |
| **adapters** | `app/adapters/{mcp,a2a,http}` | traduc protocolul, normalizează erorile, aplică DLP | nu sar peste policy |
| **store** | `app/db` | repository-uri filtrate pe `workspace_id`, migrații | nu conține logică de autorizare |
| **audit** | `app/audit` | evenimente imutabile, metering | nu blochează request-ul la eroare de scriere (se face outbox) |

Regula de dependență: `api → policy → store`, `api → adapters → policy`, `adapters → vault`. `policy` nu importă `adapters`. `store` nu importă nimic din afară.

## Runtime

Procesul are două anvelope, alese prin `RUNTIME`: `persistent` (self-host: pool de conexiuni, SSE, sesiuni, stdio) și `request_response` (Lambda/Cloud Run: JSON, fără sesiuni, fără SSE, fără stdio). Anvelopa este o decizie de configurare; restul codului citește `runtime.features`. Un endpoint care cere o funcție absentă întoarce `409 persistent_runtime_required`, cu `requirement` în corp. Nu există cale de cod care să imite persistența. Detalii în [`deployment-profiles.md`](deployment-profiles.md).

## Fluxuri

### F1 — Agentul cheamă un tool MCP

```
POST /mcp/{agent_slug}  (tools/call)
 1. authn: API key sau certificat → agent_id + workspace_id
 2. rate limit: contor atomic în usage_counter
 3. policy: grant activ pe (agent, service)? tool în allowlist? argumente valide?
    └─ nu → 403 tool_not_allowed, audit deny, fără apel upstream
 4. vault: connection activ? token valid? altfel refresh lazy
    └─ nu → 409 connection_required + authorize_url
 5. vault: token exchange (aud=service, scope=intersecție, TTL 5m)
 6. adapter: apel upstream, timeout, retry idempotent
 7. DLP pe rezultat, apoi răspuns
 8. audit allow + metering (în aceeași tranzacție cu decizia)
```

Pasul 6 depinde de anvelopă: în `request_response`, un upstream care cere sesiune sau răspuns SSE este refuzat înainte de apelul upstream, cu `409 persistent_runtime_required`.

### F2 — Omul editează capabilitățile din UI

```
PUT /v1/workspaces/{ws}/agents/{id}/grants/{service}
 1. authn: sesiune user (cookie sau bearer de CLI) sau API key de agent
 2. permisiune: grant:write
 3. dacă apelantul e agent: verifică ceiling + subset din propriile granturi
 4. validare: tool-urile există în manifestul serviciului
 5. upsert grant + audit, într-o tranzacție
 6. răspuns: grantul nou + lista de tool-uri efectiv expuse
```

### F3 — Agentul descoperă și cere acces

```
GET  /v1/catalog?q=invoice        → servicii + tool-uri vizibile (metadata doar)
POST /v1/workspaces/{ws}/agents/{id}/grants/{s}/request → approval_request (status=pending)
  ├─ dacă apelantul are grant:approve și cererea e în ceiling → auto-aprobare
  └─ altfel → notificare către owneri; UI arată cererea în inbox
```

### F4 — Prima autorizare OAuth

```
POST /v1/workspaces/{ws}/agents/{id}/connections/{service}/authorize
  → { authorize_url, expires_at }
[agentul afișează linkul utilizatorului]
GET  /oauth/callback?code&state
  → schimb cod pe token, criptare, salvare connection, redirect la return_url
```

Detalii în [`../05-connections-and-oauth/README.md`](../05-connections-and-oauth/README.md).

### F5 — Agentul cere o identitate

```
POST /v1/workspaces/{ws}/identity-requests
 1. authn: agent
 2. permisiune: identity:request
 3. validare: binding în ceiling, user membru, service permis
 4. creare identity_request (pending)
    ├─ delegation → se generează authorize_url pentru user
    └─ agent_credential / service_account → așteaptă aprobare
 5. aprobare de om sau de agent cu identity:approve
 6. fulfill: conexiune nouă sau credențial nou, legat de cerere
```

Detalii în [`../04-identity-and-access/README.md`](../04-identity-and-access/README.md#cereri-de-identitate) și [`../05-connections-and-oauth/README.md`](../05-connections-and-oauth/README.md).

## Reguli de caching

Cerința este: **cache pe client, nimic pe server**.

| Ce | Server | Client |
|---|---|---|
| Politică / granturi | interogare la fiecare request | revalidare la focus + după mutație |
| Tokenuri upstream | niciodată cache-uite în proces; citite din DB per request | nu se expun niciodată |
| GET-uri de catalog | `ETag` calculat din `manifest_hash` + `updated_at` | `If-None-Match`, 304 |
| Assets statice | `Cache-Control: public, max-age=31536000, immutable` (hash în nume) | browser |
| API | `Cache-Control: no-store` | SWR în memorie, per sesiune |

Excepție unică, documentată: **cache-ul intern al SDK-ului KMS pentru data keys** (max 5 min, per proces). Altfel fiecare request ar face un round-trip la KMS. Este cache criptografic, nu cache de politică.

Catalogul (`upstream_service` + `service_tool`) este **index persistent**, nu cache. Rutarea unui tool este un lookup pe `(workspace_id, service, tool)`; descoperirea umple catalogul, iar apelurile nu contactează upstream-ul pentru a afla unde să meargă. Detalii în [`../06-policy-and-grants/discovery-and-search.md`](../06-policy-and-grants/discovery-and-search.md).

Consecințe acceptate:
- Fiecare request face minim o interogare de politică. La 200 req/s cu Postgres asta e trivial; la 5000 req/s se adaugă un read replica sau un cache explicit, decizie amânată.
- Rate limiting-ul are nevoie de stare partajată. În v1 se face cu `INSERT ... ON CONFLICT DO UPDATE` pe `usage_counter`, pe bucket de minut. Redis rămâne escape hatch, nu dependență.

## Moduri de eșec

| Componentă cade | Comportament |
|---|---|
| Postgres | `503 policy_unavailable`, fail closed, `Retry-After` |
| KMS | `503 vault_unavailable`, fail closed pe serviciile cu credențiale |
| Upstream MCP | `502 upstream_error` cu `retryable: true` dacă metoda e idempotentă |
| OAuth provider | connection marcat `needs_reauth`, se emite link nou la următorul apel |
| Scrierea de audit | request-ul continuă; evenimentul intră într-un outbox persistat și se scrie async |
| Rate limiter | fail closed pe agenții cu buget, fail open pe cei fără limită configurată |

## Observabilitate

- `trace_id` generat la edge, propagat în `X-Trace-Id`, în log-uri, în audit și către upstream.
- Log-uri JSON structurate: `ts, level, trace_id, workspace_id, actor_type, actor_id, route, status, duration_ms`.
- Metrici: `gateway_requests_total{route,status}`, `policy_decisions_total{decision,reason}`, `upstream_duration_seconds{service,method}`, `connection_refresh_total{result}`, `grant_denials_total{agent,service}`.
- OpenTelemetry pentru trace-uri; span pe fiecare adaptor.

## Structura de cod propusă

```
ai-gateway/
  .agents/                 # aceste specificații
  app/
    main.py                # FastAPI, lifespan
    cli/                   # Typer: agw serve + agw migrate + agw admin recover
    api/                   # rutele /v1
    core/                  # config, authn, errors, tracing
    policy/                # evaluator, ceiling, argument constraints
    vault/                 # crypto, oauth, token exchange
    adapters/              # mcp, a2a, http
    db/                    # modele, repository, migrații Alembic
    audit/                 # evenimente, metering
  web/                     # SPA (Vite) — amânat, nu se construiește în v1
  tests/
  pyproject.toml
  Dockerfile
```
