// The "roast it" questions on the last screen of comics/index.html (shown when
// the link has ?c=<name>). comic_notify.py reads this too, so the email uses
// the same labels. Keep the value plain JSON.
var COMIC_FEEDBACK = [
  { "k": "book", "label": "Would this get you to book a weekend?", "type": "one",
    "options": ["Already emailing", "Probably", "Tell me more", "Not for me"] },
  { "k": "landed", "label": "Which screens landed?", "type": "many",
    "options": ["The name", "The room", "The money", "Recent company", "Your night", "Want a weekend?"] },
  { "k": "cut", "label": "Which one would you cut?", "type": "one",
    "options": ["The name", "The room", "The money", "Recent company", "Your night", "Cut nothing"] },
  { "k": "missing", "label": "What's missing?", "type": "text", "ph": "Hotel, pay details, a photo of the green room, a therapist" },
  { "k": "punch_up", "label": "Punch up a line. You're the professional.", "type": "text", "ph": "\"Same rock. Better lighting.\" should say..." },
  { "k": "name", "label": "Your name", "type": "short", "ph": "So I know who to thank" }
];
