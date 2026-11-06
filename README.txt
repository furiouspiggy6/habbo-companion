HABBO COMPANION v1.1.6 — SINGLE-WINDOW USER INTERFACE
=======================================================
Habbo Companion now provides the main user-facing workspace for Habbo,
G-Earth's already-working connection engine, packet viewer and manipulator.

- Primary controls: Start engine, Launch Habbo and Connect packet viewer.
- Reorganised Packet Viewer into one CONNECTION + PACKETS workspace.
- Original G-Earth window is normally hidden after startup (1.8 seconds
  after the extension backend responds). Engine still starts in normal
  window mode to preserve the tested JavaFX and AIR initialisation.
- One-time migration turns ON the "hide original window" setting only;
  it does not change or re-enable your engine automatic-start preference.
- "Advanced settings" expands within Companion to show the original engine
  window for troubleshooting, return to single-window view, set hotel and
  ports, inspect the network, or use recovery and diagnostic tools.
- Launch Habbo uses the internal engine's backend check rather than
  requiring its original window to be visible. Because port 9092 does not
  independently confirm the proxy WAITING state, Habbo launch still
  requires confirmation.
- Packet viewer is deliberately connected manually AFTER Habbo loads
  into a room to avoid the previously reproduced 60% loading freeze.
- Windows proxy/hosts safety controls and consent requirements remain.

IMPORTANT: This is a SINGLE USER-FACING WINDOW, not one OS process. The
MIT-licensed G-Earth Java process still runs internally in the background.
Windows UAC may be required, and elevated windows may resist hiding under
some Windows configurations. If hiding fails, Companion reports it.
The live behaviour must still be tested on the user's PC.
