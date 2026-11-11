HABBO COMPANION v1.1.21 — OPT-IN MULTI-PLAYER COFFEE ROTATION
==============================================================

MULTI-PERSON ROTATION
---------------------
A new Group mode checkbox in Packet Manipulator > Coffee Pass Loop lets
you list two to eight willing participants, separated by commas.
The loop hands a cup to each in list order, then reverses which cup each
participant receives on the next round. Each participant receives both
Cup 1 and Cup 2 per complete group cycle. The option is disabled by
default and never changes the existing single-recipient coffee loop
or Give 1 cup action.

Start coffee pass loop resolves each username using the room user list
or an exact Habbo profile reply before offering the existing confirmation
dialog. All names appear in the confirmation. A profile confirms an
account ID but does not prove their room presence or consent. A missing,
unknown or mismatched account stops group setup.

To reduce rapid unsolicited handoffs, group mode requires at least
10 seconds between individual packet actions. Set Delay per action to
10 or more when Group mode is enabled. Set Complete loop cycles to
0 to run until stopped, or enter a finite number.

EXCLUSIONS AND BLOCKS
---------------------
Type a username in "Exclude participant" and click "Remove from rotation".
The recipient is excluded immediately; if fewer than two participants
remain, the group loop stops. A known room departure also excludes
that player. Nobody excluded is automatically re-added.

This version deliberately does NOT probe whether another Habbo has
blocked or ignored you and does NOT periodically retry sending to a
player who has blocked or opted out. A rejected handoff is not
reliable proof of a block: a recipient could be out of range, absent,
or otherwise unable to accept a hand item.

DELIVERY STATUS
---------------
The monitor continues to separate pass requests from CarryObject room
updates, which are evidence of carrying an item but not a definitive
per-cup receipt. Profile-based IDs without a room index cannot be
independently verified. No success is claimed merely from a sent packet.

All previous features remain: original Habbo PNG chat bubbles, whisper
alignment, G-Earth integration, one-cup gifting, single-recipient
alternating cup loop, saved settings and in-app updater.

UPDATE: Habbo Companion > Updates > Check online.
