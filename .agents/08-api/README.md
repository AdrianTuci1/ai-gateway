# 08 — API

**Status:** `[x]` suprafață REST v1
**Owns:** rute, convenții, erori, idempotență, paginare.
**Depends on:** [`../06-policy-and-grants/README.md`](../06-policy-and-grants/README.md), [`../05-connections-and-oauth/README.md`](../05-connections-and-oauth/README.md)

## Convenții

- Prefix `/v1`, JSON peste tot, `snake_case`.
- Datetime: ISO 8601 UTC (`2026-11-02T12:00:00Z`).
- ID-uri: UUID v7 ca string.
- Numerar: integer în unități minime (`cost_micros`), niciodată float.
- Autentificare: `Authorization: Bearer <api_key>` pentru agenți; cookie de sesiune pentru UI. Ambele sunt acceptate pe rutele `/v1`; ruta decide ce tip de principal permite.
- Fiecare răspuns conține `X-Trace-Id`.

## Erori

```json
{
  "error": {
    "code": "tool_not_allowed",
    "message": "Agent 'billing' is not allowed to call 'delete_invoice' on 'crm'.",
    "details": { "tool": "delete_invoice", "service": "crm", "granted": ["search_tickets"] },
    "trace_id": "01JB7Y..."
  }
}
```

| HTTP | Cod | Când |
|---|---|---|
| 400 | `invalid_request` | body invalid, câmp lipsă |
| 400 | `invalid_state` | OAuth state expirat/folosit/HMAC greșit |
| 400 | `invalid_cursor` | cursor nesemnat, trunchiat sau de altă versiune |
| 400 | `cursor_query_mismatch` | `q` sau filtrele s-au schimbat între pagini |
| 401 | `unauthenticated` | cheie absentă/invalidă |
| 401 | `enrollment_required` | lipsește credențialul; include `discovery` |
| 401 | `enrollment_token_invalid` | token de înrolare invalid, expirat sau consumat; răspuns generic |
| 403 | `bootstrap_disabled` | bootstrap-ul HTTP nu e activat |
| 403 | `forbidden` | lipsește permisiunea |
| 403 | `grant_denied` | lipsește grantul |
| 403 | `tool_not_allowed` | tool în afara grantului |
| 403 | `delegation_depth_exceeded` | A2A prea adânc |
| 404 | `not_found` | resursă inexistentă în workspace |
| 409 | `connection_required` | lipsește autorizarea; include `authorize_url` |
| 409 | `authorization_pending` | aprobare umană în curs |
| 409 | `persistent_runtime_required` | funcția cere runtime persistent; include `requirement` |
| 409 | `conflict` | unicitate încălcată |
| 410 | `bootstrap_closed` | bootstrap-ul a fost deja consumat |
| 422 | `arg_rejected` | argumente respinse de constrângeri |
| 422 | `invalid_tool_schema` | input invalid față de schema tool-ului |
| 429 | `rate_limited` | include `Retry-After` |
| 402 | `budget_exhausted` | buget epuizat |
| 501 | `feature_unavailable` | funcția nu există în runtime-ul curent |
| 502 | `upstream_error` | eroare upstream, cu `retryable` |
| 502 | `upstream_auth_error` | credențial upstream respins |
| 503 | `policy_unavailable` | DB indisponibil; fail closed |
| 503 | `vault_unavailable` | KMS indisponibil |
| 503 | `ca_unavailable` | CA indisponibil; retry cu `enrollment_id` |

Regula: un cod, un înțeles. `403` nu se folosește pentru „nu există"; altfel scurgeri de informație între workspace-uri.

`POST /v1/enroll` întoarce `201` cu credențialul când CA-ul este intern și `202` cu `enrollment_id` când semnarea este externală. În al doilea caz, clientul reia cu `POST /v1/enroll/{id}/complete`, trimițând același CSR; `enrollment_id` este idempotent.

## Rute

