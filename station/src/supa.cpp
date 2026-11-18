// Sign-in works like the staff site's: a username becomes
// <username>@sisyphusbrewing.com. The station keeps only the "refresh token"
// the database hands back (in its own flash, never in this repo), so the
// password is typed once and never stored. Signing out on the station, or
// changing that login's password, ends it.
#include "supa.h"
#include "config.h"
#include "certs.h"
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <Preferences.h>

static String accessTok, refresh;
static uint32_t accessUntil = 0;   // millis() when the accessTok token runs out

static void load() {
  if (refresh.length()) return;
  Preferences p;
  p.begin("boulder", true);
  refresh = p.getString("refresh", "");
  p.end();
}
static void save() {
  Preferences p;
  p.begin("boulder", false);
  p.putString("refresh", refresh);
  p.end();
}

bool supa_signed_in() { load(); return refresh.length() > 0; }

void supa_sign_out() {
  accessTok = ""; refresh = ""; accessUntil = 0;
  save();
}

// One HTTPS POST. Returns the status code (or <0 if no connection).
static int post(const String &path, const String &body, const String &bearer, String &resp) {
  NetworkClientSecure tls;
  tls.setCACert(ROOT_CERTS);
  HTTPClient http;
  http.setTimeout(10000);
  if (!http.begin(tls, String(SUPABASE_URL) + path)) return -1;
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Content-Type", "application/json");
  if (bearer.length()) http.addHeader("Authorization", "Bearer " + bearer);
  int code = http.POST(body);
  resp = code > 0 ? http.getString() : "";
  http.end();
  return code;
}

static bool take_tokens(const String &resp) {
  JsonDocument d;
  if (deserializeJson(d, resp)) return false;
  accessTok = d["access_token"] | "";
  refresh = d["refresh_token"] | "";
  uint32_t secs = d["expires_in"] | 3600;
  accessUntil = millis() + (secs - 120) * 1000UL;
  save();
  return accessTok.length() && refresh.length();
}

static String message_of(const String &resp, const char *fallback) {
  JsonDocument d;
  if (!deserializeJson(d, resp)) {
    const char *m = d["message"] | d["msg"] | d["error_description"] | (const char *)nullptr;
    if (m && *m) return m;
  }
  return fallback;
}

bool supa_sign_in(const String &login, const String &password, String &err) {
  String email = login;
  email.trim();
  email.toLowerCase();
  if (email.indexOf('@') < 0) email += "@" LOGIN_DOMAIN;
  JsonDocument b;
  b["email"] = email;
  b["password"] = password;
  String body, resp;
  serializeJson(b, body);
  int code = post("/auth/v1/token?grant_type=password", body, "", resp);
  if (code == 200 && take_tokens(resp)) return true;
  err = code < 0 ? "No internet. Check the wifi." : "That username and password didn't work.";
  return false;
}

static bool refresh_access(String &err) {
  load();
  if (!refresh.length()) { err = "Signed out. A manager needs to sign the station in."; return false; }
  JsonDocument b;
  b["refresh_token"] = refresh;
  String body, resp;
  serializeJson(b, body);
  int code = post("/auth/v1/token?grant_type=refresh_token", body, "", resp);
  if (code == 200 && take_tokens(resp)) return true;
  if (code < 0) { err = "No internet. Check the wifi."; return false; }
  if (code == 400 || code == 401) supa_sign_out();     // the sign-in was ended
  err = "Signed out. A manager needs to sign the station in.";
  return false;
}

bool supa_rpc(const char *fn, JsonDocument &args, JsonDocument &out, String &err) {
  if ((!accessTok.length() || (int32_t)(millis() - accessUntil) > 0) && !refresh_access(err)) return false;
  String body, resp;
  serializeJson(args, body);
  for (int attempt = 0; attempt < 2; attempt++) {
    int code = post(String("/rest/v1/rpc/") + fn, body, accessTok, resp);
    if (code == 401 && attempt == 0) {        // token ran out early: refresh once
      if (!refresh_access(err)) return false;
      continue;
    }
    if (code < 0) { err = "No internet. Check the wifi."; return false; }
    if (code >= 200 && code < 300) {
      if (deserializeJson(out, resp)) { err = "The database answered oddly. Try again."; return false; }
      return true;
    }
    err = message_of(resp, "That didn't work. Try again.");
    return false;
  }
  err = "Signed out. A manager needs to sign the station in.";
  return false;
}
