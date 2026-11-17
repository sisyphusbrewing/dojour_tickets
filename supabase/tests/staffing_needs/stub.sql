-- Bare stand-ins for the two tables the staffing numbers read: the website's
-- upcoming showtimes and the tickets sold. Only the columns that are used.
create table public.exchange_showtimes (
  variant_id bigint primary key, product_id bigint, show_title text, date_text text, ticket_type text,
  starts_at timestamptz, price numeric, seats_left integer, updated_at timestamptz default now());
create table public.tickets (
  id bigint generated always as identity primary key, show_title text, show_date text, tickets int, source text, email text);
