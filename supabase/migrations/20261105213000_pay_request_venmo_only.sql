-- /payme/ is now just name + Venmo (Sam, Nov 5 2026). Show, role and a
-- phone or email are optional; missing ones are stored as '' so the
-- not-null columns hold. The pay sheet asks which show on Approve.
create or replace function public.pay_request(p_data jsonb)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid; v_amt numeric; v_end date;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 4000 then
    raise exception 'That is a lot of words. Sam will read the short version.';
  end if;
  if coalesce(trim(p_data->>'name'), '') = '' then raise exception 'We need your name.'; end if;
  if coalesce(trim(p_data->>'handle'), '') = '' then raise exception 'We need your Venmo username.'; end if;
  begin v_amt := nullif(p_data->>'amount', '')::numeric; exception when others then v_amt := null; end;
  if v_amt is not null and (v_amt <= 0 or v_amt > 20000) then v_amt := null; end if;
  begin v_end := nullif(p_data->>'show_end', '')::date; exception when others then v_end := null; end;
  -- A bot hammering the form should not flood booking@.
  if (select count(*) from public.pay_requests where created_at > now() - interval '1 hour') >= 30 then
    raise exception 'Lots of requests right now. Try again in a bit.';
  end if;
  insert into public.pay_requests (show_name, show_dates, show_end, name, handle, role, amount, email, phone, note)
    values (coalesce(left(trim(p_data->>'show_name'), 120), ''), nullif(left(trim(p_data->>'show_dates'), 60), ''), v_end,
            left(trim(p_data->>'name'), 120), left(trim(p_data->>'handle'), 60), coalesce(left(trim(p_data->>'role'), 40), ''), v_amt,
            nullif(left(trim(p_data->>'email'), 200), ''), nullif(left(trim(p_data->>'phone'), 40), ''),
            nullif(left(trim(p_data->>'note'), 1000), ''))
    returning id into new_id;
  return new_id;
end $$;

revoke all on function public.pay_request(jsonb) from public;
grant execute on function public.pay_request(jsonb) to anon, authenticated, service_role;
