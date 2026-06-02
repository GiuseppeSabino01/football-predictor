create table if not exists matches (
    id text primary key,
    source text not null,
    competition text not null,
    season integer,
    match_date text not null,
    home_team text not null,
    away_team text not null,
    status text,
    venue text,
    stage text,
    raw_json text
);

create table if not exists news_articles (
    id text primary key,
    source text not null,
    title text not null,
    summary text,
    url text not null,
    published_at text
);

create table if not exists news_signals (
    id integer primary key autoincrement,
    team text not null,
    player text,
    signal_type text not null,
    severity text not null,
    confidence real not null,
    source_url text not null,
    reason text,
    availability text
);

create table if not exists predictions (
    id integer primary key autoincrement,
    match_id text not null,
    generated_at text not null,
    market text not null,
    selection text not null,
    probability real not null,
    fair_odd real,
    market_odd real,
    value_score real,
    recommendation text,
    confidence text
);

