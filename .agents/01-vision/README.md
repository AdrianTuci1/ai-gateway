# 01 — Viziune și scop

**Status:** `[x]` direcție stabilită
**Owns:** scop, utilizatori, non-scopuri, glosar. Fără cod.
**Depends on:** [`../00-README.md`](../00-README.md)

## Problema

Agenții au nevoie de acces la servicii externe (MCP servers, API-uri HTTP, alți agenți). Fără un punct central, fiecare agent primește credențiale late, le ține în context, iar cine a configurat agentul nu poate răspunde la întrebări simple:

- Ce servicii poate apela agentul X chiar acum?
- Cu ce identitate a apelat tool-ul `delete_invoice` la 14:32?
- Cine a acordat accesul și când expiră?
- Ce se întâmplă când un token OAuth expiră la 3 noaptea?

Gateway-ul răspunde la aceste întrebări pentru că este singurul loc care vede identitatea, politica și credențialul în același request.

## Utilizatori

| Actor | Ce face |
|---|---|
| **Dezvoltator de agent** | Creează agentul prin API-ul HTTP, îi dă identitate, îi acordă servicii și tool-uri, testează cu un client HTTP. |
| **Operator / admin de workspace** | Aprobă cereri de acces, revocă conexiuni, urmărește consumul, rulează `agw serve`. |
| **Utilizator final** | Primește link-ul de autorizare OAuth și îl aprobă o singură dată per serviciu. |
| **Agent** | Execută tool-uri; cu rol extins, poate descoperi servicii și poate edita propria configurație sau a altor agenți. |
| **Agent peer (A2A)** | Cheamă alt agent prin gateway, cu identitatea utilizatorului propagată. |

## Ce face gateway-ul

1. **Identitate.** Emite API keys și certificate de client pentru agenți. Fiecare request este atribuit unui agent concret.
2. **Catalog.** Ține lista serviciilor și a tool-urilor descoperite, cu hash pe definiție.
3. **Politică.** Decide per request: agentul are grant pe serviciul ăsta, pe tool-ul ăsta, cu argumentele astea?
4. **Broker de credențiale.** Ține tokenurile OAuth, le reîmprospătează, le schimbă pe un token cu `aud` pe resursă și TTL scurt.
5. **Consimțământ.** Generează link-ul de autorizare, îl livrează agentului, primește callback-ul, salvează tokenul.
6. **Audit și consum.** Fiecare decizie și fiecare apel ajung într-un log imutabil, cu cost și `trace_id`.
7. **Adaptoare de protocol.** MCP (HTTP și stdio prin connector), A2A, HTTP/OpenAPI.
8. **CLI.** `agw serve` pornește serverul, `agw migrate` pregătește schema, iar `agw admin recover` restaurează un administrator; administrarea trece prin HTTP.

## Model mental: IAM

Serverul se comportă ca un IAM pentru agenți. Fiecare noțiune are un echivalent:

| AWS IAM | Gateway | Unde |
|---|---|---|
| Account | Workspace | `workspace` |
| IAM user / role | Agent | `agent` |
| Access key | Cheie de agent | `agent_credential` |
| Identity policy | Grant | `agent_grant` |
| Permissions boundary | Plafon | `agent.ceiling` |
| Rol cu mai multe politici | Agent cu mai multe granturi | `agent_grant[]` |
| Resource policy | Vizibilitate serviciu | `upstream_service.discoverable` |
| Secrets Manager | Conexiune către serviciu | `service_connection` |
| AssumeRole | Delegare | `identity_request` |
| CloudTrail | Audit | `audit_event` |

Diferența față de IAM: resursa are propria autentificare (OAuth, API key, mTLS), iar gateway-ul ține credentialul în locul agentului.

## Principii

