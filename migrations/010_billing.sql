-- 010: Paddle Billing entitlements for hosted deployments (sion_api.billing).
-- One row per Paddle subscription plus an idempotency ledger of processed webhook events.
-- No customer PII is stored. Additive and idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS billing_events (
  event_id     VARCHAR(64) PRIMARY KEY,
  event_type   VARCHAR(80) NOT NULL,
  occurred_at  TIMESTAMPTZ NOT NULL,
  outcome      VARCHAR(20) NOT NULL,
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS billing_subscriptions (
  subscription_id     VARCHAR(64) PRIMARY KEY,
  customer_id         VARCHAR(64),
  user_subject        VARCHAR(255),
  status              VARCHAR(32) NOT NULL,
  price_ids           JSONB NOT NULL DEFAULT '[]'::jsonb,
  product_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
  current_period_end  TIMESTAMPTZ,
  scheduled_change    VARCHAR(32),
  last_event_at       TIMESTAMPTZ NOT NULL,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_billing_subscriptions_user_subject ON billing_subscriptions (user_subject);

COMMIT;
