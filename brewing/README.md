# Batch log

A phone-friendly brew log for the brewhouse, served by GitHub Pages at

    https://sisyphusbrewing.github.io/dojour_tickets/brewing/

Sign in with the same staff account as the door check-in app. On a phone,
"Add to Home Screen" gives it an icon and a full-screen window.

What it tracks, per batch:

* beer name, batch #, style, fermenter, status (planned → brew day →
  fermenting → conditioning → kegged → on tap → finished / dumped)
* date brewed, date kegged off, volume, OG, FG (ABV is worked out from them),
  kegs filled, free-form notes
* ingredients: grain, hops, yeast, adjuncts, water, other, each with amount,
  unit, stage (mash, boil, whirlpool, dry hop, …) and timing
* a log of gravity and temperature readings and tasting notes, stamped with
  the day of fermentation

Edits save as soon as a field changes. "Brewed today" and "Kegged off today"
set the dates and status in one tap. "Duplicate recipe" starts a new planned
batch with the same ingredients, for rebrews.

## Data

Three tables in the Supabase project, created by
`supabase/migrations/20261013153000_brewing_batches.sql`:
`batches`, `batch_ingredients` and `batch_log`. Deleting a batch removes its
ingredients and log. Row-level security allows signed-in staff and the
service key only, like the tickets table.
