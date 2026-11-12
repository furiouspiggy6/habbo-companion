HABBO COMPANION v1.1.24 — OPTIONAL BOOKCASE / EXTRA SOURCES + SPEED TEST
=========================================================================

MORE HAND-ITEM SOURCES
----------------------
The original Coffee Pass loop still performs:
    UseFurniture Cup 1 -> PassCarryItem recipient
    UseFurniture Cup 2 -> PassCarryItem recipient
    repeat.

There is now a "Other furniture IDs" box for up to FOUR additional
hand-item dispenser furniture instance IDs. A bookcase that gives books
is one example. With one additional source, the cycle becomes:
    pick up Cup 1 -> pass -> pick up Cup 2 -> pass
    -> pick up Bookcase item -> pass -> repeat.
Each source is used sequentially; the loop NEVER tries to hold several
different items at the same time.

These must be instance IDs of furniture actually inside the Habbo room,
NOT hand-item type numbers (for example, 1003 is a book hand-item type,
not the instance ID of the bookcase in your room).

CAPTURE THE BOOKCASE WITHOUT MANUAL PACKET INSPECTION
-----------------------------------------------------
1. Start Companion and G-Earth and enter the Habbo room.
2. Stop any running coffee loop.
3. In Coffee Pass click "Capture next furniture click".
4. In Habbo, double-click your bookcase to use it.
5. Companion records that one outgoing UseFurniture instance ID and
   adds it to "Other furniture IDs" (if not already configured).
6. You can repeat for up to four additional sources.

Only item-dispensing furniture will actually give you an item. Some
bookcases are decorative; a captured ID does not prove a hand item was
picked up. The ordinary Cup 1 and Cup 2 remain unchanged.

A consenting group rotation also accepts additional sources; each
participant gets a turn for every source type over a complete group
cycle. Group mode still requires 10 seconds per packet action and
excludes anyone who opts out.

FINITE SPEED TEST / MEASURING PRACTICAL LIMITS
---------------------------------------------
The "Test speed (3 cycles)" button is a finite single-recipient test
(not available in group mode). It always uses the optional sender-side
CarryObject confirmations whether or not the checkbox for confirmed
pickup is enabled. It requires your own Habbo account's room avatar
index to be recognized first: use "Detect my avatar" if necessary.

The test performs exactly THREE full source cycles at the entered
Delay per action and then STOPS automatically. You must confirm the
recipient before sending any test packets.

The displayed summary includes:
- elapsed time;
- the number of your own positive carrying-item updates (pickups);
- the number of confirmed empty-hand updates following a pass request;
- outgoing PassCarryItem request count;
- confirmed own pickup events per minute; and
- pickup confirmation counts for EACH source furniture ID.

These are measurements of the sender's client and server messages,
NOT receipts on the recipient's client. If your own avatar cannot be
identified, the test will not run rather than guessing. If a carry
confirmation does not arrive, the test stops after its timeout and
reports partial statistics. It does not silently claim a transfer
succeeded or try to work around rate limits.

To compare practical throughput, run a test at a chosen delay and note
the confirmed pickup events per minute. Then repeat with a DIFFERENT
delay, or compare two-cup rotation versus rotation including a
bookcase. A larger furniture list does not necessarily increase item
throughput; the Habbo server may enforce shared limits/cooldowns.
The test does NOT automatically step through increasingly fast speeds.

All previous features remain: original Habbo PNG speech bubbles,
whispers on the right, optional confirmed hand state, username
resolution, manual opt-out, unlimited regular cycles and updater.

INSTALL: Habbo Companion > Updates > Check online.
