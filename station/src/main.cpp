// The Boulder: the gift card station at the front bar (Sam, Nov 18 2026: "a
// fun thing for the front ... with the boulder and the touch screen so people
// can type the amount in and hit add and write the card right there").
//
// What it does:
//   New card     tap New card, type the amount, set a blank card on the
//                boulder. The station makes the card in the database, writes
//                its link on the card, reads it back, locks it, and puts the
//                money on. Then: "Ring $25 on the Gift card item in GoTab."
//   A card       set any gift card on the boulder: its number and balance,
//                with Add and Take off.
//   Undo         every Add or Take off can be undone for two minutes.
//
// The rules (who may do what, never below $0, $500 at a time, nothing ever
// deleted) live in the database (supabase/migrations/2026111800*_gift_*.sql),
// the same ones the /gift/ page follows. This screen only shows and asks.
// The station signs in with its own staff login, typed once by a manager.
#include <Arduino.h>
#include <WiFi.h>
#include <lvgl.h>
#include "board.h"
#include "config.h"
#include "feedback.h"
#include "reader.h"
#include "secrets.h"
#include "supa.h"

// ---------- what the screen is doing ----------
enum Screen { S_SIGNIN, S_HOME, S_AMOUNT, S_WAIT_BLANK, S_CARD, S_DONE, S_MSG };
enum Mode { M_NEW, M_ADD, M_TAKE };

static Screen screen = S_HOME;
static Mode mode = M_NEW;
static long cents = 0;                 // the amount being typed
static uint32_t touchedAt = 0;         // for going back home when left alone
static bool readerOk = false;

// The card on screen.
static String cardCode;
static int cardNumber = 0;
static long cardBalance = 0;           // cents
static bool cardActive = true;

// A new card being made: the database row exists once newCode is set.
static String newCode;
static int newNumber = 0;
static uint8_t newUid[7];
static uint8_t newUidLen = 0;

static long undoMove = 0;              // the last change, for Undo
static uint32_t undoUntil = 0;

// LVGL calls back in the middle of drawing, so buttons only leave a note here
// and loop() acts on it.
enum Act { A_NONE, A_NEW, A_ADD, A_TAKE, A_HOME, A_CONFIRM, A_UNDO, A_SIGNIN, A_KEY, A_QUICK };
static volatile Act act = A_NONE;
static intptr_t actArg = 0;

// Signing in.
static lv_obj_t *taUser = nullptr, *taPass = nullptr;
static lv_obj_t *amountLabel = nullptr;
static String signinErr;

// ---------- money as text ----------
static String money(long c) {
  char b[24];
  snprintf(b, sizeof b, "$%ld.%02ld", c / 100, labs(c) % 100);
  return b;
}
static long to_cents(JsonVariant v) { return lround(v.as<double>() * 100.0); }

// ---------- look ----------
static const lv_color_t SLATE = lv_color_hex(0x4A6378);
static const lv_color_t INK = lv_color_hex(0x2B2929);
static const lv_color_t GOOD = lv_color_hex(0x2E7D4F);
static const lv_color_t BAD = lv_color_hex(0xB3261E);

static void on_click(lv_event_t *e) {
  touchedAt = millis();
  act = (Act)(intptr_t)lv_event_get_user_data(e);
  actArg = (intptr_t)lv_obj_get_user_data(lv_event_get_target(e));
}

static lv_obj_t *new_screen() {
  lv_obj_t *s = lv_obj_create(NULL);
  lv_obj_set_style_bg_color(s, INK, 0);
  lv_obj_set_style_text_color(s, lv_color_white(), 0);
  lv_obj_clear_flag(s, LV_OBJ_FLAG_SCROLLABLE);
  return s;
}
static lv_obj_t *label(lv_obj_t *p, const String &t, const lv_font_t *f, lv_align_t al, int x, int y) {
  lv_obj_t *l = lv_label_create(p);
  lv_label_set_text(l, t.c_str());
  lv_obj_set_style_text_font(l, f, 0);
  lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_align(l, al, x, y);
  return l;
}
static lv_obj_t *button(lv_obj_t *p, const String &t, Act a, lv_color_t c, int w, int h, lv_align_t al, int x, int y, intptr_t arg = 0) {
  lv_obj_t *b = lv_btn_create(p);
  lv_obj_set_size(b, w, h);
  lv_obj_align(b, al, x, y);
  lv_obj_set_style_bg_color(b, c, 0);
  lv_obj_set_style_radius(b, 16, 0);
  lv_obj_set_user_data(b, (void *)arg);
  lv_obj_add_event_cb(b, on_click, LV_EVENT_CLICKED, (void *)(intptr_t)a);
  lv_obj_t *l = lv_label_create(b);
  lv_label_set_text(l, t.c_str());
  lv_obj_set_style_text_font(l, &lv_font_montserrat_28, 0);
  lv_obj_center(l);
  return b;
}
static void show(lv_obj_t *s, Screen which) {
  lv_scr_load_anim(s, LV_SCR_LOAD_ANIM_FADE_ON, 150, 0, true);
  screen = which;
  touchedAt = millis();
}
// Put a "working" note up and draw it now, before a slow call.
static void busy(const String &t) {
  lv_obj_t *s = new_screen();
  label(s, t, &lv_font_montserrat_36, LV_ALIGN_CENTER, 0, 0);
  lv_scr_load(s);
  lv_refr_now(NULL);
}

