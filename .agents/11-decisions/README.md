# 11 — Decizii (ADR)

**Status:** `[x]` decizii în vigoare
**Owns:** contextul și consecințele deciziilor structurale.
**Depends on:** toate

Format: context → decizie → consecințe. O decizie se schimbă printr-un ADR nou, nu prin editarea celui vechi.

---

## ADR-001 — Fără P2P, un singur Postgres

**Context.** Întrebarea era dacă avem nevoie de o librărie Python de P2P ca să scalăm. În același timp, candidatul la stocare era „o singură bază de date". Cerința a venit în două forme: un profil **edge**, unde P2P nu e posibil, și un profil **self-host**, unde există autoscale — dar și acolo autoscale-ul se poate face fără P2P.

**Decizie.** Fără P2P în ambele profiluri. Un singur Postgres ca sursă de adevăr, N replici stateless în spatele unui load balancer. Autoscale-ul se bazează pe metrici externe (RPS, CPU, latență) și pe replici identice, nu pe coordonare între noduri.

**De ce.**
- Librăriile P2P (`py-libp2p`, gossip, CRDT-uri) rezolvă descoperirea de noduri și propagarea de mesaje între noduri care nu se cunosc. Load balancer-ul știe deja unde e fiecare replică, iar baza de date oferă coordonare tranzacțională.
- Starea gateway-ului este mică și relațională: zeci de mii de rânduri, nu miliarde de evenimente. Un join rezolvă în 2 ms ce un sistem P2P ar rezolva cu consistență eventuală.
- Consistența contează: o revocare trebuie văzută de toate replicile imediat. Gossip-ul aduce fereastră de inconsistență, exact acolo unde nu-ți permiți.

**Ce folosim în loc.** Pentru fan-out de evenimente (revocări, invalidare), `LISTEN/NOTIFY` din Postgres sau Redis pub/sub dacă apare nevoia. Ambele sunt un bus, nu un protocol P2P.

**Când s-ar schimba.** Multi-region active-active. Atunci problema nu e transportul, ci baza de date: Aurora Global, CockroachDB sau partiționare pe regiune. P2P tot nu ajută.

**Consecințe.** Un singur punct de adevăr (bun pentru audit, risc pentru disponibilitate). Necesită backup, PITR, replica de citire. Latența depinde de distanța până la DB.

---

## ADR-002 — Stateless, cu stare exclusiv în Postgres + KMS

**Context.** Dorința de a rula în Lambda/Workers și de a scala orizontal.

**Decizie.** Nicio stare mutabilă în proces: fără sesiuni în memorie, fără cache de politică, fără contoare locale, fără job-uri de fundal. Tot ce e mutabil ajunge în Postgres; secretele în vault criptat cu KMS.

**Consecințe.**
- O interogare de politică și o decriptare per request. Acceptat.
- Refresh-ul de token devine lazy, în request. Acceptat.
- Rate limiting prin DB. La scară mare, Redis.
- Singura excepție: cache-ul intern al SDK-ului KMS pentru data keys (5 min).
- Streaming-ul rămâne posibil pe containere, nu pe Lambda.

---

## ADR-003 — FastAPI + SPA în același worker

**Context.** Cerința: „interfata web cât și serverul backend FastAPI să stea în același worker".

**Decizie.** Un singur artefact de deploy. Build-ul SPA se copiază în imagine; FastAPI servește `/assets` din `StaticFiles` și face fallback la `index.html` pentru rutele SPA.

**De ce.** Fără CORS, fără al doilea deploy, cookie same-site, un singur pipeline și un singur loc de observabilitate.

**Consecințe.**
- Orice schimbare de UI redeployează și API-ul. Assets statice cu hash în nume și `immutable`. Cold start-ul include importul aplicației, nu și build-ul UI.
- **v0.4:** UI-ul este amânat; containerul servește doar API-ul până la faza UI. Montarea statică rămâne proiectată, dar nu se construiește.

**Lambda.** Funcționează cu `Mangum`, dar UI-ul static se servește mai bine din CDN în fața Lambda. Pentru Cloud Run / containere, montarea directă e suficientă.

**Cloudflare Workers.** Respins: runtime-ul Python (Pyodide) nu suportă FastAPI + drivere DB async în mod fiabil.

