-- A settlement on the get-paid page. A manager can put a short statement on
-- a payee (the run, each show's tickets and door, the total) and the comic
-- sees it above the form at getpaid/?t=<token>. The comic can then say how
-- much of it to send now by Venmo/Zelle/PayPal/Cash App; the rest is a check
-- (Grace writes it). Their answer lands in payees.request.
--
-- statement: {"title": "...", "rows": [{"label": "...", "tickets": n, "amount": n}],
--             "total": n, "note": "..."}
-- request:   {"now_amount": n, "check_amount": n, "note": "..."}

alter table public.payees add column if not exists statement jsonb;
alter table public.payees add column if not exists request jsonb;

create or replace function public.payee_public(p public.payees)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'name', p.name, 'email', p.email, 'phone', p.phone, 'method', p.method, 'handle', p.handle,
    'legal_name', p.legal_name, 'w9_on_file', p.w9_path is not null, 'info_at', p.info_at,
    'statement', p.statement, 'request', p.request);
$$;

create or replace function public.payee_save(p_token text, p_data jsonb, p_w9_path text default null)
returns jsonb language plpgsql security definer set search_path = public as $$
declare p public.payees;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then
    raise exception 'data must be an object';
  end if;
  if length(p_data::text) > 4000 then
    raise exception 'that is a lot of words';
  end if;
  if p_w9_path is not null and split_part(p_w9_path, '/', 1) <> p_token then
    raise exception 'That W-9 is not in your folder';
  end if;
  update public.payees set
      method     = nullif(p_data->>'method', ''),
      handle     = nullif(left(trim(p_data->>'handle'), 120), ''),
      legal_name = nullif(left(trim(p_data->>'legal_name'), 160), ''),
      email      = coalesce(nullif(left(trim(p_data->>'email'), 200), ''), email),
      phone      = coalesce(nullif(left(trim(p_data->>'phone'), 40), ''), phone),
      request    = case when jsonb_typeof(p_data->'request') = 'object' then p_data->'request' else request end,
      w9_path    = coalesce(p_w9_path, w9_path),
      w9_at      = case when p_w9_path is not null then now() else w9_at end,
      info_at    = now()
    where token = p_token
    returning * into p;
  if p.id is null then
    raise exception 'No one with that link';
  end if;
  return public.payee_public(p);
end $$;
