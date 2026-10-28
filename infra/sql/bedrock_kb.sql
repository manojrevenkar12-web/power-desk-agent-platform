-- One-time setup of the Aurora PostgreSQL table that the Bedrock knowledge base writes to.
-- Run with the RDS Data API as the cluster admin after the first deploy (see docs/RUNBOOK.md).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS bedrock_kb;
CREATE TABLE IF NOT EXISTS bedrock_kb.desk_chunks (
  id uuid PRIMARY KEY,
  embedding vector(1024),
  chunks text,
  metadata json,
  custom_metadata jsonb
);
CREATE INDEX IF NOT EXISTS desk_chunks_embedding ON bedrock_kb.desk_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS desk_chunks_text ON bedrock_kb.desk_chunks USING gin (to_tsvector('simple', chunks));
CREATE INDEX IF NOT EXISTS desk_chunks_meta ON bedrock_kb.desk_chunks USING gin (custom_metadata);
