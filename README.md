# AI Gateway

Control plane pentru identitatea agenților și politica de acces la tool-uri.
Specificațiile sunt în [`.agents/`](.agents/); implementarea de față acoperă
backend-ul din faza P0 și o parte din P1.

## Ce rulează

- FastAPI cu SQLAlchemy 2 async.
- PostgreSQL în producție; SQLite acceptat pentru dezvoltare și teste.
- CLI `agw` doar pentru ciclul de viață al serverului: `serve` și `migrate`.
- Interfața web este o aplicație React servită de backend la `/`.

## Pornire locală

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
export AGW_BOOTSTRAP_ENABLED=true
export AGW_BOOTSTRAP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AGW_DEV_AUTH=false   # doar pentru teste locale fără parolă
.venv/bin/agw migrate
.venv/bin/agw serve --reload
```

`agw migrate` rulează migrațiile Alembic din `migrations/`; revizia de bază
este `0001`.

CLI-ul acoperă pornirea, migrațiile și recuperarea de urgență a
administratorului. Toate celelalte operații trec prin HTTP. Primul
administrator se creează o singură dată, cu tokenul de bootstrap și o parolă
locală:

```bash
curl -sS http://127.0.0.1:8080/v1/bootstrap \
  -H "X-Bootstrap-Token: $AGW_BOOTSTRAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workspace_slug":"acme","workspace_name":"Acme",
       "owner_email":"you@example.com","password":"a-long-password"}'
```

Răspunsul conține un token de sesiune, afișat o singură dată. Folosește-l ca
`Authorization: Bearer <token>`. Interfața de la `http://127.0.0.1:8080/` cere
workspace-ul (`acme`), emailul și parola. `AGW_PASSWORD_AUTH_ENABLED=false`
închide autentificarea locală cu parolă. `AGW_DEV_AUTH=true` activează în plus
endpoint-ul de dezvoltare `/v1/auth/dev-login`, care emite sesiune doar pe baza
emailului și nu trebuie folosit în producție.

### Google OIDC

Autentificarea cu Google este opțională. Configurează un OAuth client de tip
„Web application” în Google Cloud Console, cu redirect URI
`<AGW_PUBLIC_BASE_URL>/v1/auth/oidc/google/callback`, apoi pornește serverul cu:

```bash
export AGW_GOOGLE_CLIENT_ID="....apps.googleusercontent.com"
export AGW_GOOGLE_CLIENT_SECRET="..."
export AGW_GOOGLE_ALLOWED_DOMAINS="gmail.com"
```

Butonul „Continue with Google” apare automat când ambele credențiale sunt
setate. Gateway-ul validează tokenul Google, cere email verificat și verifică
domeniul. Un cont Google trebuie să corespundă unui utilizator deja aprobat în
workspace; OIDC nu creează membri noi. Pentru Google Workspace cu domeniu
propriu, pune domeniul în `AGW_GOOGLE_ALLOWED_DOMAINS` (listă separată prin
virgulă).

## Înregistrare cu aprobare și identități umbrelă

O **identitate** grupează o persoană și agenții ei într-o singură aprobare.
Fiecare entitate (persoană sau agent) are propriul rol, permisiuni, credențiale
și granturi, dar intrarea în workspace se decide la nivel de identitate.

Persoanele și agenții pot cere acces singuri, fără token:

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/signup \
  -H "Content-Type: application/json" \
  -d '{"kind":"user","email":"dana@example.com","display_name":"Dana",
       "password":"a-long-password"}'

curl -sS http://127.0.0.1:8080/v1/workspaces/acme/signup \
  -H "Content-Type: application/json" \
  -d '{"kind":"agent","agent_slug":"research-bot","agent_name":"Research Bot",
       "identity_name":"Dana","owner_email":"dana@example.com"}'
```

Cererea apare în **Identities → Pending access requests**, unde un owner sau
admin alege rolul și aprobă ori respinge. Până la aprobare, autentificarea
persoanei răspunde `403 approval_pending`. Aprobarea unui agent creează agentul,
membership-ul, identitatea activă și un API key afișat o singură dată. Agentul
devine administratorul identității (`is_identity_admin=true`).

Un administrator de identitate poate invita persoana în identitatea deja
activă, fără o nouă aprobare de la un admin de workspace:

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/identity-groups/<identity_id>/invites \
  -H "Authorization: Bearer <agent-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"email":"dana@example.com","role":"viewer"}'
```

