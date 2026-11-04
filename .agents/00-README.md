# AI Gateway — specificații

**Status:** draft v0.9 — 2026-11-04
**Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async) pentru Postgres, DynamoDB pentru edge, Typer pentru CLI, Terraform pentru deployment.

**v0.9:** deploy manual prin `gh workflow run deploy.yml`: credențiale din Google Secret Manager prin OIDC, state Terraform partajat în S3 cu lock DynamoDB, imagine construită și publicată în ECR înainte de apply.
**v0.8:** edge pe DynamoDB: strat de stocare cu două implementări (SQL și DynamoDB), tabel unic cu link-uri consistente, Terraform fără VPC/NAT pentru DynamoDB. Postgres rămâne backendul self-host și opțiunea Lambda din VPC.
**v0.7:** artefacte de deployment: Docker Compose cu Postgres pentru self-host și Terraform pentru API Gateway HTTP API + Lambda + RDS Postgres.
**v0.6:** CLI minimal (`agw serve`, `agw migrate`, `agw admin recover`); toată administrarea trece prin HTTP. UI amânat.
**v0.5:** server persistent doar în self-host; serverless rulează în `request_response` cu capabilități reduse și refuzuri explicite (`409 persistent_runtime_required`), fără adaptoare de persistență. Profilurile `edge`/`self-host` devin `request_response`/`persistent`.
**v0.4:** catalog persistat cu rutare prin lookup, căutare lexicală fără `pgvector`.
**v0.3:** paginare cu cursor semnat, căutare hibridă (retrasă în v0.4), meta-tools pentru caiete mari de unelte.
**v0.2:** două profiluri de deployment (edge / self-host), OAuth pe triada `(user, agent, service)`, cereri de identitate inițiate de agent, scos proxy-ul LLM din scope.

## Ce construim

Un control plane care dă fiecărui agent o **identitate** și decide, per agent, **ce servicii, tool-uri și agenți peers poate apela**. Gateway-ul este singurul punct care vede simultan identitatea agentului, politica și credențialele upstream.

Trei lucruri pe care le face și pe care agenții nu le pot face singuri:

1. **Emite și revocă identități** — API key gestionat sau certificat mTLS emis de CA-ul gateway-ului. Agentul poate **cere** o identitate (pentru el, pentru un sub-agent sau pentru o delegare), dar nu și-o poate aproba singur.
2. **Ține credențialele serviciilor** — tokenuri OAuth, API keys, certificate upstream. Agentul primește doar un token scurt, cu `aud` pe resursa concretă.
3. **Mediază consimțământul** — OAuth are trei subiecți: **user**, **agent**, **service**. Gateway-ul generează link-ul de autorizare, îl dă agentului, iar agentul îl arată utilizatorului.

## Ce nu face

