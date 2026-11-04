# 06.1 — Catalog, rutare și căutare

**Status:** `[x]` proiectat; fără embeddings în v1
**Owns:** catalogul persistat, rutarea către serviciu, paginarea, căutarea lexicală.
**Depends on:** [`README.md`](README.md), [`../03-domain-model/schema.md`](../03-domain-model/schema.md), [`../12-cli/README.md`](../12-cli/README.md), [ADR-015](../11-decisions/README.md#adr-015--catalog-persistat-și-căutare-lexicală)

## Catalogul este index, nu cache

Gateway-ul nu întreabă toate MCP-urile ca să afle unde duce un tool. La descoperire, salvează manifestul în Postgres:

```
upstream_service   crm, https://crm.internal/mcp, auth_type=oauth2
service_tool       crm__list_invoices, schema, definition_hash, seen_at
```

La apel, rutarea este un lookup:

```sql
select s.id, s.endpoint, s.kind, t.name
from service_tool t
join upstream_service s on s.id = t.service_id
where s.workspace_id = :ws
  and s.name = :service_slug        -- "crm"
  and t.name = :tool_name;          -- "list_invoices"
```

Un index unic pe `(service_id, name)` și unul pe `(workspace_id, name)` fac din asta o citire de 1–2 ms. Zero apeluri upstream pentru rutare.

### De ce nu se numește cache

Un cache se invalidează pe timp și poate fi reconstruit din sursă. Catalogul este **stare derivată persistentă**, cu contract de prospețime:

| Câmp | Sens |
|---|---|
| `manifest_synced_at` | ultima descoperire reușită |
| `service_tool.last_seen_at` | ultima apariție în `tools/list` |
| `definition_hash` | detectează schimbarea unui tool |
| `embedding` | nu există în v1 |

Consecințe:
- Refuzul unui tool necunoscut este explicit: `404 tool_unknown`, cu sugestia `POST /v1/workspaces/{ws}/services/{id}/discover`.
- Un tool dispărut din manifest nu se șterge imediat; se marchează și, după două cicluri, iese din listări.
- Datele supraviețuiesc restartului și nu depind de un singur proces.

### Când se reîmprospătează

| Trigger | Cine | Notă |
|---|---|---|
| `POST /v1/workspaces/{ws}/services/{id}/discover` | om | explicit, imediat |
| la adăugarea serviciului | server | o dată |
| programat (`auto_sync`) | job extern | zilnic, implicit |
| schimbare de `definition_hash` | descoperire | granturile devin `stale` |
| **lazy miss** (opțional) | request | vezi mai jos |

**Lazy miss** este singura apropiere de cache în runtime, și este limitată: dacă un tool nu e găsit în catalog, gateway-ul poate face *o singură* descoperire pentru serviciul respectiv, apoi reîncearcă lookup-ul. Se activează doar cu `lazy_discover_on_miss=true`, maximum o dată pe serviciu pe minut, cu timeout de 3 s. Dacă upstream-ul e lent, request-ul eșuează cu `503 manifest_stale`, nu așteaptă.

## Două operații

| | **Listare** | **Căutare** |
|---|---|---|
| Scop | enumerare completă, deterministă | găsire după text |
| Ordine | `(service, name, id)` | `(score desc, id)` |
| Cursor | `(name, id)` | `(score, id)` + `query_hash` |
| Când | `GET /v1/catalog`, UI de configurare | `GET /v1/catalog?q=invoice`, `gateway__search_tools` |

## Contractul de paginare

Cursor opac, semnat HMAC, fără offset și fără `total`.

```json
{ "v": 1, "k": ["crm", "list_invoices", "9f2c..."], "qh": "sha256:ab12..." }
```

- `v` — versiunea contractului; cursor vechi → `400 invalid_cursor`.
- `k` — cheia ultimului element.
- `qh` — hash-ul interogării și al filtrelor; schimbarea lui `q` → `400 cursor_query_mismatch`.

Reguli:

1. Fără `offset`; inserările între pagini nu produc duplicate.
2. `has_more` și `next_cursor`; fără număr total.
3. `limit` 1–200, implicit 50.
4. Semnătura previne cursorii fabricați; verificare constant-time.
5. Cursorul nu ține stare pe server, deci funcționează identic în ambele anvelope de execuție.

REST:

```json
{
  "items": [ { "service": "crm", "name": "list_invoices", "score": 0.42 } ],
  "next_cursor": "eyJ2IjoxLCJrIjpb...",
  "has_more": true
}
```

MCP folosește aceleași câmpuri standard:

```json
{ "jsonrpc": "2.0", "id": 3, "method": "tools/list",
  "params": { "cursor": "eyJ2Ijox...", "limit": 50 } }
```

## Căutare lexicală

Suficientă pentru un catalog de unelte, fără dependențe externe.

Două semnale, fuzionate simplu:

| Semnal | Implementare | Prinde |
|---|---|---|
| full-text | `tsvector` + `ts_rank_cd` | cuvinte din nume și descriere |
| trigram | `pg_trgm` similarity pe nume | typo-uri, nume parțiale |

```sql
with q as (select websearch_to_tsquery('simple', :q) as tsq),
scored as (
  select t.id,
         ts_rank_cd(t.search_tsv, q.tsq)                      as text_score,
         similarity(t.name, :q)                               as name_score
  from service_tool t
  join upstream_service s on s.id = t.service_id
  cross join q
  where s.workspace_id = :ws
    and (:service_id is null or t.service_id = :service_id)
    and (t.search_tsv @@ q.tsq or t.name % :q)
)
select id, (text_score + 0.5 * name_score) as score
from scored
where score > 0.01
order by score desc, id
limit :limit;
```

Ajustări:

- `+0.05` dacă tool-ul este deja în grantul apelantului;
- excludere pentru serviciile `discoverable = false` fără grant;
- rezultatul sub prag se întoarce gol, cu `hint`.

Fără embeddings, fără provider extern, fără backfill. Când catalogul depășește câteva mii de unelte și utilizatorii nu nimeresc termenii, se poate adăuga un semnal vectorial în spatele unei migrații versionate; contractul de API rămâne același.

## Filtre

| Parametru | Efect |
|---|---|
| `service` | restrânge la un serviciu |
| `kind` | `mcp_http`, `http`, `a2a` |
| `granted` | doar ce e în grantul agentului |
| `read_only` | doar `annotations.readOnlyHint = true` |

Filtrele intră în `query_hash`; schimbarea lor resetează cursorul.

## Meta-tools

Când un agent are peste `max_tools_inline` (implicit 64) tool-uri în grant, `tools/list` întoarce primele 64 plus:

| Tool | Ce face |
|---|---|
| `gateway__search_tools` | caută lexical în tot ce are voie; maximum 20 de descriptori |
| `gateway__describe_tool` | schema completă pentru un nume calificat |
| `gateway__list_services` | serviciile disponibile, fără tool-uri |

Apelul rămâne `tools/call` cu numele calificat. Rezultatul căutării conține numele real, nu o referință opacă.

## Securitate

1. Filtrul de vizibilitate se aplică în SQL, înainte de sortare.
2. `discoverable = false` → exclus pentru cine nu are grant; numărul de rezultate nu trădează existența.
3. Fără cross-workspace, chiar dacă numele coincid.
4. Interogările nu se stochează implicit; opțional `search_log` cu text trunchiat la 200 de caractere, retenție 7 zile, per workspace.

## HTTP și UI

```bash
curl -sS "http://127.0.0.1:8080/v1/catalog?q=invoice&limit=20" \
  -H "Authorization: Bearer $AGW_TOKEN"
```

```bash
curl -sS "http://127.0.0.1:8080/v1/catalog?service=crm" \
  -H "Authorization: Bearer $AGW_TOKEN"
```

UI-ul (amânat, vezi [`../09-ui/README.md`](../09-ui/README.md)) refolosește aceleași endpoint-uri: filtrare locală pe pagina încărcată, căutare server-side cu debounce, „Load more" cu cursor per interogare.

## Limite

| Resursă | Limită |
|---|---|
| `limit` pagină | 200 (50 implicit) |
| candidați evaluați | 500 per interogare |
| latență țintă | < 15 ms p95, cu index |
| descoperire lazy | 1/minut/serviciu, timeout 3 s |

## Teste

1. 10 000 de tool-uri, paginare completă fără duplicate.
2. Inserare între pagini: niciun element sărit.
3. Cursor cu HMAC modificat → `400 invalid_cursor`.
4. `q` schimbat cu cursor vechi → `400 cursor_query_mismatch`.
5. Serviciu ascuns nu apare pentru agent fără grant, la niciun query.
6. Rutare `crm__list_invoices` → un singur lookup, zero apeluri upstream.
7. Tool absent din catalog → `404 tool_unknown`, fără apel upstream (sau lazy discover, dacă e activat).
8. Descoperire eșuată → catalogul vechi rămâne servibil, cu `manifest_stale_at` setat.

## Fallback-uri

| Situație | Comportament |
|---|---|
| `pg_trgm` indisponibil | doar `tsvector` |
| manifest vechi | se servește catalogul existent, cu marcaj de prospețime |
| upstream indisponibil la discover | păstrează manifestul anterior; nu golește catalogul |
| cursor invalid după deploy | `400`, clientul reia de la prima pagină |