// ---------- screens ----------
static void show_home() {
  lv_obj_t *s = new_screen();
  label(s, "SISYPHUS GIFT CARDS", &lv_font_montserrat_20, LV_ALIGN_TOP_MID, 0, 26);
  label(s, readerOk ? "Set a card on the boulder" : "The card reader isn't answering.\nCheck its wires.",
        &lv_font_montserrat_48, LV_ALIGN_CENTER, 0, -40);
  label(s, "to see what's on it", &lv_font_montserrat_28, LV_ALIGN_CENTER, 0, 30);
  button(s, "New card", A_NEW, SLATE, 340, 90, LV_ALIGN_BOTTOM_MID, 0, -36);
  newCode = ""; newNumber = 0; newUidLen = 0;
  fx_idle();
  show(s, S_HOME);
}

static void show_msg(const String &t, bool bad = true) {
  lv_obj_t *s = new_screen();
  lv_obj_t *l = label(s, t, &lv_font_montserrat_36, LV_ALIGN_CENTER, 0, -50);
  lv_obj_set_width(l, 720);
  lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
  button(s, "OK", A_HOME, bad ? BAD : SLATE, 260, 84, LV_ALIGN_BOTTOM_MID, 0, -36);
  if (bad) fx_error();
  show(s, S_MSG);
}

static void update_amount() {
  if (amountLabel) lv_label_set_text(amountLabel, money(cents).c_str());
}

static void show_amount(Mode m) {
  mode = m;
  cents = 0;
  lv_obj_t *s = new_screen();
  String head = m == M_NEW ? "New card: how much goes on it?"
              : m == M_ADD ? "Add to card #" + String(cardNumber)
              : "Take off card #" + String(cardNumber) + "  (it has " + money(cardBalance) + ")";
  label(s, head, &lv_font_montserrat_28, LV_ALIGN_TOP_LEFT, 30, 24);
  amountLabel = label(s, "$0.00", &lv_font_montserrat_48, LV_ALIGN_TOP_LEFT, 30, 90);

  const int quick[] = QUICK_AMOUNTS;
  for (int i = 0; i < 3; i++)
    button(s, "$" + String(quick[i]), A_QUICK, SLATE, 110, 64, LV_ALIGN_TOP_LEFT, 30 + i * 122, 180, quick[i] * 100);
  if (m == M_TAKE && cardBalance > 0)
    button(s, "All of it", A_QUICK, SLATE, 352, 64, LV_ALIGN_TOP_LEFT, 30, 256, cardBalance);

  // The number pad on the right. Typing shifts in from the cents: 2 5 0 0 is $25.00.
  static const char *keys[] = {"1", "2", "3", "\n", "4", "5", "6", "\n", "7", "8", "9", "\n", "00", "0", LV_SYMBOL_BACKSPACE, ""};
  lv_obj_t *pad = lv_btnmatrix_create(s);
  lv_btnmatrix_set_map(pad, keys);
  lv_obj_set_size(pad, 360, 330);
  lv_obj_align(pad, LV_ALIGN_TOP_RIGHT, -20, 20);
  lv_obj_set_style_text_font(pad, &lv_font_montserrat_36, 0);
  lv_obj_add_event_cb(pad, [](lv_event_t *e) {
    lv_obj_t *o = lv_event_get_target(e);
    const char *t = lv_btnmatrix_get_btn_text(o, lv_btnmatrix_get_selected_btn(o));
    if (!t) return;
    touchedAt = millis();
    if (!strcmp(t, LV_SYMBOL_BACKSPACE)) cents /= 10;
    else if (cents < 100000) cents = cents * (t[1] ? 100 : 10) + atoi(t);
    if (cents > 99999) cents = 99999;
    update_amount();
  }, LV_EVENT_VALUE_CHANGED, nullptr);

  String go = m == M_TAKE ? "Take off" : m == M_ADD ? "Add" : "Next";
  button(s, "Cancel", A_HOME, lv_color_hex(0x555050), 200, 84, LV_ALIGN_BOTTOM_LEFT, 30, -24);
  button(s, go, A_CONFIRM, m == M_TAKE ? BAD : GOOD, 360, 84, LV_ALIGN_BOTTOM_RIGHT, -20, -24);
  show(s, S_AMOUNT);
}

