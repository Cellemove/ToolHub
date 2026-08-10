-- External tools open a URL instead of an internal route.
alter table public.tools add column if not exists url text;

insert into public.tools (slug, name, description, icon, status, sort, url) values
  ('recast', 'Recast',
   'File converter — drop a file, pick a format, download the result.',
   'convert', 'live', 2, 'https://file-converter-app-iota.vercel.app'),
  ('invoice-checker', 'Invoice Checker',
   'Reconciles invoice files against live Shopify orders — prices, quantities and SKUs.',
   'invoice', 'live', 3, 'https://invoice2-0-tau.vercel.app'),
  ('adfactory', 'AdFactory',
   'Research-to-script ad pipeline — avatar deep dives, angles and ready ad scripts.',
   'ads', 'live', 4, 'https://cellumove-ad-factory.vercel.app')
on conflict (slug) do nothing;
