# 09 — Interfața web

**Status:** `[ ]` amânat — se construiește după ce API-ul este stabil
**Owns:** structura UI, editarea capabilităților, fluxul de consimțământ, caching client.
**Depends on:** [`../08-api/README.md`](../08-api/README.md), [`../12-cli/README.md`](../12-cli/README.md)

> v1 livrează API-ul HTTP și CLI-ul de proces. Acest document rămâne contractul pentru UI, ca să nu se piardă deciziile când îl construim.

## Tehnologie

- SPA (React + TypeScript + Vite), servită din același proces ca API-ul.
- Fără SSR: aplicația e internă, autentificată, cu date per user. SSR ar adăuga un runtime și un cache pe server, ambele interzise prin design.
- State server: TanStack Query. State local: Zustand sau context. Fără Redux.
- Formulare: react-hook-form + zod, cu schemele generate din OpenAPI.

## Harta ecranelor

```
/                                  → workspace switcher / lista de agenți
/w/{ws}/agents                     → lista
/w/{ws}/agents/{id}                → detaliu, taburi
/w/{ws}/agents/{id}/capabilities   → editorul de servicii + tool-uri
/w/{ws}/agents/{id}/connections    → autorizări per serviciu
/w/{ws}/agents/{id}/activity       → audit filtrat pe agent
/w/{ws}/services                   → catalog + adăugare serviciu
/w/{ws}/services/{id}              → detalii, manifest, tools, sync
/w/{ws}/approvals                  → inbox de cereri (grant + identitate)
/w/{ws}/audit                      → audit global
/w/{ws}/usage                      → consum și bugete
/w/{ws}/members                    → membri și roluri
```

## Ecranul de capabilități

Ecranul central. Trebuie să răspundă la „ce poate face agentul acum?" și să permită schimbarea în câteva click-uri.

```
┌ Agent: billing-agent ─────────────────────────────────────────────┐
│ Identitate  agw_live_7f3a…        [Rotate]                        │
│ Rol         agent:editor          [Change]                        │
│ Buget       5 000 cereri/zi · 41% folosit                           │
├───────────────────────────────────────────────────────────────────┤
│ Servicii                                           [+ Add service]│
│                                                                   │
│ ▾ crm            MCP · OAuth · authorized 2h ago      [Revoke]    │
│    ☑ search_tickets        readOnly                              │
│    ☑ get_customer          readOnly        tenant = own          │
│    ☐ delete_invoice        destructive                            │
│    ☐ export_all            admin                                  │
│                                                                   │
│ ▸ tickets        MCP · API key · needs authorization   [Authorize]│
│ ▸ reports-agent  A2A · OAuth · authorized             [Settings]  │
└───────────────────────────────────────────────────────────────────┘
```

Interacțiuni:

- Checkbox-ul pe tool scrie imediat `PUT .../grants/{service}` (idempotent, stare completă).
- Lista de tool-uri se paginează server-side la 50; sub 200 de tool-uri se poate afișa integral, cu virtualizare.
- Bara de căutare are două moduri: filtrare locală pe ce e încărcat și căutare globală pe server (debounce 250 ms), cu rezultate grupate pe serviciu.
- „Load more" păstrează cursorul per interogare; schimbarea query-ului îl resetează.
- Tool-urile `destructive` cer confirmare, cu numele serviciului scris de utilizator.
- Selecția pe serviciu are „select all" doar pentru tool-urile non-destructive; un buton separat pentru restul.
- Construirea de argument constraints: editor simplu (equals / enum / pattern / max_length) pentru 90% din cazuri, JSON pentru restul.
- Orice schimbare arată un diff înainte de salvare: „+2 tools, -1 tool".
- Un tool `stale` apare cu badge și nu poate fi reactivat fără re-sync.

### Cine editează

- Dacă utilizatorul are `grant:write`, checkbox-urile sunt active.
- Dacă nu, sunt read-only, cu buton „Request access", care creează un `approval_request`.
- Dacă sesiunea aparține unui agent (`actor_type=agent`), bara de sus arată explicit: **„Editing as agent: reports-agent (ceiling: 4 services)"**. Niciodată implicit.
- Un indicator permanent arată cât din ceiling e folosit.

## Fluxul de consimțământ

1. Serviciul apare cu badge `needs authorization`.
2. Click pe „Authorize" → `POST /authorize` → se deschide linkul într-un tab nou.
3. Tab-ul gateway afișează „Waiting for authorization…" și face polling la 2 s pe `GET /connections` (max 5 min).
4. La succes, tab-ul se închide și lista se reîncarcă.
5. Dacă providerul întoarce eroare, se afișează motivul (`access_denied`, `invalid_scope`) și buton „Try again".

Pentru agenți autonomi, linkul ajunge în inbox ca `identity_request` de tip `delegation`, cu text explicativ: cine l-a cerut, pentru ce tool, ce scope-uri și pentru ce user.

## Inbox de aprobări

- Filtre: `pending`, `approved`, `denied`, `expired`; tip: grant / identity / connection / role.
- Fiecare cerere arată: agentul, serviciul, tool-urile sau scope-urile cerute, justificarea, diferența față de ceiling.
- Pentru `identity_request` de tip `delegation`, aprobarea nu produce acces direct: deschide pasul de consimțământ, cu link-ul OAuth și explicația „agentul X va acționa pentru userul Y pe serviciul Z".
- Acțiuni: `Approve`, `Approve with changes` (deschide editorul pre-completat), `Deny` cu notă obligatorie.
- Aprobarea în masă există doar pentru cereri identice pe același serviciu.

## Cache pe client

Server-ul nu cache-uiește; clientul compensează.

| Date | Strategie |
|---|---|
| Liste (agenți, servicii) | `staleTime: 30s`, revalidare la focus |
| Detaliu agent | `staleTime: 10s` |
| Catalog | `staleTime: 5m`, `ETag` / `If-None-Match` |
| Rezultate de căutare | `staleTime: 0`, cheie `(q, mode, filters, cursor)`, fără persistare |
| Audit | paginare infinită, `staleTime: 0` |
| Mutations | optimistic update cu rollback pe eroare |

Reguli:
- Nicio cheie de cache nu conține tokenuri sau secrete.
- La `401` se golește cache-ul și se redirecționează la login.
- La `403` / `409` nu se face retry automat.
- `ETag` se trimite pentru GET-uri de catalog și manifest; `304` economisește banda fără să adauge cache pe server.

## Stări goale și de eroare

Fiecare ecran are patru stări proiectate explicit:

1. **gol** — „Niciun agent încă" + acțiune primară;
2. **încărcare** — skeleton, nu spinner global;
3. **eroare** — mesaj + `trace_id` copiabil + buton retry;
4. **fără permisiune** — explicație și cerere de acces, nu pagină 403 seacă.

## Accesibilitate și responsive

- Navigare completă cu tastatura; focus visible.
- Contrast AA pe toate badge-urile de stare.
- Tabelele de tool-uri devin carduri sub 900px.
- Editorul de capabilități funcționează pe tabletă; pe telefon doar citire și aprobare.

## Ce nu face UI-ul

- Nu construiește promptul agentului.
- Nu editează credențiale upstream în clar (doar replace).
- Nu afișează tokenuri, nici parțial.
- Nu permite grant pe `*`.