static void show_wait_blank(const String &note = "") {
  lv_obj_t *s = new_screen();
  if (note.length()) {
    lv_obj_t *n = label(s, note, &lv_font_montserrat_28, LV_ALIGN_BOTTOM_MID, 0, -140);
    lv_obj_set_style_text_color(n, lv_color_hex(0xFF8A80), 0);
  }
  label(s, money(cents) + " on a new card", &lv_font_montserrat_28, LV_ALIGN_TOP_MID, 0, 30);
  label(s, "Set a blank card\non the boulder", &lv_font_montserrat_48, LV_ALIGN_CENTER, 0, -20);
  button(s, "Cancel", A_HOME, lv_color_hex(0x555050), 260, 84, LV_ALIGN_BOTTOM_MID, 0, -36);
  show(s, S_WAIT_BLANK);
}

static void show_card() {
  lv_obj_t *s = new_screen();
  label(s, "GIFT CARD #" + String(cardNumber), &lv_font_montserrat_28, LV_ALIGN_TOP_MID, 0, 30);
  if (!cardActive) {
    label(s, "Switched off", &lv_font_montserrat_48, LV_ALIGN_CENTER, 0, -40);
    label(s, "Ask a manager. Its money moved to another card.", &lv_font_montserrat_28, LV_ALIGN_CENTER, 0, 30);
    button(s, "Done", A_HOME, SLATE, 260, 84, LV_ALIGN_BOTTOM_MID, 0, -36);
    fx_error();
  } else {
    lv_obj_t *bal = label(s, money(cardBalance), &lv_font_montserrat_48, LV_ALIGN_CENTER, 0, -70);
    lv_obj_set_style_transform_zoom(bal, 512, 0);   // twice as big
    label(s, "left on this card", &lv_font_montserrat_28, LV_ALIGN_CENTER, 0, 20);
    button(s, "Take off", A_TAKE, BAD, 230, 90, LV_ALIGN_BOTTOM_LEFT, 30, -30);
    button(s, "Add", A_ADD, GOOD, 230, 90, LV_ALIGN_BOTTOM_MID, 0, -30);
    button(s, "Done", A_HOME, lv_color_hex(0x555050), 230, 90, LV_ALIGN_BOTTOM_RIGHT, -30, -30);
  }
  show(s, S_CARD);
}

static void show_done(const String &big, const String &todo) {
  lv_obj_t *s = new_screen();
  lv_obj_set_style_bg_color(s, GOOD, 0);
  label(s, big, &lv_font_montserrat_48, LV_ALIGN_CENTER, 0, -90);
  lv_obj_t *l = label(s, todo, &lv_font_montserrat_36, LV_ALIGN_CENTER, 0, 10);
  lv_obj_set_width(l, 740);
  lv_label_set_long_mode(l, LV_LABEL_LONG_WRAP);
  if (undoMove) button(s, "Undo", A_UNDO, lv_color_hex(0x1F5537), 230, 84, LV_ALIGN_BOTTOM_LEFT, 40, -30);
  button(s, "Done", A_HOME, INK, 300, 84, LV_ALIGN_BOTTOM_RIGHT, -40, -30);
  fx_ok();
  show(s, S_DONE);
}

