// Talking to the database: sign in once, then call the gift card functions.
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

bool supa_signed_in();                                    // have a saved sign-in
bool supa_sign_in(const String &login, const String &password, String &err);
void supa_sign_out();
// Call a database function (gift_card_look, gift_card_load, ...). On success
// out holds its answer. On failure err is the message to show staff.
bool supa_rpc(const char *fn, JsonDocument &args, JsonDocument &out, String &err);
