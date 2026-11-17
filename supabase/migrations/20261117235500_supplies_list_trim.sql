-- Supplies list clean-up (Sam, Nov 17 2026): "We don't use receipt paper
-- anymore", "we don't need wristbands on there", "don't need PBW cleaner,
-- star san on there", and the mic batteries "don't need to be on the show
-- part either, maybe put that in office".
-- Hidden, not deleted, so any of them can come back by setting active = true.
-- Already applied to the live database on Nov 17 2026.
update public.supply_items set active = false
 where name in ('Receipt paper (GoTab)', 'Wristbands', 'PBW cleaner', 'Sanitizer (Star San)');
update public.supply_items set category = 'Office', sort = 41
 where name = 'AA batteries (mics)';