Gateway-ul **nu proxyază apeluri LLM**. Nu rutează modele, nu numără tokeni, nu ține chei de provider. Mediază exclusiv apeluri la unelte: API HTTP, MCP și alți agenți (A2A). Vezi [ADR-011](11-decisions/README.md#adr-011--gateway-ul-nu-proxyază-apeluri-llm).

Interfața grafică este **amânată**. v1 livrează API-ul HTTP și CLI-ul de proces, inclusiv break-glass-ul; UI-ul vine după ce fluxurile sunt stabile. Vezi [`12-cli/README.md`](12-cli/README.md).

## Index

| Fișier | Conținut | Status |
|---|---|---|
| [`01-vision/README.md`](01-vision/README.md) | scop, utilizatori, non-scopuri, glosar | draft |
| [`02-architecture/README.md`](02-architecture/README.md) | componente, fluxuri, reguli de caching | draft |
| [`02-architecture/stateless-deployment.md`](02-architecture/stateless-deployment.md) | stateless, Lambda vs containere, Postgres pooling | draft |
| [`02-architecture/deployment-profiles.md`](02-architecture/deployment-profiles.md) | profil persistent și request/response, capabilități, autoscale fără P2P | draft |
| [`03-domain-model/README.md`](03-domain-model/README.md) | entități, invarianți, ERD | draft |
| [`03-domain-model/schema.md`](03-domain-model/schema.md) | DDL Postgres | draft |
| [`04-identity-and-access/README.md`](04-identity-and-access/README.md) | identitate agent, roluri, matrice de permisiuni, ceiling | draft |
| [`04-identity-and-access/enrollment.md`](04-identity-and-access/enrollment.md) | bootstrap admin, enrollment token, device flow, schimb de certificat | draft |
| [`05-connections-and-oauth/README.md`](05-connections-and-oauth/README.md) | consimțământ per serviciu, vault, refresh, revocare | draft |
| [`06-policy-and-grants/README.md`](06-policy-and-grants/README.md) | ordinea de evaluare, grants, discovery, approvals | draft |
| [`06-policy-and-grants/discovery-and-search.md`](06-policy-and-grants/discovery-and-search.md) | catalog persistat, rutare, paginare, căutare lexicală | draft |
| [`07-protocols/README.md`](07-protocols/README.md) | MCP și A2A în gateway | draft |
| [`07-protocols/mcp.md`](07-protocols/mcp.md) | proxy MCP, filtrare de tool-uri, namespacing | draft |
| [`07-protocols/a2a.md`](07-protocols/a2a.md) | agent cards, delegații, propagare de identitate | draft |
| [`08-api/README.md`](08-api/README.md) | suprafața REST, erori, idempotență | draft |
| [`09-ui/README.md`](09-ui/README.md) | ecrane, editare de capabilități, caching client | amânat v1.x |
| [`10-roadmap/README.md`](10-roadmap/README.md) | faze de livrare | draft |
| [`11-decisions/README.md`](11-decisions/README.md) | ADR-uri | draft |
| [`12-cli/README.md`](12-cli/README.md) | comenzile `agw`, `serve`, bridge stdio | draft |
| [`13-ci/README.md`](13-ci/README.md) | deploy manual, OIDC, secretul de deploy, state partajat | draft |

## Decizii luate în acest draft

| # | Decizie | Motiv scurt |
|---|---|---|
| D1 | **Fără P2P, în ambele anvelope.** Un singur Postgres + N replici stateless. `request_response` și `persistent` folosesc același model. | Librăriile P2P rezolvă descoperirea de noduri; LB-ul și DB-ul fac deja asta. Autoscale-ul nu cere coordonare între noduri. Vezi [ADR-001](11-decisions/README.md#adr-001--fără-p2p-un-singur-postgres). |
| D2 | **Stateless per request.** Nicio sesiune, cache sau contor în memorie. | Permite scalare orizontală, autoscale și rulare în Lambda/Cloud Run. Vezi [ADR-002](11-decisions/README.md#adr-002--stateless-cu-stare-exclusiv-în-postgres--kms). |
| D3 | **Un singur artefact:** server FastAPI + CLI în același pachet; UI adăugat mai târziu în același container. | Un deploy, un pipeline. Vezi [ADR-003](11-decisions/README.md#adr-003--fastapi--spa-în-același-worker) și [ADR-017](11-decisions/README.md#adr-017--cli-pentru-ciclul-de-viață-http-pentru-administrare). |
| D4 | **Postgres pentru self-host, DynamoDB pentru edge**, prin același strat de stocare. | Postgres păstrează join-urile și integritatea referențială acolo unde contează; DynamoDB elimină VPC-ul și NAT-ul pe edge. Vezi [ADR-004](11-decisions/README.md#adr-004--postgresql-pentru-self-host) și [ADR-021](11-decisions/README.md#adr-021--strat-de-stocare-cu-două-backend-uri). |
| D5 | **Grants și connections sunt lucruri separate.** Grantul autorizează, conexiunea aprovizionează credențialul. | Un agent poate avea grant fără să fi autorizat încă serviciul; atunci primește `connection_required` + link. |
| D6 | **Autoritatea de a edita e plafonată de autoritatea proprie.** Un agent nu poate acorda altui agent mai mult decât are el. | Blochează escaladarea de privilegii prin agenți-editor. |
| D7 | **Fără cache pe server.** Cache doar în client (UI sau client HTTP), plus `ETag` pentru GET-uri. | Cerință explicită; costul e o interogare de politică per request. |
| D8 | **Două profiluri de deployment:** `persistent` și `request_response`, același cod, configurare diferită. | Serverless cere driver DB prin HTTP și request-uri scurte; self-host cere pooling și procese long-lived. Vezi [ADR-012](11-decisions/README.md#adr-012--două-profiluri-edge-și-self-host), amendat de D15. |
| D9 | **Fără proxy LLM.** Doar tools, MCP și A2A. | Scope explicit; scoate din discuție rutarea de modele și metering-ul de tokeni. Vezi [ADR-011](11-decisions/README.md#adr-011--gateway-ul-nu-proxyază-apeluri-llm). |
| D10 | **OAuth pe triada `(user, agent, service)`.** | Fiecare agent are propria delegare, cu propriul consimțământ. Vezi [ADR-013](11-decisions/README.md#adr-013--oauth-pe-triada-user-agent-service). |
| D11 | **Agentul poate cere o identitate, nu și-o poate aproba.** | Cererea intră în `identity_request` și e decisă de un om sau de un agent cu `identity:approve`. Vezi [ADR-014](11-decisions/README.md#adr-014--cereri-de-identitate-inițiate-de-agent). |
| D12 | **Catalog persistat, rutare prin lookup.** Nu se apelează MCP-urile pentru a găsi o rută. | `service_tool` este interogat direct în Postgres; descoperirea umple catalogul. Vezi [ADR-015](11-decisions/README.md#adr-015--catalog-persistat-și-căutare-lexicală). |
| D13 | **CLI pentru ciclul de viață, HTTP pentru administrare.** Comenzile sunt `agw serve`, `agw migrate` și `agw admin recover`. | Un singur contract public; serverul rămâne granița de încredere, iar CLI-ul nu ține credențiale. Vezi [ADR-017](11-decisions/README.md#adr-017--cli-pentru-ciclul-de-viață-http-pentru-administrare). |
| D14 | **Fără `pgvector` în v1.** Căutare lexicală + trigram, paginare cu cursor semnat. | Catalogul are zeci de mii de rânduri; embeddings ar adăuga provider, backfill și latență fără câștig clar. Vezi [ADR-015](11-decisions/README.md#adr-015--catalog-persistat-și-căutare-lexicală) și [ADR-016](11-decisions/README.md#adr-016--contract-de-paginare-cu-cursor-semnat). |
| D15 | **Server persistent doar în self-host.** Serverless rulează în `request_response`: JSON, fără sesiuni, SSE, stdio sau push. | Capabilitățile se declară per serviciu și se refuză cu `409 persistent_runtime_required`; fără adaptoare care imită persistența. Vezi [ADR-018](11-decisions/README.md#adr-018--persistent-doar-în-self-host). |
| D16 | **Fără trust-on-first-use.** Adminul se creează out-of-band; agenții se înrolează cu token one-time sau device code, iar tokenul se consumă la emiterea certificatului. | Primul apelant nu poate primi `owner`: un endpoint public ar fi câștigat de oricine găsește URL-ul. Vezi [ADR-019](11-decisions/README.md#adr-019--fără-trust-on-first-use-înrolare-cu-token-one-time). |
| D17 | **TLS terminat la platformă; cheia agentului rămâne la agent.** Certificatul serverului e ACM/ingress; certificatul agentului e semnat dintr-un CSR. | mTLS per request merge în ambele anvelope; cheia privată a serverului nu intră în proces, iar cea a agentului nu poate sta la server. Vezi [ADR-020](11-decisions/README.md#adr-020--tls-terminat-la-platformă-cheia-privată-a-agentului-rămâne-la-agent). |
| D18 | **Deploy manual, credențiale din Secret Manager, state partajat.** `gh workflow run deploy.yml`, OIDC către Google, un secret cu tot env-ul, backend S3 cu lock DynamoDB. | Un push nu atinge producția; nicio cheie în GitHub; un singur loc de rotație și un singur state pentru CI și stație. Vezi [ADR-022](11-decisions/README.md#adr-022--deploy-manual-credențiale-din-secret-manager-state-partajat). |

## Întrebări deschise

1. **Runtime serverless concret:** Lambda + API Gateway, Cloud Run cu scale-to-zero, sau Fly Machines? Cloudflare Workers iese din discuție (ADR-012). Vezi [`02-architecture/deployment-profiles.md`](02-architecture/deployment-profiles.md).
2. **IdP pentru oameni:** Keycloak self-hosted, Auth0, sau Supabase Auth?
3. **Evaluarea în request_response:** dacă instanța e departe de Postgres, politica se evaluează la origin sau se acceptă un snapshot semnat în KV? Recomandarea spec-ului: evaluare la origin, fără cache.
4. **Argument constraints** în v1 sau doar allowlist de tool-uri?
5. **Identități efemere:** acceptăm un `identity_request` cu TTL de minute pentru un task, sau doar delegări persistente?
6. **Multi-region** de la început? Dacă da, devine Aurora Global / CockroachDB, nu P2P.

## Cum citim specificațiile

Ordinea de citire pentru implementare: `01` → `02` → `12` → `03` → `04` → `06` → `05` → `07` → `08` → `10`. Profilul de deployment (`02-architecture/deployment-profiles.md`) se alege la P0, pentru că decide driverul de DB și runtime-ul.

Fiecare fișier are un antet `Status / Owns / Depends on`, ca în restul proiectelor din `~/Projects`. Când o decizie se schimbă, se actualizează ADR-ul din `11-decisions` și fișierul care o consumă.
