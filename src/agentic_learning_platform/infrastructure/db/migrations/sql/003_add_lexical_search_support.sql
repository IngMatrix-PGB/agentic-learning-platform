-- 003_add_lexical_search_support
-- Adds PostgreSQL native full-text search to document_chunks, for Hybrid
-- Retrieval (PR-006): Vector Search + PostgreSQL FTS + Reciprocal Rank
-- Fusion (RRF). This is PostgreSQL's own tsvector/ts_rank_cd ranking — NOT
-- the Okapi BM25 formula (see docs/architecture.md's PR-006 section; that
-- distinction is why this codebase always says "lexical search"/
-- "PostgreSQL FTS", never "BM25").
--
-- `content_tsv` is a GENERATED ALWAYS ... STORED column: PostgreSQL
-- (re)computes it automatically on every INSERT/UPDATE of `content`, so
-- IngestionService needs zero changes to keep this index in sync.
--
-- Unlike migration 002, this one does NOT require a clean database — a
-- generated column backfills its value for existing rows as part of the
-- ALTER TABLE itself, with no NOT NULL-without-a-default conflict.
--
-- 'spanish' is PostgreSQL's built-in text search configuration: Snowball
-- stemming + a Spanish stopword list, both included by PostgreSQL itself —
-- no tokenization/stemming/stopword code of our own to write or maintain.

ALTER TABLE document_chunks
    ADD COLUMN content_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED;

CREATE INDEX IF NOT EXISTS document_chunks_content_tsv_idx
    ON document_chunks USING GIN (content_tsv);
