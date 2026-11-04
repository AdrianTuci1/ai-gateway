# Terraform

The Terraform environment [`envs/edge-lambda`](envs/edge-lambda) deploys the
control plane to AWS Lambda behind API Gateway HTTP API. Two storage backends
are supported:

1. **DynamoDB** (`data_backend = "dynamodb"`, the default) — the edge path.
   Lambda runs outside a VPC, so there is no NAT Gateway and no RDS.
2. **Postgres** (`data_backend = "postgres"`) — Lambda runs in private subnets
   with RDS Postgres and an optional RDS Proxy.

For a self-hosted server instead, see [`../docker`](../docker).

Both paths use the `request_response` runtime: JSON only, no SSE, no MCP
sessions, no stdio, no A2A streaming. Tool calls fail after 25 seconds and API
Gateway ends requests at 30 seconds.

## Architecture

DynamoDB (default):

```
Client ── HTTPS ──► API Gateway HTTP API ──► Lambda (Mangum)
                                                │
                                                ├── Secrets Manager (app secret)
                                                └── DynamoDB (single table)
```

Postgres:

```
Client ── HTTPS ──► API Gateway HTTP API ──► Lambda (Mangum, private subnets)
                                                │
                                                ├── Secrets Manager (app secret)
                                                └── RDS Proxy ──► RDS Postgres
```

- With DynamoDB the Lambda has no VPC configuration and uses AWS-managed
  networking. With Postgres it runs in two private subnets behind a NAT Gateway
  for upstream MCP/HTTP egress.
- The app secret holds `secret_key` and `bootstrap_token`; with Postgres it also
  holds `database_url`. The Lambda reads it at cold start, so credentials never
  appear in Lambda environment variables.
- The migration Lambda prepares storage before the API route is created:
  Alembic for Postgres, idempotent builtin-role seeding for DynamoDB.
- Client certificates are disabled (`AGW_CA_ENABLED=false`) because Lambda has
  no durable filesystem for the internal CA. Agents enroll with API keys.
- Expired enrollment tokens, device codes, and grants are removed by DynamoDB
  TTL (`expires_at_epoch`).

## Data model (DynamoDB)

One table with `pk`/`sk`:

- Entity items: `WORKSPACE#<id>`, `AGENT#<id>`, `SERVICE#<id>`,
  `ENROLL#<id>`, and similar, with `sk = #META`.
- Item collections: credentials and grants live under `AGENT#<id>`, tools under
  `SERVICE#<id>`.
- Lookup items (`LOOKUP#...`) provide strongly consistent lookups for slugs,
  emails, prefixes, and device codes. Reads use `ConsistentRead`, so a write is
  visible to the next request without waiting for index replication.
- Audit events are stored under `AUDIT#<workspace_id>` with a sortable
  timestamp key, which keeps the newest-first query cheap.
- Uniqueness (workspace slug, agent slug, service name, member, device code) is
  enforced with conditional writes and transactions.

The table is created with on-demand billing, encryption at rest, point-in-time
recovery, and TTL. No GSIs are required.

## Prerequisites

- Terraform 1.7 or newer
- AWS CLI v2 with credentials that can create Lambda, API Gateway, ECR, IAM,
  Secrets Manager, CloudWatch, and DynamoDB (or VPC/RDS for the Postgres path)
- Docker with `buildx`
- `jq` for reading secrets in the examples

## Deploy

```bash
cd deploy/terraform/envs/edge-lambda
cp backend.tf.example backend.tf     # edit bucket, key, region, lock table
cp terraform.tfvars.example terraform.tfvars
terraform init
../../scripts/deploy.sh
```

`deploy.sh` performs the two-phase apply:

1. Create the ECR repository.
2. Build the Lambda image for `linux/amd64` and push it.
3. Apply storage, secrets, Lambda, and API Gateway.

Export `TF_STATE_BUCKET` (plus `TF_STATE_KEY`, `TF_LOCK_TABLE`, `AWS_REGION`)
and `deploy.sh` writes the shared backend first, so a local run uses the same
state as the CI workflow.

The second apply runs the migration Lambda before the API route is created. If
the migration fails because a dependency is still warming up, run
`terraform apply` again; both paths are idempotent.

To switch an existing deployment to Postgres, set `data_backend = "postgres"`
and apply. This creates a new, empty database; move data first if you need it.

### Manual image build

```bash
REPOSITORY="$(terraform output -raw ecr_repository_url)"
REGION="$(terraform output -raw aws_region)"
IMAGE="$REPOSITORY:$(git rev-parse --short HEAD)"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"

docker buildx build --platform linux/amd64 \
  -f ../../../docker/Dockerfile.lambda \
  -t "$IMAGE" --push ../../../..

terraform apply -var="image_uri=$IMAGE"
```

## Deploy from GitHub Actions

The edge stack deploys from a manual dispatch:

```bash
gh workflow run deploy.yml
gh workflow run deploy.yml -f data_backend=postgres -f environment_name=staging
gh workflow run deploy.yml -f apply=false          # plan only, no changes
```

