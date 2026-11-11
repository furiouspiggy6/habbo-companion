HABBO COMPANION v1.1.14 — ROOM PLAYER LOOKUP FIX
================================================

FIXED:
- "Refresh room players" no longer displays an indefinite waiting message.
  After 12 seconds it says whether a Users packet was received.
- Room user identification now checks G-Earth's packet-name metadata
  instead of assuming a name is present in the legacy packet rendering.
- Reads G-Earth's decoded packet expression for player IDs/usernames.
- If expression detection is incomplete, tries reading the stable
  user-count / first-ID / first-username binary prefix.
- Clearly reports if a Users packet arrived but could not be decoded.
- No username is guessed. The existing manual numeric fallback remains.

INSTRUCTIONS:
1. Open Habbo Companion, then enter the Habbo room with the person.
2. Open Packet Manipulator > Coffee Pass.
3. Enter exact username, or click Refresh room players.
4. If the refresh says no Users response after 12 seconds, leave the room
   and re-enter while Companion and G-Earth are connected.
5. Click Give 1 cup and confirm the recipient's name and ID.

The G-Earth GetHeightMap request does not guarantee that Habbo will resend
the player list. Re-entering a room is a more reliable way to receive
the initial room Users packet if the player-name cache is empty.

The existing chat overlay, one-cup transfer, two-cup loop, native packet
viewer, and updater are preserved. Success in an actual Habbo room has
not yet been verified. Server restrictions can reject sent actions.

Update using Habbo Companion > Updates > Check online.
