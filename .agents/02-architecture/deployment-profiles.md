# 02.2 — Profiluri de execuție: persistent și request/response

**Status:** `[x]` regulă de bază
**Owns:** ce rulează persistent, ce rulează per request, ce funcții sunt disponibile în fiecare.
**Depends on:** [`README.md`](README.md), [`stateless-deployment.md`](stateless-deployment.md), [ADR-018](../11-decisions/README.md#adr-018--persistent-doar-în-self-host)

## Regula

**Serverul persistent există doar în self-host.** În serverless/edge rulează același cod în modul `request_response`: fără conexiuni deschise, fără sesiuni, fără streaming. Nu construim adaptoare care să imite persistența.

Consecința practică: nu există „edge ca self-host mic". Există două anvelope de execuție, cu capabilități diferite, declarate explicit.

| | **persistent** (self-host) | **request_response** (serverless) |
|---|---|---|
| Proces | long-lived, N replici | per invocare |
| Conexiuni DB | pool | una per invocare sau driver HTTP |
| Răspuns MCP | JSON sau SSE | doar JSON |
| Sesiuni MCP | da | nu |
| Connector stdio | da | nu |
| A2A `message/stream` | da | nu |
| A2A push notifications | da | nu |
| Tool calls | sync și streaming | sync |
| Timeout | 900 s per stream, 300 s implicit per tool | 25 s per tool |
| Autoscale | HPA/KEDA | scale-to-N per platformă |

## Ce înseamnă „fără adaptoare"

Am respins explicit trei soluții care ar fi cerut cod de adaptare:

1. **Emularea SSE prin polling** între gateway și upstream. Ar tripla request-urile și ar schimba semantica MCP.
2. **Sesiuni ținute în DB ca să pară persistente.** Ar muta starea în baza de date fără să rezolve conexiunea upstream.
3. **Strat subțire JS pe Cloudflare Workers** în fața originului. Ar însemna două limbaje, două deploy-uri și o a doua implementare de auth.

Niciuna nu există în cod. Un serviciu care cere persistență este marcat și refuzat în modul `request_response`, cu un mesaj clar.

## Matricea de capabilități

| Funcție | persistent | request_response |
|---|---|---|
| `POST /v1/*` (CRUD, granturi, identități) | ✓ | ✓ |
| `POST /mcp/{agent}` cu răspuns JSON | ✓ | ✓ |
| `POST /mcp/{agent}` cu răspuns SSE | ✓ | ✗ `409 persistent_runtime_required` |
| `Mcp-Session-Id` | ✓ | ✗ |
| `GET /v1/catalog` + căutare/paginare | ✓ | ✓ |
| OAuth authorize + callback | ✓ | ✓ |
| mTLS per request, terminat la API Gateway/ALB | ✓ | ✓ |
| Refresh lazy de token | ✓ | ✓ |
| Bridge stdio către gateway, implementat de client | ✓ | ✓ (client-side) |
| Connector stdio către upstream | ✓ | ✗ |
| A2A `message/send` | ✓ | ✓ |
| A2A `message/stream`, push | ✓ | ✗ |
| Audit + metering | ✓ | ✓ |

TLS se termină la load balancer sau API Gateway în ambele anvelope. Certificatul serverului este gestionat de platformă (ACM, ingress, ACME), iar aplicația nu ține chei private. Certificatul clientului este validat de platformă, care trimite amprenta într-un header semnat; aplicația verifică header-ul, fără handshake în proces. Detalii în [`../04-identity-and-access/enrollment.md`](../04-identity-and-access/enrollment.md#cine-deține-cheia-privată).

## Cum se detectează cerința de persistență

La `discover`, gateway-ul notează pentru fiecare serviciu:

```json
{
  "service_id": "b6f1...",
  "runtime_requirements": {
    "streaming": true,
    "session": false,
    "stdio": false,
    "push": false
  }
}
```

Detecția:

- `initialize` care întoarce `Mcp-Session-Id` → `session: true`;
- `tools/list` sau `tools/call` care răspunde cu `text/event-stream` → `streaming: true`;
- `kind = 'mcp_stdio'` → `stdio: true`;
- agent card A2A cu `capabilities.streaming` sau `pushNotifications` → `streaming` / `push`.

În modul `request_response`:

- la înregistrarea unui serviciu cu `stdio: true` → `409 persistent_runtime_required`, imediat;
- la un apel către un serviciu cu `streaming` sau `session` → `409 persistent_runtime_required`, cu `service` și `requirement` în eroare;
- catalogul afișează badge-ul „needs persistent runtime", ca operatorul să știe de ce nu merge.

Asta este o verificare de capabilitate, nu un adaptor: codul nu încearcă să facă SSE să meargă altfel.

## Profilul persistent (self-host)

```
        ┌──────────────┐
        │ Load balancer│
        └──────┬───────┘
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  gateway-1  gateway-2  gateway-N     ← stateless, HPA
     └─────────┼─────────┘
               ▼
          PgBouncer
               ▼
          Postgres primary ──► replica
               ▼
          KMS / Vault
```

- Pool de conexiuni per proces.
- SSE și sesiuni ținute în memoria request-ului, nu în proces între request-uri.
- Connector stdio ca serviciu separat, long-lived, care expune serverele stdio ca HTTP.
- Autoscale fără P2P: HPA/KEDA pe RPS, CPU, latență; LB cu round-robin; fără sticky sessions.
- Job-uri periodice cu `pg_try_advisory_lock`, un singur câștigător.

### Durata unei conexiuni

Streamable HTTP ține o conexiune deschisă pe durata unui `tools/call`. Plafonul de 15 minute al platformei este suficient: `MCP_STREAM_MAX_SECONDS = 900`, iar timeout-ul implicit de tool rămâne 300 s. Un call care atinge plafonul se închide cu `upstream_timeout`, iar clientul poate relua cu `tools/call` din nou.

Apelurile peste 60 s se marchează în audit cu `slow_upstream`, ca operatorul să vadă unde se pierde timpul. Conexiunea nu se ține deschisă între apeluri; fiecare `tools/call` are propriul ciclu.

## Profilul request_response (serverless)

```
API Gateway / Function URL
        ▼
  Lambda (Mangum) ──► DynamoDB (edge, fără VPC)
        │                 sau Postgres prin RDS Proxy (VPC)
        └──► upstream HTTP/MCP (request/response)
```

- Handler: `mangum.Mangum(app)`, un proces per invocare.
- Storage: DynamoDB pentru edge. Postgres rămâne opțiune când datele trebuie să stea în VPC sau când se cer join-uri; atunci se folosește `NullPool` cu RDS Proxy, sau un driver HTTP (Neon, Supabase, Aurora Data API). Alegerea e configurare, nu cod de adaptor.
- Timeout de tool call: 25 s, sub limita platformei.
- Fără `asyncio.create_task` care supraviețuiește invocării.
- Fără `stdio`, fără SSE, fără WebSocket.
- OAuth callback pe un domeniu stabil, nu pe un host de invocare.
- `min-instances` / provisioned concurrency pentru cold start.

**Cloudflare Workers nu este o țintă.** Runtime-ul Python (Pyodide) nu susține FastAPI cu drivere DB async, iar un strat JS ar fi al doilea gateway. Dacă e nevoie de POP-uri Cloudflare, ele pot face doar DNS/CDN/WAF în fața originului serverless.

## Configurare

```python
class Runtime(str, Enum):
    PERSISTENT = "persistent"
    REQUEST_RESPONSE = "request_response"

class Settings(BaseSettings):
    runtime: Runtime = Runtime.PERSISTENT
    database_url: str
    db_driver: Literal["asyncpg", "http"] = "asyncpg"
    db_pool_size: int = 5
    tool_timeout_seconds: int = 300
    mcp_stream_max_seconds: int = 900
```

La startup, o validare refuză combinațiile imposibile:

- `tool_timeout_seconds > mcp_stream_max_seconds` → eroare de configurare;
- `runtime=request_response` + `ENABLE_STDIO=true` → eroare de configurare;
- `runtime=request_response` + servicii cu `stdio` în DB → warning la boot, eroare la primul apel;
- `runtime=persistent` + `db_driver=http` → permis, dar semnalat la boot ca mod neobișnuit.

`GET /v1/runtime` întoarce capabilitățile, ca CLI-ul și clienții să știe ce să aștepte:

```json
{
  "runtime": "request_response",
  "features": { "mcp_sse": false, "mcp_sessions": false, "stdio": false, "a2a_stream": false }
}
```

## Matricea de decizie

| Întrebare | Da | Runtime |
|---|---|---|
| Ai nevoie de SSE de la MCP sau de sesiuni? | da | persistent |
| Ai nevoie de connector stdio? | da | persistent |
| Ai nevoie de A2A streaming sau push? | da | persistent |
| Vrei scale-to-zero și operare minimă? | da | request_response |
| Rulezi în VPC-ul clientului, cu Postgres local? | da | persistent |
| Trafic mic, buget mic, fără streaming? | da | request_response |

Un deployment poate avea ambele: un origin persistent în regiunea principală și instanțe request_response pentru operații de control. Ambele folosesc același backend de stocare. Serviciile marcate „needs persistent runtime" sunt refuzate doar pe cele request_response.

## Riscuri

| Risc | Profil | Mitigare |
|---|---|---|
| Un serviciu MCP cere SSE | request_response | marcat la discover, refuz clar, mutat pe persistent |
| Cold start | request_response | provisioned concurrency |
| Epuizarea conexiunilor | persistent | PgBouncer + plafon pe replici |
| Timeout de platformă | request_response | timeout de tool 25 s |
| Un stream atinge plafonul de 15 min | persistent | `MCP_STREAM_MAX_SECONDS=900`, reluare din client, `slow_upstream` în audit |
| Operatorul se așteaptă la paritate | ambele | `GET /v1/runtime` + badge în catalog + `agw serve --check` |

## Artefacte de deployment

- **Docker + Postgres** — [`deploy/docker`](../../deploy/docker): imagine
  non-root, `docker-compose.yml` cu Postgres, volume pentru DB și CA, runtime
  `persistent`.
- **AWS Lambda + DynamoDB** — [`deploy/terraform`](../../deploy/terraform),
  `data_backend = "dynamodb"` (implicit): API Gateway HTTP API, Lambda cu
  Mangum, un singur tabel DynamoDB. Fără VPC și fără NAT Gateway,
  `request_response`. Lambda-ul de migrare seedează rolurile builtin înainte
  de activarea rutei.
- **AWS Lambda + Postgres** — același mediu Terraform cu
  `data_backend = "postgres"`: Lambda în subnet-uri private, RDS Postgres și
  RDS Proxy opțional, `request_response`. Migrațiile rulează prin Lambda-ul
  dedicat înainte de activarea rutei.
- Accesul la date trece prin interfața `Store`, cu implementări SQL și
  DynamoDB. Vezi [ADR-021](../11-decisions/README.md#adr-021--strat-de-stocare-cu-două-backend-uri).
- Lambda folosește `AGW_CA_ENABLED=false`. Pe Postgres folosește și
  `AGW_DB_POOL_MODE=null`. Înrolarea cu certificate client cere un CA durabil,
  deci pe edge se folosesc API keys până la un backend KMS/HSM.
- Pe DynamoDB, `agw admin recover` nu este disponibil; recuperarea se face prin
  roluri de operator și HTTP.
- Deploy-ul pe edge se pornește manual, cu `gh workflow run deploy.yml`.
  Credențialele vin din Google Secret Manager prin OIDC, iar state-ul Terraform
  stă într-un bucket S3 partajat, cu lock în DynamoDB. Detalii în
  [`../13-ci/README.md`](../13-ci/README.md).
