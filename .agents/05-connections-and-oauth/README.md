# 05 — Conexiuni și OAuth

**Status:** `[x]` flux stabilit
**Owns:** consimțământul per serviciu, vault-ul de credențiale, refresh, revocare.
**Depends on:** [`../04-identity-and-access/README.md`](../04-identity-and-access/README.md), [`../03-domain-model/schema.md`](../03-domain-model/schema.md)

## Principiul

Serviciile upstream își păstrează autentificarea proprie. Gateway-ul nu inventează un protocol unic; învață tipul de auth al fiecărui serviciu și vorbește pe limba lui.

| `auth_type` | Cine deține credențialul | Flux |
|---|---|---|
| `oauth2` | utilizatorul, per serviciu | authorization code + PKCE, link către user |
| `api_key` | workspace-ul | cheie introdusă o dată de admin, stocată criptat |
| `mtls` | gateway-ul | certificat de client încărcat de admin |
| `none` | — | serviciu intern, doar grant |

## Legătura grant ↔ conexiune

Un **grant** spune *ce* are voie agentul. O **conexiune** spune *cu ce* se autentifică. Sunt independente:

```
grant activ + conexiune activă        → apel normal
grant activ + nicio conexiune         → 409 connection_required + authorize_url
grant activ + conexiune needs_reauth  → 409 connection_required + link nou
fără grant                            → 403 tool_not_allowed (nu se ajunge la conexiune)
```

Această separare permite:
- unui om să pregătească toate granturile înainte ca userul să autorizeze ceva;
- unui agent să ceară acces la un serviciu fără să blocheze pe cineva;
- revocarea credențialului fără pierderea configurației.

## Cine autorizează

OAuth are trei subiecți: **user**, **agent**, **service**. Modul implicit este triada completă: fiecare agent are propria delegare, cu propriul consimțământ.

`upstream_service.credential_policy` decide granularitatea:

| Valoare | Conexiunea aparține | Când o folosești |
|---|---|---|
| `per_agent` (implicit) | `(user, agent, service)` — triada | implicit; izolare maximă, audit fără ambiguitate |
| `per_user` | `(user, service)`, partajată între agenții userului | servicii read-only, mai puțină frecție |
| `workspace` | `(workspace, service)`, o singură conexiune | API keys de serviciu, conturi de serviciu |

Pentru `workspace`, `user_id` și `agent_id` sunt NULL, iar API-ul marchează conexiunea ca „shared". Diferența este impusă prin `check constraint` în schemă, nu doar în cod.

Conexiunea pe triadă este rezultatul unei `identity_request` de tip `delegation`. Când un om o inițiază direct din UI, cererea se creează automat și se auto-aprobă (omul are autoritatea), apoi se generează link-ul. Când o inițiază un agent, aprobarea trece printr-un alt principal.

## Fluxul de autorizare (OAuth 2.0 + PKCE)

### 1. Initiere

```http
POST /v1/workspaces/{ws}/agents/{agent_id}/connections/{service_id}/authorize
Authorization: Bearer agw_live_...
Content-Type: application/json

{ "scopes": ["crm.read", "crm.write"], "return_url": "https://app.example.com/agents/42" }
```

Răspuns:

```json
{
  "authorize_url": "https://crm.example.com/oauth/authorize?client_id=...&code_challenge=...&state=...",
  "state_id": "0f2c...",
  "expires_at": "2026-11-02T12:10:00Z",
  "requested_scopes": ["crm.read", "crm.write"]
}
```

Permisiune necesară: `connection:authorize`. Pentru un agent, doar pe serviciile pe care le are deja în grant.

### 2. Ce se întâmplă în spate

```
oauth_state:
  code_verifier  ← generat, criptat cu DEK-ul workspace-ului
  redirect_uri   ← PUBLIC_BASE_URL + /oauth/callback
  requested_scopes ← intersecție(scope cerute, scope permise de serviciu, scope maxime din ceiling)
  expires_at     ← now() + 10 min
```

`state` = id-ul rândului + HMAC, ca să nu poți injecta un id arbitrar.

### 3. Callback

```http
GET /oauth/callback?code=...&state=...
```

Rută publică, fără autentificare de utilizator (input-ul vine de la provider). Pași:

1. Verifică HMAC-ul `state` și încarcă rândul; verifică `expires_at > now()` și `consumed_at is null`.
2. Marchează `consumed_at` atomic (`update ... where consumed_at is null returning *`); al doilea callback primește `400 invalid_state`.
3. Decriptează `code_verifier`, schimbă codul pe token la `token_endpoint`, cu `client_secret` din vault.
4. Validează răspunsul: `access_token` prezent, `scope` acoperă măcar scope-urile cerute pentru tool-urile din grant.
5. Upsert `service_connection` (criptat), status `active`, `expires_at` din `expires_in`.
6. Dacă grantul era `pending`, îl trece pe `active` **doar** dacă exista deja aprobare; altfel rămâne `pending` și se creează `approval_request`.
6b. Dacă flow-ul provine dintr-o `identity_request` de tip `delegation`, o marchează `fulfilled` și setează `fulfilled_connection_id`.
7. Audit `connection.authorize` cu `actor = user`.
8. Redirect la `return_url` cu `?connection=ok` sau `?connection=error&code=...`.

Erorile providerului (`access_denied`, `invalid_scope`) se întorc ca pagină prietenoasă în UI, plus audit cu `decision = deny`.

### 4. Cum ajunge linkul la utilizator

Trei căi, toate necesare:

