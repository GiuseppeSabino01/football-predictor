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

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'llm_prediction_cache'
          and policyname = 'llm prediction cache read'
    ) then
        create policy "llm prediction cache read"
        on public.llm_prediction_cache
        for select
        using (true);
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'llm_prediction_cache'
          and policyname = 'llm prediction cache insert'
    ) then
        create policy "llm prediction cache insert"
        on public.llm_prediction_cache
        for insert
        with check (true);
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'llm_prediction_cache'
          and policyname = 'llm prediction cache update'
    ) then
        create policy "llm prediction cache update"
        on public.llm_prediction_cache
        for update
        using (true)
        with check (true);
    end if;
end $$;

create table if not exists public.worldcup_simulation_runs (
    run_id text primary key,
    generated_at text not null,
    label text not null,
    model text not null,
    payload_json jsonb not null
);

alter table public.worldcup_simulation_runs enable row level security;

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'worldcup_simulation_runs'
          and policyname = 'worldcup simulation runs read'
    ) then
        create policy "worldcup simulation runs read"
        on public.worldcup_simulation_runs
        for select
        using (true);
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'worldcup_simulation_runs'
          and policyname = 'worldcup simulation runs insert'
    ) then
        create policy "worldcup simulation runs insert"
        on public.worldcup_simulation_runs
        for insert
        with check (true);
    end if;
end $$;