1. **Deny by default.** Orice tool care nu e explicit în grant este refuzat. Promptul de sistem este sugestie.
2. **Credențialele nu intră în contextul modelului.** Gateway-ul le injectează în request-ul upstream; agentul nu le vede niciodată.
3. **Autoritatea se plafonează.** Un agent-editor nu poate acorda mai mult decât are el, iar un agent nu poate depăși `ceiling`-ul setat de om.
4. **Politica e date, nu cod.** Se versionneză, se testează cu dry-run, se aplică fără redeploy.
5. **Fail closed.** Dacă politică sau vault-ul nu răspund, request-ul este refuzat, nu trecut.
6. **Fiecare scriere lasă o urmă.** Audit-ul se scrie în aceeași tranzacție cu mutarea.
7. **CLI și server în același binar.** UI-ul vine după ce fluxurile sunt stabile.
8. **Trei subiecți în OAuth.** Fiecare delegare leagă un **user**, un **agent** și un **serviciu**. Nu există token „de platformă" partajat între agenți.
9. **Agentul cere, omul aprobă.** Un agent poate iniția o cerere de identitate; aprobarea și consimțământul rămân la un principal cu autoritate.
10. **Catalogul e index, nu cache.** Rutarea se face prin lookup în Postgres; descoperirea umple catalogul, nu request-ul.

## Non-scopuri (v1)

- **Proxy LLM.** Gateway-ul nu rutează modele, nu ține chei de provider și nu numără tokeni. Mediază doar unelte: API HTTP, MCP, A2A. Vezi [ADR-011](../11-decisions/README.md#adr-011--gateway-ul-nu-proxyază-apeluri-llm).
- **Interfață grafică în v1.** Amânată după stabilizarea API-ului. Vezi [`../12-cli/README.md`](../12-cli/README.md).
- **Runtime de agent.** Gateway-ul nu planifică, nu ține memorie conversațională, nu orchestrează pași. Doar mediază apeluri.
- **Căutare semantică / vector store.** v1 folosește căutare lexicală în Postgres. Un semnal vectorial poate fi adăugat ulterior, în spatele aceleiași interfețe.
- **Facturare.** Doar metering și bugete; export către finance.
- **Editor de prompturi.** Promptul aparține agentului.
- **Multi-region active-active.** Un singur regiune în v1; vezi [ADR-001](../11-decisions/README.md#adr-001--fără-p2p-un-singur-postgres).
- **Server-side caching.** Interzis prin design; vezi D7 în [`00-README.md`](../00-README.md).
- **Paritate de streaming în serverless.** Streaming-ul MCP, sesiunile, stdio și push-ul A2A există doar în profilul `persistent`. În `request_response` sunt refuzate explicit, fără adaptoare. Vezi [ADR-018](../11-decisions/README.md#adr-018--persistent-doar-în-self-host).

## Glosar

| Termen | Sens |
|---|---|
| **Agent** | Principal cu identitate proprie, care cheamă servicii prin gateway. |
| **Serviciu** | Resursă upstream: MCP server, API HTTP, agent A2A, endpoint de model. |
| **Tool** | Operație expusă de un serviciu, cu schemă de input. |
| **Grant** | Permisiunea `(agent, serviciu, tool-uri, constrângeri)`. |
| **Conexiune (connection)** | Credențialul efectiv pentru un serviciu, legat de un utilizator și opțional de un agent. |
| **Ceiling** | Plafonul maxim de capabilități al unui agent; niciun grant nu poate depăși ceiling-ul. |
| **Consent link** | URL-ul de autorizare OAuth generat de gateway pentru un serviciu. |
| **Discovery** | Interogarea catalogului pentru servicii/tool-uri vizibile apelantului. |
| **Approval** | Cerere de acces în așteptare, decisă de un om sau de un agent cu `grant:approve`. |
| **Workspace** | Granița de tenancy: agenți, servicii, roluri, bugete. |

## Criterii de succes

- Un agent nou primește identitate și primul grant în sub 2 minute, din UI.
- Un tool call fără grant este refuzat cu cod și motiv, fără să ajungă la upstream.
- Un token OAuth expirat produce un link nou, fără intervenție manuală în DB.
- Fiecare apel are `trace_id`, agent, tool, decizie și cost în audit.
- Adăugarea unui serviciu MCP nou cere doar configurare, fără cod.
