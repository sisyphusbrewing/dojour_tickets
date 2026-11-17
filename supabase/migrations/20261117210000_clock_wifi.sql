-- Clocking with the button only works on the club wifi (Sam, Nov 17 2026:
-- "People can also clock in and out on their phone but they have to be
-- connected to our wifi to do so").
--
-- There are two ways to clock in or out on the Clock page:
--   - Hold the phone to the tag at the bar. That stays as it was and works on
--     any connection: the tag is the proof of being there.
--   - Tap the big button. From now on that only works from the club's wifi.
-- How the database knows: every request arrives with the public internet
-- address it came from, and every phone on the club's wifi shares the club's
-- address. A manager standing in the club, on the wifi, taps "This is the
-- club wifi" once (Clock page, Payroll tab) and that address is kept here.
-- Until that has been done the rule is off and the button works as before, so
-- putting this in changes nothing by itself.
--
-- Things worth knowing:
--   - If the internet company gives the club a new address (rare), the button
--     stops working for everyone until a manager at the club taps "This is
--     the club wifi" again. The tag keeps working the whole time, and a
--     manager can switch the rule off from anywhere.
--   - An iPhone with iCloud Private Relay switched on hides its address, so
--     it looks like it isn't on the wifi. Those phones use the tag.
--   - "I left earlier" and "I forgot to clock in" are typed in by hand, are
--     marked as typed and tell the managers, so they still work from home.
--   - The address is not a secret, but it is kept out of the repo and is
--     never shown on a page.

alter table public.clock_settings add column if not exists club_nets cidr[] not null default '{}';

-- The network this request came from, as the outside world sees it. An
-- ordinary (IPv4) address is kept whole; a long (IPv6) one is cut to the part
-- every device on one wifi shares. Empty when it can't be told.
-- "cf-connecting-ip" is written by the front door of the database's web
-- address and can't be faked by the phone; "x-forwarded-for" is the fallback.
create or replace function public.clock_caller_net()
returns cidr language plpgsql stable set search_path = public as $$
declare h json; v_raw text; v_ip inet;
begin
  begin
    h := nullif(current_setting('request.headers', true), '')::json;
  exception when others then return null; end;
  v_raw := coalesce(nullif(trim(h ->> 'cf-connecting-ip'), ''),
                    nullif(trim(split_part(coalesce(h ->> 'x-forwarded-for', ''), ',', 1)), ''));
  if v_raw is null then return null; end if;
  begin v_ip := v_raw::inet; exception when others then return null; end;
  return network(set_masklen(v_ip, case when family(v_ip) = 6 then 64 else 32 end));
end $$;

-- 'unset' = no manager has said which network is the club's (the rule is off),
-- 'on' = this request came from the club wifi, 'off' = it didn't.
create or replace function public.clock_wifi_state()
returns text language sql stable security definer set search_path = public as $$
  select case when cardinality(club_nets) = 0 then 'unset'
              when coalesce(public.clock_caller_net() = any (club_nets), false) then 'on'
              else 'off' end
    from public.clock_settings $$;

-- Everything the Clock page needs to draw itself for the person signed in.
-- Same as before, plus "wifi" so the page can say so before the button is tapped.
create or replace function public.clock_status()
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_today date := public.schedule_today();
        v_open public.time_punches;
        v_shift public.shifts;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  select * into v_open from public.time_punches
   where user_id = v_me and clock_out is null and not removed and clock_in > now() - public.clock_forgot_after()
   order by clock_in desc limit 1;
  if v_open.shift_id is not null then
    select * into v_shift from public.shifts where id = v_open.shift_id;
  else
    select * into v_shift from public.shifts
     where id = public.clock_shift_for(v_me, coalesce(v_open.work_date, v_today), coalesce(v_open.clock_in, now()));
  end if;
  return jsonb_build_object(
    'name', public.schedule_name(v_me),
    'on_schedule', coalesce((select on_schedule from public.staff_roles where user_id = v_me), false),
    'now', now(),
    -- 'on' / 'off' the club wifi, or 'unset' while no manager has said which network it is.
    'wifi', public.clock_wifi_state(),
    'open', case when v_open.id is null then null else
      jsonb_build_object('id', v_open.id, 'clock_in', v_open.clock_in, 'in_at_bar', v_open.in_at_bar) end,
    'shift', case when v_shift.id is null then null else
      jsonb_build_object('id', v_shift.id, 'work_date', v_shift.work_date, 'start_time', v_shift.start_time,
                         'end_time', v_shift.end_time, 'position', v_shift.position) end,
    -- The last thing they finished today, so the page can say "Clocked out at 9:04 PM".
    'last', (select jsonb_build_object('id', t.id, 'clock_in', t.clock_in, 'clock_out', t.clock_out, 'tips', t.tips)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is not null
                and t.clock_out > now() - interval '12 hours'
              order by t.clock_out desc limit 1),
    -- Shifts from the last five weeks that are finished but have no tips typed in.
    'need_tips', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'work_date', t.work_date,
                              'clock_in', t.clock_in, 'clock_out', t.clock_out) order by t.clock_in desc)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is not null and t.tips is null
                and t.tips_run is null and t.work_date >= v_today - 35), '[]'::jsonb),
    'forgot', coalesce((select jsonb_agg(jsonb_build_object('id', t.id, 'work_date', t.work_date, 'clock_in', t.clock_in) order by t.clock_in)
               from public.time_punches t
              where t.user_id = v_me and not t.removed and t.clock_out is null
                and t.clock_in <= now() - public.clock_forgot_after()), '[]'::jsonb));
