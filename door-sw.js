// Keeps the door page opening when the club internet is down (Sam, Nov 18
// 2026: "For every show there needs to be the ability for it to run in every
// scenario except a power outage").
//
// It only touches the door page and the few files it needs. Every other page
// on the staff site goes to the network exactly as before.
//
// Always the network first, so a fix to the door page shows up right away;
// the saved copy is used only when the network fails or hangs for 4 seconds.
// The guest list itself is kept by the page (index.html), not here.

var CACHE = 'door-v1';
var PAGE_FILES = [
  '/',
  '/index.html',
  '/staff.css',
  '/staff.js',
  '/posters/assets/sisyphus-badge-dark-bg.png',
  '/brewing/icons/icon-192.png',
  '/brewing/icons/apple-touch-icon.png'
];
var SUPABASE_JS = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) {
    // One missing file must not stop the rest from being saved.
    return Promise.all(PAGE_FILES.concat([SUPABASE_JS]).map(function (url) {
      return cache.add(new Request(url, { cache: 'reload' })).catch(function () {});
    }));
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('door-') === 0 && k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function isDoorFile(request) {
  if (request.method !== 'GET') return false;
  var url = new URL(request.url);
  if (url.origin === self.location.origin) return PAGE_FILES.indexOf(url.pathname) !== -1;
  if (url.href.indexOf(SUPABASE_JS) === 0) return true;
  return url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
}

function withTimeout(promise, ms) {
  return new Promise(function (resolve, reject) {
    var t = setTimeout(function () { reject(new Error('timeout')); }, ms);
    promise.then(function (r) { clearTimeout(t); resolve(r); }, function (e) { clearTimeout(t); reject(e); });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (!isDoorFile(request)) return;   // not ours: the browser handles it as usual
  // The door page is saved under "/" whether it was opened as / or /index.html,
  // and without any ?query, so the saved copy is found either way.
  var url = new URL(request.url);
  var key = url.origin === self.location.origin
    ? (url.pathname === '/index.html' ? '/' : url.pathname)
    : request.url;
  event.respondWith(
    withTimeout(fetch(request), 4000).then(function (response) {
      if (response && (response.ok || response.type === 'opaque')) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put(key, copy); });
      }
      return response;
    }).catch(function () {
      return caches.match(key).then(function (hit) { return hit || Response.error(); });
    })
  );
});
