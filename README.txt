HABBO COMPANION v1.0.9 — VERIFIED STARTUP-LAUNCH FIX
=====================================================

PowerShell testing confirmed the user's G-Earth beta starts and reaches
Waiting for connection with:
Start-Process -Verb RunAs -ArgumentList
'--connect flash --host game-us.habbo.com --port 30000'

Companion previously sent Windows SW_SHOWMINNOACTIVE (7) at process creation,
which differs from that successful normal-window launch behavior.

FIX
- Use the same normal-window startup mode (SW_SHOWNORMAL=1) as the successful
  PowerShell test, with G-Earth's native --connect flash flags.
- Do NOT start G-Earth minimized. Minimize its GUI 3.5 seconds AFTER local
  extension port 9092 starts responding, while leaving the Java process running.
- Explicitly distinguish Windows launch acceptance from backend availability.
- Never attach the G-Python packet viewer before Habbo completes login.
- All packet manipulation rules start disabled. Save previous user settings.
- No change to the working G-Earth path or existing chat functionality.

IMPORTANT
The extension port responding does NOT independently prove that the game proxy
has reached Waiting for connection. Before launching Habbo for the first test,
check G-Earth's connection state. If Habbo gets stuck at 60% again, disable
automatic preparation and use the previously working manual Connect sequence.

This changes the launch behavior observed to differ from successful PowerShell
test. The Windows behavior cannot be verified until tested on the user's PC.