end $$;

-- The one button. Not on the clock: clock in. On the clock: clock out.
-- p_code is the code from the bar tag's link, when the tap came from it.
-- Same as before, plus the wifi rule for a tap that didn't come from the tag.
create or replace function public.clock_punch(p_code text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_me uuid := auth.uid();
        v_at boolean;
        v_open public.time_punches;
        v_did text;
begin
  if not public.is_staff() then raise exception 'Staff only.'; end if;
  if not exists (select 1 from public.staff_roles where user_id = v_me and on_schedule) then
    raise exception 'This login isn''t on the schedule, so it can''t clock in. Ask a manager to add it.'; end if;
  v_at := coalesce(nullif(trim(p_code), '') = (select bar_code from public.clock_settings), false);
  -- Two taps at the same instant wait their turn instead of both clocking in.
  perform pg_advisory_xact_lock(hashtext('clock:' || v_me::text));
  select * into v_open from public.time_punches
   where user_id = v_me and clock_out is null and not removed and clock_in > now() - public.clock_forgot_after()
   order by clock_in desc limit 1 for update;
  -- Without the tag, the button only works on the club wifi (once a manager
  -- has said which network that is). Nothing is written when it is refused.
  -- The hint lets the page tell this refusal from any other.
  if not v_at and public.clock_wifi_state() = 'off' then
    if v_open.id is not null then
      raise exception 'You''re not on the club wifi. Join it, or hold your phone to the tag at the bar, to clock out. Already gone home? Tap "I left earlier".'
        using hint = 'wifi';
    end if;
    raise exception 'You''re not on the club wifi. Join it, or hold your phone to the tag at the bar, to clock in.' using hint = 'wifi';
  end if;
  if v_open.id is not null then
    if now() - v_open.clock_in < interval '2 minutes' then
      update public.time_punches set removed = true, clock_out = now(), out_at_bar = v_at where id = v_open.id;
      v_did := 'undone';
    else
      update public.time_punches set clock_out = now(), out_at_bar = v_at where id = v_open.id;
      v_did := 'out';
    end if;
  else
    insert into public.time_punches (user_id, work_date, clock_in, shift_id, in_at_bar)
    values (v_me, public.schedule_today(), now(), public.clock_shift_for(v_me, public.schedule_today(), now()), v_at);
    v_did := 'in';
  end if;
  return public.clock_status() || jsonb_build_object('did', v_did);
end $$;

-- Managers: is the rule on, and is this phone on the club wifi right now?
create or replace function public.clock_wifi()
returns jsonb language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  return jsonb_build_object('state', public.clock_wifi_state(), 'seen', public.clock_caller_net() is not null);
end $$;

-- Managers: "This is the club wifi". Keeps the network this request came
-- from as the club's (replacing whatever was kept before), which switches the
-- rule on. Only to be tapped in the club, on the club wifi.
create or replace function public.clock_wifi_here()
returns jsonb language plpgsql security definer set search_path = public as $$
declare v_net cidr := public.clock_caller_net();
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  if v_net is null then raise exception 'Couldn''t tell which network this phone is on. Try again in a minute.'; end if;
  update public.clock_settings set club_nets = array[v_net];
  return public.clock_wifi();
end $$;

-- Managers: switch the rule off (the button works from anywhere again) until
-- someone taps "This is the club wifi" the next time.
create or replace function public.clock_wifi_off()
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  if not public.is_manager() then raise exception 'Managers only.'; end if;
  update public.clock_settings set club_nets = '{}';
  return public.clock_wifi();
end $$;

revoke all on function public.clock_caller_net(), public.clock_wifi_state(), public.clock_wifi(),
  public.clock_wifi_here(), public.clock_wifi_off() from public, anon, authenticated;
grant execute on function public.clock_wifi(), public.clock_wifi_here(), public.clock_wifi_off() to authenticated;

notify pgrst, 'reload schema';
