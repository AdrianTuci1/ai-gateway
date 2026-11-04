# 07.2 — A2A (Agent2Agent)

**Status:** `[~]` proiectat, implementare în v2
**Owns:** descoperirea agenților peers, delegația, propagarea identității.
**Depends on:** [`README.md`](README.md), [`../05-connections-and-oauth/README.md`](../05-connections-and-oauth/README.md)

## Răspunsul la întrebarea „se face la fel?"

**Nu în totalitate.** Tiparul de identitate este similar — agentul are o identitate, gateway-ul mediază, tokenurile sunt scurte. Diferența este unitatea de autorizare și ce se propagă mai departe.

| | MCP | A2A |
|---|---|---|
| Unitate de autorizare | tool individual | agent + skill + scopul task-ului |
| Descoperire | `tools/list` de la server | agent card, la un path well-known |
| Stare | sesiune scurtă | task cu ciclu de viață (poate dura ore) |
| Identitate propagată | doar a apelantului | a utilizatorului final, prin lanțul de delegații |
| Riscul principal | tool prea puternic | confused deputy și bucle de delegație |
| Maturitate gateway | ecosistem larg | puține produse, specificație în mișcare |

## Ce este un agent card

Document JSON servit de agentul remote, care descrie identitatea, capabilitățile și modul de autentificare:

```json
{
  "name": "reports-agent",
  "description": "Generates financial reports",
  "url": "https://reports.example.com/a2a",
  "version": "1.2.0",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "skills": [
    { "id": "monthly_report", "name": "Monthly report",
      "description": "…", "inputModes": ["text"], "outputModes": ["text", "file"] }
  ],
  "securitySchemes": {
    "oauth": {
      "type": "oauth2",
      "flows": { "clientCredentials": {
        "tokenUrl": "https://auth.example.com/token",
        "scopes": { "agent:invoke": "Invoke the agent" }
      } }
    },
    "mtls": { "type": "mutualTLS" }
  },
  "security": [{ "oauth": ["agent:invoke"] }]
}
```

Gateway-ul îl tratează ca **date nesigure**:
- fetch doar pe HTTPS, cu timeout și limită de dimensiune (256 KB);
- validare de schemă;
- `securitySchemes` se afișează admin-ului la înregistrare, nu se aplică automat;
- `card_hash` se recalculează periodic; o schimbare majoră (URL, securitySchemes) cere re-aprobare umană.

## Rolurile gateway-ului

### 1. Registry

`upstream_service.kind = 'a2a'` are `endpoint = card URL`. La înregistrare:

1. fetch card, validare, salvare `agent_card` + `card_hash`;
2. mapare `skills` → `service_tool` (fiecare skill devine un tool apelabil);
3. `auth_type` derivat din `securitySchemes` primul suportat (`oauth2` > `mtls` > `apiKey`);
4. admin confirmă scope-urile și modul de consimțământ.

### 2. Broker de identitate

Aici e partea care nu are echivalent în MCP.

Un apel A2A are trei identități implicate:

```
user U  ──delegates──►  agent A  ──calls──►  agent B
   sub = U                act = A            vede: sub=U, act=A
```

Gateway-ul emite un token pentru apelul către B, cu:
- `sub` = utilizatorul final (`app_user.id`);
- `act` = agentul apelant (`agent.id`);
- `aud` = URL-ul agentului B;
- `scope` = skill-urile permise;
- TTL 5 minute.

Dacă B acceptă doar propriul IdP (cazul frecvent), gateway-ul face **client credentials** către IdP-ul lui B și trimite identitatea delegată în extensia de mesaj A2A (`metadata.act`, `metadata.sub`), semnată. B poate verifica semnătura dacă o suportă; dacă nu, primește doar identitatea agentului A, iar propagarea utilizatorului se pierde. Acest lucru se documentează explicit în UI la înregistrarea serviciului.

### 3. Punct de aplicare a politicii

```json
{
  "agent_id": "A",
  "service_id": "B",
  "tools": ["monthly_report"],
  "arg_constraints": { "monthly_report": { "period": { "pattern": "^\\d{4}-(0[1-9]|1[0-2])$" } } },
  "max_delegation_depth": 2
}
```

