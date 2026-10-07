-- Transactional outbox for the Sion core (public schema).
-- Same contract as the ORM model sion_api.models.OutboxEvent; idempotent (safe to replay).
-- Pattern adopted from ArchOntos (packages/regulation, ADR-0001): canonical writes and their
-- events commit atomically; projections are rebuildable consumers.

CREATE TABLE IF NOT EXISTS outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type varchar(50) NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type varchar(100) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  attempts integer NOT NULL DEFAULT 0 CONSTRAINT ck_outbox_attempts CHECK (attempts >= 0),
  last_error text,
  next_attempt_at timestamptz,
  consumer varchar(200)
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_events (published_at, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate ON outbox_events (aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished_created
  ON outbox_events (created_at) WHERE published_at IS NULL;
