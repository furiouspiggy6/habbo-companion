HABBO COMPANION v1.1.19 — GIVE COFFEE WITHOUT ROOM CHAT
==========================================================

You can now give a cup by typing someone's Habbo username EVEN IF THEY
HAVE NOT SPOKEN IN ROOM CHAT.

HOW IT WORKS
------------
1. Enter the same Habbo room as the intended recipient.
2. Open Packet Manipulator > Coffee Pass Loop.
3. Enter the exact Recipient username and press Give 1 cup.
4. Companion checks its current room-player list. If the player is not
   mapped, it sends GetExtendedProfileByName to the Habbo server.
5. Habbo must return the matching username and a valid numeric account ID.
6. Confirm the username and ID in the existing dialog before any cup
   packets are sent.

NO CHAT REQUIREMENT
-------------------
A Habbo profile confirms the account identity, but does NOT prove that
the account is standing in your current room. The confirmation dialog
clearly warns you when only the profile ID was verified. Ensure the
person is actually in the room yourself; Habbo can reject an out-of-room
or out-of-range item pass.

Verified profile IDs are held in a separate in-session cache rather
than being falsely counted as detected room occupants. Room changes,
disconnects and restarts clear the cache. Unknown or mismatched profile
replies never trigger a transfer.

Nothing changes for users already mapped from room packets. The
numeric fallback ID remains available when username is blank. Original
Habbo PNG bubbles, whisper-right alignment, coffee pass loop and all
other features are preserved.

INSTALL: Habbo Companion > Updates > Check online.
