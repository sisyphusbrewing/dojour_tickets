-- Let a show's report go to more than one address (comma separated).
create or replace function public.agent_update_contact(p_token text, p_email text, p_name text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.show_agents; v_email text;
begin
  v_email := lower(regexp_replace(trim(p_email), '[[:space:]]*[,;][[:space:]]*', ', ', 'g'));
  if v_email !~ '^[^[:space:]@,]+@[^[:space:]@,]+\.[^[:space:]@,]+(, [^[:space:]@,]+@[^[:space:]@,]+\.[^[:space:]@,]+)*$' then
    raise exception 'That does not look like an email address';
  end if;
  update public.show_agents
     set agent_email = v_email, agent_name = coalesce(nullif(left(trim(p_name), 120), ''), agent_name),
         updated_at = now()
   where token = p_token
   returning * into a;
  if a.show_title is null then raise exception 'No report with that link'; end if;
  return public.agent_get(p_token);
end $$;
