HABBO COMPANION 1.0.2 — G-EARTH AUTO PREPARE
=================================================

WHAT'S NEW
- In Packet Viewer, enable "Automatically prepare G-Earth when Companion opens"
  (enabled by default). Select the WORKING G-Earth beta with Find G-Earth once.
- Companion requests Windows administrator permission for G-Earth and asks
  G-Earth to prepare its Flash/AIR connection before Habbo is launched.
- "Launch Habbo (with G-Earth)" starts the selected Habbo launcher after a
  warm-up delay. Select your Habbo launcher .exe once; the location is saved.
- Habbo already running? Companion will not start G-Earth mid-session.
- Existing View Chat, custom bubbles, scrollback and settings remain.

IMPORTANT
This version has been checked for Python syntax, client startup flow, and
update/restore behaviour, but the automatic G-Earth beta connection has NOT
been tested live on this Windows PC. A visible G-Earth window is not proof its
proxy is ready. If you see a 60% freeze, disable auto-prepare and use the beta's
manual connection that already worked. UAC approval may be needed each launch.

HOW TO USE
1. Close Habbo before launching Companion.
2. Open Companion. Approve the G-Earth administrator permission prompt.
3. Wait for G-Earth to show Waiting for connection.
4. Launch Habbo normally, or use the new integrated Launch Habbo button.

FILES AND PRIVACY
Keeps settings at %APPDATA%\HabboViewChat\settings.json; does not bundle or
modify G-Earth itself or your Habbo AIR SWF, private logs, or account data.

UPDATES
Companion > Updates > Check online:
https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json
