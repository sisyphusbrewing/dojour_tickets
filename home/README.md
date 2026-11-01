# Sam's home board

Full-screen portrait dashboard for the Apolosign wall display at Sam's house:
https://staff.sisyphusbrewing.com/home/

Sailing on top, Sisyphus underneath. Everything updates itself, and the page
reloads at 4 am so changes merged here reach the wall by morning.

- Wind map: earth.nullschool, centered on the boat
- On the water: wind and gusts (Open-Meteo, knots), waves (Open-Meteo marine), sunset, drive time (OSRM)
- Sail call: next 3 daytime windows, Go / Maybe / Drifty / Stay in from wind, gusts, waves, rain and temperature
- NWS nearshore forecast and active advisories for the marine zone
- Next at Sisyphus: next headliner and the next shows, from the store's products.json
- Calendar: rotates every 20 s between the Sisyphus calendar (next 4 show nights) and the personal calendar (next 4 days, only when `ical=` is set)
- Sailing word of the day, and what's on tap (GoTab feed)

## URL options

| Option | Default | |
|---|---|---|
| `boat=lat,lon` | Bayfield, WI | where the boat is |
| `spot=` | Apostle Islands | name shown in "On the water" |
| `zone=` | `LSZ147` | NWS nearshore zone (LSZ147 Sand Island to Bayfield, LSZ150 Outer Apostles, LSZ121 Chequamegon Bay) |
| `from=lat,lon` | Sisyphus | where the drive starts |
| `home=lat,lon` | Minneapolis | where the big temperature is for |
| `k=` | none | short key for calendars saved in `supabase/functions/ical-proxy/boards.ts` (not committed). Keeps the URL short enough to type on the screen |
| `ical=` | none | a calendar's secret iCal address, read through the `ical-proxy` edge function. Repeat it to show several calendars together |
