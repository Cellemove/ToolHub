-- Teardown — winning-ad deconstruction tool.
insert into public.tools (slug, name, description, icon, status, sort, url) values
  ('teardown', 'Teardown',
   'Winning-ad deconstruction — Gemini watches the ad and returns a frame-by-frame script plus the 14-part workbook.',
   'teardown', 'live', 7, 'https://teardown-gamma.vercel.app')
on conflict (slug) do nothing;
