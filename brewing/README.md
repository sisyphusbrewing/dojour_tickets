# Batch log

A phone-friendly brew log for the brewhouse, served by GitHub Pages at

    https://sisyphusbrewing.github.io/dojour_tickets/brewing/

Sign in with the same staff account as the door check-in app. On a phone,
"Add to Home Screen" gives it an icon and a full-screen window.

Two tabs: **Batches** and **Recipes**. The batches tab opens with a board of
the cellar (FV1 to FV8 and the brite tank) showing what is in each tank and
its day count.

What it tracks, per batch:

* beer name, batch #, style, tank, status (planned → brew day →
  fermenting → conditioning → kegged → on tap → finished / dumped)
* date brewed, date kegged off, volume, OG, FG (ABV is worked out from them),
  kegs filled, free-form notes
* ingredients: grain, hops, yeast, adjuncts, water, other, each with amount,
  unit, stage (mash, boil, whirlpool, dry hop, …) and timing
* a log of gravity and temperature readings and tasting notes, stamped with
  the day of fermentation

Recipes hold the binder: style, batch size, target OG/FG (and ABV), IBU, SRM,
mash temperature and time, boil time, yeast, where it came from (e.g. "Binder
p. 12"), process notes and the ingredient list.

Edits save as soon as a field changes. "Brewed today" and "Kegged off today"
set the dates and status in one tap. "Brew this" on a recipe starts a batch
with the recipe's ingredients, size and target OG copied in. "Save as recipe"
on a batch adds it to the library. "Duplicate batch" starts a new planned batch
with the same ingredients.

## Data

Tables in the Supabase project, created by the migrations in
`supabase/migrations/`: `batches`, `batch_ingredients`, `batch_log`,
`recipes`, `recipe_ingredients` and `tanks`. Deleting a batch removes its
ingredients and log. Deleting a recipe keeps the batches brewed from it.
Tanks are rows in `tanks`; add, rename or retire one there. Row-level security allows signed-in staff and the
service key only, like the tickets table.
