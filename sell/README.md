# How Shows Actually Sell

Two-page handout for comics (Oct 2026): tracked ads vs fan lists, the pixel, lessons from the booking side, and Sam's numbers story.

- `index.html` — the handout. Prints as two letter pages; on phones it becomes one column with a "Download the PDF" button.
- `how-shows-actually-sell.pdf` — the print file (rendered from `index.html` with Playwright `page.pdf`, Letter).
- `shopify-page.html` — body of the Shopify page `how-shows-sell`, which iframes this folder so comics only see sisyphusbrewing.com.

NFC tags and QR codes: `https://www.sisyphusbrewing.com/pages/how-shows-sell?t=nfc` (or `?t=qr`).
Headliner numbers are anonymized (Headliner #1 and #2). Don't add names.