### Identitate

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/me` | autentificat |
| `GET` | `/v1/runtime` | public |
| `POST` | `/v1/auth/device/code` | public |
| `POST` | `/v1/auth/device/token` | public, cu `device_code` |
| `POST` | `/v1/auth/refresh` | refresh token |
| `POST` | `/v1/auth/logout` | autentificat |
| `GET` | `/.well-known/agw` | public |
| `POST` | `/v1/enroll` | public, cu enrollment token |
| `POST` | `/v1/enroll/{id}/complete` | public, cu `enrollment_id` și CSR |
| `POST` | `/v1/enroll/device` | public |
| `POST` | `/v1/enroll/device/token` | public, cu `device_code` |
| `POST` | `/v1/enroll/device/approve` | sesiune user |
| `POST` | `/v1/bootstrap` | public, cu bootstrap token, doar înainte de primul workspace |
| `GET` | `/v1/workspaces` | — |
| `POST` | `/v1/workspaces` | — (creează owner) |
| `GET` | `/v1/workspaces/{ws}` | `workspace:read` |
| `PATCH` | `/v1/workspaces/{ws}` | `workspace:update` |
| `GET` | `/v1/workspaces/{ws}/members` | `member:read` |

### Agenți

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/workspaces/{ws}/agents` | `agent:read` |
| `POST` | `/v1/workspaces/{ws}/agents` | `agent:create` |
| `GET` | `/v1/workspaces/{ws}/agents/{id}` | `agent:read` |
| `PATCH` | `/v1/workspaces/{ws}/agents/{id}` | `agent:update` |
| `DELETE` | `/v1/workspaces/{ws}/agents/{id}` | `agent:delete` |
| `POST` | `/v1/workspaces/{ws}/agents/{id}/credentials` | `agent:credential_rotate` |
| `POST` | `/v1/workspaces/{ws}/agents/{id}/credentials/{cid}/revoke` | `agent:credential_rotate` |
| `POST` | `/v1/workspaces/{ws}/enrollment-tokens` | `agent:create` |
| `DELETE` | `/v1/workspaces/{ws}/enrollment-tokens/{id}` | `agent:create` |
| `GET` | `/v1/workspaces/{ws}/agents/{id}/grants` | `grant:read` |
| `PUT` | `/v1/workspaces/{ws}/agents/{id}/grants/{service_id}` | `grant:write` |
| `DELETE` | `/v1/workspaces/{ws}/agents/{id}/grants/{service_id}` | `grant:write` |
| `POST` | `/v1/workspaces/{ws}/agents/{id}/grants/{service_id}/request` | `grant:request` |
| `GET` | `/v1/workspaces/{ws}/agents/{id}/usage` | `usage:read` |

`PUT` pe grant este **idempotent și complet**: body-ul descrie starea dorită, nu un patch.

```json
PUT /v1/workspaces/acme/agents/42/grants/b6f1...
{
  "tools": ["search_tickets", "get_customer"],
  "arg_constraints": { "get_customer": { "tenant": { "equals": "${principal.tenant}" } } },
  "expires_at": "2026-12-31T00:00:00Z"
}
```

Răspunsul include starea rezultată și lista efectivă de tool-uri expuse.

### Servicii și catalog

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/workspaces/{ws}/services` | `service:read` |
| `POST` | `/v1/workspaces/{ws}/services` | `service:create` |
| `GET` | `/v1/workspaces/{ws}/services/{id}` | `service:read` |
| `PATCH` | `/v1/workspaces/{ws}/services/{id}` | `service:update` |
| `DELETE` | `/v1/workspaces/{ws}/services/{id}` | `service:delete` |
| `POST` | `/v1/workspaces/{ws}/services/{id}/discover` | `service:discover` |
| `GET` | `/v1/workspaces/{ws}/services/{id}/tools` | `service:read` |
| `GET` | `/v1/catalog` | `service:discover` |

Ambele rute de listare acceptă `limit` (1–200, implicit 50) și `cursor`. Catalogul acceptă în plus `q`, `kind`, `granted` și `read_only`.

```http
GET /v1/catalog?q=refund+invoice&kind=mcp_http&limit=20&cursor=...
```

```json
{
  "items": [
    { "service_id": "b6f1...", "service": "crm", "name": "refund_invoice",
      "description": "Issue a refund", "score": 0.031, "granted": false }
  ],
  "next_cursor": "eyJ2IjoxLCJrIjpb...",
  "has_more": true
}
```

Contractul complet, inclusiv regulile de cursor și fuziunea lexical + vector, este în [`../06-policy-and-grants/discovery-and-search.md`](../06-policy-and-grants/discovery-and-search.md).

### Conexiuni

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/workspaces/{ws}/agents/{id}/connections` | `connection:read` |
| `POST` | `/v1/workspaces/{ws}/agents/{id}/connections/{service_id}/authorize` | `connection:authorize` |
| `DELETE` | `/v1/workspaces/{ws}/agents/{id}/connections/{service_id}` | `connection:revoke` |
| `GET` | `/oauth/callback` | public, validat prin `state` |

