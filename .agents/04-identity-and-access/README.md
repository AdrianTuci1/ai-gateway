# 04 — Identitate și acces

**Status:** `[x]` model de permisiuni stabilit
**Owns:** identitatea agentului, roluri, matricea de permisiuni, plafonul de autoritate.
**Depends on:** [`../03-domain-model/README.md`](../03-domain-model/README.md), [`enrollment.md`](enrollment.md)

## Identitatea agentului

Gateway-ul emite identitatea; agentul nu și-o alege.

Înrolarea are propria specificație: primul administrator apare printr-un bootstrap out-of-band, iar agenții primesc identitatea cu un token one-time sau printr-un device code aprobat de un om. Vezi [`enrollment.md`](enrollment.md). Niciun request HTTP nu acordă rolul `owner` primului venit.

### Varianta A — API key gestionat (implicit în v1)

```
agw_live_7f3a9c2e_<32 bytes base62>
     │    │        └─ secret, afișat o singură dată
     │    └─ key id, căutat în DB fără să compare secretul
     └─ mediu
```

- Stocare: `argon2id(secret)`, plus `prefix` pentru UI.
- Verificare: lookup după key id (index), apoi comparare constant-time a hash-ului.
- Expirare implicită: 90 zile; rotație din UI sau API, cu suprapunere de 24h între chei.
- Revocare instantă: `revoked_at`; verificat la fiecare request.
- Prin API: `POST /v1/workspaces/{ws}/agents/{id}/credentials`; cheia se afișează o singură dată, apoi doar prefixul.

### Varianta B — certificat de client (mTLS)

- Agentul generează keypair + CSR, trimite CSR-ul (sau doar cheia publică) la gateway.
- Gateway semnează cu un CA intermediar dedicat, cu SAN `spiffe://{workspace_slug}/agent/{agent_id}`.
- Emiterea cere un token de înrolare one-time sau un device code aprobat; tokenul se consumă în aceeași tranzacție cu semnarea.
- CA-ul poate fi intern (implicit) sau ACM Private CA. Cheia privată a agentului rămâne la agent; serverul păstrează doar certificatul public, serialul și issuer-ul.
- Durată: 24h–30 zile. Preferință pentru Certificate short-lived + reemitere automată, ca să nu fie nevoie de CRL.
- LB-ul termină TLS și trimite certificatul verificat în header (`X-Client-Cert-Fingerprint`, `X-Client-Cert-SAN`), semnat de LB; gateway are încredere doar în header-ul venit de la LB.
- Mapare: `agent_credential.cert_fingerprint` sau `spiffe_id` → agent.

### Ce nu acceptăm

- Identitate din prompt, din query string sau din body.
- „Service account" partajat între agenți — pierzi atribuirea.
- Tokenuri de provider ținute de agent.

## Principalul uman

- Login prin IdP (OIDC). Sesiune = cookie `HttpOnly; Secure; SameSite=Lax`, semnat, cu `sid` care poate fi revocat din DB.
- `app_user.idp_subject` este cheia stabilă; emailul se poate schimba.
- Un om poate fi membru în mai multe workspace-uri, cu roluri diferite.

## Roluri

Rolurile sunt bundle-uri de permisiuni. Un rol builtin are `workspace_id = null`; unul custom aparține unui workspace.

| Rol | Pentru cine | Idee |
|---|---|---|
| `owner` | om | tot, inclusiv ștergerea workspace-ului |
| `admin` | om | tot în afară de ștergerea workspace-ului și transferul de ownership |
| `operator` | om | aprobă acces, revocă conexiuni, urmărește consumul |
| `developer` | om | creează agenți, cere acces, configurează servicii |
| `viewer` | om | citire |
| `agent:executor` | agent | doar execută ce are în grant |
| `agent:requester` | agent | descoperă catalogul și cere acces |
| `agent:editor` | agent | editează granturi în limita plafonului propriu |
| `agent:admin` | agent | administrează agenți și servicii în workspace, fără membership |

## Permisiuni

```
workspace:read            workspace:update           workspace:delete
member:read               member:invite              member:update_role        member:remove
agent:read                agent:create               agent:update              agent:delete
agent:credential_rotate
service:read              service:create             service:update            service:delete
service:discover
grant:read                grant:request              grant:write               grant:approve
connection:read           connection:authorize       connection:revoke
identity:request          identity:approve
audit:read                usage:read
policy:read               policy:write
```

