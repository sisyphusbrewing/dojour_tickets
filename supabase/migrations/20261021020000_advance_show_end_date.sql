-- A run of shows (Ali Sultan, Oct 22-24): the advance keeps the last night
-- so the welcome email and the trip ticket can say "Thu–Sat, October 22–24".
alter table public.advances add column if not exists show_end_date date;

create or replace function public.advance_public(a advances) returns jsonb language sql stable as $f$
  select jsonb_build_object(
    'show_name', a.show_name,
    'show_date', a.show_date,
    'show_end_date', a.show_end_date,
    'show_time', a.show_time,
    'contact_name', a.contact_name,
    'contact_email', a.contact_email,
    'status', a.status,
    'data', a.data,
    'headshot_path', a.headshot_path,
    'submitted_at', a.submitted_at,
    'trip_at', a.trip_at
  );
$f$;
