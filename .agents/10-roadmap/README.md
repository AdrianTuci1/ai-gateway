# 10 — Roadmap

**Status:** `[x]` faze propuse
**Owns:** ordinea de livrare, criterii de ieșire.
**Depends on:** toate celelalte

Fiecare fază se termină cu ceva demonstrabil end-to-end. Nu se începe o fază înainte ca precedenta să aibă criterii de ieșire verificate.

## P0 — Schelet și API (1–2 săptămâni)

- FastAPI + Typer în același pachet; `agw serve` pornește API-ul, `agw migrate` pregătește schema.
- `POST /v1/bootstrap` cu token de deployment, `bootstrap_state`, `GET /.well-known/agw`.
- Rute HTTP pentru workspace-uri, agenți, enrollment tokens și înrolare.
- `agw admin recover` pentru break-glass, cu audit obligatoriu.
- `POST /v1/enroll` cu CSR, emitere de certificat prin CA intermediar și consum atomic al tokenului.
- Alegerea runtime-ului (`persistent` sau `request_response`) și a driverului de DB; `GET /v1/runtime` și validarea de configurare la startup. Vezi [`02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md).
- Postgres + Alembic, primele migrații pentru `workspace`, `app_user`, `agent`, `membership`, `role_definition`.
- AuthN: API key pentru agenți, sesiune device-flow pentru oameni.
- Roluri builtin + `require()`.
- Audit minim: fiecare mutație.

**Ieșire:** un agent creat prin HTTP primește o cheie, `GET /v1/me` răspunde cu ea, iar acțiunea apare în `GET /v1/workspaces/{ws}/audit`. Un al doilea agent se înrolează cu token one-time, primește certificat, iar tokenul este refuzat la reutilizare. `agw admin recover` restaurează owner-ul și lasă urmă în audit.

## P1 — Catalog, MCP și grants (2–3 săptămâni)

- `upstream_service`, `service_tool`, `agent_grant`.
- Descoperire MCP (`tools/list`), hash per tool, catalog persistat.
- Detecția `runtime_requirements` la discover (`streaming`, `session`, `stdio`, `push`) și gate-ul de capabilități: `409 persistent_runtime_required` pentru funcțiile absente din anvelopă.
- Rutare prin lookup `(workspace, service, tool)`; `404 tool_unknown` cu sugestie de discover.
- Paginare cu cursor pe listări și pe `tools/list`.
- Căutare lexicală: `tsvector` + `pg_trgm`, fără embeddings.
- Gateway ca MCP server: `initialize`, `tools/list` filtrat, `tools/call` cu evaluator.
- Rute HTTP pentru servicii, discover, catalog și granturi.
- Namespacing, limite, erori `-3200x`.
- Simulare de politică.

**Ieșire:** un agent cu grant pe `crm` vede doar tool-urile permise și primește `403` pe restul; `GET /v1/catalog?q=invoice` răspunde din catalog fără să contacteze MCP-ul; apelul ajunge la upstream.

## P2 — Conexiuni OAuth (2 săptămâni)

- `service_connection`, `oauth_state`, envelope encryption.
- Flux authorize → callback → vault → refresh lazy.
- Link de autorizare în răspunsul `connection_required` și în `GET /v1/workspaces/{ws}/agents/{id}/connections`.
- Revocare.

**Ieșire:** un serviciu OAuth real funcționează cap-coadă; tokenul expirat se reîmprospătează fără intervenție; tokenul nu apare în log-uri.

## P3 — Descoperire, aprobări și cereri de identitate (2–3 săptămâni)

- `GET /v1/catalog` filtrat.
- `approval_request`, inbox, notificări.
- `identity_request`: `delegation`, `agent_credential`, `service_account`; aprobare de către alt principal, fulfill prin callback OAuth.
- Roluri de agent: `agent:requester`, `agent:editor`; permisiuni `identity:request` și `identity:approve`.
- Plafonul de autoritate (ceiling) aplicat la scrieri de grant, de rol și de identitate.
- Rute HTTP pentru cereri de grant, aprobări și cereri de identitate.
- `GET /v1/workspaces/{ws}/audit?decision=deny` pentru verificarea refuzurilor.

**Ieșire:** un agent cu `agent:editor` poate adăuga un tool în limita plafonului și primește aprobare automată; dincolo de plafon i se creează cerere. Un agent poate cere o delegare și primește linkul OAuth după aprobare.

## P4 — A2A și bugete (2–3 săptămâni)

- `upstream_service.kind = 'a2a'`, fetch agent card, skills ca tool-uri.
- Token delegat `sub`/`act`, limită de adâncime, `a2a_task`.
- `usage_counter` pe cereri, limite pe agent, `402 budget_exhausted`.

**Ieșire:** un agent cheamă un peer A2A cu identitatea userului propagată; limita de cereri depășită blochează apelul.

## P5 — UI și întărire (continuu)

- UI web: listă agenți, editor de capabilități, inbox de aprobări, audit. Reia endpoint-urile existente.
- mTLS cu CA intermediar și certificate short-lived.
- DLP pe rezultate, redactare de secrete.
- Partiționare `audit_event`, export în object storage.
- OpenTelemetry, dashboard-uri, alerte pe `grant_denials` și `connection_refresh` eșuat.
- Read replica pentru catalog.
- Evaluare Redis pentru rate limiting, dacă rândul devine fierbinte.

## Riscuri

| Risc | Impact | Mitigare |
|---|---|---|
| Specificația A2A se schimbă | rescriere adaptor | adaptor izolat, `agent_card` stocat ca JSON |
| Un serviciu cere SSE sau sesiune în `request_response` | funcția lipsește | marcat la discover, refuz `409`, mutat pe runtime persistent; fără adaptoare |
| Un serviciu upstream schimbă tool-urile | apeluri rupte | hash + grant `stale` + notificare |
| Consimțământul OAuth per agent devine obositor | adopție scăzută | `credential_policy = per_user` pentru read-only |
| Rate limiting pe DB nu ține la scară | latență | bucket pe minut; Redis ca escape hatch |
| Agenți-editor escaladează | breșă | test dedicat pe plafon, în CI |

## Indicatori de succes

- Timp median de la creare agent la primul tool call reușit: < 5 min.
- Procent de apeluri respinse cu motiv clar în CLI și API: 100%.
- Zero tokenuri în log-uri (test canary).
- Latență adăugată de gateway: p99 < 25 ms pentru apeluri non-streaming.
