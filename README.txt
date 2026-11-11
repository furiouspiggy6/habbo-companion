HABBO COMPANION v1.1.18 — SHOUTS LEFT, WHISPERS RIGHT
========================================================

FIXED: Bold "shout" bubbles were incorrectly being aligned to the right.
Habbo AIR's room-chat event types are:
  0 = normal speech (left)
  1 = whisper (right when "Whispers on the right" is ON)
  2 = shout / bold speech (left)
  10 = bot speech (left)
  11 = bot shout (left)
  12 = bot whisper (right)

The previous Companion code incorrectly treated type 2 (SHOUT) as WHISPER.
The original Habbo client source confirms that type 1 is WHISPER
and type 2 is SHOUT.

Packet-based whisper hints now apply only when the local Habbo chat feed
did not supply an explicit chat type. They cannot override a real shout
from the client.

The original Habbo chat PNG artwork is rendered unchanged (no custom
white bubbles). Coffee username resolution, room-player mapping fixes,
and all other packet tools are preserved.

UPDATE: Habbo Companion > Updates > Check online.
