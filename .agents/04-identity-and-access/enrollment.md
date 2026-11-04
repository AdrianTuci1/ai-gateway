# 04.1 — Bootstrap și înrolare

**Status:** `[x]` regulă de înrolare
**Owns:** cum apare primul administrator, cum se înrolează un agent, ce știe agentul înainte de primul apel.
**Depends on:** [`README.md`](README.md), [`../03-domain-model/schema.md`](../03-domain-model/schema.md), [`../08-api/README.md`](../08-api/README.md), [ADR-019](../11-decisions/README.md#adr-019--fără-trust-on-first-use-înrolare-cu-token-one-time)

## Problema

Un agent nou nu știe nimic: nici ce workspace există, nici ce roluri are, nici ce servicii poate apela. Tot ce are este un URL. Prima întrebare este cine îi dă identitatea, iar a doua este cine devine administrator la instalare.

## Regula

**Primul apelant nu devine administrator.** Autoritatea nu se acordă pe baza ordinii în care sosesc request-urile. Un endpoint public care dă `owner` primului venit este trust-on-first-use: oricine găsește URL-ul înainte de operator câștigă, iar un scan de porturi, un DNS rebinding sau un deployment partajat ajung ca atac.

Adminul se creează **out-of-band**, la instalare, printr-o acțiune deliberată și auditabilă. Agenții se înrolează cu un **token one-time** sau printr-un **device code aprobat de un om**. Ambele variante produc un credențial și se consumă.

## Bootstrap: primul administrator

Bootstrap-ul este o operație HTTP, disponibilă doar cât timp nu există niciun workspace:

```bash
export AGW_BOOTSTRAP_ENABLED=true
export AGW_BOOTSTRAP_TOKEN="$(openssl rand -base64 32)"
```

```http
POST /v1/bootstrap
X-Bootstrap-Token: <token>

{"workspace_slug":"acme","workspace_name":"Acme","owner_email":"you@example.com"}
```

- Creează workspace-ul, userul owner și membership-ul `owner`.
- Refuză dacă există deja un workspace; endpoint-ul se închide definitiv.
- Răspunsul conține un token de sesiune, afișat o singură dată.

Endpoint-ul este închis implicit:

```python
class Settings(BaseSettings):
    bootstrap_enabled: bool = False          # explicit, per deployment
    bootstrap_token: SecretStr | None = None # 256 de biți, din secret manager
```

Reguli:

1. Request-ul cere `X-Bootstrap-Token`; comparare constant-time, rate limit 5/min/IP.
2. Endpoint-ul răspunde doar cât timp `bootstrap_state.completed_at is null` și nu există niciun workspace.
3. La succes se creează un **user** owner, niciodată un agent, și se setează `completed_at`.
4. După succes, endpoint-ul răspunde `410 bootstrap_closed` pentru totdeauna. Tokenul se rotește sau se scoate din secret manager.
5. `bootstrap_enabled=false` → `403 bootstrap_disabled`, chiar dacă tokenul există.

Tokenul de bootstrap are 256 de biți și este generat de platformă. Nu se afișează în log-uri și nu se acceptă din query string.

### Break-glass

Dacă adminul este pierdut în self-host, recuperarea se face local, cu acces la
host:

```bash
agw admin recover \
  --workspace acme \
  --user you@example.com \
  --reason "lost IdP access"
```

Comanda setează membership-ul pe rolul `owner`, scrie `admin.recover` în audit
și afișează un token de sesiune o singură dată. Nu există endpoint HTTP de
recuperare. În Lambda, recuperarea se face prin acces administrativ la RDS și
Secrets Manager.

## Ce știe agentul înainte de primul apel

Agentul are nevoie de exact trei lucruri, provisionate de operator:

| Lucru | De unde | De ce |
|---|---|---|
| URL-ul gateway-ului | configurarea agentului | singurul lucru care nu poate fi descoperit |
| Un token de înrolare **sau** dreptul de a cere aprobarea unui om | secret manager / env / operator | dovada că operatorul l-a autorizat |
| Fingerprint-ul CA (self-host) | lângă token | ancora de încredere pentru TLS |

Restul — versiunea API, endpoint-urile, protocoalele, modul de autentificare, pașii de onboarding — se află din documentul de descoperire. Un agent nu poate porni cu zero informații; are nevoie de o ancoră de încredere. Tot ce urmează după ancoră se descoperă.

## Documentul de descoperire

`GET /.well-known/agw` este public, fără tenant și fără secrete:

```json
{
  "api_version": "v1",
  "gateway_id": "gw_7c1e",
  "protocols": { "mcp": "2025-06-18", "a2a": "0.2" },
  "auth": {
    "agent": ["mtls", "api_key"],
    "enrollment": ["token", "device_code"],
    "user": ["oidc"]
  },
  "endpoints": {
    "enroll": "https://gw.example.com/v1/enroll",
    "device_authorization": "https://gw.example.com/v1/enroll/device",
    "device_token": "https://gw.example.com/v1/enroll/device/token",
    "mcp": "https://gw.example.com/mcp/{agent_slug}",
    "catalog": "https://gw.example.com/v1/catalog"
  },
  "trust": { "ca_fingerprint_sha256": "9f2c..." },
  "onboarding": "Fără credențial? Cere operatorului un enrollment token sau pornește device enrollment."
}
```

Răspuns cache-abil 5 minute, rate limitat. Nu enumeră workspace-uri și nu spune dacă un agent există.

Un request neautentificat pe o rută protejată întoarce:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="agw", enroll="/v1/enroll"

{
  "error": "enrollment_required",
  "discovery": "/.well-known/agw",
  "hint": "Cere operatorului un enrollment token sau folosește device enrollment."
}
```

## Căile de înrolare

| Cale | Pentru cine | Ce primește agentul | Cine aprobă |
|---|---|---|---|
| **Token de înrolare** | agenți headless, CI, containere | certificat sau API key | operatorul, la emiterea tokenului |
| **Device code** | agent pe laptopul unui om, prima rulare | certificat sau API key | omul, autentificat în browser |
| **Cheie publică pre-înregistrată** | medii cu HSM / keypair generat de operator | certificat | operatorul, la înregistrare |

### A. Token de înrolare

Operatorul creează tokenul prin API:

```bash
curl -sS http://127.0.0.1:8080/v1/workspaces/acme/enrollment-tokens \
  -H "Authorization: Bearer $AGW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent_slug":"billing","role":"agent:executor","ttl_minutes":15,"ceiling":{}}'
