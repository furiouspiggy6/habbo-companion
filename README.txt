HABBO COMPANION v1.0.8 — BACKGROUND G-EARTH STARTUP
===================================================
Companion starts G-Earth before Habbo, with a minimized Windows process.
G-Earth's own --connect flash --host HOST --port PORT arguments request
the Habbo AIR proxy connection. No PowerShell, simulated clicks, or
dependency on a visible G-Earth window.

CHANGES
- Launch minimized (Windows SW_SHOWMINNOACTIVE), not hidden/headless.
- Poll G-Earth's local extension service (typically port 9092) instead
  of waiting for a JavaFX window. When the port responds, G-Earth's
  extension backend is available.
- One-time migration enables startup and minimize, as requested; the
  user can disable either option later.
- Discover a clearly identifiable beta EXE in common installation and
  Downloads folders if the saved executable has moved.
- Report missing executable, admin denial, backend timeout or existing
  G-Earth instance in Packet Viewer's STATUS text, above the packet list.
- Preserve all saved settings and packet rules. Rules always start OFF.
- NEVER attach the packet viewer during Habbo login.
- Empty Packet Viewer before Habbo logs in is NORMAL.

IMPORTANT
Port 9092 responding is not confirmation that the Flash proxy is
WAITING_FOR_CLIENT. G-Earth may still have a GUI event loop and may
request Windows administrator consent; there is no UAC bypass or
true headless mode. CLI auto-connect remains experimental on this PC.
If Habbo stalls at 60%, disable background auto-start and revert to
the known-working manual Connect sequence.
