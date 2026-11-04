# 07.1 — MCP

**Status:** `[x]` specificație v1
**Owns:** gateway-ul ca MCP server și ca MCP client.
**Depends on:** [`README.md`](README.md)

## Rolul dublu

```
Agent ──MCP──► Gateway ──MCP──► MCP server upstream
        (server)       (client)
```

Gateway-ul este **MCP server** pentru agent și **MCP client** pentru upstream. Aceasta este singura formă care permite filtrarea la descoperire: agentul primește un `tools/list` deja filtrat, nu unul complet pe care să-l ignore.

## Endpoint

```
POST /mcp/{agent_slug}
Authorization: Bearer agw_live_...
Content-Type: application/json
Accept: application/json, text/event-stream
```

Transport: **streamable HTTP** (preferred). SSE legacy acceptat doar pentru upstream-uri vechi. `stdio` nu e expus clienților; este folosit doar intern, în runtime-ul de connector.

## Runtime

Răspunsul depinde de anvelopa de execuție (vezi [`../02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md)):

| Situație | persistent | request_response |
|---|---|---|
| Client cere JSON | JSON | JSON |
| Client cere SSE | SSE | `409 persistent_runtime_required` |
| Upstream cere sesiune (`Mcp-Session-Id`) | suportat | refuz la apel |
| Upstream răspunde doar SSE | suportat | refuz la apel |
| Upstream stdio | connector | indisponibil |

În modul `request_response`, `initialize` anunță explicit:

```json
{
  "capabilities": { "tools": { "listChanged": true } },
  "instructions": "Stateless runtime: JSON responses only, no sessions, no streaming."
}
```

Detecția cerințelor upstream se face la descoperire și se salvează în `upstream_service.runtime_requirements`. Un serviciu care cere persistență este refuzat cu `409`, nu adaptat.

## `initialize`

Răspunsul descrie capabilitățile **efective** ale agentului, nu ale gateway-ului:

```json
{
  "protocolVersion": "2025-06-18",
  "serverInfo": { "name": "ai-gateway", "version": "0.1.0" },
  "capabilities": {
    "tools": { "listChanged": true },
    "resources": { "subscribe": false },
    "prompts": {}
  },
  "instructions": "Tools are scoped to this agent's grants. Calls outside the grant are rejected."
}
```

Dacă agentul nu are niciun grant activ, `capabilities.tools` lipsește și `instructions` explică starea. Nu returnăm o listă goală fără explicație.

## `tools/list`

Se construiește din granturile active, la fiecare cerere:

```python
async def list_tools(ctx) -> list[Tool]:
    out = []
    for grant in await store.active_grants(ctx.agent_id):
        service = grant.service
        for tool in grant.tools:
            definition = service.tool(tool)
            out.append(Tool(
                name=f"{service.slug}__{tool}",
                description=definition.description,
                inputSchema=definition.input_schema,
                annotations={"gateway/service": service.slug},
            ))
    return out
```

### Namespacing

`{service}__{tool}`, cu `__` ca separator rezervat. Motive:

- două servicii pot avea `search` cu semantică diferită;
- allowlist-ul devine lizibil în audit;
- coliziunile sunt imposibile prin construcție;
- un nume de tool care conține deja `__` este respins la descoperire (validare la înregistrarea serviciului).

### Paginare

`tools/list` respectă paginarea din specificație:

```json
{ "jsonrpc": "2.0", "id": 3, "method": "tools/list",
  "params": { "cursor": "eyJ2Ijox...", "limit": 50 } }
```

```json
{ "jsonrpc": "2.0", "id": 3,
  "result": { "tools": [ ], "nextCursor": "eyJ2Ijox..." } }
```

Cursorul este același contract ca la REST: opac, semnat, legat de filtre. Ordinea este stabilă (`service`, `tool`), ca paginile să nu se suprapună. Un client care ignoră `nextCursor` vede doar prima pagină, de aceea limita implicită este 50.

### Limite

- Maxim 64 de tool-uri inline într-o pagină; peste, clientul paginează sau folosește meta-tools.
- Descrierile se trunchiază la 1 KB; schemele la 8 KB per tool.
- `listChanged` se emite când un grant se schimbă; fără push activ în v1, clientul reîncarcă la următorul `tools/list`.

### Meta-tools

Când agentul are peste `max_tools_inline` (implicit 64) tool-uri în grant, `tools/list` întoarce primele 64 plus trei meta-tools:

| Tool | Ce face |
|---|---|
| `gateway__search_tools` | caută în tot ce are voie; întoarce maximum 20 de descriptori cu `name`, `description`, `input_schema` |
| `gateway__describe_tool` | schema completă pentru un nume calificat |
| `gateway__list_services` | serviciile disponibile, fără tool-uri |

`gateway__search_tools` folosește căutarea lexicală din [`../06-policy-and-grants/discovery-and-search.md`](../06-policy-and-grants/discovery-and-search.md) și acceptă `cursor`, ca orice listare. Rezultatul conține numele calificat real; apelul rămâne `tools/call`, fără referințe opace.

Această abordare ține contextul agentului mic fără să ascundă capabilități: tot ce e în grant rămâne descoperibil, doar că în mai mulți pași.

## `tools/call`

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "crm__search_tickets",
    "arguments": { "query": "refund", "tenant": "acme" }
  }
}
```

Pași:

1. Parsează namespace-ul; un nume fără `__` → `-32602`.
2. `evaluate(ctx, service_id, tool, args)` — ordinea din [`../06-policy-and-grants/README.md`](../06-policy-and-grants/README.md).
3. Ia conexiunea; refresh lazy dacă e nevoie.
4. Token exchange: `aud` = endpoint-ul serviciului, `scope` = intersecția dintre scope-urile conexiunii, cele cerute de tool și cele permise de grant.
5. Apelează upstream-ul cu timeout (implicit 30 s), fără retry pe metode ne-idempotente.
6. DLP pe rezultat.
7. Audit + metering.
8. Răspuns MCP normal.

### Când lipsește conexiunea

MCP nu are un cod standard pentru „necesită autorizare". Folosim un rezultat de eroare cu `data` structurat, pe care clienții noștri îl înțeleg:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "error": {
    "code": -32001,
    "message": "connection_required",
    "data": {
      "service": "crm",
      "authorize_url": "https://gateway.example.com/v1/...",
      "expires_at": "2026-11-02T12:10:00Z"
    }
  }
}
```

Coduri proprii în spațiul `-32000..-32099`:

| Cod | Sens |
|---|---|
| `-32001` | `connection_required` |
| `-32002` | `grant_denied` |
| `-32003` | `tool_not_allowed` |
| `-32004` | `arg_rejected` |
| `-32005` | `approval_required` |
| `-32006` | `budget_exhausted` |

Codurile JSON-RPC standard rămân pentru erori de protocol.

## `resources/*` și `prompts/*`

Aceeași filozofie: listarea se filtrează pe grant.

- `resources/list` → doar resursele din `grant.resources`, cu `uri_template` expandat la URI-uri concrete când serviciul le expune.
- `resources/read` → verifică prefixul URI față de grant, apoi proxyează.
- `prompts/list` / `prompts/get` → doar prompturile serviciilor cu grant. Prompturile sunt text controlat de upstream; se tratează ca input extern, nu ca instrucțiuni de sistem.

În v1, resursele și prompturile sunt opționale (feature flag per serviciu), pentru că puține MCP servere le folosesc.

## Descoperirea manifestului

```http
POST /v1/workspaces/{ws}/services/{id}/discover
```

1. Deschide o sesiune MCP către upstream cu credențialele serviciului (nu ale agentului).
2. Cheamă `initialize` + `tools/list` + opțional `resources/list`, `prompts/list`.
3. Normalizează și calculează `definition_hash` per tool:
   `sha256(name + description + canonical_json(input_schema))`.
4. Upsert în `service_tool`: `last_seen_at = now()`.
5. Tool-urile dispărute → `last_seen_at` rămâne vechi; după 2 cicluri se marchează `removed_at`.
6. Un tool al cărui hash se schimbă → eveniment `tool.definition_changed`; dacă tool-ul e într-un grant activ, grantul trece pe `stale` și se notifică ownerii (protecție la rug-pull).
7. `upstream_service.manifest_hash` = hash agregat; se folosește pentru ETag.

Descoperirea rulează:
- la adăugarea serviciului;
- manual din UI;
- programat (job extern, zilnic) pentru serviciile marcate `auto_sync`.

## Sesiuni

MCP streamable HTTP permite un `Mcp-Session-Id`. Gateway-ul:

- acceptă sesiuni doar în runtime-ul `persistent`;
- **nu ține stare în memorie între request-uri**; scrie `mcp_session` în DB doar dacă upstream-ul cere explicit stare;
- preferă upstream-urile stateless; pentru cele stateful, folosește sesiunea ca cheie de rutare către același upstream;
- expiră sesiunile după 30 min de inactivitate;
- în `request_response`, orice upstream care cere sesiune este refuzat cu `409 persistent_runtime_required`;
- nu suportă request-uri server-initiated (sampling, elicitation) în v1 — le respinge explicit, ca să nu blocheze un worker.

## Servere `stdio`

Un MCP server `stdio` este un proces local. Nu poate rula într-un worker stateless. Disponibil **doar în runtime-ul `persistent`**; în `request_response`, înregistrarea unui serviciu `stdio` este refuzată cu `409 persistent_runtime_required`. Opțiuni:

1. **Connector dedicat** — un serviciu separat, long-lived, care expune serverele stdio ca streamable HTTP. Gateway-ul îl tratează ca `mcp_http`.
2. **Sidecar per agent** — pentru self-host, cu un container care rulează serverul și un socket Unix.

v1: doar opțiunea 1, iar `kind = 'mcp_stdio'` este marcat `requires_connector: true` și nu poate fi adăugat fără un connector înregistrat.

## Securitate

- Un tool descoperit nu înseamnă un tool permis. Descoperirea umple catalogul; grantul decide.
- `inputSchema` de la upstream este tratată ca date nevalidate; se validează cu un validator JSON Schema strict înainte de a fi trimisă mai departe.
- Rezultatele sunt tratate ca input nesigur: DLP, limită de dimensiune, fără execuție.
- Un upstream nu poate influența politica: câmpurile din rezultat care seamănă a instrucțiuni sunt raportate, nu aplicate.
