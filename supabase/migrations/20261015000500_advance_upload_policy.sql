-- The headshot upload policy looked up the token in public.advances, but a
-- storage policy runs as the uploader (anon), who cannot read that table. Check
-- the token through a security-definer function instead.

create or replace function public.advance_token_valid(p_token text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.advances a where a.token = p_token);
$$;
revoke all on function public.advance_token_valid(text) from public;
grant execute on function public.advance_token_valid(text) to anon, authenticated, service_role;

alter policy "Upload a headshot with a valid advance token" on storage.objects
  with check (bucket_id = 'advance' and public.advance_token_valid((storage.foldername(name))[1]));
