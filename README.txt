HABBO COMPANION v1.1.0 — MANAGED G-EARTH ENGINE
============================================

One application to open and control: Habbo Companion owns the engine setup,
launcher, packet viewer, and packet manipulation user interface.

WHAT HAPPENS WHEN YOU OPEN COMPANION
- Companion checks whether the G-Earth engine is installed under:
  %APPDATA%\HabboViewChat\engine\1.5.4-beta-29
- First run: it imports the previously selected, working G-Earth beta folder
  into its managed engine directory (no new download), if available.
- Otherwise: it downloads G-Earth 1.5.4-beta-29, Windows x64, from the
  official G-Realm/G-Earth GitHub release (about 103 MB) ONCE.
- The official archive is checked for its SHA-256 digest before extraction:
  c2bffcf8ef8e9df6b2355fe6c5f45690bc24b7211f9848728209e0a9b2b4a6e6
- The engine's original MIT license is retained in the install directory.
- The managed engine is started with the already verified Windows normal
  launch behavior and G-Earth's native Flash/AIR automatic connect flags.
- After its extension backend responds on port 9092, Companion can minimize
  the engine window while it runs in the background.
- The companion updater remains small; it doesn't redownload 103 MB each time.

BUILT-IN FUNCTIONS
- Packet Viewer, with capture and packet inspection
- Packet Manipulator, with opt-in block/replace rules and manual send
- Chat overlay and chat display settings
- Engine status directly above Packet Viewer
- Install/repair engine and advanced troubleshooting controls

LIMITATIONS
- This is an integrated, self-managed copy of the G-Earth Java engine, NOT an
  independent Python reimplementation of the underlying G-Earth proxy.
- The official engine still runs as a separate Java process internally.
- Windows administrator consent may still be requested by G-Earth.
- A responsive extension port is NOT proof the Habbo proxy has reached
  Waiting for connection. Check the proxy state during the first launch.
- DO NOT attach the packet viewer until Habbo has fully loaded into a room,
  to avoid repeating the earlier 60% load freeze.
- Packet manipulation starts OFF, even when rules were saved previously.
- Test on your PC is still required; the release build validates Python
  syntax and the update package, not the live Habbo AIR connection.

G-Earth upstream: https://github.com/G-Realm/G-Earth
G-Earth release: https://github.com/G-Realm/G-Earth/releases/tag/1.5.4-beta-29
License: MIT, Copyright (c) 2018 sirjonasxx.
The full license is copied into the local managed engine installation.
