\set ON_ERROR_STOP 0
\set sam '00000000-0000-0000-0000-000000000001'
\set mgr '00000000-0000-0000-0000-000000000002'
\set dee '00000000-0000-0000-0000-000000000003'
\set jay '00000000-0000-0000-0000-000000000004'
\set door '00000000-0000-0000-0000-000000000005'
-- Every check prints "ok" or "FAIL". Lines marked (expect ERROR) are meant to fail.
\echo == set up: The manager posts a shift for Jay today
set role authenticated; select set_config('request.jwt.claim.sub', :'mgr', false);
insert into shifts (work_date, start_time, end_time, position, user_id, published)
values (schedule_today(), '16:00', '21:00', 'Bar', :'jay', true);

\echo == the door login cannot clock in (expect ERROR: Staff only)
select set_config('request.jwt.claim.sub', :'door', false);
select clock_punch(null);
\echo == a login that is not on the schedule cannot clock in (expect ERROR: is not on the schedule)
select set_config('request.jwt.claim.sub', :'sam', false);
select clock_punch(null);

\echo == Jay clocks in without the sticker: tied to today shift, not marked at the bar
select set_config('request.jwt.claim.sub', :'jay', false);
select case when (clock_punch('wrong-code') ->> 'did') = 'in' then 'ok' else 'FAIL' end as clock_in;
select case when shift_id is not null and not in_at_bar and clock_out is null then 'ok' else 'FAIL' end as tied_to_shift from time_punches;
select case when (clock_status() -> 'open') is not null and (clock_status() -> 'shift' ->> 'position') = 'Bar' then 'ok' else 'FAIL' end as status_shows_it;
\echo == a second tap inside two minutes undoes it
select case when (clock_punch(null) ->> 'did') = 'undone' then 'ok' else 'FAIL' end as undone;
select case when (clock_status() -> 'open') = 'null'::jsonb and (select bool_and(removed) from time_punches) then 'ok' else 'FAIL' end as nothing_open;

\echo == Jay taps the sticker: marked at the bar. Three hours later, clocks out.
select case when (clock_punch('x') ->> 'did') = 'in' then 'ok' else 'FAIL' end as in_again;
reset role;
update time_punches set in_at_bar = true, clock_in = now() - interval '3 hours' where clock_out is null;
select bar_code as code from clock_settings \gset
set role authenticated; select set_config('request.jwt.claim.sub', :'jay', false);
select case when (clock_punch(:'code') ->> 'did') = 'out' then 'ok' else 'FAIL' end as clock_out;
select case when out_at_bar and round(extract(epoch from clock_out - clock_in) / 3600) = 3 then 'ok' else 'FAIL' end as three_hours_at_bar
  from time_punches where not removed;
select case when (clock_status() -> 'last' ->> 'clock_out') is not null then 'ok' else 'FAIL' end as status_says_clocked_out;

\echo == staff see only their own hours; a manager sees everyone
select set_config('request.jwt.claim.sub', :'dee', false);
select case when count(*) = 0 then 'ok' else 'FAIL' end as darrin_sees_none from time_punches;
select set_config('request.jwt.claim.sub', :'mgr', false);
select case when count(*) = 2 then 'ok' else 'FAIL' end as grace_sees_all from time_punches;

\echo == staff cannot write hours straight into the table (expect 2 ERRORs: permission denied)
select set_config('request.jwt.claim.sub', :'dee', false);
insert into time_punches (user_id, work_date) values (:'dee', schedule_today());
update time_punches set clock_in = now() - interval '9 hours';

\echo == Dee forgets to clock out: 17 hours later the old one waits, and the button clocks him in fresh
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as darrin_in;
reset role;
update time_punches set clock_in = now() - interval '17 hours', work_date = ((now() - interval '17 hours') at time zone 'America/Chicago')::date
 where user_id = :'dee';
set role authenticated; select set_config('request.jwt.claim.sub', :'dee', false);
select case when (clock_status() -> 'open') = 'null'::jsonb and jsonb_array_length(clock_status() -> 'forgot') = 1 then 'ok' else 'FAIL' end as old_one_waits;
select case when (clock_punch(null) ->> 'did') = 'in' then 'ok' else 'FAIL' end as fresh_clock_in;
select (clock_status() -> 'forgot' -> 0 ->> 'id')::bigint as old_id, (clock_status() -> 'open' ->> 'id')::bigint as new_id \gset
\echo == he types when he left (5 hours after clocking in); managers are told
select (((clock_in + interval '5 hours') at time zone 'America/Chicago')::time)::text as left_at from time_punches where id = :old_id \gset
select case when (clock_left_at(:old_id, :'left_at') ->> 'did') = 'typed' then 'ok' else 'FAIL' end as typed;
select case when out_typed and round(extract(epoch from clock_out - clock_in) / 3600) = 5 then 'ok' else 'FAIL' end as five_hours_typed from time_punches where id = :old_id;
\echo == a time that has not happened yet is refused (expect ERROR)
select clock_left_at(:new_id, ((now() + interval '1 hour') at time zone 'America/Chicago')::time);
\echo == nobody can type a clock-out on someone else punch (expect ERROR: already clocked out)
select set_config('request.jwt.claim.sub', :'jay', false);
select clock_left_at(:new_id, ((now() - interval '1 minute') at time zone 'America/Chicago')::time);

