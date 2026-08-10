-- ToolHub tools registry. Run in the Supabase SQL editor (or `supabase db push`).
create table if not exists public.tools (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  description text not null default '',
  icon text not null default 'tool',
  status text not null default 'live', -- live | soon
  sort int not null default 0,
  created_at timestamptz not null default now()
);

alter table public.tools enable row level security;

create policy "public read tools"
  on public.tools for select
  using (true);

insert into public.tools (slug, name, description, icon, status, sort) values
  ('roas-breakeven', 'ROAS Calculator',
   'Break-even and target ROAS from price, COGS, fees and margin goals. Multi-currency.',
   'chart', 'live', 1)
on conflict (slug) do nothing;