```

```
agw_enroll_7f3a9c2e_<32 bytes base62>
     │        │        └─ secret, afișat o singură dată
     │        └─ key id
     └─ tipul credențialului
```

Tokenul este legat de un workspace, un slug de agent, un rol și un ceiling. Agentul nu poate cere alt rol și nu poate depăși ceiling-ul: template-ul vine din token, nu din request.

Fluxul:

```http
POST /v1/enroll
Authorization: Bearer agw_enroll_7f3a9c2e_...

{
  "agent_slug": "billing",
  "credential_type": "client_cert",
  "csr_pem": "-----BEGIN CERTIFICATE REQUEST-----...",
  "metadata": { "host": "billing-01", "runtime": "python-3.12" }
}
```

Răspuns:

```json
{
  "agent_id": "42",
  "workspace_id": "ws_acme",
  "credential": {
    "type": "client_cert",
    "certificate_pem": "-----BEGIN CERTIFICATE-----...",
    "ca_chain_pem": ["-----BEGIN CERTIFICATE-----..."],
    "spiffe_id": "spiffe://acme/agent/42",
    "expires_at": "2026-11-03T12:00:00Z"
  },
  "runtime": { "mcp_url": "https://gw.example.com/mcp/billing" },
  "renewal": { "url": "/v1/agent/credentials/renew", "after_seconds": 43200 }
}
```

Cu CA intern, verificarea tokenului, crearea agentului, semnarea CSR-ului și marcarea `consumed_at` se fac într-o singură tranzacție. Un al doilea request cu același token primește `401 enrollment_token_invalid`, fără să afle dacă tokenul a fost folosit, expirat sau niciodată valid.

Cu un CA extern, semnarea iese din tranzacție. Tokenul trece în `reserved`, răspunsul este `202` cu `enrollment_id`, iar agentul continuă cu `POST /v1/enroll/{id}/complete`, trimițând același CSR. Tokenul rămâne consumat de la rezervare; `enrollment_id` este cheia de idempotență pentru retry.

Pentru runtime-uri care nu pot ține o cheie privată sau nu fac mTLS, `credential_type = "api_key"` întoarce o cheie `agw_live_...` în locul certificatului. Tokenul de înrolare rămâne singurul secret de bootstrap.

### B. Device code

Pentru un agent care rulează pe laptopul unui om și nu are token provisionat:

```http
POST /v1/enroll/device
{ "agent_name": "billing-local", "requested_role": "agent:executor" }
```

```json
{
  "device_code": "dc_9c2...",
  "user_code": "K7QF-2M9X",
  "verification_uri": "https://gw.example.com/activate",
  "expires_in": 600,
  "interval": 5
}
```

Agentul afișează:

```
→ Deschide https://gw.example.com/activate
  Cod: K7QF-2M9X
  Aștept aprobarea... (expiră în 10 min)