static void show_signin() {
  lv_obj_t *s = new_screen();
  label(s, "Sign the station in (managers, once)", &lv_font_montserrat_28, LV_ALIGN_TOP_LEFT, 24, 16);
  taUser = lv_textarea_create(s);
  lv_textarea_set_one_line(taUser, true);
  lv_textarea_set_placeholder_text(taUser, "Station's username");
  lv_obj_set_size(taUser, 360, 56);
  lv_obj_align(taUser, LV_ALIGN_TOP_LEFT, 24, 60);
  taPass = lv_textarea_create(s);
  lv_textarea_set_one_line(taPass, true);
  lv_textarea_set_password_mode(taPass, true);
  lv_textarea_set_placeholder_text(taPass, "Password");
  lv_obj_set_size(taPass, 360, 56);
  lv_obj_align(taPass, LV_ALIGN_TOP_LEFT, 400, 60);
  lv_obj_t *kb = lv_keyboard_create(s);
  lv_obj_set_size(kb, 800, 260);
  lv_obj_align(kb, LV_ALIGN_BOTTOM_MID, 0, 0);
  lv_keyboard_set_textarea(kb, taUser);
  auto focus = [](lv_event_t *e) { lv_keyboard_set_textarea((lv_obj_t *)lv_event_get_user_data(e), lv_event_get_target(e)); };
  lv_obj_add_event_cb(taUser, focus, LV_EVENT_FOCUSED, kb);
  lv_obj_add_event_cb(taPass, focus, LV_EVENT_FOCUSED, kb);
  lv_obj_add_event_cb(kb, [](lv_event_t *) { act = A_SIGNIN; }, LV_EVENT_READY, nullptr);
  button(s, "Sign in", A_SIGNIN, GOOD, 200, 50, LV_ALIGN_TOP_RIGHT, -24, 140);
  if (signinErr.length()) {
    lv_obj_t *e = label(s, signinErr, &lv_font_montserrat_20, LV_ALIGN_TOP_LEFT, 24, 150);
    lv_obj_set_style_text_color(e, lv_color_hex(0xFF8A80), 0);
  }
  show(s, S_SIGNIN);
}

// ---------- doing things ----------
static bool look(const String &code, String &err) {
  JsonDocument a, r;
  a["p_code"] = code;
  if (!supa_rpc("gift_card_look", a, r, err)) return false;
  if (!(r["found"] | false)) { err = "That card isn't one of ours."; return false; }
  cardCode = code;
  cardNumber = r["number"] | 0;
  cardBalance = to_cents(r["balance"]);
  cardActive = r["active"] | false;
  return true;
}

// Put money on or take it off the card on screen.
static bool move_money(bool on, long c, const char *note, String &err) {
  JsonDocument a, r;
  a["p_code"] = cardCode;
  a["p_amount"] = serialized(String(c / 100) + "." + (c % 100 < 10 ? "0" : "") + String(c % 100));
  a["p_note"] = note;
  if (!supa_rpc(on ? "gift_card_load" : "gift_card_spend", a, r, err)) return false;
  cardBalance = to_cents(r["balance"]);
  undoMove = r["move"] | 0L;
  undoUntil = millis() + 115000UL;   // the database allows 2 minutes; stop offering a bit sooner
  return true;
}

// A blank card is on the boulder and the amount is typed: make the card.
static void make_card(const Tag &t) {
  String err;
  if (!newCode.length()) {
    busy("Making a new card...");
    JsonDocument a, r;
    if (!supa_rpc("gift_card_new", a, r, err)) { show_msg(err); return; }
    newCode = (const char *)(r["code"] | "");
    newNumber = r["number"] | 0;
  }
  memcpy(newUid, t.uid, t.uidLen);
  newUidLen = t.uidLen;
  busy("Writing card #" + String(newNumber) + "...\nKeep it on the boulder");
  if (!reader_write(newCode.c_str(), err)) {
    fx_error();
    show_wait_blank(err);  // the same card number is kept: set it down again
    return;
  }
  cardCode = newCode;
  cardNumber = newNumber;
  cardBalance = 0;
  cardActive = true;
  long c = cents;
  newCode = ""; newNumber = 0; newUidLen = 0;
  busy("Putting " + money(c) + " on card #" + String(cardNumber) + "...");
  if (!move_money(true, c, "New card at the Boulder", err)) {
    show_msg("Card #" + String(cardNumber) + " is made, but the money didn't go on: " + err +
             "\nSet it down again and tap Add.");
    return;
  }
  show_done("Card #" + String(cardNumber) + " has " + money(cardBalance),
            "Now ring " + money(c) + " on the \"Gift card\" item in GoTab and take the payment.");
}

static void confirm_amount() {
  if (cents <= 0) return;
  String err;
  if (mode == M_NEW) {
    if (cents > 50000) { show_msg("At most $500 at a time."); return; }
    // The blank may already be sitting on the boulder.
    if (newUidLen && reader_still_there()) {
      Tag t; memcpy(t.uid, newUid, newUidLen); t.uidLen = newUidLen; t.kind = TAG_BLANK;
      make_card(t);
    } else show_wait_blank();
    return;
  }
  if (mode == M_TAKE && cents > cardBalance) {
    show_msg("This card only has " + money(cardBalance) + ". Take that off and they pay the rest the usual way.");
    return;
  }
  long c = cents;
  busy(mode == M_ADD ? "Adding..." : "Taking off...");
  if (!move_money(mode == M_ADD, c, "At the Boulder", err)) { show_msg(err); return; }
  if (mode == M_ADD)
    show_done(money(c) + " added. Card #" + String(cardNumber) + " has " + money(cardBalance),
              "Now ring " + money(c) + " on the \"Gift card\" item in GoTab and take the payment.");
  else
    show_done(money(c) + " off. " + money(cardBalance) + " left on card #" + String(cardNumber),
              "Now close the tab in GoTab with the \"Gift card\" payment for " + money(c) + ".");
}

