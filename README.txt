HABBO COMPANION v1.1.2 — ONE-CLICK DIAGNOSIS AND REPAIR
=====================================================
This update directly addresses "Engine installed · backend OFFLINE."

- Removes false Habbo-window detection from blocking G-Earth startup.
- Adds Diagnose & repair in Packet Viewer. It checks whether G-Earth/Java
  runs, whether port 9092 responds, and then safely tries the *known working*
  Windows PowerShell Start-Process -Verb RunAs launch sequence if the engine
  is not running. Windows UAC consent is still required.
- Avoids starting duplicate G-Earth processes if one is already detected.
- Adds Copy diagnostic, for a local report with engine status and PIDs but
  no packet contents, messages, or account data. Also saves
  %APPDATA%\HabboViewChat\gearth-diagnostic-last.txt
- Checks network setup off the UI thread so Companion remains responsive.
- Fixes the online updater's stale-manifest problem by requesting a fresh
  cache-busted URL and displaying the feed version.
- The managed G-Earth 1.5.4 beta engine remains installed and is not
  downloaded again. User settings and packet rules are preserved.

IMPORTANT
The extension port responding does not prove the Habbo proxy is WAITING.
Keep Habbo closed until G-Earth is ready; do not attach packet viewer until
Habbo has loaded, to avoid the previous 60% freeze.
These Windows behaviors need live verification on the user's PC.