```

Omul se autentifică, alege workspace-ul, rolul și ceiling-ul (în limita propriei autorități) și aprobă. Agentul poll-uiește `POST /v1/enroll/device/token` cu `device_code` la intervalul dat; primește credențialul o singură dată. Poll-ul prea rapid primește `429 slow_down`; cererea neaprobată încă întoarce `409 authorization_pending`.

`user_code` este „parola simplă" din întrebare, în singura formă sigură: opt caractere, generat de server, valabil 10 minute, cinci încercări. Nu autentifică singur pe nimeni — identifică o cerere pending, iar aprobarea cere o sesiune umană. `device_code` rămâne la agent și nu se afișează.

### C. Cheie publică pre-înregistrată

Operatorul încarcă un CSR sau o cheie publică pentru un agent existent. La primul apel, agentul se prezintă direct cu certificatul; nu există secret de bootstrap. Potrivit pentru HSM, TPM sau keypair generat de platformă.

## Schimbul de certificat

1. Agentul generează keypair-ul local. Cheia privată nu pleacă niciodată din proces.
2. Trimite CSR-ul; gateway validează că CN/SAN-ul cerut nu contrazice tokenul.
3. Gateway semnează cu CA-ul intermediar dedicat, SAN `spiffe://{workspace_slug}/agent/{agent_id}`.
4. Durată implicită 24h; reînnoire la 50% din viață, prin mTLS, la `/v1/agent/credentials/renew`.
5. La reînnoire, gateway verifică fingerprint-ul certificatului curent și refuză dacă agentul prezintă altă ancoră.
6. Certificatul vechi rămâne valid 1h după reînnoire, ca să acopere procesele care încă îl folosesc.
7. Revocarea: `agent.status = 'revoked'` sau `agent_credential.revoked_at`; verificat la fiecare request.

Agentul salvează certificatul și lanțul cu permisiuni `0600`, iar fingerprint-ul CA într-un fișier separat. Nu scrie cheia privată în log-uri, în variabile de mediu sau în răspunsuri de tool.

### Cine deține cheia privată

Certificatele serverului și ale agentului au proprietari diferiți. Confuzia dintre ele produce fie un endpoint nesigur, fie un agent care nu se poate autentifica.

| Certificat | Cheia privată | Cine emite | TLS se termină la |
|---|---|---|---|
| **Server** (`https://gw...`) | platforma: ACM, ALB, ingress | ACM public sau ACME | LB / API Gateway / ingress |
| **Client agent** | agentul | CA intern, ACM PCA sau alt PKI | LB / API Gateway, care validează lanțul |

#### Certificatul serverului

Un certificat ACM — sau Let's Encrypt, sau certificatul gestionat de Cloud Run — este alegerea corectă pentru endpoint. Cheia privată este non-exportabilă și rămâne la platformă; aplicația nu o vede niciodată. În serverless, TLS se termină la API Gateway, ALB sau CloudFront, iar funcția primește request-ul deja decriptat. ACM funcționează în serverless exact în acest model; încărcarea certificatului în procesul Python nu este o opțiune.

#### Certificatul agentului

Aici ACM nu poate ține cheia. Agentul trebuie să demonstreze posesia unei chei private la fiecare handshake; dacă cheia stă la server, agentul nu are cu ce să se autentifice. De aceea agentul generează keypair-ul, trimite CSR-ul, iar gateway-ul semnează. ACM Private CA poate fi semnatarul, însă cheia rămâne la agent.

#### Serverless și mTLS

mTLS per request funcționează în `request_response`: API Gateway (mutual TLS cu truststore în S3) sau ALB validează certificatul client și trimite amprenta verificată către aplicație. Gateway-ul citește header-ul semnat de platformă, fără handshake în proces. Un tunel TLS ținut deschis între request-uri rămâne disponibil doar în profilul `persistent`.