static void undo() {
  String err;
  if (!undoMove || (int32_t)(millis() - undoUntil) > 0) { show_msg("Too late to undo. Ask a manager."); return; }
  busy("Undoing...");
  JsonDocument a, r;
  a["p_move"] = undoMove;
  undoMove = 0;
  if (!supa_rpc("gift_card_undo", a, r, err)) { show_msg(err); return; }
  cardBalance = to_cents(r["balance"]);
  show_msg("Undone. Card #" + String(cardNumber) + " has " + money(cardBalance) +
           " again.\nIf you rang it in GoTab, void it there too.", false);
}

// A card was set down.
static void on_tag(const Tag &t) {
  fx_card();
  String err;
  if (screen == S_WAIT_BLANK) {
    bool sameAsBefore = newUidLen && t.uidLen == newUidLen && !memcmp(t.uid, newUid, newUidLen);
    if (t.kind == TAG_BLANK || (sameAsBefore && (t.kind == TAG_OTHER || (t.kind == TAG_OURS && newCode == t.code)))) {
      make_card(t);
    } else if (t.kind == TAG_OURS) {
      fx_error();
      show_wait_blank("That card is already a gift card. Use a blank one.");
    } else {
      fx_error();
      show_wait_blank("That card can't be written. Use a blank one.");
    }
    return;
  }
  if (screen != S_HOME && screen != S_CARD && screen != S_DONE && screen != S_MSG) return;
  if (t.kind == TAG_BLANK) {
    memcpy(newUid, t.uid, t.uidLen);
    newUidLen = t.uidLen;
    show_amount(M_NEW);
    newUidLen = t.uidLen;   // show_amount doesn't clear it; kept so Next writes this card
    return;
  }
  if (t.kind == TAG_OTHER) { show_msg("That's not a Sisyphus gift card."); return; }
  busy("Reading card...");
  if (!look(t.code, err)) { show_msg(err); return; }
  undoMove = 0;
  show_card();
}

// ---------- start ----------
void setup() {
  Serial.begin(115200);
  board_begin();
  fx_begin();
  busy("Starting...");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  readerOk = reader_begin();
  if (supa_signed_in()) show_home();
  else show_signin();
}

void loop() {
  lv_timer_handler();
  fx_tick();

  Act a = act;
  act = A_NONE;
  String err;
  switch (a) {
    case A_NONE: break;
    case A_NEW: newUidLen = 0; show_amount(M_NEW); break;
    case A_ADD: show_amount(M_ADD); break;
    case A_TAKE: show_amount(M_TAKE); break;
    case A_HOME: show_home(); break;
    case A_QUICK: cents = actArg; update_amount(); break;
    case A_CONFIRM: confirm_amount(); break;
    case A_UNDO: undo(); break;
    case A_SIGNIN: {
      String u = lv_textarea_get_text(taUser), p = lv_textarea_get_text(taPass);
      busy("Signing in...");
      if (supa_sign_in(u, p, err)) { signinErr = ""; show_home(); }
      else { signinErr = err; show_signin(); }
      break;
    }
    default: break;
  }

  // No reader at start-up (a loose wire, or it was plugged in afterwards):
  // look again every ten seconds while the home screen is up, so nobody has
  // to restart the station.
  static uint32_t lastLook = 0;
  if (!readerOk && screen == S_HOME && millis() - lastLook > 10000) {
    lastLook = millis();
    readerOk = reader_begin();
    if (readerOk) show_home();
  }

  // Watch the reader, except while signing in or typing an amount.
  static uint32_t lastPoll = 0;
  if (readerOk && screen != S_SIGNIN && screen != S_AMOUNT && millis() - lastPoll > 150) {
    lastPoll = millis();
    Tag t;
    if (reader_poll(t)) on_tag(t);
  }

  // Left alone: go back home.
  if ((screen == S_CARD || screen == S_DONE || screen == S_MSG || screen == S_AMOUNT || screen == S_WAIT_BLANK) &&
      millis() - touchedAt > IDLE_BACK_MS) show_home();
  // A database answer said we're signed out.
  if (screen != S_SIGNIN && !supa_signed_in()) show_signin();

  delay(5);
}
