-- Jerky and sticks are ordered by the case (Sam, Nov 17 2026: "The jerky
-- order should probably be by cases too"). Ye Olde Butcher invoices bill 25
-- of each kind, so one case = 25. Applied live through the connector the
-- same day.
update public.supply_reorders
   set intro = 'Can we get a delivery at Sisyphus? We need (cases of 25):',
       lines = '[{"qty":1,"unit":"cases","item":"Original Jerky"},
                 {"qty":1,"unit":"cases","item":"Sweet & Spicy Jerky"},
                 {"qty":1,"unit":"cases","item":"Pepper Jerky"},
                 {"qty":1,"unit":"cases","item":"Pepper Jack Sticks"},
                 {"qty":1,"unit":"cases","item":"Cheddar Sticks"}]'::jsonb,
       notes = 'Cases of 25. Kevin delivers about a week later.'
 where label = 'Beef jerky & sticks';
