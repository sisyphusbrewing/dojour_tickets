// The one list of staff tools. The staff home page (/staff/) draws its tiles
// from it and the top bar on every tool (staff/nav.js) draws its "All tools"
// menu from it, so a new tool is added in exactly one place: here.
//
// For each tool:
//   id     short name, never reused (it is how "Your usual" remembers a tool)
//   title  what the tile says
//   desc   one plain sentence: what it is for
//   href   where it opens. Start with "/" for a page on this site.
//   min    the lowest login that can open it: door, staff, manager or owner
//   group  which heading it sits under (see STAFF_GROUPS)
//   ico    the picture on the tile
//   find   extra words the search box should match
//   flag   'voice' = only the logins on the voice notes list see it
//   out    true = opens in a new tab (it is not one of our pages)
var STAFF_GROUPS = [
  { id: 'show',   title: 'Show night' },
  { id: 'you',    title: 'Just for you' },
  { id: 'events', title: 'Tickets & events' },
  { id: 'comedy', title: 'Comedy' },
  { id: 'bar',    title: 'Bar & beer' }
];

var STAFF_TOOLS = [
  // Show night
  { id: 'door', group: 'show', min: 'door', ico: '🎟️', href: '/', title: 'Door',
    desc: 'Tonight’s guest list and check-in.', find: 'guest list check in tickets will call names' },
  { id: 'timer', group: 'show', min: 'staff', ico: '⏱️', href: '/timer/', title: 'Stage timer',
    desc: 'The light the comic sees. Started from the Stream Deck.', find: 'clock light time' },
  { id: 'deck', group: 'show', min: 'staff', ico: '🎛️', href: '/staff/stream-deck.html', title: 'Stream Deck guide',
    desc: 'What every button and knob at the bar does.', find: 'buttons sound lights music mic volume av' },
  { id: 'crash', group: 'show', min: 'staff', ico: '🧯', href: '/av/if-it-crashes.html', title: 'If the show computer restarts',
    desc: 'Get sound and lights back, step by step.', find: 'crash broken no sound help pc companion' },
  { id: 'supplies', group: 'show', min: 'staff', ico: '📦', href: '/supplies/', title: 'Supplies',
    desc: 'The stock sheet. Count it, and booking@ hears when something runs low.', find: 'stock inventory order low napkins count' },

  // Just for you
  { id: 'schedule', group: 'you', min: 'staff', ico: '🕓', href: '/schedule/', title: 'Schedule',
    desc: 'Who works when. Trade a shift, ask for time off, say when you can’t work.', find: 'shifts hours time off swap trade availability calendar when i work' },
  { id: 'voice', group: 'you', min: 'door', ico: '🎙️', href: '/voice/', title: 'Voice notes', flag: 'voice',
    desc: 'Record a meeting or a thought. Claude emails you the summary and to-dos.', find: 'record meeting memo' },

  // Tickets & events
  { id: 'manager', group: 'events', min: 'manager', ico: '📋', href: '/manager/', title: 'Manager',
    desc: 'Guest lists for every show, ticket counts, new shows, staff logins.', find: 'comps guest list new show logins passwords counts' },
  { id: 'sales', group: 'events', min: 'manager', ico: '📈', href: '/sales/', title: 'Sales by day',
    desc: 'Tickets bought each day, website vs Dojour, and which shows still sell on Dojour.', find: 'report chart tickets sold' },
  { id: 'exchange', group: 'events', min: 'staff', ico: '🔁', href: '/exchange/', title: 'Swap tickets',
    desc: 'Customer bought the wrong night? Their order # and email move it to another night of the same show.', find: 'exchange wrong night move order refund' },

  // Comedy
  { id: 'mic', group: 'comedy', min: 'staff', ico: '🎲', href: '/mic/host.html', title: 'Tuesday mic',
    desc: 'Online sign-ups for the Tuesday open mic. Add the booked comics, draw the rest at random.', find: 'open mic sign up draw lineup list' },
  // Built for Grace (Sam, Nov 14 2026); open to managers since Nov 15 2026.
  { id: 'booking', group: 'comedy', min: 'manager', ico: '🗓️', href: '/booking/', title: 'Booking board',
    desc: 'Every weekend at a glance: who’s booked, what each show still needs, and new booking requests.', find: 'weekends contract w9 host feature requests calendar' },
  { id: 'advance', group: 'comedy', min: 'manager', ico: '🎤', href: '/advance/booking.html', title: 'Booking desk',
    desc: 'Comedian advances: who’s booked, what they sent, what’s missing.', find: 'advance comic travel hotel green room' },
  { id: 'payouts', group: 'comedy', min: 'owner', ico: '💸', href: '/payouts/', title: 'Pay comics',
    desc: 'Who we owe. Tap Pay, send it, tap Paid.', find: 'pay venmo paypal check owe settlement' },
  { id: 'payme', group: 'comedy', min: 'manager', ico: '🙋', href: '/payme/', title: 'Comic pay request form',
    desc: 'Send this to a comic who needs paying. Their request shows up on Pay comics.', find: 'pay request w9 form' },
  { id: 'inbox', group: 'comedy', min: 'owner', ico: '🪨', href: 'https://claude.ai/artifact/LFjnAQcjgGrr1QghpTvj3C', out: true, title: 'Boulder Inbox',
    desc: 'Sam’s email game. One email at a time: archive, reply, or send to booking@.', find: 'email inbox' },
  { id: 'css', group: 'comedy', min: 'owner', ico: '📊', href: '/css/', title: 'CSS',
    desc: 'Comic Scoring System. Grades, house stars, the face, and notes on every comic.', find: 'comic scores grades notes rating' },
  { id: 'sign', group: 'comedy', min: 'manager', ico: '🖼️', href: '/sign/review.html', title: 'Sign pictures',
    desc: 'What customers drew on the taproom LED sign. Take any down.', find: 'led sign drawings chalkboard draw brightness' },
  { id: 'tank', group: 'comedy', min: 'manager', ico: '🦈', href: '/tank/review.html', title: 'Sam’s Tank pitches',
    desc: 'Monthly show pitches to read and rate.', find: 'pitch show ideas' },

  // Bar & beer
  { id: 'printmenu', group: 'bar', min: 'staff', ico: '🖨️', href: '/menu/print.html', title: 'Print menu',
    desc: 'Today’s taps on one page, straight from GoTab.', find: 'beer list taps paper' },
  { id: 'tvmenu', group: 'bar', min: 'staff', ico: '📺', href: 'https://www.sisyphusbrewing.com/pages/tv-menu', out: true, title: 'TV menu board',
    desc: 'What the taproom TV is showing.', find: 'tv screen beer list taps' },
  { id: 'brewing', group: 'bar', min: 'manager', ico: '🍺', href: '/brewing/', title: 'Batch log',
    desc: 'Tanks, batches and recipes.', find: 'brew tanks recipes fermenter' }
];

// Which tools a login can open. role is door, staff, manager or owner;
// canVoice says whether this login is on the voice notes list.
var STAFF_RANK = { door: 1, staff: 2, manager: 3, owner: 4 };
function staffToolsFor(role, canVoice) {
  var rank = STAFF_RANK[role] || 1;
  return STAFF_TOOLS.filter(function (t) {
    if (rank < STAFF_RANK[t.min]) return false;
    if (t.flag === 'voice' && !canVoice) return false;
    return true;
  });
}

// "Your usual": each device remembers which tools get opened on it, so the
// ones a person actually uses float to the top of their staff page.
function staffToolUsed(id) {
  try {
    var use = JSON.parse(localStorage.getItem('staffToolUse') || '{}');
    use[id] = (use[id] || 0) + 1;
    localStorage.setItem('staffToolUse', JSON.stringify(use));
  } catch (e) {}
}
function staffToolUse() {
  try { return JSON.parse(localStorage.getItem('staffToolUse') || '{}') || {}; } catch (e) { return {}; }
}
