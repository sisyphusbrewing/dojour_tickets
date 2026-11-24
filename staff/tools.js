// The one list of staff tools. The staff home page (/staff/) draws its tiles
// from it and the top bar on every tool (staff/nav.js) draws its "All tools"
// menu from it, so a new tool is added in exactly one place: here.
//
// For each tool:
//   id     short name, never reused
//   title  what it is called
//   short  a shorter name for its button on the staff home page, when the
//          title is too long to fit on a phone (most tools don't need one)
//   desc   one plain sentence: what it is for
//   href   where it opens. Start with "/" for a page on this site.
//   min    the lowest login that can open it: door, staff, manager or owner
//   opens  optional: the day (YYYY-MM-DD, Minneapolis) the tool opens to
//          everyone at "min". Before that day only "early" logins see it.
//   early  who sees it before "opens" (for example manager)
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
  // For whoever checks tickets at the door (mostly comics, not on the time
  // clock): the night, a name and a Venmo. It lands on Pay comics for Sam to
  // approve and pay (Sam, Nov 17 2026). The page itself needs no login.
  { id: 'doorshift', group: 'show', min: 'door', ico: '🚪', href: '/doorshift/', title: 'Worked the door', short: 'Worked the door',
    desc: 'Worked the door on a show night? Send in the night so you get paid.', find: 'door shift pay paid venmo worked form submit' },
  // Report unsafe behavior, anonymously if they like (Sam, Nov 17 2026). The
  // tag and the sign in the Green Room open the same page. No login needed.
  { id: 'safe', group: 'show', min: 'door', ico: '🛟', href: '/safe/', title: 'Say something',
    desc: 'Someone made you or another person feel unsafe? Tell Sam and Grace. Your name is optional.', find: 'unsafe report harassment safety green room anonymous complaint' },
  { id: 'timer', group: 'show', min: 'staff', ico: '⏱️', href: '/timer/', title: 'Stage timer',
    desc: 'The light the comic sees. Started from the Stream Deck.', find: 'clock light time' },
  { id: 'deck', group: 'show', min: 'staff', ico: '🎛️', href: '/staff/stream-deck.html', title: 'Stream Deck guide', short: 'Deck guide',
    desc: 'What every button and knob at the bar does.', find: 'buttons sound lights music mic volume av' },
  { id: 'crash', group: 'show', min: 'staff', ico: '🧯', href: '/av/if-it-crashes.html', title: 'If the show computer restarts', short: 'Computer crashed',
    desc: 'Get sound and lights back, step by step.', find: 'crash broken no sound help pc companion' },
  // The beers guests picked on their phones before they got here, for the
  // bar to pour as each guest checks in (Sam, Nov 18 2026: "drinks ready as
  // you check in"). Only Sam sees the tile for now: guests aren't sent the
  // "Your night" page yet. When he opens it to the bar, change min to staff.
  { id: 'firstround', group: 'show', min: 'owner', ico: '🍺', href: '/firstround/', title: 'First round',
    desc: 'Beers guests picked ahead of time. Pour one when its guest checks in.', find: 'first beer drinks waiting pre order pour your night guest' },
  { id: 'supplies', group: 'show', min: 'staff', ico: '📦', href: '/supplies/', title: 'Supplies',
    desc: 'The stock sheet. Count it, and booking@ hears when something runs low.', find: 'stock inventory order low napkins count' },

  // Just for you
  { id: 'schedule', group: 'you', min: 'staff', ico: '🕓', href: '/schedule/', title: 'Schedule',
    desc: 'Who works when. Trade a shift, ask for time off, say when you can’t work.', find: 'shifts hours time off swap trade availability calendar when i work' },
  // The time clock (Sam, Nov 16 2026): tap in, tap out, type the night's tips.
  // Everyone's since Nov 17 2026. It was a manager's tool at first, set to
  // open on Mon Nov 30, the first day of a pay period. Sam opened it the day
  // the tag at the bar worked: "they will be tracking their tips on that page
  // as well, no more go-tab for clocking in and out". So the pay period of
  // Nov 16 to 29 has its first days on the old clock and the rest here.
  { id: 'clock', group: 'you', min: 'staff', ico: '⏱️', href: '/clock/', title: 'Clock',
    desc: 'Clock in and out with a tap at the bar. Add your tips, see your hours for the pay period.', find: 'clock in out punch hours tips tip tracker payroll timesheet time when i work gotab nfc tap' },
  // Help (Sam, Nov 24 2026): ask the staff helper how to do anything at work
  // (Claude, answering only from the staff handbook), or send Sam an idea, a
  // request, something broken or an FYI. Owner only until Sam has looked over
  // the handbook's contents; then min becomes staff for both tiles.
  { id: 'help', group: 'you', min: 'owner', ico: '💬', href: '/help/', title: 'Ask for help', short: 'Ask for help',
    desc: 'Ask how to do anything at work: the clock, the deck, GoTab, gift cards, printers. If it can’t solve it, one tap sends it to Sam.', find: 'help question how do i tech support broken stuck ai assistant handbook' },
  { id: 'tellsam', group: 'you', min: 'owner', ico: '📮', href: '/help/?tell', title: 'Tell Sam',
    desc: 'An idea, something you need from Sam, something broken, or just so you know. Ideas can go without your name.', find: 'suggestion idea feedback request ask sam need approval broken report thoughts' },
  { id: 'voice', group: 'you', min: 'door', ico: '🎙️', href: '/voice/', title: 'Voice notes', flag: 'voice',
    desc: 'Record a meeting or a thought. Claude emails you the summary and to-dos.', find: 'record meeting memo' },

  // Tickets & events
  { id: 'manager', group: 'events', min: 'manager', ico: '📋', href: '/manager/', title: 'Manager',
    desc: 'Guest lists for every show, ticket counts, new shows, staff logins.', find: 'comps guest list new show logins passwords counts' },
  // The events@ inbox sorted: private events, ticket questions, accessibility,
  // with Done / Later (Sam, Nov 17 2026: "We should probably do this for the
  // events@ email as well").
  { id: 'inbox', group: 'events', min: 'manager', ico: '📬', href: '/inbox/', title: 'Events inbox',
    desc: 'Who wrote to events@ and what they want: private events, ticket questions, accessibility. Mark each one done.', find: 'events@ email private event rental party group refund accessibility' },
  { id: 'sales', group: 'events', min: 'manager', ico: '📈', href: '/sales/', title: 'Sales by day',
    desc: 'Tickets bought each day, website vs Dojour, and which shows still sell on Dojour.', find: 'report chart tickets sold' },
  { id: 'exchange', group: 'events', min: 'staff', ico: '🔁', href: '/exchange/', title: 'Swap tickets',
    desc: 'Customer bought the wrong night? Their order # and email move it to another night of the same show.', find: 'exchange wrong night move order refund' },

  // Comedy
  { id: 'mic', group: 'comedy', min: 'staff', ico: '🎲', href: '/mic/host.html', title: 'Tuesday mic',
    desc: 'Tuesday open mic: set the host, send them the link for their 4 guaranteed comics, and see the lineup. At 6:30, 8 spots fill: first-timers first, the rest drawn.', find: 'open mic sign up draw lineup list' },
  { id: 'michosts', group: 'comedy', min: 'manager', ico: '🎤', href: '/mic/hosts.html', title: 'Mic hosts',
    desc: 'Who hosts the Tuesday open mic and the Thursday showcase, week by week. Send a Tuesday host their link.', find: 'open mic showcase host hosts thursday tuesday' },
  // Built for Grace (Sam, Nov 14 2026); open to managers since Nov 15 2026.
  { id: 'booking', group: 'comedy', min: 'manager', ico: '🗓️', href: '/booking/', title: 'Booking board',
    desc: 'Every weekend at a glance: who’s booked, what each show still needs, and new booking requests.', find: 'weekends contract w9 host feature requests calendar' },
  { id: 'advance', group: 'comedy', min: 'manager', ico: '🎤', href: '/advance/booking.html', title: 'Booking desk',
    desc: 'Comedian advances: who’s booked, what they sent, what’s missing.', find: 'advance comic travel hotel green room' },
  { id: 'payouts', group: 'comedy', min: 'owner', ico: '💸', href: '/payouts/', title: 'Pay comics',
    desc: 'Who we owe, comics and door shifts. Tap Pay, send it, tap Paid.', find: 'pay venmo paypal check owe settlement door' },
  { id: 'payme', group: 'comedy', min: 'manager', ico: '🙋', href: '/payme/', title: 'Comic pay request form', short: 'Pay request form',
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
  // Tap gift cards (Sam, Nov 17 2026). The card's own link opens the same
  // page; this tile opens it without a card: type a card's number, and for
  // managers every card, the totals and making new ones.
  { id: 'gift', group: 'bar', min: 'staff', ico: '🎁', href: '/gift/', title: 'Gift cards',
    desc: 'Tap a gift card to see what’s on it and take a tab off it.', find: 'gift card balance nfc tap redeem load sell present' },
  { id: 'printmenu', group: 'bar', min: 'staff', ico: '🖨️', href: '/menu/print.html', title: 'Print menu',
    desc: 'Today’s taps on one page, straight from GoTab.', find: 'beer list taps paper' },
  { id: 'tvmenu', group: 'bar', min: 'staff', ico: '📺', href: 'https://www.sisyphusbrewing.com/pages/tv-menu', out: true, title: 'TV menu board', short: 'TV menu',
    desc: 'What the taproom TV is showing.', find: 'tv screen beer list taps' },
  { id: 'brewing', group: 'bar', min: 'manager', ico: '🍺', href: '/brewing/', title: 'Batch log',
    desc: 'Tanks, batches and recipes.', find: 'brew tanks recipes fermenter' }
];

// Which tools a login can open. role is door, staff, manager or owner;
// canVoice says whether this login is on the voice notes list.
var STAFF_RANK = { door: 1, staff: 2, manager: 3, owner: 4 };
// The lowest login that can see a tool today: "early" until the tool's
// "opens" day (by Minneapolis's calendar), "min" from then on.
function staffToolMin(t, today) {
  today = today || new Date().toLocaleDateString('en-CA', { timeZone: 'America/Chicago' });
  return t.opens && t.early && today < t.opens ? t.early : t.min;
}
function staffToolsFor(role, canVoice) {
  var rank = STAFF_RANK[role] || 1;
  return STAFF_TOOLS.filter(function (t) {
    if (rank < STAFF_RANK[staffToolMin(t)]) return false;
    if (t.flag === 'voice' && !canVoice) return false;
    return true;
  });
}