### Identități

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/workspaces/{ws}/identity-requests` | `identity:request` |
| `POST` | `/v1/workspaces/{ws}/identity-requests` | `identity:request` |
| `GET` | `/v1/workspaces/{ws}/identity-requests/{id}` | `identity:request` |
| `POST` | `/v1/workspaces/{ws}/identity-requests/{id}/approve` | `identity:approve` |
| `POST` | `/v1/workspaces/{ws}/identity-requests/{id}/deny` | `identity:approve` |
| `POST` | `/v1/workspaces/{ws}/identity-requests/{id}/cancel` | solicitantul |

### Aprobări, audit, simulare

| Metodă | Rută | Permisiune |
|---|---|---|
| `GET` | `/v1/workspaces/{ws}/approvals` | `grant:read` |
| `POST` | `/v1/workspaces/{ws}/approvals/{id}/approve` | `grant:approve` |
| `POST` | `/v1/workspaces/{ws}/approvals/{id}/deny` | `grant:approve` |
| `GET` | `/v1/workspaces/{ws}/audit` | `audit:read` |
| `POST` | `/v1/workspaces/{ws}/policy/simulate` | `policy:read` |
| `GET` | `/v1/workspaces/{ws}/usage` | `usage:read` |

### Protocoale

| Metodă | Rută | Note |
|---|---|---|
| `POST` | `/mcp/{agent_slug}` | MCP streamable HTTP |
| `POST` | `/v1/a2a/{agent_slug}` | v2 |
| `GET` | `/healthz` | liveness, fără DB |
| `GET` | `/readyz` | DB + KMS ping |

## Paginare

Cursor opac, semnat, nu offset:

```http
GET /v1/workspaces/acme/audit?limit=50&cursor=eyJ0cyI6...
```

```json
{ "items": [], "next_cursor": "eyJ0cyI6...", "has_more": true }
```

`limit` maxim 200, implicit 50. Cursorul encodează cheia de sortare (`(ts, id)` pentru audit, `(score, id)` pentru căutare, `(name, id)` pentru listări) și un hash al interogării. Detalii în [`../06-policy-and-grants/discovery-and-search.md`](../06-policy-and-grants/discovery-and-search.md#contractul-de-paginare).

## Idempotență

- Header `Idempotency-Key` pe `POST`/`PUT`.
- Cheia + hash-ul body-ului se salvează în `idempotency_record`.
- Aceeași cheie cu body diferit → `409 conflict`.
- Aceeași cheie cu același body → răspunsul original, `200` cu header `Idempotent-Replay: true`.
- TTL 24h, curățare prin job.

## Rate limiting

- Pe principal și pe rută: `429` cu `Retry-After` și `X-RateLimit-Remaining`.
- Limitele vin din rol și din `agent.ceiling.budget`.
- Contorizare în `usage_counter`, bucket de minut.

## Versionare

- `/v1` îngheață contractul; câmpuri noi se adaugă, cele existente nu se schimbă semantic.
- Un câmp se scoate după o perioadă de deprecare cu header `Deprecation` și `Sunset`.
- Breaking changes → `/v2`, cu ambele rute active minimum 6 luni.

## Exemplu complet: agentul cere acces și primește link

```http
GET /v1/catalog?q=invoice
Authorization: Bearer agw_live_...

200 { "items": [ { "service_id": "b6f1...", "name": "crm", "granted": false } ] }
```

```http
POST /v1/workspaces/acme/agents/42/grants/b6f1.../request
{ "tools": ["list_invoices"], "justification": "answering billing questions" }

202 { "approval_id": "a91...", "status": "pending" }
```

```http
# după aprobare
POST /v1/workspaces/acme/agents/42/connections/b6f1.../authorize
{ "return_url": "https://app.example.com/agents/42" }

200 { "authorize_url": "https://crm.example.com/oauth/authorize?...", "expires_at": "..." }
```

```http
# agentul cheamă tool-ul înainte ca userul să autorizeze
POST /mcp/billing-agent

{ "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": { "name": "crm__list_invoices", "arguments": {} } }

200 { "jsonrpc": "2.0", "id": 1,
      "error": { "code": -32001, "message": "connection_required",
                 "data": { "authorize_url": "https://gateway.../authorize?..." } } }
```

## Exemplu: agentul cere o identitate

```http
POST /v1/workspaces/acme/identity-requests
Authorization: Bearer agw_live_...

{
  "kind": "delegation",
  "agent_id": "42",
  "service_id": "b6f1...",
  "user_id": "u-17",
  "requested_scopes": ["crm.read"],
  "purpose": "answer billing questions for the user"
}

202 {
  "id": "ir_9c2...",
  "status": "pending",
  "approval_required": true,
  "expires_at": "2026-11-09T12:00:00Z"
}
```

```http
# după aprobare de către un alt principal
GET /v1/workspaces/acme/identity-requests/ir_9c2...

200 {
  "id": "ir_9c2...",
  "status": "approved",
  "authorize_url": "https://crm.example.com/oauth/authorize?...",
  "expires_at": "2026-11-02T12:10:00Z"
}
```

```http
# după consimțământul userului
200 {
  "id": "ir_9c2...",
  "status": "fulfilled",
  "fulfilled_connection_id": "c0a1...",
  "binding": { "user_id": "u-17", "agent_id": "42", "service_id": "b6f1..." }
}
```
