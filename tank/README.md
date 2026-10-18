# Sam's Tank

The pitch form for Sam's Tank, a monthly show at Sisyphus. People send a
two-minute video pitch for a show; Sam picks one. Served by GitHub Pages and
embedded on the site:

    https://www.sisyphusbrewing.com/pages/sams-tank

The Shopify page "Sam's Tank" (handle `sams-tank`) iframes `tank/index.html`;
its body is in `tank/shopify-page.html`.

1. Someone fills in the form. Answers save on their device as they type.
2. The video is a link (YouTube, Instagram, Drive...) or an upload up to 50 MB
   into the private Supabase bucket `tank`.
3. **Send my pitch** saves it with `tank_pitch()` into `public.tank_pitches`.
4. The form calls the `job-applied` edge function with `kind: "tank"`, which
   starts the "Sam's Tank pitch" action (`tank_notify.yml` → `tank_notify.py`).
   That emails booking@sisyphusbrewing.com with the answers and a link to the
   video, Reply-To the person pitching. Set the repo variable `TANK_EMAIL_TO`
   to send them somewhere else.

Every pitch is on `tank/review.html` (door-app sign-in): watch, take notes,
mark it new / maybe / winner / pass.

Questions live in `tank/fields.js`; the form, the review list and the email
all read it. The pitch copy is plain HTML at the top of `tank/index.html`.
