# Docker + Postgres

Self-hosted deployment with the gateway and Postgres in containers. The gateway
runs in the `persistent` runtime, so SSE and MCP sessions are available.

## Start

```bash
cd deploy/docker
cp .env.example .env
# Replace POSTGRES_PASSWORD, AGW_SECRET_KEY, and AGW_BOOTSTRAP_TOKEN.
docker compose up -d --build
```

The gateway waits for Postgres, runs `agw migrate`, then starts on
`http://127.0.0.1:8080`. The placeholder UI is at `/`.

Generate secrets:

```bash
openssl rand -base64 48   # AGW_SECRET_KEY
openssl rand -base64 48   # AGW_BOOTSTRAP_TOKEN
openssl rand -hex 24      # POSTGRES_PASSWORD
```

## Bootstrap

```bash
curl -sS http://127.0.0.1:8080/v1/bootstrap \
  -H "X-Bootstrap-Token: $AGW_BOOTSTRAP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"workspace_slug":"acme","workspace_name":"Acme","owner_email":"you@example.com"}'
```

The response contains a session token, shown once. After the first workspace,
the bootstrap endpoint returns `410`.

## Data

- `postgres-data` keeps the database.
- `ca-data` keeps the internal CA. Back it up with the database; losing it
  invalidates every client certificate.

```bash
docker compose exec postgres pg_dump -U agw agw > backup.sql
docker run --rm -v deploy_docker_ca-data:/ca -v "$PWD":/backup alpine \
  tar -czf /backup/ca.tar.gz -C /ca .
```

## Upgrade

```bash
docker compose build gateway
docker compose up -d gateway
```

The container runs `agw migrate` before starting. With more than one gateway
replica, run migrations as a separate one-off command instead:

```bash
docker compose run --rm gateway agw migrate
```

## Operations

- Logs: `docker compose logs -f gateway`
- Health: `curl -fsS http://127.0.0.1:8080/healthz`
- Database shell: `docker compose exec postgres psql -U agw -d agw`
- Bootstrap token: change it in `.env` and recreate the gateway after the first
  workspace; the endpoint stays closed.

## Limitations

- The container uses the internal file-backed CA. For production, move the
  signing key to KMS/HSM or an external CA.
- Postgres runs as a single container. Use a managed database or a replicated
  setup for production.
- The compose file runs one gateway replica. Scale horizontally with an
  external load balancer and a shared Postgres; the application is stateless.
