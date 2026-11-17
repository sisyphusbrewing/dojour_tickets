-- Reorder buttons list each kind on its own line (Sam, Nov 17 2026: "you
-- click pretzels then it has each flavor", "Same with Beef Jerky/ Beef
-- Sticks"), so each one gets its own tick box on the Supplies page.
-- Flavors and usual counts come from the last invoices: Von Hanson's #33010
-- (Oct 12 2026) and Ye Olde Butcher Shoppe #41179 (Sep 2026). Applied to the
-- live database through the Supabase connector on Nov 17 2026.
update public.supply_reorders
   set intro = 'Can we get a snack order delivered to Sisyphus this week? We need:',
       lines = '[{"qty":1,"unit":"case","item":"Parmesan pretzels"},
                 {"qty":1,"unit":"case","item":"Zesty Herb pretzels"},
                 {"qty":1,"unit":"case","item":"Dill Ranch pretzels"},
                 {"qty":1,"unit":"case","item":"Tangy Mustard pretzels"},
                 {"qty":1,"unit":"case","item":"Cheddar Sour Cream pretzels"}]'::jsonb,
       notes = 'Cases of 27 cups. Delivers the same week.'
 where label = 'Pretzels';

update public.supply_reorders
   set label = 'Beef jerky & sticks',
       intro = 'Can we get a delivery at Sisyphus? We need:',
       lines = '[{"qty":25,"unit":"","item":"Original Jerky"},
                 {"qty":25,"unit":"","item":"Sweet & Spicy Jerky"},
                 {"qty":25,"unit":"","item":"Pepper Jerky"},
                 {"qty":25,"unit":"","item":"Pepper Jack Sticks"},
                 {"qty":25,"unit":"","item":"Cheddar Sticks"}]'::jsonb,
       notes = 'Kevin delivers about a week later.'
 where label = 'Beef jerky';

-- Units are written plural ("cases", "kegs"); a count of exactly 1 drops the
-- s, so a ticked "1" reads "1 case Parmesan pretzels", not "1 cases".
update public.supply_reorders set lines = (
  select jsonb_agg(case when l->>'unit' in ('case') then jsonb_set(l, '{unit}', '"cases"') else l end order by o)
    from jsonb_array_elements(lines) with ordinality as x(l, o))
 where label = 'Pretzels';

create or replace function public.reorder_email_body(
  p_greeting text, p_intro text, p_lines jsonb, p_note text, p_signer text)
returns text language sql immutable set search_path = public as $$
  select concat_ws(E'\n',
    p_greeting, '',
    p_intro,
    (select string_agg(
              concat_ws(' ', trim_scale((l->>'qty')::numeric)::text,
                        nullif(case when (l->>'qty')::numeric = 1 and trim(l->>'unit') ~ 's$'
                                    then regexp_replace(trim(l->>'unit'), 's$', '')
                                    else trim(l->>'unit') end, ''),
                        trim(l->>'item')),
              E'\n' order by o)
       from jsonb_array_elements(coalesce(p_lines, '[]')) with ordinality as x(l, o)
      where coalesce((l->>'qty')::numeric, 0) > 0),
    case when nullif(trim(p_note), '') is not null then E'\n' || trim(p_note) end,
    '', 'Thanks much!', p_signer)
$$;
