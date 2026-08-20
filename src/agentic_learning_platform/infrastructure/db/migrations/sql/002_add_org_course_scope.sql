-- 002_add_org_course_scope
-- Adds organization/course scope to source_documents and document_chunks,
-- and replaces the global checksum uniqueness with one scoped to
-- (organization_id, course_id) — the same document bytes can now exist as
-- separate documents in different courses (see docs/architecture.md's
-- PR-004 section).
--
-- organization_id/course_id are TEXT, not UUID: their real values will come
-- from an external identity provider (Cognito/OIDC/an LMS) whose ID format
-- is not yet known.
--
-- Requires a clean database (no pre-existing rows) — ADD COLUMN ... NOT NULL
-- cannot be applied against rows that have no scope to backfill, and there
-- is no meaningful placeholder scope for old local demo data. Run
-- `docker compose down -v` before the first boot on this schema version.

ALTER TABLE source_documents
    ADD COLUMN organization_id TEXT NOT NULL,
    ADD COLUMN course_id TEXT NOT NULL;

ALTER TABLE document_chunks
    ADD COLUMN organization_id TEXT NOT NULL,
    ADD COLUMN course_id TEXT NOT NULL;

ALTER TABLE source_documents
    DROP CONSTRAINT IF EXISTS source_documents_checksum_sha256_key;

ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_org_course_checksum_key
    UNIQUE (organization_id, course_id, checksum_sha256);

-- Composite index for the scoped WHERE this migration exists to enable —
-- see PgVectorStoreAdapter.search(), which filters directly on this table
-- (not via a JOIN to source_documents) so the filter stays index-friendly
-- alongside the HNSW ANN index on `embedding`.
CREATE INDEX IF NOT EXISTS document_chunks_org_course_idx
    ON document_chunks (organization_id, course_id);

-- Structural integrity for the chunk<->document scope invariant: a chunk's
-- organization_id/course_id must match its parent document's, enforced by
-- PostgreSQL itself, not only by insert_document() being the sole writer.
-- The plain single-column FK below is superseded by the composite one (any
-- row satisfying the 3-column match necessarily satisfies the 1-column
-- one too) — replaced, not kept alongside it, to avoid a redundant
-- constraint enforcing a strict subset of the same rule.
ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_id_org_course_key
    UNIQUE (id, organization_id, course_id);

ALTER TABLE document_chunks
    DROP CONSTRAINT document_chunks_document_id_fkey;

ALTER TABLE document_chunks
    ADD CONSTRAINT document_chunks_document_id_fkey
    FOREIGN KEY (document_id, organization_id, course_id)
    REFERENCES source_documents (id, organization_id, course_id)
    ON DELETE CASCADE;
