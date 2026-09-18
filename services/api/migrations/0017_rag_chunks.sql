-- ARG-053 · The indexable corpus: norms, guides and the client's own documentation.
--
-- One store, as Phase 01 decided: the vectors live in pgvector beside everything else, with an
-- HNSW index, which at the scale of this corpus —tens of thousands of fragments— answers in
-- milliseconds.
--
-- `reference` is the point of the whole table: the citable place («RGPD art. 32.1.a»). A fragment
-- that cannot be quoted is of no use to a DPO. `origin` lets the assistant cite with propriety:
-- what the norm says is not what the client's own procedure says.
-- pgvector is in the image since S1-02, but no migration had needed it until now.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE argos.rag_chunks (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source       text NOT NULL,
  origin       text NOT NULL CHECK (origin IN ('norm', 'guide', 'client')),
  reference    text NOT NULL,
  text         text NOT NULL,
  embedding    vector(384) NOT NULL,
  chunk_sha256 text NOT NULL UNIQUE CHECK (chunk_sha256 ~ '^[0-9a-f]{64}$'),
  indexed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_rag_chunks_vector ON argos.rag_chunks
  USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_rag_chunks_origin ON argos.rag_chunks (origin);
-- Lexical search beside the vector one: article numbers are what embeddings treat worst (ARG-054).
CREATE INDEX ix_rag_chunks_text ON argos.rag_chunks
  USING gin (to_tsvector('spanish', reference || ' ' || text));

GRANT SELECT, INSERT ON argos.rag_chunks TO argos_ai;
GRANT USAGE ON SEQUENCE argos.rag_chunks_id_seq TO argos_ai;
