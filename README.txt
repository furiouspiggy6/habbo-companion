HABBO COMPANION v1.1.17 — COFFEE USERNAME RESOLUTION FIX
============================================================

WHY THE COFFEE TOOL SHOWED "0 PLAYERS":
Previous versions could erase the entire detected room-player list when
any player left, even when unrelated users were still in the room.

FIXES:
- An incoming UserRemove now removes only the known matching room index.
  Players with unrelated IDs remain mapped.
- Give 1 cup / Start coffee loop now works when the player list was not
  received: type an exact Habbo username and the tool sends
  GetExtendedProfileByName to Habbo through your existing G-Earth session.
- An ExtendedProfile response returns the server-confirmed numeric account
  ID and username; the answer must match the requested username exactly.
- Profile-based gifting is allowed only after the player has spoken in
  the CURRENT Habbo room according to the existing local chat feed.
  This ensures an unrelated player's profile isn't accepted as proof
  of their presence in the room.
- If the target hasn't spoken in the room, ask them to say something
  then press Give 1 cup again. The matching profile ID is retained
  only for that room/session, without guessing an ID.
- Profile lookup gives a specific error after 8 seconds. It does not
  send a cup unless the target can be verified and the confirmation
  dialog is accepted.
- Room/session changes clear pending lookups and profile caches.

HOW TO USE:
1. Connect Habbo Companion and G-Earth, and enter the same Habbo room.
2. Have the recipient say something in chat (for the fallback method).
3. Packet Manipulator > Coffee Pass Loop.
4. Type their exact username and press Give 1 cup.
5. Confirm the displayed username and numeric ID before sending.

The existing two-cup continuous loop, manual recipient ID fallback,
original Habbo speech bubble artwork, one-line/wrapped setting,
whisper-right, and update flow are preserved.

This build has automated tests but the profile packet exchange and
actual coffee transfer must be confirmed in a running Habbo client.
