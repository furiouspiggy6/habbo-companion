HABBO COMPANION v1.1.10 — AUTOMATIC G-EARTH PACKET CONNECTION
===============================================================
Coffee Pass Loop no longer requires opening Packet Viewer or clicking its
Connect button to attach Companion's own G-Python packet extension.

New connection behaviour:
- G-Earth remains the engine; G-Manipulate and Packet Logger remain independent.
- Companion attaches its packet tools to the local G-Earth extension port
  automatically when the backend is online and Habbo has not yet launched.
- If Habbo is already open, Companion waits for room evidence from the local
  chat bridge so it does not attach during the AIR loading screen.
- You can instead press Start in Coffee Pass Loop after you enter the room.
  Companion will attach directly and wait for the active room connection,
  then ask for confirmation before sending any coffee packets.
- The Coffee Pass Loop tab now shows the packet connection status.
- Automatic packet-tool attachment does NOT enable packet logging,
  manipulation rules, or any automated sending.
- If auto-connection fails, the tool reports the error and can retry later.
- STOP cancels both a pending coffee-loop start and a running loop.
- Connection loss stops running loops; it never silently resumes them.


WIDE CHAT / WHISPERS
--------------------
In View Chat the new settings are enabled by default:
- "Single-line chat bubbles (auto width)": messages stay on a single row
  and expand across the Habbo window rather than wrapping in the old
  narrow bubble column.
- "Whispers on the right": Habbo ChatItem type 2 chat is right-aligned
  while regular speech remains left-aligned.
- Native Habbo PNG artwork is kept for short, already single-line
  bubbles. PNGs that contain multiple rows are replaced with a one-line
  rendering (style colours retained, avatar represented with an initial).
- Long text may shrink to a 9-point font; if still wider than the
  actual Habbo window, it displays an ellipsis. No content is drawn
  beyond the window boundary.
- One shared vertical chat stack preserves chronological order and avoids
  collisions between normal chat and whispers.
- Both settings can be disabled to restore the previous wrapped layout.
- The overlay grows to the game width in this mode, remaining click-through.

Existing features preserved:
- Packet Viewer remains available for optional troubleshooting.
- Rules & Replay, manual injection, coffee IDs, target ID, and interval.
- Engine launch, network safeguards, updater, and local user settings.
- Minimum coffee-loop interval remains 0.1 seconds; server rate limits
  or unavailable items can prevent a sent packet from working in Habbo.

Instructions:
1. Start Companion (with G-Earth enabled), then start Habbo and enter a room.
2. Open Packet Manipulator -> Coffee Pass Loop. No Packet Viewer step needed.
3. Check that connection status reads READY.
4. Select cups/recipient, then press Start and approve the confirmation.
5. If Habbo was already running before Companion, press Start once; the
   extension can connect there and will confirm before it begins sending.

To update: Updates -> Check online -> approve v1.1.10.
