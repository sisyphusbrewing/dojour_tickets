# Comics

A seven-screen, tap-through pitch for comics: the name, the room, the money,
who's been up, what the night is like, and how to book. Phones first.

    https://www.sisyphusbrewing.com/pages/comics

The Shopify page "Comics" (handle `comics`) iframes `comics/index.html`; its
body is in `comics/shopify-page.html`. The festival NFC cards hold
`/pages/comics?t=nfc` and their QR codes `/pages/comics?t=qr`.

Copy lives in the `STEPS` list in `index.html`. Booking is a mailto to
booking@sisyphusbrewing.com with a short template. `#3` opens screen 3.

## Notes from comics

Send a comic `/pages/comics?c=<their-name>` and the walkthrough becomes a
feedback round: screen 1 says hi by name, and after "Want a weekend?" comes
"Now roast it" (questions in `comics/feedback.js`). Answers save with
`comic_feedback_submit()` into `public.comic_feedback`, then the `job-applied`
edge function (kind `comic`) starts `comic_notify.yml`, which emails
booking@ (repo variable `COMIC_EMAIL_TO` overrides). `comic_view()` logs how
far each named link got in `public.comic_views`; the email lists that too.