Aceleași primitive ca la MCP. Diferențe:
- `max_delegation_depth` se scade la fiecare hop;
- bugetul rămas se propagă în `metadata.budget`;
- un task care depășește adâncimea este refuzat cu `403 delegation_depth_exceeded`.

### 4. Tracker de task-uri

A2A are un ciclu de viață: `submitted → working → input-required → completed | failed | canceled`. Gateway-ul ține `a2a_task` cu `remote_task_id`, ca `tasks/get` și `tasks/cancel` să funcționeze stateless.

## Runtime

A2A are două regimuri, iar gateway-ul le tratează diferit:

| Metodă | persistent | request_response |
|---|---|---|
| `message/send` | da | da |
| `message/stream` | da | `409 persistent_runtime_required` |
| push notifications (webhook) | da | nu |
| `tasks/get`, `tasks/cancel` | da | da |

În `request_response`, apelurile sunt sincrone: gateway-ul așteaptă răspunsul final și îl întoarce ca tool result. Un task care rămâne `working` după timeout este raportat ca `task_pending`, cu `task_id` pentru `tasks/get`.

## Cum expunem A2A în v1

**Variantă simplă, recomandată pentru început:** fiecare skill al unui agent remote devine un tool apelabil prin MCP.

```
crm__search_tickets          (MCP upstream)
reports-agent__monthly_report (A2A upstream, expus ca tool)
```

Agentul apelant folosește același `tools/call`; gateway-ul traduce în `message/send` A2A. Beneficii:
- un singur mecanism de grant și audit;
- un singur endpoint MCP pentru agent;
- fără cod nou în clientul de agent.

Limite: fără streaming de task-uri, fără `input-required` interactiv. Pentru v1 sunt acceptabile.

**Variantă nativă (v2):** `/v1/a2a/{agent_slug}` care expune gateway-ul ca agent A2A complet, cu card propriu generat din granturi. Utilă când alți agenți din afara platformei vor să cheme agenții noștri.

## Fluxul unui apel (v1)

```
1. Agent A postează tools/call "reports-agent__monthly_report"
2. evaluate(): grant pe service B, skill monthly_report, argumente
3. conexiunea către B: OAuth client credentials (per workspace) sau token delegat
4. gateway emite token: sub=U, act=A, aud=B, scope=monthly_report, ttl=5m
5. POST {B.url}/message/send  { message, metadata: { sub, act, trace_id, depth: 1, budget } }
6. B răspunde cu task (completed sau input-required)
7. dacă e input-required: gateway întoarce tool result cu `status: input-required` și un `task_id`
8. audit: agent A, service B, skill, sub U, depth, cost
```

## Anti-pattern-uri

1. **Token passthrough.** Tokenul primit de la A nu se trimite mai departe la B. Se face exchange cu `aud = B`.
2. **Identitate de service account pentru toți utilizatorii.** Distruge auditul și permite acces la datele altui user.
3. **Delegație fără limită de adâncime.** A→B→C→A produce buclă și cost exploziv.
4. **Încredere în `agent card` fără validare.** Cardul e controlat de peer.
5. **Auto-descoperire nelimitată.** Un agent nu poate adăuga singur un peer; adăugarea cere `service:create` sau aprobare.

## Detecția buclelor

- `trace_id` se propagă; un peer care returnează un `trace_id` deja văzut în lanț este respins.
- `depth` crește la fiecare hop; peste `max_delegation_depth` → refuz.
- Perechea `(agent, service, skill, hash(args))` se ține într-un set per `trace_id`, cu TTL de 10 min, în `a2a_task`.

## Open questions

1. Acceptăm agent cards semnate de terți, cu ce trust anchor?
2. Suportăm push notifications (webhook) în v1 sau doar polling pe `tasks/get`?
3. Cine e autoritatea pentru `sub` când apelul pornește dintr-un cron, fără utilizator? Propunere: un `service principal` sintetic, marcat în audit ca `actor_type=system`.
4. Cum tratăm un peer care nu acceptă decât propria identitate: îl marcăm `degraded_identity` în UI și cerem confirmare explicită la înregistrare.
