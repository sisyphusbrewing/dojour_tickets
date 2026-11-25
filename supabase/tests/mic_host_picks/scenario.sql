-- Host picks and the draw for the Tuesday open mic. Dates are built from
-- today, so this runs the same any day. Every check line should say ok.
\set ON_ERROR_STOP 0
create temp table t_ctx as select (now() at time zone 'America/Chicago')::date as today;
grant select on t_ctx to anon, authenticated;
insert into mic_signups (mic_date, name, email, status)
  select today, 'Hat ' || g, 'h' || g || '@x.co', 'hat' from t_ctx, generate_series(1, 15) g;
-- Two of them are first-timers: they always get up.
update mic_signups set first_time = true where name in ('Hat 14', 'Hat 15');
insert into mic_signups (mic_date, name, status, slot) select today, 'Staff Booked', 'booked', 1 from t_ctx;
insert into mic_hosts (mic_date, host_name, token) select today, 'Test Host', 'tok_today_aaaaaaaaaaaaaaaa' from t_ctx;
insert into mic_hosts (mic_date, host_name, token) select today - 7, 'Old Host', 'tok_old_bbbbbbbbbbbbbbbbbbbb' from t_ctx;

set role anon;
select case when mic_host_get('tok_today_aaaaaaaaaaaaaaaa')->>'host_name' = 'Test Host' then 'ok' else 'FAIL' end as "get: host name by link";
select case when mic_host_get('nope') is null then 'ok' else 'FAIL' end as "get: wrong link shows nothing";
select mic_host_save('tok_today_aaaaaaaaaaaaaaaa', array['  Pick A ', 'Pick B', '', 'Pick C']) is not null;
reset role;
select case when string_agg(name, ',' order by slot) = 'Pick A,Pick B,Pick C,Staff Booked' then 'ok' else 'FAIL ' || string_agg(name || slot, ',' order by slot) end
  as "save: before the draw, picks then staff-booked" from mic_signups where status in ('booked', 'drawn');
set role anon;
select mic_host_save('tok_today_aaaaaaaaaaaaaaaa', array['Pick D', 'Pick A', 'Pick B']) is not null;
reset role;
select case when string_agg(name, ',' order by slot) = 'Pick D,Pick A,Pick B,Staff Booked' then 'ok' else 'FAIL ' || string_agg(name || slot, ',' order by slot) end
  as "change: new picks replace old, in the new order" from mic_signups where status in ('booked', 'drawn');
select case when count(*) = 3 then 'ok' else 'FAIL' end as "change: old picks kept as cancelled" from mic_signups where host_pick and status = 'cancelled';

-- The automatic draw only runs on the day from 6:30: a past or future Tuesday does nothing.
set role anon;
select case when mic_draw(today - 7)->>'drawn' = '0' and mic_draw(today + 7)->>'drawn' = '0' then 'ok' else 'FAIL' end as "auto draw: not on other days" from t_ctx;
reset role;

-- Draw by hand (staff), 12 spots: both first-timers plus 10 of the other 13.
set request.jwt.claim.role = 'authenticated';
select case when (mic_draw(today, 12, true)->>'drawn')::int = 12 then 'ok' else 'FAIL' end as "draw: 12 in all" from t_ctx;
select case when (mic_draw(today, 12, true)->>'drawn')::int = 0 then 'ok' else 'FAIL' end as "draw: second draw does nothing" from t_ctx;
reset request.jwt.claim.role;
select case when count(*) = 3 then 'ok' else 'FAIL' end as "draw: 3 not drawn" from mic_signups where status = 'not_drawn';
select case when count(*) = 2 then 'ok' else 'FAIL' end as "draw: first-timers all up" from mic_signups where first_time and status = 'drawn';
-- 4 prebooked, 12 drawn: blocks of 3.
select case when string_agg(case when status = 'drawn' then 'R' else left(name, 1) || right(name, 1) end, ' ' order by slot)
                 = 'R R R PD R R R PA R R R PB R R R Sd' then 'ok'
            else 'FAIL ' || string_agg(case when status = 'drawn' then 'R' else name end, ' ' order by slot) end
  as "order: blocks of drawn names, each closed by a prebooked comic"
  from mic_signups where status in ('booked', 'drawn');
select case when array_agg(slot order by slot) = array(select generate_series(1, 16)) then 'ok' else 'FAIL' end as "order: slots 1 to 16"
  from mic_signups where status in ('booked', 'drawn');