Răspunsul conține un link one-time, `${AGW_PUBLIC_BASE_URL}/claim/<token>`.
Persoana își creează contul și își alege parola la acel link, apoi intră în
aceeași identitate. Administratorii de identitate pot invita doar cu rolul
`viewer`; un admin de workspace (`identity:approve`) poate alege orice rol uman.
Invitațiile expiră după `AGW_IDENTITY_INVITE_TTL_HOURS` (implicit 168 de ore).
`AGW_SIGNUP_ENABLED=false` închide endpoint-ul public de înregistrare.

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/agents \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"slug":"billing","name":"Billing","role":"agent:executor"}'
```

Documentația OpenAPI este la `/docs`, iar starea runtime la `/v1/runtime`.

## Interfața web

Aplicația React stă în [`web/`](web/) și compilează în `src/agw/web/dist`,
astfel încât un singur proces servește API-ul și interfața.

```bash
cd web
npm install
npm run dev    # http://127.0.0.1:5173, proxy /v1 și /mcp către agw serve pe 8080
npm run build  # scrie bundle-ul în src/agw/web/dist
```

Tokenii de design sunt în [`web/src/tokens.css`](web/src/tokens.css): suprafețe
plate, colțuri drepte, tipografie densă de 13px, un singur albastru de accent.
Regulile de layout și componentele sunt în `web/src/styles.css`. Sidenav-ul se
poate retrage la o bandă de iconițe din butonul de collapse din topbar sau din
headerul navigației; starea se păstrează în browser.

Ecranele urmează structura portalului:

- **Home** — sumar, grupuri de resurse cu membri expandabili și ultimele trace-uri.
- **All resources** — resurse independente și din grupuri, cu filtre pe tip și grup.
- **Resource groups** — grupuri cu membri nested, creare, redenumire, ștergere și
  atribuire de resurse.
- **Agents / Services** — detaliile resursei, uneltele descoperite (MCP sau
  OpenAPI pentru API-uri HTTP), schema lor, granturile și credentialele agentului.
- **Create / Edit** — fiecare resursă, grup și grant are pagină proprie, cu
  breadcrumb `Create` sau `Edit`, în locul ferestrelor modale.
- **Discovery** — butonul *Discover tools* citește catalogul MCP sau documentul
  OpenAPI (`/openapi.json`, `/swagger.json` ori URL-ul serviciului) și
  actualizează catalogul de unelte și manifestul serviciului.
- **Identities** — identități umbrelă cu entitățile nested, roluri, permisiuni,
  aprobări în așteptare și generare de linkuri de invitație one-time.
- **Policies & grants** — granturile pe resurse, cu constrângeri de argumente.
- **Tracing** — lista trace-urilor, waterfall pe spanuri și detaliul fiecărui span.
- **Audit log** — evenimente, filtrate pe rezultat și acțiune.

Tracing și audit folosesc pagini numerotate de 50 de rânduri. Endpointurile
`GET /v1/workspaces/{ws}/traces` și `/audit` primesc `limit` (1–200), `page`
și opțional `as_of`; răspunsul include `X-Total-Count` și `X-Snapshot`.
Snapshot-ul fixează setul de date pentru navigarea între pagini, astfel încât
trace-urile sau evenimentele noi să nu decaleze rezultatele.

## Recuperarea administratorului

Dacă owner-ul își pierde accesul, rulează pe host, cu aceeași configurare ca
serverul:

```bash
agw admin recover \
  --workspace acme \
  --user you@example.com \
  --reason "lost IdP access"
```

Comanda setează rolul `owner`, scrie `admin.recover` în audit și afișează un
token de sesiune o singură dată. Adaugă `--create-user` când emailul nu există.

## Deployment

- **Docker + Postgres** — [`deploy/docker`](deploy/docker): containerized
  gateway and Postgres, `persistent` runtime, SSE and MCP sessions enabled.
- **AWS Lambda + DynamoDB** — [`deploy/terraform`](deploy/terraform): the edge
  path. API Gateway HTTP API, Lambda with Mangum, and a single DynamoDB table.
  No VPC or NAT Gateway. `request_response` runtime.
- **AWS Lambda + Postgres** — same Terraform environment with
  `data_backend = "postgres"`: Lambda in private subnets, RDS Postgres, and an
  optional RDS Proxy.

Deploys run from a manual dispatch: `gh workflow run deploy.yml`. Credentials
come from Google Secret Manager through GitHub OIDC, and Terraform state is
shared in S3 with DynamoDB locking. See
[`deploy/terraform/README.md`](deploy/terraform/README.md#deploy-from-github-actions).

The storage layer supports both backends through one interface. Postgres uses
SQLAlchemy and Alembic; DynamoDB uses a single table with item collections and
lookup items. `agw migrate` runs Alembic for Postgres and seeds the builtin
roles for DynamoDB. `agw admin recover` stays available on self-hosted SQL
backends; on DynamoDB use an operator role through the HTTP API.

## Teste

```bash
.venv/bin/pytest
```

## Note de implementare

- SQLite este suportat pentru dezvoltare; tabelele folosesc tipuri portabile.
  Căutarea avansată `tsvector` și indexurile trigram rămân pe PostgreSQL.
- CA-ul intern scrie materialul criptografic în `AGW_CA_DIR` (implicit
  `.agw-ca/`). În producție, cheia CA trebuie să stea în KMS sau HSM.
- Streaming-ul MCP SSE este disponibil în runtime-ul `persistent`. În
  `request_response` răspunsurile sunt JSON, iar funcțiile care cer persistență
  întorc `409 persistent_runtime_required`.
