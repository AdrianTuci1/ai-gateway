# CI/CD — deploy prin GitHub Actions

Un singur drum de la commit la edge: un workflow manual care construiește
imaginea, o publică în ECR și aplică Terraform. Nu există deploy automat.

```
gh workflow run deploy.yml
  → GitHub OIDC → cont de serviciu Google
  → un secret din Secret Manager (env-ul întreg de deploy)
  → docker build + push în ECR
  → terraform init (state S3 partajat) + apply
  → GET /healthz prin API Gateway
```

## Regula de declanșare

`workflow_dispatch` este singurul declanșator. Un push nu pornește nimic, iar
`pull_request` lipsește deliberat: deploy-ul are credențiale de producție, deci
trebuie cerut explicit. Regula e aceeași ca în `core-infra`, unde
`scripts/check-triggers.sh` o verifică mecanic.

```bash
gh workflow run deploy.yml
gh workflow run deploy.yml -f data_backend=postgres -f environment_name=staging
gh workflow run deploy.yml -f apply=false        # plan, fără modificări
gh workflow run deploy.yml -f image_tag=sha-abc1234
```

## Credențiale: OIDC, nu secrete de repository

Nicio valoare nu stă în GitHub. Rularea cere un token OIDC, Google îl validează
și îl schimbă pe credențiale temporare de cont de serviciu. Apoi workflow-ul
citește **un singur secret** din Secret Manager, `ai-gateway/deploy-env`, care
conține tot mediul de deploy ca obiect JSON:

| Cheie | Rol |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | credențialele cu care se aplică Terraform și se împinge imaginea |
| `AWS_REGION` | regiunea bucket-ului de state, a tabelei de lock și a stack-ului |
| `TF_STATE_BUCKET` | bucket-ul de state |
| `TF_STATE_KEY` | opțional; implicit `ai-gateway/edge-lambda/terraform.tfstate` |
| `TF_LOCK_TABLE` | opțional; implicit `terraform-locks` |

Orice altă cheie ajunge în mediu neatinsă, deci o setare nouă de deploy e o
versiune nouă a secretului, nu o modificare de workflow. Scriptul
`deploy/ci/load-deploy-env.sh` maschează fiecare valoare în log și scrie doar
numele cheilor.

În repo rămân două **variabile**, ale căror nume sunt publice:

| Variabilă | De unde |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `terraform output workload_identity_provider` din `core-infra` |
| `GCP_SERVICE_ACCOUNT` | `terraform output service_accounts["ai-gateway"]` din `core-infra` |

Contul de serviciu, cutia de secret și legătura OIDC se creează din
`core-infra`: intrarea `ai-gateway` din `services.yaml`. Cât timp `repo_id` e
`TODO`, contul și cutia există, dar nimeni nu poate împrumuta contul; se
completează după ce repo-ul GitHub există, apoi se rulează `terraform apply`.

## State-ul Terraform

State-ul nu stă pe stație și nu intră în git. `deploy/ci/render-backend.sh`
generează `backend.tf` (ignorat de git) din variabilele de deploy. Bucket-ul și
tabela de lock sunt cele ale organizației, descrise în `core-infra`
`docs/access.md`: S3 cu blocare în DynamoDB (`terraform-locks`). Stack-ul
folosește același bucket sub cheia lui, ca să nu apară un al doilea mecanism.

Două rulări nu se calcă: `concurrency: ai-gateway-deploy` serializează
workflow-ul, iar blocarea din DynamoDB acoperă și un `apply` pornit de pe
stație.

## Pașii

1. **Verifică variabilele** — fără ele, pasul se oprește cu numele celor lipsă.
2. **Autentificare OIDC** la Google.
3. **Citește și încarcă secretul** de deploy; valorile sunt mascate.
4. **Verifică identitatea AWS** (`sts get-caller-identity`).
5. **Scrie backend-ul** și rulează `terraform init`.
6. **Creează repo-ul ECR** (`apply -target`), fiindcă Lambda are nevoie de
   imagine înainte de primul apply complet.
7. **Construiește și împinge imaginea** pentru `linux/amd64`. Tag-ul implicit
   este `sha-<commit>`.
8. **Aplică** tot mediul cu `image_uri` și `data_backend`.
9. **Smoke test**: `GET /healthz` prin API Gateway, cu retry pentru cold start.
10. **Summary** pe pagina rulării: backend, mediu, imagine, URL, tabelă, funcția
    de migrare, cheia de state.

Cu `apply=false`, pașii 6–9 sunt săriți și se rulează doar `terraform plan`.

## Ce poate eșua și ce spune eroarea

- **Variabile lipsă** → pasul 1 numește variabilele; se pun cu `gh variable set`.
- **`auth` pică** → federarea nu există încă sau `repo_id` nu e completat în
  `services.yaml`, deci legătura către cont lipsește.
- **Secretul nu se citește** → cutia `ai-gateway/deploy-env` nu are versiune sau
  contul de serviciu nu are `secretmanager.secretAccessor` pe ea.
- **`terraform init` pică pe backend** → cheia `TF_STATE_BUCKET` e greșită sau
  credențialele nu au acces la bucket ori la tabela de lock.
- **Migrarea pică la primul apply** → pentru DynamoDB, tabela trebuie să existe
  înaintea seed-ului de roluri; modulul așteaptă politica runtime, care poartă
  ARN-ul tabelei, deci ordinea e impusă în graf.
- **Smoke test pică** → vezi logurile Lambda din CloudWatch; `/healthz` întoarce
  `ok` doar dacă `store.ping()` reușește.

## Ce nu face

- Nu rulează `agw admin recover`; pe edge nu există, iar pe Postgres self-host
  rămâne o operație locală.
- Nu rotește secrete de aplicație: `secret_key` și `bootstrap_token` sunt
  generate de Terraform și rămân stabile între apply-uri.
- Nu șterge infrastructura. `terraform destroy` se rulează de pe stație, cu
  `dynamodb_deletion_protection` luat în calcul.