[`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) has
`workflow_dispatch` as its only trigger. It builds the image, pushes it to ECR,
applies the environment, and calls `/healthz` through API Gateway.

### Credentials

No credential is stored in GitHub. The workflow trades a GitHub OIDC token for
a Google service account, then reads one Secret Manager secret that holds the
whole deploy environment:

| Secret | Content |
|---|---|
| `staticlabs/ai-gateway-deploy-env` | JSON object with the deploy variables below |

| Key | What it is |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | credentials the deploy uses |
| `AWS_REGION` | region of the bucket, the lock table, and the stack |
| `TF_STATE_BUCKET` | bucket that holds the state |
| `TF_STATE_KEY` | optional; default `ai-gateway/edge-lambda/terraform.tfstate` |
| `TF_LOCK_TABLE` | optional; default `terraform-locks` |

Any other key is passed to the workflow untouched, so a new deploy setting is a
new secret version rather than a change to the workflow. Every value is masked
in the run log; only the key names are printed.

```bash
# create or rotate the deploy environment
gcloud secrets versions add ai-gateway-deploy-env \
  --project staticlabs --data-file=deploy-env.json
```

The repository holds two variables, whose names are public:

```bash
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER -R <owner>/ai-gateway \
  --body "projects/<number>/locations/global/workloadIdentityPools/github/providers/github"
gh variable set GCP_SERVICE_ACCOUNT -R <owner>/ai-gateway \
  --body "ai-gateway@staticlabs.iam.gserviceaccount.com"
```

The service account, the secret box, and the OIDC binding come from
[`core-infra`](https://github.com/staticlabsro/core-infra): the catalog entry in
`services.yaml` creates the account and the box, and its `repo_id` must be
filled once the GitHub repository exists so the binding is created. Both values
above are outputs of `terraform output service_accounts` and
`terraform output workload_identity_provider` there.

### Terraform state

State is shared, not local. `deploy/ci/render-backend.sh` writes a gitignored
`backend.tf` from `TF_STATE_BUCKET`, `TF_STATE_KEY`, `TF_LOCK_TABLE`, and
`AWS_REGION`. The bucket and lock table are the organization's Terraform state
setup, documented in core-infra `docs/access.md`: an S3 bucket with the
`terraform-locks` DynamoDB table. This stack uses them under its own key, so
there is one state mechanism in the organization, not two.

Local runs keep working: copy `backend.tf.example`, or export the same four
variables and run `deploy/ci/render-backend.sh`.

## Bootstrap the first admin

The app secret contains a random bootstrap token. Read it, then call the API:

```bash
API="$(terraform output -raw api_url)"
SECRET="$(terraform output -raw app_secret_arn)"
TOKEN="$(aws secretsmanager get-secret-value --secret-id "$SECRET" \
  --query SecretString --output text | jq -r .bootstrap_token)"

curl -sS "$API/v1/bootstrap" \
  -H "X-Bootstrap-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workspace_slug":"acme","workspace_name":"Acme","owner_email":"you@example.com"}'
```

The response contains a session token, shown once. Use it as
`Authorization: Bearer <token>` for the other routes. The bootstrap endpoint
returns `410` after the first workspace exists. After bootstrapping, set
`AGW_BOOTSTRAP_ENABLED = "false"` in the environment map and apply again.

## Verify

```bash
API="$(terraform output -raw api_url)"
curl -sS "$API/healthz"
curl -sS "$API/v1/runtime"
curl -sS "$API/.well-known/agw"
```

`/v1/runtime` reports `request_response` and the disabled features. The
placeholder UI is served at `/`. `data_backend` and `dynamodb_table_name` are
terraform outputs.

## Operations

- **Logs:** `aws logs tail "/aws/lambda/$(terraform output -raw function_name)" --follow`.
- **Prepare storage after a change:** invoke the migration Lambda:
  `aws lambda invoke --function-name "$(terraform output -raw migration_function_name)" --payload '{}' /tmp/migrate.json`.
  For DynamoDB this reseeds builtin roles; for Postgres it runs Alembic.
- **Updates:** rebuild and push the image, then
  `terraform apply -var="image_uri=$IMAGE"`.
- **DynamoDB:** inspect items with the AWS console or
  `aws dynamodb query --table-name "$(terraform output -raw dynamodb_table_name)" ...`.
  Point-in-time recovery is enabled; restore creates a new table.
- **Postgres:** RDS is private. Use a bastion or SSM port-forwarding session.
- **Secrets:** rotate `secret_key` only together with a planned session
  invalidation. Rotating the database password requires updating the RDS
  instance and the app secret.

## Cost

With DynamoDB the fixed components are one Lambda function, one HTTP API, one
Secrets Manager secret, and the table's on-demand capacity. There is no NAT
Gateway and no RDS instance.

With Postgres the stack adds a `db.t4g.micro` instance, an optional RDS Proxy,
and a NAT Gateway. Set `enable_rds_proxy = false` to remove the proxy and keep
`db_multi_az = false` for development. Set `enable_vpc = true` to put the
DynamoDB Lambda in the VPC anyway, for example to reach private upstreams.

## Security notes

- Terraform state contains the app secret and, for Postgres, the database
  password. Use an encrypted S3 backend with locking and restrict access.
- The Lambda execution role can read only the app secret and act on the gateway
  table (when DynamoDB is selected).
- With Postgres, RDS is not publicly accessible and accepts traffic from the
  Lambda security group and the proxy.
- Client certificate enrollment is disabled. API keys are hashed with argon2id.
- Set `dynamodb_deletion_protection = true`, or `db_deletion_protection = true`
  and `db_multi_az = true`, for production.

## Destroy

```bash
terraform destroy
```

If deletion protection is enabled, disable it first. The ECR repository and
Secrets Manager secrets are removed by default; add `force_delete` only when
you intend to drop the image and secret history. Destroying the stack also
removes the DynamoDB table and its data.
