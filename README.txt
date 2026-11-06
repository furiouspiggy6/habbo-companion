HABBO COMPANION v1.1.1 — MANAGED ENGINE SETUP RECOVERY
=========================================================

This release fixes the initial setup issue reported in v1.1.0:
the Packet Viewer showed "Engine: not yet installed" even though automatic
integrated engine startup was enabled and Habbo was closed.

- Engine installation is now independent from window-title detection.
  It is safe to install the engine even if another program presents a
  Habbo-like title. Only the final proxy launch is postponed if Habbo
  really is running.
- Automatic startup exceptions are displayed in Packet Viewer instead
  of silently disappearing inside the Python .pyw process.
- Engine installation errors remain visible across periodic status polls,
  until the user deliberately retries installation.
- A status message distinguishes startup not yet attempted, installation
  pending, installed but backend offline, and actionable setup errors.
- Install / repair continues to work even if the automatic first run
  was interrupted. Previous chat and packet settings are preserved.
- Additional offline tests exercise false-positive window detection
  and error persistence.

Integrated runtime: G-Earth 1.5.4-beta-29 (MIT).
Companion still uses the original Java engine internally and does not
replace its packet proxy with a separately written Python implementation.
Packet manipulation starts OFF; attach the viewer only after Habbo loads.
