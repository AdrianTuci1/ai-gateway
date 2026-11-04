# 07 — Protocoale

**Status:** `[x]` MCP complet, A2A în v2
**Owns:** modul în care gateway-ul vorbește MCP și A2A.
**Depends on:** [`../06-policy-and-grants/README.md`](../06-policy-and-grants/README.md), [`../02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md)

## De ce protocolul contează pentru gateway

Un gateway care doar proxyează nu poate filtra. Diferența dintre un reverse proxy și un gateway AI este exact **cunoașterea semanticii**: la MCP știe ce e un tool și ce e un `tools/call`; la A2A știe ce e un skill și ce e o delegație. Fără asta, politica se aplică pe URL-uri, ceea ce e prea grosier și ușor de ocolit.

## Suprafețele expuse

| Cale | Protocol | Cine cheamă | Autentificare |
|---|---|---|---|
| `/mcp/{agent_slug}` | MCP streamable HTTP | agent | API key / mTLS |
| `/v1/agents/{id}/connections/{service}/authorize` | REST | agent sau UI | API key / sesiune |
| `/v1/catalog` | REST | agent | API key |
| `/v1/a2a/{agent_slug}` | A2A (v2) | agent peer | OAuth2 / mTLS |

Fiecare agent are propriul endpoint MCP. Nu există un `/mcp` global: endpoint-ul per agent face ca granturile să fie explicite și previne confuzia între agenți.

## Runtime

Aceleași rute există în ambele anvelope, cu capabilități diferite:

| Funcție | persistent | request_response |
|---|---|---|
| MCP JSON (`tools/list`, `tools/call`) | da | da |
| MCP SSE și sesiuni | da | `409 persistent_runtime_required` |
| Connector stdio | da | indisponibil |
| A2A `message/send` | da | da |
| A2A `message/stream`, push | da | `409 persistent_runtime_required` |

Refuzul este explicit, cu `requirement` în corp; nu există răspuns degradat care să pară că funcționează. Vezi [`../02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md).

## Adaptoare

```
app/adapters/
  base.py        # ProtocolAdapter: discover(), call_tool(), health()
  mcp/
    server.py    # expune gateway-ul ca MCP server către agent
    client.py    # MCP client către upstream
    transport.py # streamable-http; sse și stdio doar în runtime persistent
  a2a/
    card.py      # fetch + validare agent card
    client.py    # message/send, tasks/get, streaming
    server.py    # v2
  http/
    openapi.py   # servicii HTTP descrise prin OpenAPI
```

Interfața comună:

```python
class ProtocolAdapter(Protocol):
    async def discover(self, service: Service, creds: Credential | None) -> Manifest: ...
    async def call(self, service: Service, tool: str, args: dict,
                   creds: Credential | None, ctx: RequestContext) -> ToolResult: ...
    async def health(self, service: Service) -> Health: ...
```

Detalii: [`mcp.md`](mcp.md), [`a2a.md`](a2a.md).

## Maparea erorilor

Fiecare adaptor traduce erorile native în taxonomia gateway-ului:

| Sursă | Cod gateway | Retryable |
|---|---|---|
| MCP `-32601 Method not found` | `tool_not_found` | nu |
| MCP `-32602 Invalid params` | `upstream_invalid_params` | nu |
| MCP timeout | `upstream_timeout` | da, dacă metoda e idempotentă |
| HTTP 401/403 upstream | `upstream_auth_error` | nu; marchează `needs_reauth` |
| HTTP 429 upstream | `upstream_rate_limited` | da, cu backoff |
| A2A `input-required` | `task_input_required` | nu (e stare, nu eroare) |
| TLS failure | `upstream_tls_error` | nu |

Regula: erorile upstream nu se strecoară niciodată ca text brut către agent. Se normalizează, se logează complet, se returnează sumarizat.

## Conținutul care intră înapoi în model

Rezultatele tool-urilor trec prin DLP înainte de a fi returnate:

- redactare de secrete detectabile (chei, tokenuri, JWT, numere de card);
- limită de dimensiune (implicit 256 KB per răspuns; peste, se trunchiază cu marcaj explicit);
- strip de instrucțiuni de tip „ignore previous instructions" din conținutul returnat de upstream (euristică, nu garanție);
- păstrarea unui `content_hash` pentru deduplicare în client.

DLP e euristic în v1 și este documentat ca atare; nu înlocuiește un scanner dedicat.
