HABBO COMPANION v1.1.3 — AUTO-HIDE INTEGRATED ENGINE WINDOW
==============================================================
The user's screenshot confirmed the integrated G-Earth 1.5.4 beta 29 engine
is automatically launching and says "Waiting for connection" in G-Earth.
This update retains that successful startup and changes only window handling.

- Companion launches the engine normally; NEVER start JavaFX minimized.
- After the backend responds on extension port 9092, automatically request
  SW_HIDE for the G-Earth window (not just minimize-to-taskbar).
- Check IsWindowVisible to verify Windows actually hid the window. Retry
  for up to 10 attempts; report when window hiding was not confirmed.
- Add "Hide now" to Packet Viewer for manual hiding without PowerShell.
- Advanced G-Earth restores the same running engine window without relaunch.
- After manually opening the window, automatic hiding is paused so it stays
  accessible until "Hide now" or the next startup.
- Checkbox now says "Hide engine window when ready." Unchecking it shows
  the advanced window; checking it requests hiding.
- Keep the existing G-Earth auto-connect args, packet viewer, manipulator,
  user settings and current managed runtime unchanged.
- Additional tests check that hide is after backend readiness, window hide
  is verified, and advanced restore is supported.

G-Earth remains an internal Java process; hiding its window does not stop
its proxy or change game packets. On Windows systems that prevent external
applications from controlling elevated windows, the window may stay visible;
Companion reports that rather than pretending hide succeeded.

As before, the extension port being online is not proof that the game proxy
has reached Waiting for connection. The user confirmed that state manually
in the screenshot for their current startup.
