# 02.1 — Stateless și deployment

**Status:** `[x]` decizie luată, cu limite documentate
**Owns:** inventarul de stare, regulile de statelessness, țintele de runtime, pooling-ul DB.
**Depends on:** [`README.md`](README.md), [`deployment-profiles.md`](deployment-profiles.md), [ADR-002](../11-decisions/README.md#adr-002--stateless-cu-stare-exclusiv-în-postgres--kms), [ADR-003](../11-decisions/README.md#adr-003--fastapi--spa-în-același-worker), [ADR-018](../11-decisions/README.md#adr-018--persistent-doar-în-self-host)

## Răspuns scurt

**Da, poate fi stateless.** Toată starea mutabilă ajunge în backendul de stocare — Postgres în self-host, DynamoDB pe edge — iar credențialele în vault criptat cu KMS. Procesul nu ține sesiuni, nu ține cache de politică, nu ține contoare în memorie. Poți rula N replici identice și poți rula în Lambda pentru partea de control plane.

**Cu o excepție importantă:** streaming-ul (SSE de la MCP upstream) și sesiunile MCP cer un runtime `persistent`. Limita de platformă de 15 minute este suficientă pentru un `tools/call` — plafonul nostru este 900 s, implicit 300 s — deci durata nu e problema. Problema este modelul de invocare: în `request_response` fiecare request este o invocare separată, fără canal deschis între apeluri și fără loc unde să ții sesiunea. Pentru data plane cu streaming, runtime-ul recomandat este un container (Cloud Run, Fly, ECS Fargate). Alegerea completă între cele două profiluri este în [`deployment-profiles.md`](deployment-profiles.md).

## Inventarul de stare

| Stare | Unde trăiește | TTL | Notă |
|---|---|---|---|
| Sesiune user | cookie semnat (JWT) + `session` în DB dacă e nevoie de revocare | 12h | fără sesiune în memorie |
| Sesiune agent | API key / certificat, verificat per request | — | hash în DB, nu în memorie |
| `oauth_state` | tabel `oauth_state` | 10 min | PKCE verifier criptat |
| Tokenuri upstream | `service_connection`, criptate | după provider | decriptare per request |
| Politică | backend de stocare (Postgres / DynamoDB) | — | interogare per request |
| Rate limit | `usage_counter` (bucket minut) | 2 zile | upsert atomic |
| Idempotență | `idempotency_record` | 24h | hash pe body |
| Sesiune MCP | `mcp_session` | 30 min | opțional; vezi mai jos |
| Task A2A | `a2a_task` | 7 zile | pentru `tasks/get` |
| Fișiere temporare | `/tmp` | per invocare | nimic persistent |

## Reguli de statelessness (verificate în CI)

1. **Fără dicționare globale mutabile** în afara constantelor. Un test lint respinge `global` la nivel de modul în `app/`.
2. **Fără sesiuni în memorie.** Cookie semnat, verificat cu cheie din KMS/secret.
3. **Fără rate limiter în memorie.** Contor în DB.
4. **Fără `BackgroundTasks` pentru muncă ce trebuie să supraviețuiască.** Refresh-ul de token se face lazy, în request. Job-urile periodice rulează în afara procesului (EventBridge Scheduler → Lambda, sau Cloud Scheduler → job).
5. **Fără scriere pe disc** în afara `/tmp`.
6. **Fără conexiuni long-lived către upstream** ținute între request-uri.
7. **Fără sticky sessions.** Orice replică poate servi orice request.
8. **Migrații la deploy, nu la boot.** Un job separat rulează `alembic upgrade head`; altfel N replici concurează.

## Ținte de runtime

| Runtime | Control plane (CRUD, OAuth callback) | Data plane (MCP streaming) | Verdict |
|---|---|---|---|
| **Cloud Run** | da | da (timeout 60 min, SSE ok) | **recomandat** |
| **Fly.io / ECS Fargate** | da | da | recomandat |
| **AWS Lambda (container image)** | da, cu Mangum | nu: request/response merge, sesiuni și SSE continuu nu | control plane only |
| **Cloudflare Workers (Python)** | teoretic | nu | **nu** — runtime Pyodide, fără drivere DB async reale |
| **VPS + systemd** | da | da | ok pentru self-host |

### Lambda, concret

- Adapter: `mangum.Mangum(app)`, un handler.
- Imagine de container (până la 10 GB), nu zip, ca să încapă dependențele.
- Cu Postgres: `AGW_DB_POOL_MODE=null` → `NullPool` în SQLAlchemy; fiecare invocare deschide o conexiune. Cu RDS Proxy sau PgBouncer în mod tranzacție, altfel epuizezi `max_connections`.
- Cu DynamoDB: `AGW_DB_BACKEND=dynamodb` și `AGW_DYNAMODB_TABLE`. Nu există pool de conexiuni și nu e nevoie de VPC; Lambda ajunge la tabel prin rețeaua AWS.
- `AGW_CA_ENABLED=false`: Lambda nu are un filesystem durabil pentru cheia CA. Se folosesc API keys; certificatele client cer un CA extern sau KMS/HSM.
- Secretele vin dintr-un secret JSON (`secret_key`, `bootstrap_token`, plus `database_url` când backendul este Postgres) citit la cold start; cheia DB nu intră în variabilele de mediu Lambda.
- Cold start: 1–2 s cu FastAPI + SQLAlchemy. Provisioned concurrency dacă e nevoie.
- Fără `asyncio.create_task` care depășește durata invocării.
- Timeout maxim 15 min; implicit 30 s în API Gateway. Setează `timeout` explicit.

### Cloud Run, concret

- `min-instances=1` ca să eviți cold start pe UI.
- `concurrency=40–80` per instanță, în funcție de DB pool.
- `--timeout=3600` dacă vrei SSE lung.
- `--no-cpu-throttling` pentru streaming.

## Conexiuni la storage

| Mediu | Strategie |
|---|---|
| Cloud Run / containere, Postgres | pool async (asyncpg) per proces, `pool_size=5–10`, `max_overflow=0` |
| Lambda, Postgres | `NullPool` + RDS Proxy / PgBouncer tranzacțional |
| Lambda, DynamoDB | client boto3 partajat, fără pool și fără VPC |
| Dezvoltare | Postgres în Docker sau SQLite, pool normal; DynamoDB prin moto sau un endpoint local |

Reguli:
- `statement_timeout` la 5 s pentru request-uri, 30 s pentru job-uri.
- Index pe fiecare cale de politică: `agent_grant(agent_id, service_id, status)`.
- Tranzacții scurte; niciun apel HTTP upstream ținut în tranzacție.

## Configurare

Toate prin environment, fără fișiere de config în container:

```
DB_BACKEND=sql|dynamodb
DATABASE_URL=postgresql+asyncpg://...        # sql
DYNAMODB_TABLE=ai-gateway-dev                # dynamodb
KMS_KEY_ID=...
PUBLIC_BASE_URL=https://gateway.example.com
SESSION_SIGNING_KEY=<secret>
OAUTH_CALLBACK_PATH=/oauth/callback
LOG_LEVEL=info
RUNTIME=persistent|request_response
DB_DRIVER=asyncpg|http
```

Secretele (client secrets de provider, cheia de sesiune) vin din Secrets Manager, încărcate la startup. Rotirea lor cere restart; asta e acceptabil pentru că sunt puține.

## Un singur worker: API acum, UI mai târziu

v1 servește doar API-ul. Când UI-ul va exista, se adaugă în același container, fără al doilea serviciu:

```
Dockerfile (multi-stage)
  stage web: node build → /web/dist        # doar când există UI
  stage api: python deps → /app
  final: copy /web/dist → /app/web/dist     # opțional
```

FastAPI:
```python
app.mount("/assets", StaticFiles(directory="web/dist/assets"), name="assets")

@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse("web/dist/index.html")   # fallback pentru rutele SPA
```

Rutele `/v1/*`, `/mcp/*`, `/oauth/*`, `/healthz` sunt declarate înaintea catch-all-ului. Cât timp UI-ul lipsește, catch-all-ul nu există și orice rută necunoscută întoarce `404` JSON.

API-ul nu depinde de montarea statică: `/v1` și `/mcp` merg și când UI-ul nu e construit.

## Scalare

- Orizontală, fără stare: `replicas = f(CPU, RPS)`. LB-ul nu are nevoie de sticky sessions.
- Baza de date scalează vertical întâi; apoi read replica pentru catalog și audit.
- Bugetul de latență: +8–15 ms per request pentru politică + decriptare. Sub 25 ms cu Postgres local în aceeași regiune.
- Limita reală la scală mare: contorul de rate limit (rând fierbinte). Soluție: bucket pe minut și pe agent, nu un singur rând global.
