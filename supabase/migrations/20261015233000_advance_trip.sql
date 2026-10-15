-- The welcome kit: when a comedian is booked, staff send an excited email
-- (advance_welcome.py) that links to the trip (advance/trip.html), the advance
-- one playful stop at a time. Each stop saves into the same advances.data as
-- the one-page form, merging rather than replacing; the last stop sends it in
-- with advance_submit like the form does.

alter table public.advances add column if not exists trip_at timestamptz;          -- last save from the trip
alter table public.advances add column if not exists welcome_sent_at timestamptz;  -- welcome email went out

create or replace function public.advance_public(a public.advances)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'show_name', a.show_name,
    'show_date', a.show_date,
    'show_time', a.show_time,
    'contact_name', a.contact_name,
    'contact_email', a.contact_email,
    'status', a.status,
    'data', a.data,
    'headshot_path', a.headshot_path,
    'submitted_at', a.submitted_at,
    'trip_at', a.trip_at
  );
$$;

-- Save one stop of the trip. Keys it sends replace the same keys in data;
-- everything else stays.
create or replace function public.advance_trip(p_token text, p_data jsonb, p_headshot_path text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.advances;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 20000 then
    raise exception 'that is a lot of words';
  end if;
  update public.advances set
      data          = data || p_data,
      headshot_path = coalesce(p_headshot_path, headshot_path),
      trip_at       = now()
    where token = p_token
    returning * into a;
  if a.id is null then
    raise exception 'No advance with that link';
  end if;
  return public.advance_public(a);
end $$;

revoke all on function public.advance_trip(text, jsonb, text) from public;
grant execute on function public.advance_trip(text, jsonb, text) to anon, authenticated, service_role;
