create table if not exists public.llm_prediction_cache (
    cache_key text primary key,
    match_id text not null,
    match_label text not null,
    match_date text not null,
    model text not null,
    generated_at text not null,
    payload_json jsonb not null
);

alter table public.llm_prediction_cache enable row level security;

create policy "llm prediction cache read"
on public.llm_prediction_cache
for select
using (true);

create policy "llm prediction cache insert"
on public.llm_prediction_cache
for insert
with check (true);

create policy "llm prediction cache update"
on public.llm_prediction_cache
for update
using (true)
with check (true);