\echo == staff cannot fix hours or read the sticker code (expect 2 ERRORs: Managers only)
select clock_fix(:new_id, null, schedule_today(), '10:00', '11:00', null, false);
select clock_bar_code();

\echo == The manager fixes Dee hours, adds a late night for Jay (past midnight = 9 hours), removes a mistake
select set_config('request.jwt.claim.sub', :'mgr', false);
select case when clock_bar_code() = :'code' then 'ok' else 'FAIL' end as manager_reads_code;
select case when clock_fix(:new_id, null, schedule_today() - 1, '10:00', '15:30', 42.5, false) = :new_id then 'ok' else 'FAIL' end as fixed;
select case when fixed_by is not null and tips = 42.50 and clock_hours(clock_in, clock_out) = 5.5 then 'ok' else 'FAIL' end as five_and_a_half from time_punches where id = :new_id;
select clock_fix(null, :'jay', schedule_today() - 2, '16:00', '01:00', null, false) as added_id \gset
select case when extract(epoch from clock_out - clock_in) / 3600 = 9 then 'ok' else 'FAIL' end as nine_hours_past_midnight from time_punches where id = :added_id;
select clock_fix(:added_id, null, null, null, null, null, true) as removed_id \gset
select case when removed and fixed_by is not null then 'ok' else 'FAIL' end as removed from time_punches where id = :removed_id;
\echo == hours in the future are refused (expect ERROR)
select clock_fix(null, :'jay', schedule_today() + 1, '16:00', '17:00', null, false);

\echo == tips: Jay types the credit tips for the finished shift, then corrects them
select set_config('request.jwt.claim.sub', :'jay', false);
select (clock_status() -> 'need_tips' -> 0 ->> 'id')::bigint as jaz_shift \gset
select case when jsonb_array_length(clock_status() -> 'need_tips') = 1 then 'ok' else 'FAIL' end as one_shift_needs_tips;
select case when (clock_tips(:jaz_shift, 120.555) ->> 'did') = 'tips' then 'ok' else 'FAIL' end as tips_saved;
select case when (clock_tips(:jaz_shift, 123.45) ->> 'did') = 'tips' and jsonb_array_length(clock_status() -> 'need_tips') = 0 then 'ok' else 'FAIL' end as tips_changed;
select case when tips = 123.45 then 'ok' else 'FAIL' end as tips_are_right from time_punches where id = :jaz_shift;
\echo == nobody can type tips on another person shift, or negative tips (expect 2 ERRORs)
select set_config('request.jwt.claim.sub', :'dee', false);
select clock_tips(:jaz_shift, 5);
select set_config('request.jwt.claim.sub', :'jay', false);
select clock_tips(:jaz_shift, -1);

\echo == forgot to clock in: Jay writes in a shift from three days ago, 5:30 PM to 12:30 AM = 7 hours, with tips
select case when (clock_add_mine(schedule_today() - 3, '17:30', '00:30', 88, 'forgot to clock in') ->> 'did') = 'added' then 'ok' else 'FAIL' end as written_in;
select case when in_typed and out_typed and tips = 88 and clock_hours(clock_in, clock_out) = 7 then 'ok' else 'FAIL' end as seven_hours_written_in
  from time_punches where user_id = :'jay' and work_date = schedule_today() - 3;
\echo == the same hours twice, a shift that is not over, and one six weeks back are refused (expect 3 ERRORs)
select clock_add_mine(schedule_today() - 3, '18:00', '20:00', null, '');
select clock_add_mine(schedule_today() + 1, '10:00', '11:00', null, '');
select clock_add_mine(schedule_today() - 40, '10:00', '11:00', null, '');

\echo == pay periods are two weeks from Monday Nov 2 2026
select case when clock_period_start(date '2026-11-02') = date '2026-11-02' and clock_period_start(date '2026-11-15') = date '2026-11-02'
             and clock_period_start(date '2026-11-16') = date '2026-11-16' and clock_period_start(date '2026-11-01') = date '2026-10-19'
        then 'ok' else 'FAIL' end as pay_periods;

\echo == payroll: staff cannot see it (expect ERROR: Managers only); the manager sees hours and tips per person
select * from clock_payroll(schedule_today(), null);
select set_config('request.jwt.claim.sub', :'mgr', false);
select name, hours, tips, shifts, written_in, no_tips from clock_payroll(schedule_today(), null);
-- Jay: 3.00 clocked (tips 123.45) + 7.00 written in (tips 88) = 10.00 h, $211.45, one written in.
-- Dee: 5.00 typed clock-out (no tips) + 5.50 fixed by The manager (tips 42.50) = 10.50 h, $42.50, one written in, one without tips.
select case when hours = 10.00 and tips = 211.45 and shifts = 2 and written_in = 1 and no_tips = 0 then 'ok' else 'FAIL' end as jaz_totals
  from clock_payroll(schedule_today(), null) where user_id = :'jay';
