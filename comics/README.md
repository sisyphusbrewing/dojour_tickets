# Comics

A five-screen, tap-through pitch Sam hands to comics he wants to book (NFC
card): hi, the two rooms, the deal, your weekend, and "How should we get in
touch?". Written in Sam's voice (/mnt/project-files/voice/). Phones first.

    https://www.sisyphusbrewing.com/pages/comics

The Shopify page "Comics" (handle `comics`) iframes `comics/index.html`; its
body is in `comics/shopify-page.html`. The NFC cards hold
`/pages/comics?t=nfc` and their QR codes `/pages/comics?t=qr`.

Copy lives in the `STEPS` list in `index.html`. The last screen asks how to
get in touch (directly, their agent, some other way), saves it with
`comic_feedback_submit()` as `data.kind = "booking"` (`tag` = `booking:nfc`
etc.), and `comic_notify.py` emails it to booking@. `#3` opens screen 3.

## Notes from comics

Send a comic `/pages/comics?c=<their-name>` and the walkthrough becomes a
feedback round: screen 1 says hi by name, and after "Want a weekend?" comes
"Now roast it" (questions in `comics/feedback.js`). Answers save with
`comic_feedback_submit()` into `public.comic_feedback`, then the `job-applied`
edge function (kind `comic`) starts `comic_notify.yml`, which emails
booking@ (repo variable `COMIC_EMAIL_TO` overrides). `comic_view()` logs how
far each named link got in `public.comic_views`; the email lists that too.
