# AI Gateway

Control plane for agent identities, credentials, and tool access. FastAPI
backend with a React admin UI and one store interface backed by Postgres/SQLite
or DynamoDB.

## Deploy

Edge stack (API Gateway, Lambda, DynamoDB) from a checkout with AWS credentials:

```bash
./deploy/terraform/scripts/deploy.sh
```

The command initializes Terraform, builds the Lambda image, pushes it to ECR, and
applies the stack. For Postgres, set `data_backend = "postgres"` in
`deploy/terraform/envs/edge-lambda/terraform.tfvars` (copy it from
`terraform.tfvars.example` first).

From CI, the same deploy is a manual dispatch:

```bash
gh workflow run deploy.yml -f data_backend=dynamodb -f environment_name=prod
```

Self-hosted Docker + Postgres lives in [`deploy/docker`](deploy/docker).

## Run locally

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/agw migrate
AGW_BOOTSTRAP_ENABLED=true AGW_BOOTSTRAP_TOKEN=dev-token .venv/bin/agw serve
```

Create the first owner once, then open `http://127.0.0.1:8080` and sign in with
workspace `acme`, the e-mail, and the password:

```bash
curl -sS http://127.0.0.1:8080/v1/bootstrap \
  -H "X-Bootstrap-Token: dev-token" \
  -H "Content-Type: application/json" \
  -d '{"workspace_slug":"acme","workspace_name":"Acme",
       "owner_email":"you@example.com","password":"a-long-password"}'
```

E-mail and password sign-in is the default. Google OIDC is optional and limited
to `gmail.com` unless `AGW_GOOGLE_ALLOWED_DOMAINS` says otherwise; set
`AGW_GOOGLE_CLIENT_ID` and `AGW_GOOGLE_CLIENT_SECRET`, and register
`<AGW_PUBLIC_BASE_URL>/v1/auth/oidc/google/callback` with Google.

## Docs

- [Operations, signup, identities, and deployment](docs/operations.md)
- [Terraform deployment](deploy/terraform/README.md)
- [Product specifications](.agents/)
- OpenAPI at `/docs` on a running gateway.

## Tests

```bash
.venv/bin/python -m pytest -q
```
