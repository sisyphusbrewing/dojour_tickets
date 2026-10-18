// Sam's Tank pitch form: the questions. The form (tank/index.html), the review
// list (tank/review.html) and the email (tank_notify.py) all read this list.
// The list after the "=" is plain JSON so Python can read it too.
var TANK_SECTIONS = [
  {
    "title": "The show",
    "fields": [
      {"k": "show_name", "label": "Show name", "req": true, "full": true, "placeholder": "Working titles welcome"},
      {"k": "logline", "label": "The show in one sentence", "req": true, "full": true,
       "placeholder": "One sentence. Make it count."},
      {"k": "format", "label": "What kind of show", "type": "select", "req": true,
       "options": ["Stand-up showcase", "Storytelling", "Game show", "Roast or debate", "Improv or sketch", "Something new"]},
      {"k": "run", "label": "Has it run before?", "type": "select", "req": true,
       "options": ["Never. Brand new.", "A few times", "It's running somewhere now"]},
      {"k": "cast", "label": "Who's in it", "type": "textarea", "full": true,
       "placeholder": "Host, regulars, the guy who does the thing."}
    ]
  },
  {
    "title": "The pitch",
    "fields": [
      {"k": "video_url", "label": "Link to your 2-minute pitch", "type": "url", "full": true,
       "placeholder": "YouTube, Instagram, Drive…",
       "help": "Make sure it isn't private. Unlisted is fine."},
      {"k": "video", "label": "Or upload it", "type": "file", "full": true,
       "help": "Up to 50 MB. A link is easier if your phone shoots in 4K."}
    ]
  },
  {
    "title": "You",
    "fields": [
      {"k": "name", "label": "Name", "req": true, "full": true, "placeholder": "First and last"},
      {"k": "email", "label": "Email", "type": "email", "req": true},
      {"k": "phone", "label": "Phone", "type": "tel"},
      {"k": "socials", "label": "Instagram or website", "full": true, "placeholder": "Where we can see more of you"},
      {"k": "else", "label": "Anything else?", "type": "textarea", "full": true}
    ]
  }
];
