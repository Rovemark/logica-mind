-- Logica Mind — Supabase schema
-- Run once in the Supabase SQL editor before using SupabaseStore.
-- pgvector is optional in v0.1 (ranking is done in-process); the embedding column
-- is jsonb so it works with or without the vector extension.

create table if not exists logica_mind_memory (
    id               text primary key,
    namespace        text not null default 'default',
    content          text not null,
    layer            text not null default 'semantic',
    embedding        jsonb,
    metadata         jsonb default '{}'::jsonb,
    importance       real default 0.5,
    tags             jsonb default '[]'::jsonb,
    source_ids       jsonb default '[]'::jsonb,
    created_at       timestamptz default now(),
    access_count     integer default 0,
    last_recalled_at text,
    surprise_score   real default 0.0
);

-- idempotent migration for tables created before the session columns existed
alter table logica_mind_memory add column if not exists last_recalled_at text;
alter table logica_mind_memory add column if not exists surprise_score real default 0.0;

create index if not exists idx_lm_ns_layer  on logica_mind_memory (namespace, layer);
create index if not exists idx_lm_created    on logica_mind_memory (namespace, created_at desc);
-- speeds up metadata/session scoping (metadata->>'session' = ...)
create index if not exists idx_lm_metadata   on logica_mind_memory using gin (metadata jsonb_path_ops);

-- ── Optional: native pgvector acceleration (SupabaseStore(use_rpc=True)) ─────
-- Pin embeddings to 1024 dims (Voyage output_dimension=1024 / OpenAI dimensions=1024).
create extension if not exists vector;
alter table logica_mind_memory add column if not exists embedding_vec vector(1024);
create index if not exists idx_lm_embedding_vec
    on logica_mind_memory using hnsw (embedding_vec vector_cosine_ops);

-- keep embedding_vec in sync with the jsonb embedding on write.
-- pgvector's vector input parses the jsonb '[...]' TEXT form directly (a text[]
-- cast is NOT valid). Only populate for 1024-dim vectors (the production size);
-- other dims (hashing 256, local 384, openai 1536) leave it NULL and fall back
-- to in-process ranking, so an off-dim embedding never aborts the write.
create or replace function lm_sync_embedding_vec() returns trigger as $$
begin
  if new.embedding is not null
     and jsonb_typeof(new.embedding) = 'array'
     and jsonb_array_length(new.embedding) = 1024 then
    new.embedding_vec := new.embedding::text::vector;
  else
    new.embedding_vec := null;
  end if;
  return new;
end; $$ language plpgsql;

drop trigger if exists trg_lm_sync_vec on logica_mind_memory;
create trigger trg_lm_sync_vec before insert or update on logica_mind_memory
  for each row execute function lm_sync_embedding_vec();

-- RPC used by SupabaseStore._rpc_search: cosine similarity, namespace/layer/metadata scoped
create or replace function search_logica_mind(
    p_namespace text,
    p_query_embedding jsonb,
    p_limit int default 20,
    p_layers text[] default null,
    p_metadata_filter jsonb default null
) returns table (
    id text, namespace text, content text, layer text, embedding jsonb,
    metadata jsonb, importance real, tags jsonb, source_ids jsonb,
    created_at timestamptz, access_count integer,
    last_recalled_at text, surprise_score real, similarity float
) language sql stable as $$
  with q as (select p_query_embedding::text::vector as v)
  select m.id, m.namespace, m.content, m.layer, m.embedding, m.metadata,
         m.importance, m.tags, m.source_ids, m.created_at, m.access_count,
         m.last_recalled_at, m.surprise_score,
         1 - (m.embedding_vec <=> (select v from q)) as similarity
  from logica_mind_memory m
  where m.namespace = p_namespace
    and m.embedding_vec is not null
    and (p_layers is null or m.layer = any(p_layers))
    and (p_metadata_filter is null or m.metadata @> p_metadata_filter)
  order by m.embedding_vec <=> (select v from q)
  limit p_limit;
$$;
