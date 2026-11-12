HABBO COMPANION v1.1.26 — FIX UNKNOWN ROOM INDEX AFTER ID CONFIRMED
====================================================================

The problem:
  Account confirmed: dan.alt100 (ID 69016008);
  room index still unavailable. Re-enter the room if needed.

Your account ID lookup already worked. The problem was identifying the
separate room avatar index from Habbo's incoming "Users" packet. The
existing G-Python HEntity parser relies on variable entity tail fields
which can change with Habbo client versions. Parsing the full room
list could fail, leaving indexes unrecognized even when 50 players
were detected.

What changed:
- Companion now reads a strongly validated binary prefix of each
  Habbo room Users entity: account ID, username, motto, avatar figure,
  room index, tile coordinates, height, direction and type.
- It can recover indexes even when subsequent optional entity fields
  change or cannot be parsed by the older G-Python entity decoder.
- It matches the server-confirmed self account ID (69016008 on the
  affected screenshot) with the corresponding room index. This does
  not use account IDs as room indexes or invent numbers.
- Old G-Earth expression and G-Python entity decoders remain as
  fallbacks. Validated real binary indexes take priority.
- The packet type is checked before decoding. Wrong or ambiguous
  records are rejected rather than used for confirmed-hand coffee
  transfers.

To use:
1. Update Companion to 1.1.26 using Updates > Check online.
2. Make sure G-Earth is connected and re-enter the Habbo room once.
3. In Coffee Pass Loop, look for:
       Your avatar: dan.alt100 — room index <number>
4. If the index still cannot be decoded, leave the confirmed-hand
   checkbox OFF and use the normal timed loop. Do not type your account
   ID into the recipient room-index field.

This preserves the original fast 0.1s loop, automatic CSV recording,
bookcase sources, three-cycle speed test, group rotation, original
Habbo chat PNGs, whispers and existing updater.

The change has offline regression tests including a simulated
50-player room list. It still requires in-game validation.
