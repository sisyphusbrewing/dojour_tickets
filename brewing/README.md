# Batch log

A phone-friendly brew log for the brewhouse, served by GitHub Pages at

    https://staff.sisyphusbrewing.com/brewing/

Sign in with the same staff account as the door check-in app. On a phone,
"Add to Home Screen" gives it an icon and a full-screen window.

Three tabs: **Batches**, **Recipes** and **Order**. The batches tab opens with a board of
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

The **Order** tab builds the supplier order (grain, hops and yeast). List the brews coming up (with a
count for each), type what's on hand in pounds, and it adds up every recipe's
mash bill, groups the same malt written different ways (Rahr 2-Row, Pale Malt
2-Row, …), subtracts stock and rounds up to 55 lb bags. "Copy order" puts the
list on the clipboard to paste into an e-mail. Hops are added up the same way
and rounded up to 11 lb bags; dry yeast is in grams and rounded up to 500 g
bricks. Recipes with no yeast line are named under the yeast list. On-hand
amounts for all three live in `grain_stock`, keyed by name (pounds for grain
and hops, grams for yeast). Malts the supplier no longer
carries are swapped in `maltSub()`: any 55L crystal/caramel becomes Simpsons
Crystal T-50 and any 120L crystal becomes Simpsons Dark Roast Crystal (shown
that way on recipe cards too).

"Fill RahrBSG cart" opens rahrbsg.com with the whole order already in the
cart. Sign in there for account prices, add milling notes, and check out
yourself; nothing is ordered from the batch log. Each order line maps to a
RahrBSG item in `RAHR` in `index.html` (shown under each line as "RahrBSG:
…"). Lines with no mapping, or out of stock, are listed for adding by hand.
Hops map to the 11 lb product, and the newest crop year in stock is picked
when the cart is filled, so nothing needs changing at harvest. The lookup goes
through the `rahr-catalog` edge function because the RahrBSG catalog API
(VTEX) does not allow calls from other sites.

## Data

Tables in the Supabase project, created by the migrations in
`supabase/migrations/`: `batches`, `batch_ingredients`, `batch_log`,
`recipes`, `recipe_ingredients`, `tanks`, `grain_plan` (brews coming up) and
`grain_stock` (pounds on hand per malt). Deleting a batch removes its
ingredients and log. Deleting a recipe keeps the batches brewed from it.
Tanks are rows in `tanks`; add, rename or retire one there. Row-level security allows signed-in staff and the
service key only, like the tickets table.
