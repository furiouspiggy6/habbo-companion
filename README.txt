HABBO COMPANION v1.0.6 — VISIBLE G-EARTH STARTUP
================================================

When Companion opens, it attempts to prepare the saved G-Earth beta before Habbo starts.

- Fix: request a NORMAL visible G-Earth window from the elevated PowerShell helper.
- Fix: disable auto-minimize once, so the G-Earth window is visible for troubleshooting.
- Safe fallback: if the helper never creates a G-Earth window, use the known-working
  direct Windows launch without automatic connection flags. This may request UAC again.
- The helper still attempts the usual G-Earth Connect control when available.
- Keep Habbo closed until G-Earth says Waiting for connection.
- Only attach the packet viewer after entering Habbo; packet rules remain OFF.
- Saved chat settings, G-Earth beta path and packet rules are preserved.

If automatic Connect is not available through Windows UI Automation, G-Earth remains
visible for one manual Connect click. This version cannot guarantee that native
JavaFX controls are exposed to automation and has not been tested on the user's PC.
