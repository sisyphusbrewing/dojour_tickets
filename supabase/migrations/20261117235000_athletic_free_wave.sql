-- Sam, Nov 17 2026: "There's one more we order... the hazy NA" = Athletic
-- Free Wave Hazy IPA. Added to the Athletic NA button, 1 case. Applied live
-- through the connector the same day.
update public.supply_reorders
   set lines = lines || '[{"qty":1,"unit":"cases","item":"Athletic Free Wave Hazy IPA"}]'::jsonb
 where label = 'Athletic NA' and not lines @> '[{"item":"Athletic Free Wave Hazy IPA"}]';
