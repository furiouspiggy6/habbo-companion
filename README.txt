HABBO COMPANION v1.1.20 — COFFEE DELIVERY MONITOR & STEADIER CURSOR
===================================================================

COFFEE DELIVERY MONITOR
-----------------------
The Coffee Pass panel now reports:
- Pass requests sent: number of PassCarryItem packets accepted by the
  local G-Earth send interface. This does NOT prove the recipient got one.
- Recipient carrying-item updates observed: the number of incoming
  CarryObject notifications with a nonzero item type and a matching ROOM
  AVATAR INDEX received within four seconds of a pass request.
- When no room avatar index is known (for example, when resolving the
  username only from a Habbo public profile), it clearly says receipt
  cannot be verified from this connection.

These are separate counts. A server carry-state update suggests the
recipient was holding an item, but it is NOT a per-cup delivery receipt.
Habbo sends HandItemReceived directly to the recipient; the giver's
client cannot generally see that private notification. Sending a cup
can fail because the recipient is absent, too far away, or blocked by
server rules.

The monitor always shows the difference between requests attempted and
available server-side activity. It never labels a sent packet alone
as delivered. If you're using a profile ID without a room avatar index,
you can ask the recipient to confirm they see the cup.

CURSOR / OVERLAY STABILITY
--------------------------
Companion previously redrew the entire full-screen, transparent chat
canvas at each 120ms update, even when messages and settings did not
change. It now draws immediately on new messages, scrolling, game
window motion, and settings changes; otherwise it refreshes about
every 600ms. Full-screen click-through and window-stacking checks
are also less frequent when nothing changed.

This reduces unnecessary layered-window activity that can contribute
to cursor flicker. It does NOT programmatically move or click the
mouse. If the cursor still flickers, press STOP in Coffee Pass to test
whether rapid Habbo furniture interactions are responsible, and
try a higher delay per action.

All original native Habbo bubble PNGs, whisper-right settings,
username-based coffee targeting and unlimited loop cycles (0)
remain in place.

INSTALL: Habbo Companion > Updates > Check online.
