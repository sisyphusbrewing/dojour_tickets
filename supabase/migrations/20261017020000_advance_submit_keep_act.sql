-- The trip no longer asks for a stage name, so a trip submit must not blank
-- the act name (or a contact email) that the form or the desk already set.
create or replace function public.advance_submit(p_token text, p_data jsonb, p_headshot_path text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.advances;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 60000 then
    raise exception 'that is a lot of words';
  end if;
  update public.advances set
      data          = p_data,
      headshot_path = coalesce(p_headshot_path, headshot_path),
      act_name      = coalesce(nullif(left(p_data->>'stage_name', 120), ''), act_name),
      contact_name  = coalesce(contact_name, nullif(left(p_data->>'stage_name', 120), '')),
      contact_email = coalesce(contact_email, nullif(left(p_data->>'email', 200), '')),
      status        = 'submitted',
      submitted_at  = now()
    where token = p_token
    returning * into a;
  if a.id is null then
    raise exception 'No advance with that link';
  end if;
  return public.advance_public(a);
end $$;
