// The boulder's lights and buzzer. Both are optional (see config.h); with no
// pin set these do nothing.
#pragma once
void fx_begin();
void fx_idle();        // slow soft glow while waiting for a card
void fx_card();        // a card was set down
void fx_ok();          // money went on or came off: green and a happy chirp
void fx_error();       // something went wrong: red and a low buzz
void fx_tick();        // call from loop() to keep the lights moving
