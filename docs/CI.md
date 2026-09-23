# Continuous integration

The `.github/workflows/verify.yml` workflow runs on pull requests to `main`,
pushes to `main`, and manual dispatch.

It currently verifies:

- the Python API/unit suite on SQLite, with SQLite foreign-key enforcement enabled;
- the canonical PostgreSQL migrations, replayed twice against an ephemeral
  pgvector 0.8.6 / PostgreSQL 16 service;
- the expected core table count, seed counts, and `pgcrypto` / `vector`
  extensions.

This CI does not validate a production database backup, Google Drive OAuth
upload, scheduled Windows synchronization, or import of the original structured
31-node / 43-edge map. Those checks require the relevant credentials, device, or
source data and remain separate operational checks.