create temp table t_drawn as select id, slot from mic_signups where status = 'drawn';
-- Host changes picks after the draw: drawn names keep their relative order.
set role anon;
select mic_host_save('tok_today_aaaaaaaaaaaaaaaa', array['Pick A', 'Pick B', 'Pick C', 'Pick D']) is not null;
select case when jsonb_array_length(mic_host_get('tok_today_aaaaaaaaaaaaaaaa')->'lineup') = 17
            and mic_host_get('tok_today_aaaaaaaaaaaaaaaa')->>'drawn' = 'true' then 'ok' else 'FAIL' end as "get: host sees full lineup after draw";
reset role;
select case when (select array_agg(id order by slot) from mic_signups where status = 'drawn')
               = (select array_agg(id order by slot) from t_drawn) then 'ok' else 'FAIL' end as "redo picks: drawn order kept";
-- 5 prebooked now (4 picks + staff-booked), 12 drawn: blocks of 2, 2, 3, 2, 3.
select case when string_agg(case when status = 'drawn' then 'R' else right(name, 1) end, '' order by slot) = 'RRARRBRRRCRRDRRRd'
            then 'ok' else 'FAIL ' || string_agg(case when status = 'drawn' then 'R' else right(name, 1) end, '' order by slot) end
  as "redo picks: still interleaved" from mic_signups where status in ('booked', 'drawn');

-- Expect 6 ERRORs below: five names, wrong link, past mic, anon reading hosts,
-- anon drawing by hand, anon writing mic_draws.
set role anon;
select mic_host_save('tok_today_aaaaaaaaaaaaaaaa', array['1','2','3','4','5']);
select mic_host_save('wrong-link-wrong-link-wrong', array['x']);
select mic_host_save('tok_old_bbbbbbbbbbbbbbbbbbbb', array['x']);
select token from mic_hosts;
select mic_draw(today, 12, true) from t_ctx;
insert into mic_draws (mic_date, spots, how) values ('2030-01-01', 1, 'auto');
reset role;
select case when count(*) = 4 then 'ok' else 'FAIL' end as "refused saves changed nothing" from mic_signups where host_pick and status = 'booked';
-- The public lineup gives names only, and nothing before 6:35 (time-of-day
-- dependent, so this only checks it never leaks emails).
set role anon;
select case when (select bool_or((x->>'first')::boolean) from jsonb_array_elements(mic_host_get('tok_today_aaaaaaaaaaaaaaaa')->'lineup') x) then 'ok' else 'FAIL' end as "host page marks first-timers";
select case when coalesce(mic_public_lineup()::text, '') not like '%@%' then 'ok' else 'FAIL' end as "public lineup: no emails";
reset role;

-- Women's spots: a fresh Tuesday a week out, 20 in the hat, 4 ticked the box,
-- no first-timers. Every draw must put at least 3 of them on.
insert into mic_signups (mic_date, name, email, status, women_spot)
  select today + 7, 'W ' || g, 'w' || g || '@x.co', 'hat', g <= 4 from t_ctx, generate_series(1, 20) g;
set request.jwt.claim.role = 'authenticated';
select mic_draw(today + 7, 12, true) is not null from t_ctx;
reset request.jwt.claim.role;
select case when count(*) filter (where women_spot) >= 4 and count(*) = 12 then 'ok' else 'FAIL' end as "women: at least 30% (4 of 12)"
  from mic_signups, t_ctx where mic_date = today + 7 and status = 'drawn';
-- The name guess.
select case when mic_guess_woman('Stephanie Smith') and mic_guess_woman('Joslyne X') and not mic_guess_woman('Greg Y')
             and not mic_guess_woman('Joshua Z') and not mic_guess_woman(null) then 'ok' else 'FAIL' end as "guess by first name";
insert into mic_signups (mic_date, name, email, status) select today + 14, 'Elizabeth Q', 'eq@x.co', 'hat' from t_ctx;
select case when women_spot then 'ok' else 'FAIL' end as "new sign-up gets the guess" from mic_signups where email = 'eq@x.co';