Scopuri: pentru un principal de tip agent, permisiunile de citire și scriere se aplică implicit resurselor **proprii**. Accesul la resursele altor agenți cere sufixul explicit `:workspace` (ex. `grant:read:workspace`), care se acordă doar prin rol custom.

## Matricea rolurilor builtin

| Permisiune | owner | admin | operator | developer | viewer | agent:executor | agent:requester | agent:editor | agent:admin |
|---|---|---|---|---|---|---|---|---|---|
| `workspace:read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `workspace:update` | ✓ | ✓ |  |  |  |  |  |  |  |
| `workspace:delete` | ✓ |  |  |  |  |  |  |  |  |
| `member:*` | ✓ | ✓ | read | read | read |  |  |  |  |
| `agent:read` | ✓ | ✓ | ✓ | ✓ | ✓ | self | self | self+ws | ✓ |
| `agent:create` | ✓ | ✓ |  | ✓ |  |  |  |  | ✓ |
| `agent:update` | ✓ | ✓ | ✓ | ✓ |  |  |  | self | ✓ |
| `agent:delete` | ✓ | ✓ |  |  |  |  |  |  |  |
| `agent:credential_rotate` | ✓ | ✓ |  | self |  |  |  | self | ✓ |
| `service:read` | ✓ | ✓ | ✓ | ✓ | ✓ | doar în grant | ✓ | ✓ | ✓ |
| `service:create` | ✓ | ✓ |  | ✓ |  |  |  |  | ✓ |
| `service:update` | ✓ | ✓ |  | ✓ |  |  |  |  | ✓ |
| `service:delete` | ✓ | ✓ |  |  |  |  |  |  |  |
| `service:discover` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ | ✓ |
| `grant:read` | ✓ | ✓ | ✓ | ✓ | ✓ | self | self | self+ws | ✓ |
| `grant:request` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ | ✓ | ✓ |
| `grant:write` | ✓ | ✓ | ✓ |  |  |  |  | self+ws* | ✓ |
| `grant:approve` | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |
| `connection:read` | ✓ | ✓ | ✓ | ✓ | ✓ | self | self | self | ✓ |
| `connection:authorize` | ✓ | ✓ | ✓ | ✓ |  | self | self | self | ✓ |
| `connection:revoke` | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |
| `identity:request` | ✓ | ✓ | ✓ | ✓ |  |  | self | self | ✓ |
| `identity:approve` | ✓ | ✓ | ✓ |  |  |  |  |  | self* |
| `audit:read` | ✓ | ✓ | ✓ |  | ✓ |  |  |  | ✓ |
| `usage:read` | ✓ | ✓ | ✓ | ✓ | ✓ | self | self | self | ✓ |
| `policy:read` | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ |
| `policy:write` | ✓ | ✓ |  |  |  |  |  |  |  |

`*` — `agent:editor` poate scrie granturi doar dacă sunt submulțime din granturile proprii și din `ceiling`-ul țintei. `agent:admin` poate aproba identități doar dacă binding-ul cerut este submulțime din propriile granturi. Vezi mai jos.

## Cereri de identitate

O identitate are trei subiecți în OAuth: **user** (pentru cine se acționează), **agent** (cine acționează) și **service** (unde se acționează). Gateway-ul nu emite niciodată o identitate care să acopere mai mulți agenți deodată.

Un agent cu `identity:request` poate **cere**, niciodată **acorda**. Cererea intră în `identity_request` și urmează un drum separat de grant.

### Tipuri de cerere

| `kind` | Ce cere agentul | Cine aprobă | Ce rezultă |
|---|---|---|---|
| `delegation` | „lasă-mă să acționez pentru userul U pe serviciul S" | userul, prin consimțământ OAuth; opțional un aprobator | `service_connection` pe triada `(U, A, S)` |
| `agent_credential` | o cheie nouă pentru el sau pentru un sub-agent | `identity:approve` | `agent_credential` nou |
| `service_account` | o identitate de serviciu, fără user | `identity:approve` | `service_connection` cu `binding = 'workspace'` |

### Flux

```http
POST /v1/workspaces/{ws}/identity-requests
Authorization: Bearer agw_live_...

