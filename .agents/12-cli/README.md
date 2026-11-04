# 12 — CLI

**Status:** `[x]` ciclul de viață al serverului și break-glass; administrarea trece prin HTTP; UI amânat
**Owns:** `agw serve`, `agw migrate`, `agw admin recover`, configurarea procesului.
**Depends on:** [`../08-api/README.md`](../08-api/README.md), [ADR-017](../11-decisions/README.md#adr-017--cli-pentru-ciclul-de-viață-http-pentru-administrare)

## Decizia: CLI minimal, HTTP pentru restul

`agw` pornește serverul, rulează migrațiile și oferă recuperarea de urgență a
administratorului. Toate operațiile de administrare — workspace-uri, agenți,
servicii, granturi, catalog, audit, înrolare — se fac prin API-ul HTTP. Agenții
și operatorii folosesc același contract.

```
agw serve --runtime persistent      # pornește serverul
agw migrate                         # aplică migrațiile Alembic
agw admin recover --user ...        # break-glass, local, auditat
```

Nu există comenzi de client. Un client poate fi orice unealtă HTTP: `curl`,
SDK-ul intern al agentului, un script CI sau viitoarea interfață web.

## De ce CLI minimal

| Variantă | Ce se întâmplă | Verdict |
|---|---|---|
| Doar CLI | Fiecare mașină ține credențialele tuturor serviciilor; politica se aplică local | respins |
| CLI + client HTTP separat | Două suprafețe de întreținut, cu risc de divergență | respins |
| **CLI de proces + HTTP** | Serverul e granița de încredere; un singur contract public | **ales** |

CLI-ul nu ține credențiale de agent sau de serviciu. Tokenurile OAuth rămân în
vault-ul serverului. Tokenul de sesiune al unui om se păstrează în clientul
care face cererile HTTP.

## Instalare

```bash
uvx agw --help                 # fără instalare
pipx install ai-gateway        # instalare izolată
docker run ghcr.io/org/ai-gateway agw --help
```

Pachet Python cu intrare unică:

```toml
[project.scripts]
agw = "agw.cli:main"
```

## Configurare

Procesul citește configurarea din variabile de mediu cu prefix `AGW_`, sau
dintr-un fișier `.env` în directorul de lucru.

| Variabilă | Rol |
|---|---|
| `AGW_RUNTIME` | `persistent` sau `request_response` |
| `AGW_DATABASE_URL` | conexiunea SQLAlchemy |
| `AGW_PUBLIC_BASE_URL` | origine publică, folosită în linkuri |
| `AGW_SECRET_KEY` | semnarea sesiunilor și cheia vault-ului |
| `AGW_CA_DIR` | materialul CA intern |
| `AGW_BOOTSTRAP_ENABLED` | permite `POST /v1/bootstrap` |
| `AGW_BOOTSTRAP_TOKEN` | tokenul de deployment pentru bootstrap |

## Bootstrap prin HTTP

Primul administrator se creează out-of-band, cu un token de deployment. Nu
există trust-on-first-use și nu există un endpoint de recuperare.

```bash
export AGW_BOOTSTRAP_ENABLED=true
export AGW_BOOTSTRAP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
agw migrate
agw serve
```

```bash
curl -sS http://127.0.0.1:8080/v1/bootstrap \
  -H "X-Bootstrap-Token: $AGW_BOOTSTRAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workspace_slug":"acme","workspace_name":"Acme","owner_email":"you@example.com"}'
```

Endpoint-ul se închide după primul workspace și răspunde `410 bootstrap_closed`.
Răspunsul conține un token de sesiune, afișat o singură dată. Recuperarea unui
administrator cere acces la host sau la baza de date și se face în afara
procesului.

## Administrare prin HTTP

Exemplele presupun `AGW_TOKEN` cu tokenul de sesiune al owner-ului.

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/agents \
  -H "Authorization: Bearer $AGW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"slug":"billing","name":"Billing","role":"agent:executor"}'
```

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/enrollment-tokens \
  -H "Authorization: Bearer $AGW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_slug":"billing","role":"agent:executor","ttl_minutes":15}'
```

Înrolarea cu certificat cere un CSR generat de client. Cheia privată rămâne la
agent; serverul semnează doar CSR-ul.

```bash
curl -sS http://127.0.0.1:8080/v1/enroll \
  -H "Authorization: Bearer $AGW_ENROLL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_slug":"billing","credential_type":"client_cert","csr_pem":"..."}'
```

Restul rutelor sunt documentate în [`../08-api/README.md`](../08-api/README.md)
și în OpenAPI la `/docs`.

## `agw serve`

```bash
agw serve --runtime persistent --host 0.0.0.0 --port 8080
agw serve --runtime request_response --database-url "$DATABASE_URL"   # paritate locală
```

- Pornește FastAPI cu Uvicorn, fără SPA în v1.
- `--runtime` alege anvelopa. `persistent` e necesar pentru SSE, sesiuni MCP și
  connectorul stdio; `request_response` rulează local pentru teste, nu înlocuiește
  o platformă serverless.
- `--check` validează configurarea și conexiunea la DB, apoi iese. Raportează
  runtime-ul și capabilitățile, ca să nu descoperi lipsa lor la primul apel.
- `--create` creează tabelele direct, pentru dezvoltare. Producția folosește
  `agw migrate`.
- `SIGTERM` → shutdown graceful, fără request-uri tăiate.

## `agw migrate`

```bash
agw migrate
```

- Pe backend SQL (Postgres, SQLite) rulează `alembic upgrade head` din
  `migrations/`. Pe DynamoDB nu există schemă de migrat.
- Seed-uiește rolurile built-in, idempotent, în ambele cazuri.
- Este singura cale suportată de a pregăti storage-ul înainte de `agw serve`.
- Într-un deployment cu mai multe replici, migrarea rulează o singură dată, în
  etapa de release, înainte de pornirea noilor instanțe.
- Cu `AGW_DB_BACKEND=dynamodb`, tabelul trebuie să existe deja (îl creează
  Terraform); `agw migrate` doar seedează rolurile.

## `agw admin recover`

Break-glass pentru un administrator pierdut. Rulează pe host, cu aceeași
configurare și acces la DB ca serverul; nu trece prin HTTP.

Comanda este disponibilă doar pe backend SQL, în self-host. Refuză explicit
`AGW_DB_BACKEND=dynamodb`. În Lambda nu există shell; recuperarea se face prin
roluri de operator și HTTP, cu acces administrativ la storage și Secrets
Manager.

```bash
agw admin recover \
  --workspace acme \
  --user you@example.com \
  --reason "lost IdP access" \
  --create-user
```

- Găsește workspace-ul după slug; fără `--workspace`, îl deduce doar când
  există exact unul.
- Găsește userul după email. `--create-user` creează un user local când emailul
  nu există.
- Setează membership-ul pe rolul `owner`.
- Scrie `admin.recover` în audit, cu motivul, workspace-ul, userul și rolul
  anterior.
- Afișează un token de sesiune proaspăt, o singură dată; `--no-token` îl
  omite.
- Comanda este idempotentă: o a doua rulare confirmă rolul existent și scrie
  un eveniment nou de audit.

## Teste

1. `agw serve --check` întoarce `0` cu o configurare validă și un DB accesibil.
2. `agw serve --check` întoarce `1` dacă DB-ul nu răspunde.
3. `agw migrate` este idempotent și, pe SQL, lasă `alembic_version` la `head`.
4. `agw migrate` seed-uiește exact rolurile built-in, fără duplicate, pe SQL și
   pe DynamoDB.
5. `agw admin recover` refuză un email necunoscut fără `--create-user`.
6. `agw admin recover` restaurează rolul `owner` și scrie `admin.recover`.
7. Comenzile nu afișează tokenuri, chei sau culoare ANSI.

## Ce nu face CLI-ul

- Nu administrează agenți, servicii, granturi sau conexiuni.
- Nu ține credențiale OAuth ori chei de agent.
- Nu evaluează politică local.
- Nu scrie direct în DB în afara migrațiilor și a recuperării administrative.
- Nu are mod „offline”.