1. **UI** — buton „Authorize" pe pagina agentului, lângă serviciul marcat `needs authorization`.
2. **Răspuns de eroare structurat** — când agentul cheamă un tool fără conexiune:

```json
{
  "error": {
    "code": "connection_required",
    "message": "Service 'crm' requires authorization.",
    "service_id": "b6f1...",
    "authorize_url": "https://gateway.example.com/v1/.../authorize?...",
    "expires_at": "2026-11-02T12:10:00Z",
    "trace_id": "01J..."
  }
}
```

3. **Inbox / notificare** — pentru agenți autonomi, fără om în buclă: se creează `approval_request` de tip `connection` și se notifică ownerii (email/webhook). Apelul întoarce `409 authorization_pending`.
4. **HTTP** — un `POST` pe ruta de conexiuni a agentului afișează linkul, iar clientul poll-uiește `GET` pe aceeași rută până conexiunea devine activă. Callback-ul merge la server.

Regula: linkul este **idempotent re-emisibil**. Dacă utilizatorul îl pierde, un nou `POST /authorize` generează alt state; cel vechi expiră natural.

## Vault-ul

### Envelope encryption

```
KMS root key (per environment)
   └─ DEK per workspace, stocat criptat în `workspace_dek`
        └─ AES-256-GCM pe fiecare câmp sensibil, cu AAD = "table:column:row_id"
```

- AAD-ul leagă ciphertext-ul de rând: un token copiat în alt rând nu se decriptează.
- Rotirea DEK-ului se face prin re-criptare lazy la citire, cu `key_version` pe rând.
- Cache-ul SDK-ului KMS pentru data keys: maxim 5 min, singura excepție de la regula „fără cache pe server".

### Ce se criptează

- `access_token_enc`, `refresh_token_enc`
- `code_verifier_enc`
- `auth_config.client_secret_enc` (pentru servicii OAuth care cer secret)
- cheia privată mTLS a gateway-ului, dacă e cazul

### Ce nu se criptează

- `client_id`, `scopes`, `expires_at` — necesare pentru interogări și pentru UI.

### Reguli

- Tokenurile nu apar niciodată în log-uri, audit, mesaje de eroare sau răspunsuri API.
- `repr()` pe modelele SQLAlchemy maschează câmpurile `_enc`.
- Un test de tip „canary token" verifică faptul că un token plantat nu ajunge în log.

## Refresh

**Lazy, în request.** Fără job-uri de fundal în v1.

```python
if conn.expires_at - now() < timedelta(seconds=120):
    refresh(conn)          # POST la token_endpoint cu refresh_token
```

- Succes → update criptat, `expires_at` nou, audit `connection.refresh`.
- `invalid_grant` / `invalid_client` → `status = needs_reauth`, audit, răspuns `connection_required`.
- Eroare de rețea → `502 upstream_error` cu `retryable: true`; nu marchezi conexiunea moartă.
- Refresh-ul se face sub un lock pe rând (`select ... for update`) ca două request-uri concurente să nu consume același refresh token.

Pentru serviciile care nu dau refresh token (implicit access token), expirarea duce direct la `needs_reauth` și link nou.

## Revocare

```http
DELETE /v1/workspaces/{ws}/agents/{agent_id}/connections/{service_id}
```

1. Marchează `status = revoked`.
2. Dacă providerul suportă RFC 7009, cheamă `revoke` best-effort (nu blochează răspunsul).
3. Audit `connection.revoke` cu actorul.
4. Următorul tool call primește `connection_required`.

Revocarea nu șterge rândul: istoricul rămâne pentru audit, iar reautorizarea face un rând nou sau resetează cel vechi, în funcție de `binding`.

## Servicii fără OAuth

### API key

```json
POST /v1/workspaces/{ws}/services
{
  "name": "internal-billing",
  "kind": "http",
  "endpoint": "https://billing.internal",
  "auth_type": "api_key",
  "auth_config": { "header": "X-Api-Key" },
  "secret": "sk_..."          // write-only, niciodată returnat
}
```

Răspunsul confirmă doar `secret_set: true`. UI-ul arată „configured", cu buton „Replace".

### mTLS

Admin încarcă un certificat + cheie (PEM) sau un PKCS#12. Gateway le ține criptate și le prezintă la handshake-ul cu upstream-ul. Pentru servicii care validează SAN-ul, se configurează explicit `expected_san`.

### None

Serviciu intern; doar grantul contează. Util pentru teste și pentru MCP servere locale.

## Stări și tranziții

```
            authorize                 callback ok
(absent) ──────────────► pending ──────────────► active
                            │                      │
                            │ callback error       │ refresh invalid_grant
                            ▼                      ▼
                         (absent)             needs_reauth
                                                   │
                                    authorize ─────┘
active ── revoke ──► revoked ── authorize ──► active
```

## Teste obligatorii

1. Callback cu `state` expirat → `400`, fără scriere.
2. Callback dublu → al doilea `400`, conexiunea rămâne validă.
3. `state` cu HMAC modificat → `400`.
4. Token expirat → refresh reușit → apelul continuă fără intervenție.
5. Refresh eșuat → `409 connection_required` cu link nou.
6. Tokenul nu apare în log-uri, audit, nici în `repr`.
7. Revocare → următorul apel cere autorizare.
8. `credential_policy = per_user` → al doilea agent al aceluiași user refolosește conexiunea.
9. `credential_policy = per_agent` → al doilea agent al aceluiași user primește `connection_required` și link separat.
10. Callback pentru o `identity_request` → cererea devine `fulfilled` și `fulfilled_connection_id` e setat.
11. Un agent care încearcă să aprobe propria `identity_request` → `403`, indiferent de rol.
