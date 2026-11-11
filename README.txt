HABBO COMPANION v1.1.13 — GIVE A CUP BY USERNAME
================================================

New in Packet Manipulator > Coffee Pass:
- Enter the exact Habbo username of someone in the same room.
- Click "Give 1 cup" to use Cup 1 furniture and pass it to that player once.
- Or click "Start coffee pass loop" to repeat Cup 1/Pass/Cup 2/Pass.
- The existing numeric recipient ID is used only if username is blank.
- Names are resolved from incoming room Users packets through G-Earth.
- If a name is not found, no cup packets are sent to an old or guessed ID.
  Click "Refresh room players", or leave and re-enter the room.
- On disconnect, room changes, or target removal, automation stops.

Instructions:
1. Open Habbo Companion, then enter a Habbo room with the target.
2. Open Packet Manipulator > Coffee Pass.
3. Wait for detected player names (or click Refresh room players).
4. Enter the username and click Give 1 cup or Start coffee pass loop.
5. Confirm the shown username and ID before sending.

The parser uses only the early ID/name fields of Habbo's Users packet.
These may change in future clients: actual in-game behaviour still needs
testing. Server rules and rate limits can prevent successful transfers.

Existing chat overlay, G-Earth management, packet viewer, manipulation
rules, local settings and 0.1s minimum interval are unchanged.
No sending starts automatically at launch; each run requires a click
and confirmation.

To update: Habbo Companion > Updates > Check online.
