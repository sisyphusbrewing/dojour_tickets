-- Athletic NA reorder button (Sam, Nov 17 2026: "I also order Athletic NA
-- via e-mail ... that's with breakthrough beverage"). Rep: Anthony Pacyga at
-- Breakthru Beverage. The two styles and counts are a starting guess (Gmail
-- had no past order list); Sam is to say what he usually gets. Applied live
-- through the connector the same day.
insert into public.supply_reorders (label, vendor, to_email, greeting, intro, lines, subject, notes, sort)
select 'Athletic NA', 'Breakthru Beverage', 'anpacyga@breakthrubev.com', 'Hi Anthony,',
       'Can we get a delivery at Sisyphus? We need:',
       '[{"qty":1,"unit":"cases","item":"Athletic Run Wild IPA"},
         {"qty":1,"unit":"cases","item":"Athletic Upside Dawn Golden"}]'::jsonb,
       'Sisyphus Athletic order', 'Paid by autopay. Driver calls Sam to open the garage door.', 35
where not exists (select 1 from public.supply_reorders where label = 'Athletic NA');
