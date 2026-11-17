\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set jay '00000000-0000-0000-0000-000000000004'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
-- The addresses are made-up ones kept for examples: 203.0.113.7 plays the
-- club's wifi, 198.51.100.9 plays somebody's home.
\set club '{"cf-connecting-ip":"203.0.113.7"}'
\set home '{"cf-connecting-ip":"198.51.100.9"}'
set role authenticated;

\echo == before any manager has set the club wifi, the rule is off: the button works from anywhere
select set_config('request.jwt.claim.sub', :'jay', false); select set_config('request.headers', :'home', false);
select case when (clock_status() ->> 'wifi') = 'unset' then 'ok' else 'FAIL' end as rule_is_off;
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as button_works_anywhere;
select case when (clock_punch(null) ->> 'did') = 'undone' then 'ok' else 'FAIL' end as and_undoes;

\echo == a staff login cannot set, read or switch off the club wifi (expect 3 ERRORs: Managers only)
select clock_wifi_here();
select clock_wifi();
select clock_wifi_off();
\echo == nor read the settings table (expect ERROR: permission denied)
select * from clock_settings;

\echo == a manager whose address cannot be told is asked to try again (expect ERROR: which network this phone is on)
select set_config('request.jwt.claim.sub', :'mgr', false); select set_config('request.headers', '', false);
select clock_wifi_here();
\echo == the manager, in the club on the wifi, taps "This is the club wifi": the rule is on
select set_config('request.headers', :'club', false);
select case when (clock_wifi_here() ->> 'state') = 'on' then 'ok' else 'FAIL' end as set_at_the_club;

\echo == Jay, on the club wifi, clocks in with the button
select set_config('request.jwt.claim.sub', :'jay', false);
select case when (clock_status() ->> 'wifi') = 'on' then 'ok' else 'FAIL' end as jay_on_wifi;
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as button_on_wifi;
reset role;
update time_punches set clock_in = now() - interval '3 hours' where clock_out is null;
select bar_code as code from clock_settings \gset
set role authenticated; select set_config('request.jwt.claim.sub', :'jay', false);

\echo == from home the button is refused, and says how to clock out (expect ERROR: not on the club wifi ... I left earlier)
select set_config('request.headers', :'home', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as jay_off_wifi;
select clock_punch(null);
select clock_punch('wrong-code');
select case when (clock_status() -> 'open') <> 'null'::jsonb then 'ok' else 'FAIL' end as still_on_the_clock;
\echo == (that was 2 ERRORs: a wrong code is no better than none)
\echo == the tag works on any connection: Jay clocks out with it, off the wifi
select case when (clock_punch(:'code') ->> 'did') = 'out' then 'ok' else 'FAIL' end as tag_works_anywhere;
\echo == from home, not on the clock, the button is refused too (expect ERROR: not on the club wifi ... to clock in)
select clock_punch(null);
select case when count(*) = 1 then 'ok' else 'FAIL' end as nothing_written from time_punches where not removed;

\echo == writing a shift in by hand still works from home (it is marked as typed and managers are told)
select clock_add_mine(schedule_today() - 1, '16:00', '21:00', null, 'Forgot to clock in');
select case when count(*) = 1 then 'ok' else 'FAIL' end as typed_from_home from time_punches where in_typed;

\echo == a made-up "forwarded" address does not get past the real one
select set_config('request.headers', '{"cf-connecting-ip":"198.51.100.9","x-forwarded-for":"203.0.113.7"}', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as cannot_fake_it;
\echo == when only the forwarded list is there, its first address is used
select set_config('request.headers', '{"x-forwarded-for":"203.0.113.7, 10.0.0.1"}', false);
select case when (clock_status() ->> 'wifi') = 'on' then 'ok' else 'FAIL' end as forwarded_list;
\echo == nonsense where the address should be counts as not on the wifi, without an error
select set_config('request.headers', '{"cf-connecting-ip":"not an address"}', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as nonsense_is_off;
select set_config('request.headers', 'not json at all', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as broken_is_off;

\echo == the club gets a new, long (IPv6) address: the manager taps again and it replaces the old one
select set_config('request.jwt.claim.sub', :'mgr', false);
select set_config('request.headers', '{"cf-connecting-ip":"2001:db8:abcd:12:1::5"}', false);
select case when (clock_wifi_here() ->> 'state') = 'on' then 'ok' else 'FAIL' end as set_again;
select set_config('request.jwt.claim.sub', :'jay', false);
\echo == another phone on the same wifi shares the first half of that address: on
select set_config('request.headers', '{"cf-connecting-ip":"2001:db8:abcd:12:ffff:1:2:9"}', false);
select case when (clock_status() ->> 'wifi') = 'on' then 'ok' else 'FAIL' end as same_wifi_v6;
\echo == the wifi next door: off. The old address: off.
select set_config('request.headers', '{"cf-connecting-ip":"2001:db8:abcd:13::1"}', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as next_door_v6;
select set_config('request.headers', :'club', false);
select case when (clock_status() ->> 'wifi') = 'off' then 'ok' else 'FAIL' end as old_address_gone;

\echo == a manager switches the rule off from home: the button works from anywhere again
select set_config('request.jwt.claim.sub', :'mgr', false); select set_config('request.headers', :'home', false);
select case when (clock_wifi() ->> 'state') = 'off' then 'ok' else 'FAIL' end as manager_sees_off;
select case when (clock_wifi_off() ->> 'state') = 'unset' then 'ok' else 'FAIL' end as switched_off;
select set_config('request.jwt.claim.sub', :'jay', false);
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as button_anywhere_again;
