-- New deployment URLs + Forklane.
update public.tools set url = 'https://invoice-checker-2.vercel.app/' where slug = 'invoice-checker';
update public.tools set url = 'https://ad-factory-zeta.vercel.app/' where slug = 'adfactory';

insert into public.tools (slug, name, description, icon, status, sort, url) values
  ('forklane', 'Forklane',
   'Controlled Shopify checkout and cart experiments — variants, lift and confidence.',
   'experiment', 'live', 5, 'https://forklane.vercel.app/')
on conflict (slug) do nothing;
