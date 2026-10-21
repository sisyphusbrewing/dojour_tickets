// The comedian advance: one list used by the public form (index.html), the
// booking desk (booking.html) and the email (advance_notify.py). Add a field
// here and all three pick it up; answers live in advances.data keyed by "k".
//
// Everything after the "=" is plain JSON (advance_notify.py reads it as such).
// type: text (default) | email | tel | url | number | select | textarea | file
//       | checks (pick any; saved as "A, B")
// req: required   full: full width   help: small print under the field
// trip: the section is also asked by the welcome trip planner (trip.html)
window.ADVANCE_SECTIONS = [
  {
    "id": "act",
    "title": "Who you are",
    "fields": [
      {
        "k": "stage_name",
        "label": "Name, as it goes on the poster",
        "req": true,
        "full": true
      },
      {
        "k": "email",
        "label": "Email",
        "type": "email",
        "req": true
      },
      {
        "k": "phone",
        "label": "Cell",
        "type": "tel"
      },
      {
        "k": "role",
        "label": "You are the",
        "type": "select",
        "options": [
          "Headliner",
          "Feature",
          "Host",
          "Guest spot",
          "Not sure, ask Grace"
        ]
      },
      {
        "k": "hometown",
        "label": "Based in"
      },
      {
        "k": "agent_name",
        "label": "Agent or manager",
        "help": "If you have one. If you are reading this yourself, maybe not."
      },
      {
        "k": "agent_email",
        "label": "Their email",
        "type": "email"
      }
    ]
  },
  {
    "id": "promo",
    "title": "Promo",
    "intro": "This goes on the poster, the website and our socials. Give us the good stuff.",
    "fields": [
      {
        "k": "headshot",
        "label": "Headshot",
        "type": "file",
        "full": true,
        "help": "The biggest, sharpest one you have. It gets printed at 11 x 17, so no screenshots of screenshots."
      },
      {
        "k": "bio",
        "label": "Bio",
        "type": "textarea",
        "full": true,
        "req": true,
        "help": "Two to four sentences. Credits welcome. If it rambles we trim it, lovingly."
      },
      {
        "k": "credits",
        "label": "One-line credits",
        "full": true,
        "help": "\"As seen on ...\" Keep it true."
      },
      {
        "k": "instagram",
        "label": "Instagram",
        "placeholder": "@handle"
      },
      {
        "k": "tiktok",
        "label": "TikTok",
        "placeholder": "@handle"
      },
      {
        "k": "youtube",
        "label": "YouTube",
        "placeholder": "channel link"
      },
      {
        "k": "website",
        "label": "Website",
        "type": "url",
        "placeholder": "https://"
      },
      {
        "k": "clip_url",
        "label": "A clip we can post",
        "type": "url",
        "full": true,
        "help": "A link is fine. We will not pretend to have watched all of it."
      },
      {
        "k": "no_go",
        "label": "Anything we should not say about you",
        "type": "textarea",
        "full": true
      }
    ]
  },
  {
    "id": "travel",
    "title": "Getting here",
    "intro": "712 Ontario Ave W, Minneapolis. Parking is a whole thing; we will send the map.",
    "fields": [
      {
        "k": "travel_mode",
        "label": "Coming by",
        "type": "select",
        "options": [
          "Car",
          "Plane",
          "I live here",
          "Other"
        ]
      },
      {
        "k": "arrival",
        "label": "Arriving when",
        "placeholder": "Fri afternoon, flight lands 3:10"
      },
      {
        "k": "hotel",
        "label": "Hotel",
        "type": "select",
        "options": [
          "I have it covered",
          "Need one",
          "Not sure yet"
        ]
      },
      {
        "k": "hotel_nights",
        "label": "Which nights",
        "placeholder": "Fri and Sat"
      },
      {
        "k": "ride",
        "label": "Need a ride from the airport",
        "type": "select",
        "options": [
          "No",
          "Yes"
        ]
      },
      {
        "k": "dietary",
        "label": "Food allergies, diet, strong opinions",
        "full": true
      }
    ]
  },
  {
    "id": "stage",
    "title": "On stage",
    "fields": [
      {
        "k": "set_length",
        "label": "Set length (minutes)",
        "type": "number",
        "min": 5,
        "max": 120
      },
      {
        "k": "mic",
        "label": "Mic",
        "type": "select",
        "options": [
          "Whatever is there",
          "Handheld, no stand",
          "Handheld on a stand",
          "Wireless, I wander"
        ]
      },
      {
        "k": "stool",
        "label": "Stool",
        "type": "select",
        "options": [
          "No",
          "Yes"
        ]
      },
      {
        "k": "walk_on",
        "label": "Walk-on song",
        "placeholder": "Artist, title"
      },
      {
        "k": "intro",
        "label": "How the host introduces you",
        "type": "textarea",
        "full": true,
        "help": "Read word for word, so write it the way you want to hear it. Keep it to a breath."
      },
      {
        "k": "av",
        "label": "Projector, laptop, props, anything weird",
        "type": "textarea",
        "full": true
      },
      {
        "k": "bringing",
        "label": "Bringing your own opener or feature",
        "full": true,
        "placeholder": "Name, and their email"
      },
      {
        "k": "recording",
        "label": "Recording your set",
        "type": "select",
        "options": [
          "No",
          "Audio",
          "Video",
          "Both"
        ],
        "help": "Tell us, so the lights are right and nobody walks through the shot."
      }
    ]
  },
  {
    "id": "greenroom",
    "title": "Green room",
    "intro": "We stock it before you get here. Tell us what makes it a good night.",
    "trip": true,
    "fields": [
      {
        "k": "gr_snacks",
        "type": "checks",
        "full": true,
        "label": "Snacks",
        "options": [
          "Salty",
          "Sweet",
          "Fruit",
          "Veggies and dip",
          "Cheese and crackers",
          "Nothing, I eat after"
        ]
      },
      {
        "k": "gr_drinks",
        "type": "checks",
        "full": true,
        "label": "Drinks",
        "options": [
          "Our beer",
          "NA beer",
          "Wine",
          "Liquor",
          "Sparkling water",
          "Still water",
          "Soda",
          "Coffee",
          "Tea",
          "Kombucha"
        ]
      },
      {
        "k": "gr_wish",
        "full": true,
        "label": "The one thing that makes it a good night",
        "help": "Within reason. We are a brewery, not a yacht."
      }
    ]
  },
  {
    "id": "security",
    "title": "Security",
    "intro": "However you like it. Only Sam and Grace read this part.",
    "trip": true,
    "fields": [
      {
        "k": "sec_style",
        "type": "select",
        "label": "How you want security",
        "options": [
          "Nobody needs to notice me",
          "Someone near the stage, just in case",
          "Walk me in and out",
          "Escort all night",
          "Call me, it's a whole thing"
        ]
      },
      {
        "k": "sec_heckle",
        "type": "select",
        "label": "If someone heckles",
        "options": [
          "I handle it, stay out of it",
          "One warning, then out",
          "Out, immediately",
          "Let them cook"
        ]
      },
      {
        "k": "sec_concerns",
        "type": "textarea",
        "full": true,
        "label": "Anyone we should keep an eye out for",
        "help": "An ex, a superfan, a guy from Reddit. Photos help; email them to booking@sisyphusbrewing.com."
      }
    ]
  },
  {
    "id": "guestsets",
    "title": "Guest sets",
    "intro": "Got a friend who should be on the show? Hand them a guest set.",
    "trip": true,
    "fields": [
      {
        "k": "gs_want",
        "type": "select",
        "label": "Giving out guest sets",
        "options": [
          "No",
          "Yes"
        ]
      },
      {
        "k": "gs_who",
        "type": "textarea",
        "full": true,
        "label": "Who, and how long",
        "help": "Name, minutes, and a phone or Instagram so the host can find them."
      }
    ]
  },
  {
    "id": "guests",
    "title": "Guest list",
    "fields": [
      {
        "k": "guest_count",
        "label": "How many",
        "type": "number",
        "min": 0,
        "max": 50
      },
      {
        "k": "guest_names",
        "label": "Names",
        "type": "textarea",
        "full": true,
        "help": "First and last. A few is easy. A busload, we should talk."
      }
    ]
  },
  {
    "id": "merch",
    "title": "Merch",
    "fields": [
      {
        "k": "merch",
        "label": "Selling merch",
        "type": "select",
        "options": [
          "No",
          "Yes, I will sell it",
          "Yes, can someone sell it for me"
        ]
      },
      {
        "k": "merch_notes",
        "label": "What, and the prices",
        "full": true
      }
    ]
  },
  {
    "id": "pay",
    "title": "Getting paid",
    "intro": "You get 100% of the door. The $3 ticket fee pays the host and the feature. We settle up the night of the show.",
    "fields": [
      {
        "k": "pay_method",
        "label": "How you want it",
        "type": "select",
        "req": true,
        "options": [
          "Check",
          "Venmo",
          "Zelle",
          "PayPal",
          "Cash",
          "Direct deposit (we will send a form)"
        ]
      },
      {
        "k": "pay_handle",
        "label": "Handle, email or phone for that"
      },
      {
        "k": "payee",
        "label": "Make it out to",
        "help": "Legal name or company, exactly as the bank knows it."
      },
      {
        "k": "w9",
        "label": "W-9",
        "type": "select",
        "options": [
          "I will send one",
          "Already on file with you",
          "What is a W-9"
        ],
        "help": "Needed once you clear $600 with us in a year."
      }
    ]
  },
  {
    "id": "more",
    "title": "Anything else",
    "fields": [
      {
        "k": "anything",
        "label": "Questions, requests, confessions",
        "type": "textarea",
        "full": true
      }
    ]
  }
];
