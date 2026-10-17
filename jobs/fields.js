// Sisyphus job application: the questions. The form (jobs/index.html) and the
// email (job_notify.py) both read this list. The list after the "=" is plain
// JSON so Python can read it too.
var JOB_SECTIONS = [
  {
    "title": "Apply",
    "fields": [
      {"k": "name", "label": "Name", "req": true, "full": true, "placeholder": "First and last"},
      {"k": "email", "label": "Email", "type": "email", "req": true},
      {"k": "phone", "label": "Phone", "type": "tel", "req": true}
    ]
  },
  {
    "title": "Behind the bar",
    "fields": [
      {"k": "experience", "label": "Bartending experience", "type": "select", "req": true,
       "options": ["None yet, but I learn fast", "Under a year", "1 to 3 years", "3+ years"]},
      {"k": "start", "label": "Could start", "type": "date"},
      {"k": "where", "label": "Where have you worked?", "type": "textarea", "full": true,
       "placeholder": "Bars, restaurants, breweries. Anywhere you poured something for someone."},
      {"k": "availability", "label": "When can you work?", "type": "checks", "req": true, "full": true,
       "options": ["Weeknights", "Thursday nights", "Friday nights", "Saturday nights", "Sunday", "Weekend days"]},
      {"k": "resume", "label": "Résumé (optional)", "type": "file", "full": true,
       "help": "PDF, Word or a photo. Skip it if the answers above say it all."}
    ]
  },
  {
    "title": "The important part",
    "fields": [
      {"k": "beer", "label": "Favorite beer", "full": true, "placeholder": "Any brewery. We won't be hurt. Much."},
      {"k": "joke", "label": "The worst joke you know", "type": "textarea", "full": true},
      {"k": "else", "label": "Anything else?", "type": "textarea", "full": true}
    ]
  }
];
