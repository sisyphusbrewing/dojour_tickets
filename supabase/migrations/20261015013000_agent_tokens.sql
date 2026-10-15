-- Agents get a private link in the weekly ticket report: with it they can ask
-- for today's numbers on demand (agent/index.html -> agent-report function)
-- and change the address the report goes to. Staff still see everything.

alter table public.show_agents
  add column if not exists token text unique default encode(gen_random_bytes(12), 'hex'),
  add column if not exists last_requested_at timestamptz;

update public.show_agents set token = encode(gen_random_bytes(12), 'hex') where token is null;
alter table public.show_agents alter column token set not null;

-- What the agent page may see.
create or replace function public.agent_get(p_token text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object('show_title', a.show_title, 'agent_name', a.agent_name, 'agent_email', a.agent_email,
                            'last_requested_at', a.last_requested_at)
    from public.show_agents a where a.token = p_token;
$$;

-- Change who gets the report.
create or replace function public.agent_update_contact(p_token text, p_email text, p_name text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare a public.show_agents;
begin
  if p_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' then
    raise exception 'That does not look like an email address';
  end if;
  update public.show_agents
     set agent_email = lower(trim(p_email)), agent_name = coalesce(nullif(left(trim(p_name), 120), ''), agent_name),
         updated_at = now()
   where token = p_token
   returning * into a;
  if a.show_title is null then raise exception 'No report with that link'; end if;
  return public.agent_get(p_token);
end $$;

revoke all on function public.agent_get(text) from public;
revoke all on function public.agent_update_contact(text, text, text) from public;
grant execute on function public.agent_get(text) to anon, authenticated, service_role;
grant execute on function public.agent_update_contact(text, text, text) to anon, authenticated, service_role;
