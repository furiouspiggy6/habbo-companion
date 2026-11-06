HABBO COMPANION v1.1.9 — TWO-CUP COFFEE PASS LOOP
=================================================
Packet Manipulator now has two inner tabs: Rules & Replay and Coffee Pass Loop.

Coffee Pass Loop (OFF by default):
- Cup 1 furniture ID: 476989081
- Cup 2 furniture ID: 476989024
- Recipient target ID: 68808036 (editable)
- Delay between actions: minimum 0.1 seconds (100 ms), maximum 120
- Complete cycles: 0 to run until STOP, or 1 to 10000
- Sequence: Cup 1 -> Pass -> Cup 2 -> Pass, repeating in that order.
- Separate Start and STOP controls; target and interval are saved when started.
- Stops when Companion closes or the game/G-Earth disconnects.
- Will not run at the same time as the single-packet repeater.
- G-Earth packet parsing is validated before any action sends.

Using the feature:
1. Launch Habbo Companion, start the G-Earth engine, and join your room.
2. Connect Packet Viewer.
3. Open Packet Manipulator -> Coffee Pass Loop.
4. Enter the two captured cup IDs and the intended PassCarryItem recipient ID.
5. Set delay and cycles; press Start and confirm.
6. Use STOP whenever you want.

Recipient IDs can depend on the current room/session. Verify the target by
capturing your own PassCarryItem packet after joining a new room.
The server may ignore or rate-limit rapid commands. This tool sends actions
without confirming that the receiving avatar accepted each item.
Avoid sending unwanted items to other players or violating Habbo rules.

Auto update: Open Updates -> Check online and approve v1.1.9.
Settings and the managed G-Earth engine are not overwritten by updates.
