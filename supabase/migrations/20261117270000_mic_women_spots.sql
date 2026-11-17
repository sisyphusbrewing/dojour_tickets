-- Tuesday open mic: save a few spots for women (Sam, Nov 17 2026: "There
-- should be some element of Gender balancing to make sure it's not all men
-- that make it up, Women usually sign up less often so it's nice to make sure
-- some women make it on" / "I think just making an inference by name is okay").
--
-- Each sign-up gets women_spot, a guess from the first name (mic_guess_woman:
-- a list of common women's first names, plus endings like -a, -elle, -lyn).
-- It's only a guess and stays behind the scenes, on no page (Sam, Nov 17
-- 2026: "This part of the sorting can be done behind the scenes"). At the draw the 12 spots fill in this order:
--   1. first-timers (all of them, up to 12),
--   2. then, if fewer than 3 of the comics so far are women_spot, enough
--      women_spot comics to reach 3 (at random among them, if there are that many),
--   3. then everyone else at random.
-- All of them are then shuffled together into the running order.

alter table public.mic_signups add column if not exists women_spot boolean not null default false;

create or replace function public.mic_guess_woman(p_name text)
returns boolean language sql immutable set search_path = public as $$
  with f as (select lower(regexp_replace(split_part(trim(coalesce(p_name, '')), ' ', 1), '[^A-Za-z]', '', 'g')) as n)
  select n = any (array[
    'abby', 'abigail', 'ada', 'adriana', 'adrienne', 'aisha', 'alana', 'alejandra', 'alexa', 'alexandra',
    'alexis', 'alice', 'alicia', 'alina', 'alisha', 'alison', 'allie', 'allison', 'alma', 'alyssa',
    'amanda', 'amber', 'amelia', 'amy', 'ana', 'anastasia', 'andrea', 'angel', 'angela', 'angelica',
    'angelina', 'angie', 'anita', 'ann', 'anna', 'annabelle', 'anne', 'annie', 'antonia', 'april',
    'ariana', 'arianna', 'ashley', 'ashlyn', 'aubrey', 'audrey', 'aurora', 'autumn', 'ava', 'avery',
    'barbara', 'beatrice', 'becca', 'becky', 'bella', 'belle', 'bernadette', 'beth', 'bethany', 'betty',
    'beverly', 'bianca', 'bonnie', 'brandi', 'brandy', 'brenda', 'brianna', 'bridget', 'brittany',
    'brooke', 'brooklyn', 'caitlin', 'caitlyn', 'callie', 'camila', 'camille', 'candace', 'cara',
    'carla', 'carly', 'carmen', 'carol', 'caroline', 'carolyn', 'cassandra', 'cassidy', 'cassie',
    'catherine', 'cathy', 'cecilia', 'celeste', 'celia', 'chanel', 'charlene', 'charlotte', 'chelsea',
    'cheryl', 'chloe', 'christina', 'christine', 'cindy', 'claire', 'clara', 'claudia', 'colleen',
    'courtney', 'crystal', 'cynthia', 'daisy', 'dana', 'danielle', 'daphne', 'darlene', 'dawn', 'deanna',
    'debbie', 'deborah', 'debra', 'delilah', 'denise', 'destiny', 'diana', 'diane', 'dominique',
    'donna', 'dora', 'doris', 'dorothy', 'eden', 'edith', 'eileen', 'elaine', 'eleanor', 'elena',
    'eliza', 'elizabeth', 'ella', 'ellen', 'ellie', 'eloise', 'elsa', 'emilia', 'emily', 'emma',
    'erica', 'erika', 'erin', 'esme', 'esther', 'eva', 'evelyn', 'faith', 'fatima', 'felicia', 'fiona',
    'frances', 'francesca', 'gabriela', 'gabriella', 'gabrielle', 'gail', 'gemma', 'georgia', 'geraldine',
    'gina', 'ginger', 'gloria', 'grace', 'gracie', 'greta', 'gretchen', 'gwen', 'gwendolyn', 'hailey',
    'haleigh', 'haley', 'hallie', 'hannah', 'harriet', 'hazel', 'heather', 'heidi', 'helen', 'helena',
    'hillary', 'holly', 'hope', 'imani', 'ingrid', 'irene', 'iris', 'isabel', 'isabella', 'isabelle',
    'ivy', 'jackie', 'jacqueline', 'jada', 'jade', 'jamie', 'jane', 'janelle', 'janet', 'janice',
    'jasmine', 'jaz', 'jazmin', 'jeanette', 'jeanne', 'jenna', 'jennifer', 'jenny', 'jessica', 'jill',
    'jillian', 'joan', 'joanna', 'jocelyn', 'jodi', 'josephine', 'joslyn', 'joy', 'joyce', 'judith',
    'judy', 'julia', 'juliana', 'julie', 'juliet', 'june', 'kaitlyn', 'kara', 'karen', 'kari', 'karina',
    'kate', 'katelyn', 'katherine', 'kathleen', 'kathryn', 'kathy', 'katie', 'katrina', 'kayla',
    'kaylee', 'keisha', 'kelly', 'kelsey', 'kendra', 'kenya', 'kerry', 'khadijah', 'kiara', 'kim',
    'kimberly', 'kristen', 'kristin', 'kristina', 'krystal', 'kylie', 'lacey', 'laila', 'lana', 'latoya',
    'laura', 'lauren', 'laurie', 'layla', 'leah', 'leila', 'lena', 'leslie', 'lila', 'lillian', 'lily',
    'linda', 'lindsay', 'lindsey', 'lisa', 'liz', 'liza', 'lois', 'lola', 'lori', 'lorraine', 'louise',
    'lucia', 'lucy', 'luna', 'lydia', 'lynn', 'mackenzie', 'madeline', 'madison', 'maggie', 'maria',
    'mariah', 'marie', 'marilyn', 'marissa', 'marjorie', 'martha', 'mary', 'maya', 'megan', 'meghan',
    'melanie', 'melissa', 'mercedes', 'meredith', 'mia', 'michelle', 'mikayla', 'mila', 'mildred',
    'miranda', 'molly', 'monica', 'monique', 'morgan', 'nadia', 'nancy', 'naomi', 'natalia', 'natalie',
    'natasha', 'nicole', 'nina', 'noelle', 'nora', 'norma', 'olivia', 'paige', 'pamela', 'patricia',
    'paula', 'pauline', 'pearl', 'peggy', 'penelope', 'penny', 'phoebe', 'priscilla', 'punkie', 'quinn',
    'rachel', 'raquel', 'rebecca', 'regina', 'renee', 'rhonda', 'riley', 'rita', 'roberta', 'robin',
    'rochelle', 'rosa', 'rose', 'rosemary', 'ruby', 'ruth', 'sabrina', 'sadie', 'sally', 'samantha',
    'sandra', 'sara', 'sarah', 'sasha', 'savannah', 'scarlett', 'selena', 'serena', 'shannon', 'sharon',
    'shauna', 'sheila', 'shelby', 'shelly', 'sherry', 'shirley', 'sierra', 'simone', 'sofia', 'sonia',
    'sophia', 'sophie', 'stacy', 'stella', 'stephanie', 'sue', 'susan', 'suzanne', 'sydney', 'tamara',
    'tammy', 'tanya', 'tara', 'tasha', 'teresa', 'terri', 'tiffany', 'tina', 'tracy', 'trinity',
    'valerie', 'vanessa', 'vera', 'veronica', 'vicki', 'victoria', 'violet', 'virginia', 'vivian',
    'wanda', 'wendy', 'whitney', 'willow', 'yasmin', 'yolanda', 'yvonne', 'zoe', 'zoey'
  ])
  or (length(n) > 3 and n ~ '(a|ette|elle|lyn|lynn|lyne|ine)$'
      and n <> all (array['joshua', 'luca', 'ezra', 'nikita', 'akira', 'garcia', 'elisha', 'dakota', 'shea']))
  from f
$$;
grant execute on function public.mic_guess_woman(text) to anon, authenticated, service_role;

-- New sign-ups get the guess as they come in; staff edits stay as they are.
create or replace function public.mic_signups_guess() returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' and not new.women_spot then new.women_spot := public.mic_guess_woman(new.name); end if;
  return new;
end $$;
create trigger mic_signups_guess_woman before insert on public.mic_signups
  for each row execute function public.mic_signups_guess();

-- Everyone already in a hat gets the guess too.
update public.mic_signups set women_spot = public.mic_guess_woman(name)
 where status = 'hat' and not women_spot;

create or replace function public.mic_draw(p_date date, p_spots int default 12, p_by_hand boolean default false)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_now timestamp := now() at time zone 'America/Chicago';
  v_n int;
  v_ft uuid[]; v_w uuid[]; v_r uuid[]; v_have int; v_left int;
  c_women int := 3;   -- spots saved for comics who ticked the box (Sam, Nov 17 2026)
begin
  if p_by_hand and coalesce(auth.role(), '') not in ('authenticated', 'service_role') then
    raise exception 'Staff only.';
  end if;
  p_spots := least(greatest(coalesce(p_spots, 12), 0), 60);
  -- One draw at a time per Tuesday, so two phones can't both draw.
  perform pg_advisory_xact_lock(hashtext('mic_draw'), p_date - date '2026-01-01');
  if not p_by_hand then
    if v_now < p_date + time '18:30' or p_date < v_now::date then
      return jsonb_build_object('drawn', 0, 'why', 'not draw time');
    end if;
    if exists (select 1 from public.mic_draws where mic_date = p_date) then
      return jsonb_build_object('drawn', 0, 'why', 'already drawn');
    end if;
    p_spots := 12;
  end if;
  if exists (select 1 from public.mic_signups where mic_date = p_date and status in ('drawn', 'not_drawn')) then
    return jsonb_build_object('drawn', 0, 'why', 'already drawn');
  end if;

  -- 1. First-timers.
  select coalesce(array_agg(id), '{}') into v_ft from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat' and first_time
     order by random() limit p_spots) x;
  v_left := p_spots - cardinality(v_ft);
  -- 2. Make sure at least 3 who ticked the box are on.
  select count(*) into v_have from public.mic_signups where id = any(v_ft) and women_spot;
  select coalesce(array_agg(id), '{}') into v_w from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat' and women_spot and not (id = any(v_ft))
     order by random() limit least(v_left, greatest(c_women - v_have, 0))) x;
  v_left := v_left - cardinality(v_w);
  -- 3. Everyone else at random.
  select coalesce(array_agg(id), '{}') into v_r from (
    select id from public.mic_signups where mic_date = p_date and status = 'hat'
       and not (id = any(v_ft)) and not (id = any(v_w))
     order by random() limit v_left) x;

  with ordered as (select id, row_number() over (order by random()) as n from unnest(v_ft || v_w || v_r) as u(id))
  update public.mic_signups s set status = 'drawn', slot = 1000 + o.n::int
    from ordered o where s.id = o.id;
  update public.mic_signups set status = 'not_drawn', slot = null
   where mic_date = p_date and status = 'hat';
  insert into public.mic_draws (mic_date, spots, how)
    values (p_date, p_spots, case when p_by_hand then 'by hand' else 'auto' end)
    on conflict (mic_date) do update set spots = excluded.spots, how = excluded.how, drawn_at = now();
  perform public.mic_renumber(p_date);
  select count(*) into v_n from public.mic_signups where mic_date = p_date and status = 'drawn';
  return jsonb_build_object('drawn', v_n);
end $$;
