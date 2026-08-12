-- Registered offers per market/product/bundle — powers the ROAS market overview.
-- One active offer per (market, product, bundle); registering again replaces it.
create table if not exists public.roas_offers (
  id uuid primary key default gen_random_uuid(),
  market text not null,
  product text not null,
  bundle text not null,
  currency text not null default 'USD',
  selling_price numeric not null,
  cogs_usd numeric not null, -- COGS convention: always USD
  psp_fee numeric not null default 0.07,
  vat numeric not null default 0,
  other_fees numeric not null default 0.01,
  min_margin numeric not null default 0.15,
  target_margin numeric not null default 0.20,
  status text not null default 'active' check (status = 'active'),
  created_at timestamptz not null default now(),
  unique (market, product, bundle)
);

alter table public.roas_offers enable row level security;

-- Normalize the former shorthand if this migration is reapplied to an early table.
update public.roas_offers set market = 'USA' where market = 'US';
-- Money is always stored as USD; market currencies are frontend display-only.
update public.roas_offers set currency = 'USD' where currency <> 'USD';

create policy "public read roas_offers"
  on public.roas_offers for select
  using (true);

-- Pre-created active configurations from the market-labelled reference-sheet rows.
-- The unlabeled "4 legging + sleeve + tshirt" row is deliberately excluded:
-- assigning it to a market without source data would make the overview incorrect.
insert into public.roas_offers
  (market, product, bundle, currency, selling_price, cogs_usd, psp_fee, vat, other_fees, min_margin, target_margin)
values
  ('UK', 'VLegging V1', '1 Legging', 'USD', 29.90, 7.75, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V1', '2 Leggings', 'USD', 47.90, 17.97, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V1', '3 Leggings', 'USD', 127.91, 23.08, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V1', '2 Leggings + Sleeve', 'USD', 53.55, 13.80, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V1', '3 Leggings + Sleeve + Patch', 'USD', 73.58, 19.87, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V2', '3 Leggings + Sleeve', 'USD', 79.95, 16.50, 0.07, 0, 0.01, 0.15, 0.20),
  ('UK', 'VLegging V2', '3 Leggings + Sleeve + Top Bra', 'USD', 80.00, 20.45, 0.07, 0, 0.01, 0.15, 0.20),
  ('USA', 'VLegging V2', '3 Leggings + Sleeve', 'USD', 69.61, 14.29, 0.07, 0, 0.01, 0.15, 0.20),
  ('USA', 'VLegging V2', '3 Leggings + Sleeve + Top Bra', 'USD', 80.00, 18.00, 0.07, 0, 0.01, 0.15, 0.20),
  ('DE', 'VLegging V1', '2 Leggings', 'USD', 46.00, 11.57, 0.07, 0, 0.01, 0.15, 0.20),
  ('DE', 'VLegging V1', '3 Leggings + Sleeve', 'USD', 57.00, 16.00, 0.07, 0, 0.01, 0.15, 0.20)
on conflict (market, product, bundle) do nothing;