-- 8 open spots by default since Nov 18 2026 (Sam: "Let's put 4 fewer people
-- up randomly on the tuesday mic"), at least 3 of them women.
insert into mic_signups (mic_date, name, email, status, women_spot)
  select today + 14, 'E ' || g, 'e' || g || '@x.co', 'hat', g <= 2 from t_ctx, generate_series(1, 14) g;
set request.jwt.claim.role = 'authenticated';
select case when (mic_draw(today + 14, p_by_hand => true)->>'drawn')::int = 8 then 'ok' else 'FAIL' end as "default draw: 8 spots" from t_ctx;
reset request.jwt.claim.role;
select case when count(*) filter (where women_spot) >= 3 and count(*) = 8 then 'ok' else 'FAIL' end as "women: at least 30% (3 of 8)"
  from mic_signups, t_ctx where mic_date = today + 14 and status = 'drawn';

-- Drawn last week = half a ticket in the hat this week, never zero (Sam, Nov
-- 24 2026: "less likely to get drawn 2 weeks in a row").
insert into mic_signups (mic_date, name, email, status) select today + 21, 'Repeat Rae', 'rae@x.co', 'drawn' from t_ctx;
insert into mic_signups (mic_date, name, email, status) select today + 21, 'Sat Out Sid', 'sid@x.co', 'not_drawn' from t_ctx;
insert into mic_signups (mic_date, name, email, status) select today + 21, 'Same Name', 'old@x.co', 'drawn' from t_ctx;
select case when mic_draw_weight(today + 28, 'Someone Else', ' RAE@x.co') = 0.5
             and mic_draw_weight(today + 28, 'same name', 'new@x.co') = 0.5
             and mic_draw_weight(today + 28, 'Sat Out Sid', 'sid@x.co') = 1
             and mic_draw_weight(today + 28, 'New Person', 'new2@x.co') = 1
             and mic_draw_weight(today + 35, 'Repeat Rae', 'rae@x.co') = 1
             and mic_draw_weight(today + 28, '', '') = 1
        then 'ok' else 'FAIL' end as "repeat odds: half only for last week's drawn (email or name)" from t_ctx;
-- Never zero: a hat of only last week's comics still fills every spot.
insert into mic_signups (mic_date, name, email, status) select today + 28, 'Repeat Rae', 'rae@x.co', 'hat' from t_ctx;
insert into mic_signups (mic_date, name, email, status) select today + 28, 'Same Name', 'other@x.co', 'hat' from t_ctx;
set request.jwt.claim.role = 'authenticated';
select case when (mic_draw(today + 28, 8, true)->>'drawn')::int = 2 then 'ok' else 'FAIL' end as "repeat odds: never zero" from t_ctx;
reset request.jwt.claim.role;
-- Over many tries, half a ticket beats a whole one about 1 time in 3.
select case when avg(case when random() ^ (1.0 / 0.5::numeric) > random() ^ (1.0 / 1::numeric) then 1 else 0 end) between 0.25 and 0.42
        then 'ok' else 'FAIL' end as "repeat odds: roughly a third as often first" from generate_series(1, 4000);
-- Real draws: 4 repeaters among 16, 4 spots, 300 times. Each repeater should
-- get up less often than a newcomer, but not never.
do $$
declare d date; k int; rep int := 0; fresh int := 0;
begin
  for k in 1..300 loop
    d := date '2031-01-07' + k * 14;
    insert into mic_signups (mic_date, name, email, status)
      select d - 7, 'R' || g, 'r' || g || '@x.co', 'drawn' from generate_series(1, 4) g;
    insert into mic_signups (mic_date, name, email, status)
      select d, 'R' || g, 'r' || g || '@x.co', 'hat' from generate_series(1, 4) g;
    insert into mic_signups (mic_date, name, email, status)
      select d, 'F' || g, 'f' || g || '@x.co', 'hat' from generate_series(1, 12) g;
    perform set_config('request.jwt.claim.role', 'authenticated', true);
    perform mic_draw(d, 4, true);
    rep := rep + (select count(*) from mic_signups where mic_date = d and status = 'drawn' and name like 'R%');
    fresh := fresh + (select count(*) from mic_signups where mic_date = d and status = 'drawn' and name like 'F%');
  end loop;
  create temp table t_rep as select rep / 4.0 / 300 as rep_rate, fresh / 12.0 / 300 as fresh_rate;
end $$;
select case when rep_rate > 0.05 and rep_rate < fresh_rate * 0.8 then 'ok' else 'FAIL ' || rep_rate || ' vs ' || fresh_rate end
  as "repeat odds: real draws favor newcomers, repeaters still get up" from t_rep;

-- "Tonight's host is" on the website: tonight's host by name, no link (Sam, Nov 24 2026).
set role anon;
select case when (mic_week_hosts()->'tuesday'->>'date')::date - today between 0 and 7
             and mic_week_hosts()::text not like '%tok_%'
             and ((mic_week_hosts()->'tuesday'->>'tonight')::boolean is false or mic_week_hosts()->'tuesday'->>'host' = 'Test Host')
        then 'ok' else 'FAIL' end as "week hosts: names only, this week's Tuesday" from t_ctx;
reset role;