Dacă platforma nu oferă mTLS, enrollment-ul întoarce un API key. Ambele credențiale ies din același token.

### Backend-uri de CA

| Backend | Unde semnează | Mod de emitere |
|---|---|---|
| `internal` (implicit) | procesul gateway, cu CA intermediar local | o singură tranzacție, `201` |
| `acm_pca` | AWS ACM Private CA | rezervare + `complete`, `202` |
| `external` | step-ca, Vault PKI, alt CA | rezervare + `complete`, `202` |

CA-ul intern este implicitul pentru self-host: fără dependență de cloud, fără cost per certificat. ACM PCA este opțional pentru deployments pe AWS care vor un CA gestionat. Ambele implementează aceeași interfață:

```python
class CertificateAuthority(Protocol):
    async def issue(self, csr_pem: str, spiffe_id: str, ttl: timedelta) -> IssuedCert: ...
    async def revoke(self, serial_number: str, reason: str) -> None: ...
```

Cheia privată a CA-ului stă în KMS sau într-un HSM, niciodată în DB și niciodată în container.

## Tokenul de înrolare: reguli

| Regulă | Valoare |
|---|---|
| Entropie | 32 bytes base62 |
| TTL implicit | 15 minute; maximum 24h |
| Utilizări | exact una |
| Legare | workspace + agent slug + rol + ceiling |
| Stocare | `argon2id(secret)`, prefix pentru UI |
| Rate limit | 10/min/IP; 5 încercări per token |
| Revocare | `DELETE /v1/workspaces/{ws}/enrollment-tokens/{id}` înainte de consum |
| Audit | `enrollment.token_created`, `enrollment.consumed`, `enrollment.failed` |

Tokenul se afișează o singură dată, la creare. După consum, rămâne doar prefixul și hash-ul, pentru audit.

## De ce nu o parolă simplă partajată

- O parolă scurtă, partajată între agenți, se brute-forcează și se scurge în imagini, log-uri și repo-uri.
- Nu permite atribuire: nu poți spune care agent a primit ce identitate.
- Un endpoint care schimbă parola pe certificat devine un oracol de ghicire; rate limiting-ul ajută, dar nu repară entropia.
- „Parola dispare după exchange" este comportamentul corect, însă numai dacă secretul este strong, single-use și legat de un scope. Aici intră tokenul de înrolare și `user_code`-ul din device flow.

## Amenințări și mitigări

| Amenințare | Mitigare |
|---|---|
| Primul venit devine admin | bootstrap out-of-band; endpoint închis implicit, cu token de 256 biți |
| Token de înrolare furat | single-use, TTL 15 min, binding pe rol/ceiling, rate limit, revocare, audit |
| Replay | consum atomic; CSR legat de token; al doilea request primește același `401` generic |
| Agent care cere rol mai mare | rolul și ceiling-ul vin din token sau din aprobarea umană, niciodată din body |
| Gateway impostor | fingerprint CA provisionat out-of-band; reînnoirea refuză altă ancoră |
| Certificat furat | TTL 24h, revocare per credențial, `agent.status` verificat per request |
| Restore de DB | tokenurile expiră; adminul se recuperează cu `agw admin recover`, pe host |
| Enumerare de workspace-uri | discovery fără tenant; erori generice la token invalid |

## Teste

1. Al doilea request cu același token de înrolare → `401 enrollment_token_invalid`.
2. Token expirat → același răspuns generic, fără diferență de mesaj sau timing.
3. Token emis pentru `agent:executor` care cere `owner` în body → rolul din token, cererea ignorată sau `422`.
4. `POST /v1/bootstrap` după primul workspace → `410 bootstrap_closed`.
5. `POST /v1/bootstrap` fără token → `403 bootstrap_disabled` sau `401`, fără indicii despre existența tokenului.
6. Device flow: poll înainte de aprobare → `409 authorization_pending`; poll prea rapid → `429 slow_down`.
7. `user_code` greșit de cinci ori → cererea se închide, nu se mai acceptă aprobarea.
8. Certificat reînnoit cu alt fingerprint de CA → refuz.
9. Niciun token, cheie sau CSR nu apare în log-uri (test canary).
10. Clientul care primește certificatul îl scrie cu `0600` și nu îl afișează în stdout.
