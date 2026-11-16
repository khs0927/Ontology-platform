# Local stack with Docker Compose

`compose.yaml` runs PostgreSQL 17 with pgvector, applies the Sion core migrations once, and
starts the Sion API. It is meant for local development and for the CI smoke test
(`verify.yml`, job `compose-smoke`), not as a production deployment.

```bash
cp deploy/compose.env.example .env      # .env is git-ignored
# set SION_DB_PASSWORD and SION_API_TOKENS_JSON (tokens of 16+ characters, e.g. openssl rand -hex 24)
docker compose up -d --build --wait
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/v1/graphrag/status
docker compose down          # add -v to delete the database volume
```

| Service | What it does |
|---|---|
| `db` | `pgvector/pgvector:0.8.6-pg17`, published on `127.0.0.1:${SION_DB_PORT:-55433}` |
| `migrate` | `sion-migrate --skip-regulation`, then exits; the API starts only after it succeeds |
| `api` | `uvicorn sion_api.main:app` on `127.0.0.1:${SION_API_PORT:-8000}`, health check `/health/ready` |

- Requests reach the container through Docker's port forward, not from `127.0.0.1`, so the API
  runs in `bearer` mode and every call needs a token from `SION_API_TOKENS_JSON`.
- `SION_API_EXTRAS` installs extras into the image, for example `rag` (LightRAG GraphRAG) or
  `rag,regulation`. With `rag`, set `SION_GRAPHRAG_EMBED_MODEL`, `_DIM` and `_BASE_URL` to an
  OpenAI-compatible embedding server. LightRAG then stores its tables in the same database with
  `PGTableGraphStorage`, one workspace per project (see `docs/GRAPHRAG.md`). Do not set
  `POSTGRES_WORKSPACE`: it would merge every project into one index, so per-project requests
  answer 503 while it is set.
- Behind a TLS-intercepting proxy, build with the proxy's CA as a BuildKit secret; it is used
  only during `pip install` and is not stored in the image:
  `docker build --secret id=pip_ca,src=/path/to/ca.pem -f deploy/api.Dockerfile -t sion-api:local .`
