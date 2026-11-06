HABBO COMPANION v1.1.8 — FASTER REPEAT PACKET RATE
===================================================
The outgoing packet repeater now allows a minimum delay of 0.1 seconds
(100 milliseconds, up to 10 send attempts per second), instead of
2 seconds in v1.1.7.

- Default repeat delay changed to 0.1 seconds.
- User may still set any value from 0.1 to 120 seconds.
- Values below 0.1, non-numeric values, NaN, and Infinity remain rejected.
- Start, STOP, disconnect, and close safeguards are unchanged.
- Updated tests verify lower bound and actual 100 ms timer scheduling.
- No unlimited or zero-delay loop to avoid saturating Habbo or the UI.
- G-Earth integration, connection startup and Windows network safety
  remain unchanged.

The server can throttle cup interactions independently of the client
send rate. Packet replay may be restricted by the game's rules.
