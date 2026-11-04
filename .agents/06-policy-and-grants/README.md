# 06 — Politică, granturi, descoperire

**Status:** `[x]` algoritm de evaluare stabilit
**Owns:** ordinea de evaluare, semantica granturilor, discovery, approvals, dry-run.
**Depends on:** [`../04-identity-and-access/README.md`](../04-identity-and-access/README.md)

## Ordinea de evaluare

Se execută în această ordine, la fiecare request. Primul pas care eșuează oprește fluxul și produce un cod distinct.

| # | Verificare | Eșec |
|---|---|---|
| 1 | Identitate validă, agent `active` | `401 unauthenticated` |
| 2 | Workspace activ, agent membru | `403 forbidden` |
| 3 | Limite: RPM, buget | `429 rate_limited` / `402 budget_exhausted` |
| 4 | Serviciu `active` și în workspace | `404 service_not_found` |
| 5 | Grant `active` pe `(agent, service)` | `403 grant_denied` |
| 6 | Tool în `grant.tools` | `403 tool_not_allowed` |
| 7 | Argumente conforme cu `arg_constraints` | `422 arg_rejected` |
| 8 | Conexiune `active` (dacă `auth_type != none`) | `409 connection_required` |
| 9 | Exchange token cu `aud` + scope minim | `502 upstream_auth_error` |
| 10 | Apel upstream | `502 upstream_error` |
| 11 | DLP pe rezultat | `502 response_blocked` |

Fiecare eșec produce un `audit_event` cu `decision = deny` și `reason`, plus un `trace_id`. UI-ul poate afișa motivul exact fără să expună detalii interne.

## Semantica grantului

```json
{
  "agent_id": "…",
  "service_id": "…",
  "tools": ["search_tickets", "get_customer"],
  "resources": ["file://reports/*"],
  "arg_constraints": {
    "search_tickets": { "query": { "max_length": 200 } },
    "get_customer":  { "tenant": { "equals": "${principal.tenant}" } }
  },
  "status": "active",
  "expires_at": "2026-12-31T00:00:00Z"
}
```

Reguli:

- `tools = []` înseamnă **niciun tool**, nu „toate". Nu există wildcard în grant; wildcard-ul există doar în `ceiling`, unde e administrat de om.
- Tool-urile sunt validate la scriere față de `service_tool`. Un tool care dispare din manifest trece grantul pe `stale` și blochează apelurile până la decizie umană.
- `expires_at` este opțional; expirarea produce `403 grant_expired` și un `approval_request` nou dacă politica o cere.
- Un grant `pending` nu autorizează nimic. Poate fi vizibil în UI ca „requested".

## Constrângeri pe argumente

Minimal, declarativ, cu trei primitive:

| Primitive | Exemplu |
|---|---|
| `equals` | `{"equals": "${principal.tenant}"}` |
| `enum` | `{"enum": ["read", "list"]}` |
| `pattern` | `{"pattern": "^[A-Z]{2}-\\d{4}$"}` |
| `max_length` | `{"max_length": 500}` |
| `path_prefix` | `{"path_prefix": "/reports/"}` |

Se aplică pe valori scalare sau pe elemente de listă, nu pe obiecte imbricate în v1.

```python
def check_args(tool: str, args: dict, constraints: dict) -> None:
    for field, rule in constraints.get(tool, {}).items():
        value = args.get(field)
        if "equals" in rule and value != resolve(rule["equals"]):
            raise ArgRejected(tool, field, "equals")
        if "enum" in rule and value not in rule["enum"]:
            raise ArgRejected(tool, field, "enum")
        if "pattern" in rule and not re.fullmatch(rule["pattern"], str(value or "")):
            raise ArgRejected(tool, field, "pattern")
        if "max_length" in rule and len(str(value or "")) > rule["max_length"]:
            raise ArgRejected(tool, field, "max_length")
```

Constrângerile sunt *apărare în adâncime*. Un tool care permite SQL arbitrar trebuie limitat la nivel de credențial (user read-only în DB), nu doar prin regex.

## Descoperire (discovery)

Agentul cu `service:discover` poate interoga catalogul. Răspunsul conține **doar metadata** și doar ce e vizibil pentru el. Paginarea și căutarea lexicală au contract propriu în [`discovery-and-search.md`](discovery-and-search.md).

```http
GET /v1/catalog?q=invoice&kind=mcp_http&limit=20&cursor=...
```

```json
{
  "items": [
    {
      "service_id": "b6f1...",
      "name": "crm",
      "kind": "mcp_http",
      "description": "Customer records",
      "tools": [
        { "name": "list_invoices", "description": "…", "input_schema": { } }
      ],
      "granted": false,
      "requires_approval": true
    }
  ],
  "next_cursor": null
}
```

Reguli de filtrare:

- Doar servicii din workspace-ul apelantului.
- Doar servicii `active`.
- `input_schema` se trunchiază la un număr de caractere configurabil (implicit 4 KB per tool, 64 KB per răspuns).
- Un serviciu poate fi marcat `discoverable: false` de admin; atunci apare doar pentru cei cu grant deja.
- Descoperirea nu returnează niciodată endpoint-uri interne, credențiale sau `auth_config`.
- Rezultatele sunt paginate cu cursor; nu există `offset` și nu se promite un total. Vezi [`discovery-and-search.md`](discovery-and-search.md#contractul-de-paginare).

## Extinderea accesului

Trei căi, în funcție de cine cere și ce permisiuni are:

### A. Om cu `grant:write`

Scrie direct. Validare: tool-uri existente, ceiling-ul țintei, scope-uri permise.

### B. Agent cu `grant:write` (rol `agent:editor`)

Scrie direct, dar plafonat:

```
requested ⊆ caller.effective_tools(service)
requested ⊆ target.ceiling.tools(service)
```

Dacă cererea depășește plafonul, se transformă automat în `approval_request` în loc să fie refuzată. Astfel agentul poate cere, fără să poată lua.

### C. Agent cu `grant:request` (rol `agent:requester`)

Creează `approval_request`. Nu are efect până la decizie.

```http
POST /v1/workspaces/{ws}/agents/{agent_id}/grants/{service_id}/request
{ "tools": ["search_tickets"], "justification": "Need to answer billing questions" }
```

Răspuns: `202 Accepted` cu `approval_id` și `status: pending`.

### D. Agent cu `identity:request`

Cere o identitate (delegare, credențial propriu sau service account). Nu primește acces prin asta; primește un `identity_request` care trebuie aprobat de alt principal și, pentru delegări, confirmat de user prin OAuth.

Diferența față de A–C: un grant lărgește *ce* poate face agentul; o identitate schimbă *pentru cine* și *cu ce credențial* o face. Ambele sunt necesare pentru un apel. Detalii în [`../04-identity-and-access/README.md`](../04-identity-and-access/README.md#cereri-de-identitate).

## Aprobări

```http
GET  /v1/workspaces/{ws}/approvals?status=pending
POST /v1/workspaces/{ws}/approvals/{id}/approve
POST /v1/workspaces/{ws}/approvals/{id}/deny   { "note": "scope too broad" }
```

Reguli:

- Un om cu `grant:approve` poate aproba orice în workspace, în limita rolului propriu.
- Un agent cu `grant:approve` poate aproba doar cereri submulțime din propriile granturi (aceeași regulă de plafon).
- Auto-aprobarea este permisă doar când cererea e deja în `ceiling` **și** politica serviciului are `auto_approve: true`. Implicit: cererile de la agenți ajung la un om.
- Expirare implicită: 7 zile → `expired`, cu notificare.
- Decizia e auditată cu `actor`, `note` și `subject` complet, ca să poată fi rejucată.

### Cine e notificat

- `owner` și `admin` ai workspace-ului, prin `GET /v1/workspaces/{ws}/approvals`.
- Webhook configurabil per workspace (`approval.created`).
- Email opțional, prin provider configurat.

## Dry-run

Înainte de a salva o politică, UI-ul poate întreba „ce s-ar întâmpla?".

```http
POST /v1/workspaces/{ws}/policy/simulate
{
  "agent_id": "…",
  "service_id": "…",
  "tool": "delete_invoice",
  "args": { "id": "INV-2026-001" }
}
```

```json
{
  "decision": "deny",
  "step": 6,
  "reason": "tool_not_allowed",
  "grant_tools": ["search_tickets", "get_customer"],
  "suggestion": "Add 'delete_invoice' to the grant, or request approval."
}
```

Simularea folosește exact același evaluator, fără efecte secundare (fără exchange, fără apel upstream). Un test de consistență garantează că simularea și execuția dau același rezultat pentru același input.

## Versionarea politicii

- Fiecare grant are `updated_at` și un rând de audit cu diff-ul.
- `GET /v1/workspaces/{ws}/agents/{id}/grants/{service}/history` întoarce lanțul de modificări.
- Rollback = scrierea unei versiuni anterioare ca versiune nouă (append-only).
- Nu există „apply all" peste workspace în v1; schimbările sunt per agent, ca să rămână explicabile.

## Evaluatorul, într-un singur loc

```python
@dataclass
class Decision:
    allow: bool
    step: int
    reason: str | None = None
    grant: AgentGrant | None = None
    connection: ServiceConnection | None = None

async def evaluate(ctx: RequestContext, service_id: UUID, tool: str, args: dict) -> Decision:
    if ctx.principal.kind == "agent" and ctx.agent.status != "active":
        return Decision(False, 1, "agent_inactive")
    rate = await limits.check(ctx)
    if not rate.ok:
        return Decision(False, 3, rate.reason)
    grant = await store.get_grant(ctx.agent_id, service_id)
    if grant is None or grant.status != "active":
        return Decision(False, 5, "grant_denied")
    if tool not in grant.tools:
        return Decision(False, 6, "tool_not_allowed", grant)
    check_args(tool, args, grant.arg_constraints)          # raises ArgRejected
    conn = await store.get_connection(ctx, service_id)
    if ctx.service.auth_type != "none" and (conn is None or conn.status != "active"):
        return Decision(False, 8, "connection_required", grant, conn)
    return Decision(True, 10, None, grant, conn)
```

Adaptoarele cheamă `evaluate` și nu au voie să decidă singure. Un test de arhitectură verifică faptul că `app/adapters/**` nu importă `app/db` direct pentru citirea de granturi.

## Anti-pattern-uri interzise

- Allowlist în promptul de sistem.
- Verificare de permisiune în handler-ul de rută, duplicată.
- „Admin bypass" care sare peste evaluator.
- Cache de decizie între request-uri.
- Grant cu `tools: ["*"]` creat din UI.
- Încrederea în `annotations.readOnlyHint` ca autorizare.
