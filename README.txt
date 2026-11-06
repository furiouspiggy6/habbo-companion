HABBO COMPANION v1.1.7 — CONTROLLED OUTGOING PACKET REPEAT
============================================================
New: repeat a captured outgoing cup/interact packet without hardcoding
hotel-specific header IDs.

WORKFLOW
1. Connect G-Earth and load Habbo into a room.
2. In Packet Viewer, click Connect packet viewer if needed.
3. Interact with a cup or dispenser once.
4. Select the corresponding Outgoing packet in Packet Viewer.
5. Open Packet Manipulator and click Load selected viewer packet.
6. Set repeat interval (default 2.5 seconds; minimum 2, maximum 120).
7. Click Start repeating, review the exact packet and confirm.
8. Click STOP to end replay. Replay also stops on Habbo connection_end,
   extension errors, or when Companion closes.

SAFETY
- No automatic packet replay on startup. Existing rules remain disabled
  until explicitly enabled. No packet ID or payload is guessed.
- Only Outgoing packets are allowed; incoming injection is not replayed.
- A fresh parsed packet is sent each interval using G-Python's
  send_to_server method, not an unbounded worker/flood loop.
- Repeat interval is validated against NaN/Infinity and rate-limited to
  at least two seconds. Send failures stop the timer.
- Session connection events update replay readiness and cancel replay.
- No changes to Windows proxy, hosts, Flash/AIR connection launch or
  the viewer-attachment timing that previously froze Habbo at 60%.
- G-Earth/Java engine remains a separate background process.

Repeating a game interaction may be limited by Habbo's server and may
violate game automation rules. Use it only in your own game session.
