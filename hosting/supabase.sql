-- Going/Skip votes for the web version of the Free Food Map.
-- Paste this whole file into Supabase -> SQL Editor -> New query, and click Run (once).
--
-- One row per device and event. The site's public ("anon") key may read all votes and add,
-- change or remove votes. It cannot touch any other table. Votes are anonymous and not
-- tamper-proof: fine among fellows, not for anything that matters.

create table if not exists public.votes (
  device_id  text        not null check (char_length(device_id) between 8 and 64),
  event_id   text        not null check (char_length(event_id) between 6 and 40),
  vote       text        not null check (vote in ('going', 'skip')),
  name       text                 check (char_length(name) <= 24),
  updated_at timestamptz not null default now(),
  primary key (device_id, event_id)
);

alter table public.votes enable row level security;

drop policy if exists "anyone reads votes"   on public.votes;
drop policy if exists "anyone adds votes"    on public.votes;
drop policy if exists "anyone changes votes" on public.votes;
drop policy if exists "anyone removes votes" on public.votes;

create policy "anyone reads votes"   on public.votes for select to anon using (true);
create policy "anyone adds votes"    on public.votes for insert to anon with check (true);
create policy "anyone changes votes" on public.votes for update to anon using (true) with check (true);
create policy "anyone removes votes" on public.votes for delete to anon using (true);

grant select, insert, update, delete on public.votes to anon;

-- Old votes are ignored by the site after 30 days; this keeps the table small too.
create index if not exists votes_updated_at on public.votes (updated_at);

-- Suggestions from the site's Suggest form: an event link, or a newsletter/calendar.
-- Anyone may add and read suggestions; only you can approve one (Table Editor -> suggestions ->
-- tick "approved"), which lets the scanner read links from sites outside the Harvard allowlist.
create table if not exists public.suggestions (
  id         bigint generated always as identity primary key,
  kind       text        not null check (kind in ('event', 'source')),
  url        text                 check (url is null or (char_length(url) <= 500 and url ~* '^https?://')),
  title      text                 check (char_length(title) <= 120),
  note       text                 check (char_length(note) <= 400),
  name       text                 check (char_length(name) <= 24),
  approved   boolean     not null default false,
  created_at timestamptz not null default now(),
  check (url is not null or title is not null)
);

alter table public.suggestions enable row level security;

drop policy if exists "anyone reads suggestions" on public.suggestions;
drop policy if exists "anyone suggests"          on public.suggestions;

create policy "anyone reads suggestions" on public.suggestions for select to anon using (true);
create policy "anyone suggests"          on public.suggestions for insert to anon with check (approved = false);

grant select, insert on public.suggestions to anon;