---

## ADR-004 — PostgreSQL pentru self-host

**Context.** Candidaturi: Postgres, MySQL, DynamoDB. Inițial s-a ales un singur
backend pentru toate profilurile.

**Decizie.** Postgres rămâne backendul self-host și al variantei Lambda din VPC.
Edge-ul folosește DynamoDB, conform [ADR-021](#adr-021--strat-de-stocare-cu-două-backend-uri).

**De ce.**
- Evaluarea de politică e un join pe `agent_grant` × `upstream_service` × `service_connection`. În DynamoDB ar deveni 3 citiri sau o denormalizare greu de întreținut.
- Integritatea referențială (grant către serviciu, conexiune către agent) previne stări imposibile.
- `jsonb` acoperă `arg_constraints`, `input_schema`, `agent_card` fără scheme separate.
- Tranzacții pentru „scrie grant + scrie audit" în același commit.
- Ecosistem Python matur: asyncpg, SQLAlchemy 2, Alembic.

**MySQL** ar fi funcționat, dar fără `jsonb` indexabil la fel de bine și cu mai puțină experiență în stack-ul curent.

**DynamoDB** a fost respins pentru self-host: join-urile de politică și
tranzacțiile multi-entitate sunt naturale în SQL. Pe edge, unde volumul de
administrare e mic și nu există VPC, constrângerile se schimbă; vezi ADR-021.

**Consecințe.** Nevoie de pooling atent în Lambda. Migrațiile rulării ca job separat. Partiționare pentru audit.

---

## ADR-021 — Strat de stocare cu două backend-uri

**Context.** Edge-ul rulează pe Lambda. Un deployment cu Postgres cere VPC,
subnet-uri private, NAT Gateway și RDS, adică un cost fix și o suprafață
operațională mare pentru un control plane cu trafic redus. DynamoDB elimină
aceste componente, dar nu suportă join-uri și cere alt model de acces.

**Decizie.** Interfața `Store` mediază tot accesul la date. Are două
implementări:

- `SqlStore` păstrează interogările SQLAlchemy existente pentru Postgres și
  SQLite.
- `DynamoStore` folosește un tabel unic cu `pk`/`sk`, colecții de itemi pentru
  entitățile copil (credențiale și granturi sub agent, unelte sub serviciu) și
  link-uri `LOOKUP#...` pentru slug, email, prefix și coduri de dispozitiv.
  Citirile folosesc `ConsistentRead`, deci nu depind de replicarea GSI.

Rutele HTTP primesc `Store` prin dependență, nu o sesiune. Scrierile trec prin
metode explicite (`save_agent`, `save_grant`, `consume_enrollment_token`).
Unicitatea se impune cu scrieri condiționate și `TransactWriteItems`. Auditul
stă sub `AUDIT#<workspace_id>` cu cheie de sortare temporală. TTL pe
`expires_at_epoch` curăță tokenurile, codurile și granturile expirate.

**Consecințe.**
- Fiecare operație nouă are nevoie de implementare în ambele backend-uri.
- Pe DynamoDB nu există interogări ad-hoc SQL; diagnosticul se face prin API și
  prin comenzile DynamoDB.
- `agw admin recover` rămâne doar pe backend SQL. Pe DynamoDB, recuperarea
  trece prin roluri de operator și HTTP.
- Testele rulează aceleași fluxuri API pe SQLite și pe DynamoDB (moto).

---

## ADR-005 — Granturi și conexiuni separate

**Context.** Un agent poate avea acces configurat înainte ca utilizatorul să fi autorizat serviciul.

**Decizie.** `agent_grant` autorizează; `service_connection` aprovizionează credențialul. Sunt tabele independente.

**Consecințe.**
- Starea `connection_required` este normală, nu o eroare de configurare.
- Linkul de autorizare poate fi emis oricând, fără să atingă grantul.
- Revocarea credențialului nu șterge configurația.
- UI-ul trebuie să arate ambele dimensiuni separat.

---

## ADR-006 — Plafonul de autoritate (ceiling)

**Context.** Un agent cu permisiune de editare a tool-urilor poate, prin definiție, să-și lărgească accesul. Fără o limită, rolul de editor este echivalent cu escaladare de privilegii.

**Decizie.** Fiecare agent are un `ceiling` setat de un om. Orice scriere de grant sau de rol făcută de un agent este validată împotriva a două mulțimi: propriile granturi efective și ceiling-ul țintei.

**Consecințe.**
- `agent:editor` este util și sigur în același timp.
- Cererile peste plafon nu sunt refuzate, ci transformate în aprobări.
- Test obligatoriu în CI: un agent nu poate acorda un tool pe care nu îl are.

---

## ADR-007 — Descoperirea returnează doar metadata

**Context.** Un agent cu `service:discover` ar putea, altfel, să vadă tot catalogul, inclusiv endpoint-uri interne și configurații.

**Decizie.** `GET /v1/catalog` returnează nume, descriere, schemă de tool și starea grantului. Fără endpoint-uri, fără `auth_config`, fără credențiale.

**Consecințe.** Agentul poate decide ce să ceară, fără să afle topologia internă. Serviciile pot fi ascunse explicit (`discoverable: false`).

---

## ADR-008 — Tokenuri upstream doar pe server, niciodată în context

**Context.** Cea mai frecventă greșeală într-un gateway este să lași tokenul să circule.

**Decizie.** Agentul nu vede niciodată un token upstream. Gateway-ul îl ține criptat, îl reîmprospătează și îl injectează în request-ul către serviciu. Pentru A2A, tokenul primit nu se trimite mai departe: se face exchange cu `aud` pe peer.

**Consecințe.**
- Compromiterea unui agent nu expune credențiale de provider.
- Fiecare apel face o decriptare; costul e acceptat.
- Un test canary verifică absența tokenurilor în log-uri, audit și `repr`.

---

## ADR-009 — Fără cache pe server

**Context.** Cerință explicită: cache pe client, nimic pe server.

**Decizie.** Nicio memoizare de politică, nicio cache de token exchange, niciun cache de răspuns API. Doar `ETag` calculat la cerere pentru GET-uri de catalog.

**Consecințe.**
- Corectitudine mai bună: o revocare e vizibilă imediat.
- Latență mai mare cu 5–10 ms per request.
- La scară mare, un read replica sau un cache explicit ar putea reveni ca decizie separată, cu invalidare pe eveniment.

---

## ADR-010 — A2A expus ca tool în v1

**Context.** Implementarea completă a protocolului A2A (streaming, task-uri, push) e costisitoare.

**Decizie.** În v1, fiecare skill al unui agent remote devine un tool apelabil prin MCP. Gateway-ul traduce `tools/call` în `message/send`. Endpoint-ul A2A nativ apare în v2.

**Consecințe.**
- Un singur mecanism de grant, audit și UI.
- Fără streaming de task-uri și fără `input-required` interactiv în v1.
- Adaptorul izolat permite adăugarea endpoint-ului nativ fără rescrierea politicii.

---

## ADR-011 — Gateway-ul nu proxyază apeluri LLM

**Context.** Scope-ul inițial putea include un endpoint OpenAI-compatible, cu rutare de modele, fallback și metering de tokeni.

**Decizie.** Gateway-ul mediază exclusiv apeluri la unelte: API HTTP, MCP și agenți A2A. Nu ține chei de provider, nu rutează modele, nu numără tokeni.

**De ce.**
- Suprafața de atac și de cost se concentrează pe unelte, unde politica per tool are sens.
- Rutarea de LLM are alt ciclu de viață (catalog de modele, prețuri, fallback) și ar dubla complexitatea.
- Metering-ul de tokeni e greu de făcut exact (reasoning, cache, streaming) și ar cere reconciliere cu providerul.

**Consecințe.**
- `upstream_service.kind` nu are `llm`; `usage_counter` numără cereri, nu tokeni.
- Agentul își cheamă modelul direct, cu propria cheie; gateway-ul nu vede traficul LLM.
- Un client care vrea totuși un proxy LLM îl pune în față, separat, fără să atingă acest cod.
- Căutarea în catalog folosește index lexical în Postgres; nicio chemare către un model nu intră în calea request-ului de tool.

---

## ADR-015 — Catalog persistat și căutare lexicală

**Context.** Un gateway care ar întreba fiecare MCP la fiecare rutare ar avea latență proporțională cu numărul de servicii și ar depinde de disponibilitatea tuturor. Alternativa este un catalog persistat. Pentru căutare, s-a evaluat și un index vectorial (`pgvector`), dar catalogul are zeci de mii de rânduri, iar numele și descrierile tool-urilor conțin termenii pe care îi caută oamenii.

**Decizie.** Catalogul (`upstream_service` + `service_tool`) este sursa de rutare, interogată direct în Postgres. Căutarea este lexicală: `tsvector` + `ts_rank_cd`, cu `pg_trgm` pentru typo-uri. Fără embeddings în v1.

**De ce.**
- Rutarea devine un lookup pe index (`workspace_id, service, tool`), nu un tur al MCP-urilor.
- Lexical funcționează pe orice Postgres, fără provider extern, fără backfill, fără cost per interogare.
- `pg_trgm` acoperă typo-urile și numele parțiale, care sunt majoritatea căutărilor reale.
- Catalogul este stare derivată persistentă, cu contract de prospețime (`manifest_synced_at`, `last_seen_at`), nu un cache cu TTL.

**Consecințe.**
- Este nevoie de un job de descoperire (manual, programat sau lazy-miss limitat) care ține manifestul proaspăt.
- Un tool necunoscut produce `404 tool_unknown` cu sugestie de `discover`, nu un apel orb către upstream.
- Un semnal vectorial poate fi adăugat ulterior, în spatele aceleiași interogări, fără schimbarea contractului de API.
- `pg_trgm` este singura extensie suplimentară; dacă lipsește, rămâne `tsvector`.

---

## ADR-016 — Contract de paginare cu cursor semnat

**Context.** Listările de tool-uri și rezultatele de căutare trebuie paginate. `OFFSET` produce duplicate și elemente sărite când între pagini apar tool-uri noi, iar un cursor stocat pe server ar introduce stare.

**Decizie.** Cursor opac, semnat HMAC, care encodează cheia de sortare și hash-ul interogării. Fără `offset`, fără `total`.

**De ce.**
- Keyset pagination e stabilă la inserări.
- Semnătura previne injectarea unui cursor arbitrar și face contractul versionabil.
- Hash-ul interogării detectează schimbarea filtrelor între pagini, în loc să întoarcă rezultate incoerente.
- Nu există stare pe server, deci funcționează identic în ambele anvelope de execuție.

**Consecințe.**
- Clientul tratează cursorul ca opac; orice încercare de a-l compune manual primește `400 invalid_cursor`.
- Schimbarea `q` sau a filtrelor cere resetarea paginării.
- Nu se poate afișa „pagina 3 din 12"; UI-ul folosește „Load more" și `has_more`.
- Indexurile trebuie să acopere cheia de sortare: `(service_id, name)`, `(score, id)`, `(ts, id)`.

---

## ADR-017 — CLI pentru ciclul de viață, HTTP pentru administrare

**Context.** v1 trebuie livrat fără interfață grafică. Opțiunile erau: un CLI complet, un CLI minimal pentru proces, sau niciun CLI.

**Decizie.** Un singur pachet Python cu intrarea `agw`. CLI-ul expune `agw serve`, `agw migrate` și break-glass-ul `agw admin recover`. Toate operațiile de administrare — workspace-uri, agenți, servicii, granturi, catalog, audit, înrolare — trec prin API-ul HTTP. UI-ul este amânat.

**De ce.**
- Serverul rămâne singurul loc cu credențiale de servicii. Un CLI-only ar împrăștia secrete pe fiecare mașină.
- Un singur contract public reduce suprafețele de întreținut: agentul, scriptul CI și viitoarea interfață web folosesc aceleași rute.
- Pornirea și migrațiile sunt operații de proces, care au nevoie de acces local la configurare și DB.
- `agw serve --check` rămâne contractul de sănătate pentru pipeline.

**Consecințe.**
- Fiecare operație de administrare are echivalent HTTP documentat în [`../08-api/README.md`](../08-api/README.md).
- Bootstrap-ul se face cu `POST /v1/bootstrap` și tokenul de deployment.
- Recuperarea unui administrator se face local, în self-host, cu `agw admin recover`, care scrie audit și afișează un token de sesiune o singură dată. În Lambda nu există shell; recuperarea cere acces administrativ la RDS și Secrets Manager.
- CLI-ul nu ține tokenuri de sesiune, chei de agent sau credențiale OAuth.
- Testele CLI acoperă `serve --check`, `migrate` și `admin recover`.
- UI-ul reia aceleași endpoint-uri când va fi construit; nimic din API nu e proiectat pentru CLI.

---

## ADR-012 — Două profiluri: edge și self-host

**Context.** Deployment-ul trebuie să meargă și la edge (serverless, fără P2P, fără TCP persistent), și on-prem (containere, autoscale, Postgres local).

**Decizie.** Un singur cod, două profiluri selectabile din configurare. Diferă doar driverul de DB, runtime-ul și strategia de scalare.

> **Amendat de [ADR-018](#adr-018--persistent-doar-în-self-host).** Profilurile se numesc acum `persistent` și `request_response`; profilul `edge` devine `request_response`, cu capabilități reduse.

**De ce.**
- Duplicarea codului ar diverge în câteva luni; diferențele reale sunt puține și izolate în `app/db/engine.py`.
- Autoscale-ul nu cere P2P în niciun profil: LB + replici identice + metrici externe ajung.
- Edge-ul cere un driver HTTP către Postgres (Neon, Supabase, Aurora Data API, Hyperdrive), self-host-ul un pool clasic.

**Consecințe.**
- Profilul se alege la P0, pentru că decide driverul și runtime-ul.
- Edge-ul nu suportă SSE lung; pentru streaming rămâne profilul self-host sau un origin container.
- Politica se evaluează la origin în profilul edge; fără cache de politică.
- Detalii în [`../02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md).

---

## ADR-013 — OAuth pe triada `(user, agent, service)`

**Context.** Un serviciu poate fi autorizat o dată pentru un user și refolosit de toți agenții lui, sau separat pentru fiecare agent.

**Decizie.** Implicit, fiecare conexiune leagă exact trei subiecți: userul pentru care se acționează, agentul care acționează și serviciul. `binding = per_agent` este valoarea implicită.

**De ce.**
- Auditul răspunde fără ambiguitate la „cine a făcut ce, pentru cine".
- Compromiterea unui agent nu dă acces la delegările altuia.
- Revocarea unui agent nu atinge conexiunile celorlalți.

**Consecințe.**
- Un user cu cinci agenți autorizează de cinci ori. Se acceptă; `per_user` rămâne disponibil pentru servicii read-only.
- `service_connection` are un `check constraint` care impune forma subiecților în funcție de `binding`.
- Un index unic cu `coalesce` previne duplicatele când `user_id` sau `agent_id` sunt NULL.

---

## ADR-014 — Cereri de identitate inițiate de agent

**Context.** Un agent are nevoie să ceară o identitate: o delegare pentru un user, un credențial pentru un sub-agent sau o identitate de serviciu. Dacă i-am da dreptul să și-o acorde, rolul devine escaladare de privilegii.

**Decizie.** `identity_request` este o entitate separată, cu ciclu de viață propriu. Agentul creează cererea cu `identity:request`; un alt principal, cu `identity:approve`, o aprobă; pentru delegări, userul confirmă prin OAuth. Cererea produce o conexiune sau un credențial.

**De ce.**
- Separarea „cine cere" de „cine aprobă" este singura formă care rămâne sigură când agentul are și rol de editor.
- `approval_request` nu poate modela un flux în trei pași (aprobare → consimțământ → fulfill) cu trei subiecți.
- Auditul are nevoie de ambele capete: solicitant și aprobator, cu binding-ul exact.

**Consecințe.**
- `identity_request` are `check (approved_by_id <> requested_by_id)` în DB, nu doar în cod.
- Scope-urile cerute se intersectează cu ceiling-ul; nu există „scope implicit".
- Un agent nu poate cere o identitate pentru alt agent fără `agent:update` pe țintă și fără ca ceiling-ul țintei să permită.

---

## ADR-018 — Persistent doar în self-host

**Context.** Serverless și edge nu țin o conexiune deschisă între request-uri și nu oferă loc pentru sesiuni MCP, SSE sau procesoare stdio. Alternativele erau adaptoare care imită persistența: SSE prin polling, sesiuni ținute în DB, un strat JS peste Workers. Niciuna nu rezolvă problema reală — upstream-ul are nevoie de un canal viu.

**Decizie.** Serverul persistent există doar în self-host. În serverless/edge rulează același cod în anvelopa `request_response`: JSON, fără sesiuni, fără SSE, fără stdio, fără push A2A. Capabilitățile cerute de fiecare serviciu se detectează la descoperire și se salvează în `upstream_service.runtime_requirements`. Un apel care cere o funcție absentă întoarce `409 persistent_runtime_required`, cu `requirement` în corp.

**De ce.**
- Un adaptor de persistență mută starea în DB fără să rezolve canalul upstream; adaugă cod, latență și moduri de eșec.
- Refuzul explicit este o informație operabilă: operatorul vede ce serviciu cere ce și unde îl poate muta.
- 15 minute acoperă orice `tools/call`; plafonul nostru este 900 s, implicit 300 s. Durata nu e constrângerea care ar justifica adaptoare.
- Un singur cod, două anvelope: diferențele rămân în `app/core/runtime` și în configurare.

**Consecințe.**
- `GET /v1/runtime` publică capabilitățile; catalogul și clienții HTTP le afișează.
- Serviciile cu `stdio` se înregistrează doar în `persistent`; în `request_response` înregistrarea e refuzată.
- Un deployment poate combina un origin persistent cu instanțe request_response, ambele pe același Postgres.
- Testele de integrare rulează aceleași suite în ambele anvelope, cu cazurile `409` exceptate explicit în cea request_response.
- Detalii în [`../02-architecture/deployment-profiles.md`](../02-architecture/deployment-profiles.md).

---

## ADR-019 — Fără trust-on-first-use; înrolare cu token one-time

**Context.** Un agent nou cunoaște doar URL-ul gateway-ului. Întrebarea a fost dacă primul agent care apelează devine administrator și dacă o parolă inițială simplă, schimbată pe un certificat, este suficientă.

**Decizie.** Administratorul se creează out-of-band cu `POST /v1/bootstrap` și un token de deployment de 256 de biți, endpoint închis după primul workspace. Agenții se înrolează cu un token one-time sau printr-un device code aprobat de un om. Schimbul emite certificat sau API key și consumă tokenul atomic. `GET /.well-known/agw` publică restul informațiilor.

**De ce.**
- Trust-on-first-use pe un endpoint public înseamnă că un scan de porturi decide cine e administrator.
- Un token single-use, legat de workspace, rol și ceiling, dă atribuire, expirare și revocare. O parolă partajată nu dă niciuna.
- `user_code` din device flow oferă experiența „parolă simplă” fără să fie un secret de cont: identifică o cerere pending, iar aprobarea cere o sesiune umană.
- Cheia privată rămâne la agent; gateway semnează doar CSR-ul, deci nu vede niciodată secretul de lungă durată.

**Consecințe.**
- Schema primește `bootstrap_state`, `enrollment_token`, `enrollment_device_code`.
- `GET /.well-known/agw` este public, fără tenant și fără enumerare de workspace-uri.
- Tokenurile invalide, expirate sau consumate întorc același `401` generic, ca să nu devină oracol.
- Înrolarea și administrarea trec prin rutele HTTP din [`../08-api/README.md`](../08-api/README.md).
- Recuperarea administratorului se face local cu `agw admin recover`; nu există endpoint HTTP de recuperare.
- Detalii în [`../04-identity-and-access/enrollment.md`](../04-identity-and-access/enrollment.md).

---

## ADR-020 — TLS terminat la platformă; cheia privată a agentului rămâne la agent

**Context.** S-a propus folosirea unui certificat ACM pentru gateway: cheia privată este non-exportabilă, deci inaccesibilă aplicației. Întrebarea a fost dacă același model poate acoperi și identitatea agentului, în condițiile în care ACM nu funcționează în serverless.

**Decizie.** Separăm cele două certificate.
- **Server:** certificat public gestionat de platformă (ACM, certificat gestionat de Cloud Run, ACME/ingress). TLS se termină la LB / API Gateway / ingress; aplicația nu vede cheia privată.
- **Agent:** agentul generează keypair-ul și trimite un CSR; gateway-ul semnează cu un CA intern sau cu ACM Private CA. Cheia privată rămâne la agent.
- **mTLS per request:** terminat la platformă, care validează lanțul și trimite amprenta într-un header semnat. Aplicația verifică header-ul.

**De ce.**
- Un certificat ACM aparține edge-ului. Încărcarea lui într-un proces Lambda nu este suportată; terminarea TLS la API Gateway/ALB este modelul corect și funcționează în ambele anvelope.
- Certificatul clientului cere o cheie la client. Dacă serverul ține cheia, agentul nu poate demonstra posesia, deci nu se poate autentifica.
- mTLS per request nu cere conexiuni long-lived; se potrivește cu `request_response`. Un tunel TLS între request-uri rămâne doar în `persistent`.
- CA-ul intern evită lock-in-ul pe AWS și costul per certificat; ACM PCA rămâne un backend opțional.

**Consecințe.**
- `agent_credential` reține certificatul public, serialul și issuer-ul; cheia privată nu apare în DB.
- `enrollment_token` are starea `active|reserved|consumed|failed`; un CA extern produce `202 enrollment_id`, urmat de `complete`.
- Gateway-ul acceptă header-ul de certificat doar de la platformă; traficul direct către proces este refuzat.
- `503 ca_unavailable` este retryable cu același `enrollment_id`.
- Detalii în [`../04-identity-and-access/enrollment.md`](../04-identity-and-access/enrollment.md#cine-deține-cheia-privată).

---

## ADR-022 — Deploy manual, credențiale din Secret Manager, state partajat

**Context.** Deployment-ul are nevoie de credențiale AWS, de o cheie de
acces la ECR și de un loc stabil pentru state-ul Terraform. Varianta „secrete
de repository puse de mână” a fost respinsă la nivel de organizație: nimeni nu
știe când expiră, iar fiecare repo își ține propria copie. Rularea trebuie să
fie pornită de un om, nu de un push.

**Decizie.**
- **Declanșator unic `workflow_dispatch`.** `gh workflow run deploy.yml` este
  singura cale de a deploya. Fără `push`, fără `pull_request`, fără `schedule`.
- **Identitate prin OIDC.** Workflow-ul cere un token GitHub, Google îl schimbă
  pe credențiale temporare de cont de serviciu. În repo stau doar două
  variabile cu nume publice (`GCP_WORKLOAD_IDENTITY_PROVIDER`,
  `GCP_SERVICE_ACCOUNT`).
- **Un singur secret de deploy.** `ai-gateway/deploy-env` conține tot mediul
  necesar ca JSON: chei AWS, regiune, bucket de state, cheie și tabelă de lock.
  O setare nouă este o versiune nouă a secretului.
- **State partajat.** Backend S3 cu blocare DynamoDB, generat în CI din
  variabilele de deploy, sub cheia `ai-gateway/edge-lambda/terraform.tfstate`,
  în același bucket pe care organizația îl folosește deja.
- **Două faze de apply.** Repo-ul ECR se creează întâi, fiindcă Lambda nu poate
  porni fără imagine; apoi se construiește imaginea și se aplică restul.

**De ce.**
- Un deploy care cere un gest explicit nu poate fi declanșat de un fork, de un
  bot sau de un push greșit pe `main`.
- OIDC înlătură cheile de lungă durată din GitHub; GCP interzice oricum cheile
  de cont de serviciu prin politica de organizație.
- Un singur secret pentru tot env-ul de deploy ține rotația într-un loc și face
  workflow-ul independent de lista de chei: cheile noi nu cer modificări de cod.
- State-ul remote cu lock face apply-urile din CI și de pe stație serializabile
  și ține istoricul în afara laptopului.

**Consecințe.**
- Workflow-ul nu poate rula fără contul de serviciu, cutia de secret și
  legătura OIDC; toate trei vin din intrarea `ai-gateway` din catalogul
  `core-infra`.
- Valorile din secret sunt mascate în log; diagnosticul se face pe numele
  cheilor, nu pe valori.
- `terraform destroy` rămâne o operație de stație.
- Detalii în [`../13-ci/README.md`](../13-ci/README.md) și
  [`../deploy/terraform/README.md`](../../deploy/terraform/README.md#deploy-from-github-actions).
