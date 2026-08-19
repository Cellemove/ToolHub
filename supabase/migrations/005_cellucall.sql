-- CelluCall — call-center tool.
insert into public.tools (slug, name, description, icon, status, sort, url) values
  ('cellucall', 'CelluCall',
   'Call-center workspace — delivered-order call lists from Shopify, synced live.',
   'call', 'live', 6, 'https://cellu-call.vercel.app')
on conflict (slug) do nothing;