{
  "kind": "delegation",
  "agent_id": "42",
  "service_id": "b6f1...",
  "user_id": "u-17",
  "requested_scopes": ["crm.read"],
  "purpose": "answer billing questions for the user"
}
```

```json
{
  "id": "ir_9c2...",
  "status": "pending",
  "approval_required": true,
  "authorize_url": null,
  "expires_at": "2026-11-09T12:00:00Z"
}
```

După aprobare, răspunsul conține `authorize_url`, pe care agentul îl arată userului. După callback, cererea devine `fulfilled` și `fulfilled_connection_id` este populat.

### Reguli

1. **Când solicitantul este agent, aprobatorul diferă de el.** `approved_by_id != requested_by_id`, impus și în DB. Un om își poate auto-aproba propria delegare.
2. **Binding-ul cerut se intersectează cu ceiling-ul.** `requested_scopes ⊆ ceiling.services[S].max_scopes`; restul se taie, nu se acordă implicit.
3. **Userul trebuie să fie membru** al workspace-ului și să aibă acces la agent.
4. **Un agent nu poate cere o identitate pentru alt agent** decât dacă are `agent:update` pe acesta și ceiling-ul țintei permite.
5. **Cererea expiră** (implicit 7 zile) și devine `expired`; nu se reutilizează.
6. **Revocarea conexiunii** trece cererea în `revoked` dacă a fost singurul ei rezultat.
7. **Audit pe ambele capete:** `identity.request` și `identity.approve`, cu solicitantul, aprobatorul și binding-ul.

### De ce un tabel separat, nu `approval_request`

`approval_request` descrie o decizie umană simplă. `identity_request` are un ciclu de viață mai lung (aprobare → consent OAuth → fulfill), leagă trei entități și produce un artefact (conexiune sau credențial). Un audit curat cere ca cele două să fie separate.

### Identități efemere

Un agent poate cere o delegare cu `expires_at` scurt (minute), pentru un singur task. Cererea și conexiunea expiră împreună; nu se reînnoiesc automat. Rămâne o opțiune de configurare, nu comportamentul implicit.

## Plafonul de autoritate (ceiling)

Fiecare agent are un `ceiling` setat de un om la creare. El descrie maximumul de capabilități pe care le poate primi sau acorda vreodată.

```json
{
  "services": {
    "b6f1…": { "tools": ["search_tickets", "get_customer"], "max_scopes": ["read"] },
    "9a02…": { "tools": ["send_task"], "max_delegation_depth": 2 }
  },
  "identity": { "can_request": true, "max_ttl_hours": 720 },
  "budget": { "requests_per_day": 5000 }
}
```

Regula de aur: **autoritatea unui apelant nu poate depăși autoritatea proprie.**

```python
def authorize_grant_write(caller: Principal, target: Agent, service: Service, tools: set[str]):
    if caller.kind == "user":
        require(caller, "grant:write")
        assert tools <= set(service.tool_names())          # există în manifest
        assert tools <= target.ceiling.tools(service.id)   # plafonul țintei
        return
    # caller e agent
    assert "grant:write" in caller.permissions
    assert target.workspace_id == caller.workspace_id
    own = caller.effective_tools(service.id)
    assert tools <= own                                # nu dă ce nu are
    assert tools <= target.ceiling.tools(service.id)   # nici peste plafonul țintei
```

Aceleași reguli pentru: schimbarea de rol (subset de permisiuni), adăugarea de conexiuni (doar servicii pe care le are deja) și crearea de agenți noi (ceiling-ul noului agent ⊆ ceiling-ul creatorului, dacă creatorul e agent).

## Verificarea rolurilor la runtime

Un singur punct de intrare, ca să nu se împrăștie verificări:

```python
@dataclass(frozen=True)
class Principal:
    kind: Literal["user", "agent"]
    id: UUID
    workspace_id: UUID
    permissions: frozenset[str]
    ceiling: dict
```

```python
def require(p: Principal, perm: str, *, scope: Literal["self", "workspace"] = "self"):
    if perm in p.permissions:
        return
    if scope == "workspace" and f"{perm}:workspace" in p.permissions:
        return
    raise Forbidden(perm, principal=p.id)
```

Test obligatoriu: fiecare rută are un test care dovedește că un principal fără permisiune primește `403` și că unul cu permisiune trece.

## Rotația și revocarea

| Eveniment | Efect |
|---|---|
| Rotire API key | cheie nouă activă imediat, vechea expiră în 24h |
| Revocare agent | toate credențialele `revoked_at = now()`, conexiunile `revoked`, granturile `revoked` |
| Compromitere | revocare + audit cu motiv + notificare în inbox-ul ownerilor |
| Certificat expirat | `401` cu `WWW-Authenticate: mTLS realm="gateway"` |

Niciun cache de credențiale în proces: verificarea se face din DB la fiecare request. Costul e un index lookup.
