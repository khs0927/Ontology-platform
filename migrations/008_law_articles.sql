-- 008: canonical law-article store (law-knowledge consolidation, slice 1).
-- One row per article version; amendments add rows, nothing is updated in place.
-- Additive and idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS law_articles (
  id              UUID PRIMARY KEY,
  law_id          VARCHAR(64)  NOT NULL,
  law_name        VARCHAR(300) NOT NULL,
  law_kind        VARCHAR(40)  NOT NULL DEFAULT 'act',
  article_key     VARCHAR(16)  NOT NULL,
  title           TEXT,
  text            TEXT         NOT NULL,
  effective_from  DATE         NOT NULL,
  effective_to    DATE,
  promulgated_on  DATE,
  source_url      TEXT,
  publisher       VARCHAR(200) NOT NULL DEFAULT '국가법령정보센터',
  content_hash    VARCHAR(80)  NOT NULL,
  refs            JSONB        NOT NULL DEFAULT '[]'::jsonb,
  ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
  CONSTRAINT uq_law_article_version UNIQUE (law_id, article_key, effective_from),
  CONSTRAINT ck_law_article_period CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX IF NOT EXISTS idx_law_articles_law ON law_articles (law_id, article_key);

COMMIT;
