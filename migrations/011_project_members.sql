-- 011: project membership and invitations for hosted deployments (sion_api.projects).
-- The identity provider (Supabase Auth) only proves who a user is; which projects they may
-- read or write lives here, next to the knowledge it guards. Additive and idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS project_members (
  project_id    UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  user_subject  VARCHAR(255) NOT NULL,
  role          VARCHAR(16) NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  email         VARCHAR(320),
  added_by      VARCHAR(255),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, user_subject)
);

CREATE INDEX IF NOT EXISTS ix_project_members_user_subject ON project_members (user_subject);

-- Invitations carry only a SHA-256 of their one-time token; the token itself is shown once.
CREATE TABLE IF NOT EXISTS project_invites (
  id            UUID PRIMARY KEY,
  project_id    UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  token_sha256  CHAR(64) NOT NULL UNIQUE,
  role          VARCHAR(16) NOT NULL CHECK (role IN ('editor', 'viewer')),
  email         VARCHAR(320),
  created_by    VARCHAR(255) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL,
  accepted_by   VARCHAR(255),
  accepted_at   TIMESTAMPTZ,
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_project_invites_project ON project_invites (project_id);

COMMIT;