select case when hours = 10.50 and tips = 42.50 and shifts = 2 and written_in = 1 and no_tips = 1 then 'ok' else 'FAIL' end as darrin_totals
  from clock_payroll(schedule_today(), null) where user_id = :'dee';
\echo == a manager cannot mark payroll submitted (expect ERROR: Only the owner)
select clock_payroll_submit(schedule_today());
\echo == Sam marks it submitted: nothing is left unpaid, and the payroll itself still shows what was in it
select set_config('request.jwt.claim.sub', :'sam', false);
select clock_payroll_submit(schedule_today()) as run \gset
select case when count(*) = 0 then 'ok' else 'FAIL' end as nothing_left from clock_payroll(schedule_today(), null);
select case when sum(hours) = 20.50 and sum(tips) = 253.95 then 'ok' else 'FAIL' end as the_run_adds_up from clock_payroll(null, :run);
\echo == late tips: Dee types tips for a shift whose hours were already paid; only the tips are in the next payroll
select set_config('request.jwt.claim.sub', :'dee', false);
select case when (clock_tips(:old_id, 61.25) ->> 'did') = 'tips' then 'ok' else 'FAIL' end as late_tips;
select set_config('request.jwt.claim.sub', :'mgr', false);
select case when hours = 0 and tips = 61.25 and shifts = 0 then 'ok' else 'FAIL' end as only_the_late_tips
  from clock_payroll(schedule_today(), null) where user_id = :'dee';
\echo == paid hours and paid tips cannot be changed or removed (expect 3 ERRORs: already paid)
select clock_fix(:jaz_shift, null, schedule_today(), '09:00', '10:00', 123.45, false);
select clock_fix(:jaz_shift, null, null, null, null, null, true);
select set_config('request.jwt.claim.sub', :'jay', false);
select clock_tips(:jaz_shift, 1);
\echo == Sam takes the payroll back: everything is unpaid again
select set_config('request.jwt.claim.sub', :'sam', false);
select clock_payroll_undo(:run);
select case when sum(hours) = 20.50 and sum(tips) = 315.20 then 'ok' else 'FAIL' end as unpaid_again from clock_payroll(schedule_today(), null);
select case when (select count(*) from payroll_runs where undone_at is null) = 0 then 'ok' else 'FAIL' end as run_marked_undone;

\echo == still clocked in: one reminder after 11 hours, one 45 minutes past a shift end, never twice
reset role;
insert into time_punches (user_id, work_date, clock_in) values (:'jay', schedule_today(), now() - interval '12 hours');
insert into shifts (work_date, start_time, end_time, position, user_id, published)
values (((now() - interval '2 hours') at time zone 'America/Chicago')::date, ((now() - interval '2 hours') at time zone 'America/Chicago')::time,
        ((now() - interval '1 hour') at time zone 'America/Chicago')::time, 'Door', :'dee', true) returning id as late_shift \gset
insert into time_punches (user_id, work_date, clock_in, shift_id)
values (:'dee', ((now() - interval '2 hours') at time zone 'America/Chicago')::date, now() - interval '2 hours', :late_shift);
-- and one that is fine: clocked in an hour ago, shift not over
insert into shifts (work_date, start_time, end_time, position, user_id, published)
values (((now() - interval '1 hour') at time zone 'America/Chicago')::date, ((now() - interval '1 hour') at time zone 'America/Chicago')::time,
        ((now() + interval '1 hour') at time zone 'America/Chicago')::time, 'Bar', :'mgr', true) returning id as ok_shift \gset
insert into time_punches (user_id, work_date, clock_in, shift_id)
values (:'mgr', ((now() - interval '1 hour') at time zone 'America/Chicago')::date, now() - interval '1 hour', :ok_shift);
set role service_role;
select case when clock_queue_reminders() = 2 then 'ok' else 'FAIL' end as two_reminders;
select case when clock_queue_reminders() = 0 then 'ok' else 'FAIL' end as not_twice;
\echo == the reminder function is not for staff logins (expect ERROR: permission denied)
set role authenticated; select set_config('request.jwt.claim.sub', :'jay', false);
select clock_queue_reminders();

\echo == every notice that was written (read these through)
reset role;
select schedule_name(user_id) as told, kind, body from schedule_outbox where kind like 'clock%' order by id;
select case when (select count(*) from schedule_outbox where kind = 'clock_typed' and user_id = :'mgr') = 2
             and (select count(*) from schedule_outbox where kind = 'clock_fixed' and user_id = :'dee') = 1
             and (select count(*) from schedule_outbox where kind = 'clock_fixed' and user_id = :'jay') = 2
             and (select count(*) from schedule_outbox where kind = 'clock_open') = 2
        then 'ok' else 'FAIL' end as right_people_told;
