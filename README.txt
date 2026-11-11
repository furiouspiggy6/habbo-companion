HABBO COMPANION v1.1.22 — WAIT FOR PICKUP / EMPTY HAND
=======================================================

WHAT THIS CHANGES
-----------------
The existing coffee sequence already sends these packets IN ORDER:
  UseFurniture Cup 1  -> PassCarryItem recipient
  UseFurniture Cup 2  -> PassCarryItem recipient
  ... then repeats (or rotates through willing group participants).

However, sending an outgoing UseFurniture packet never established that
your avatar actually RECEIVED the cup first. v1.1.22 adds an OPTIONAL
checkbox in Packet Manipulator > Coffee Pass Loop:

  [ ] Wait for my avatar to receive/pass each cup

When ON:
1. Send UseFurniture for the next cup.
2. Wait for an incoming server CarryObject notification for YOUR OWN room
   avatar index with a positive item type, indicating you are holding it.
3. Wait your configured action delay, then send PassCarryItem to the
   selected recipient.
4. Wait for an incoming CarryObject notification for YOUR OWN avatar
   with item type 0, indicating your hand has emptied.
5. Wait your configured delay, then pick up the other cup and repeat.

If either notification never arrives, the loop STOPS (8 seconds for
pickup, 25 seconds for a pass/empty hand). It does not blindly continue.
A release confirmation is NOT proof that the recipient received a cup:
Habbo can drop, reject or otherwise redirect hand items.

The checkbox is OFF by default. When OFF, the prior fixed-delay sequence
is preserved unchanged, including all the existing group rotation logic.

OWN AVATAR DISCOVERY
--------------------
The app detects your own account ID and username from incoming UserObject
and matches them to your room index in the incoming Users packet. When
possible, it uses G-Python's full room entity parser to resolve indexes,
falling back to the previous name/ID parser if that parser fails.
A status line under the Coffee Pass settings shows your own room index.

If the index is unavailable, confirmed pickup mode cannot start.
Connect Companion/G-Earth before starting Habbo and re-enter the room;
this lets the app observe both your account details and room Users data.
Do not use another avatar's room index or infer it from an account ID.

Group rotation remains opt-in for willing players with a 10-second
minimum per action, and existing exclusion controls remain immediate.
Removing someone mid-acknowledgment stops that pending group action
so no old target is sent a delayed cup.

Native Habbo bubbles, whisper positioning, visual overlay,
packet viewer, delivery monitor and online updater are unchanged.

INSTALL: Habbo Companion > Updates > Check online.
