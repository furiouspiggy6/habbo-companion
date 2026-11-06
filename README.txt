HABBO COMPANION v1.0.5 — AUTOMATIC G-EARTH PREPARATION
=====================================================
Open Habbo Companion. It will start your previously selected, working G-Earth
beta and attempt to activate the native Connect control automatically.

WHAT CHANGED
- Defaults to automatic G-Earth preparation on Companion startup.
- Opens the beta normally and uses Windows UI Automation to activate its own
  Connect control. Does NOT use the unreliable early --connect flash CLI mode.
- Checks for "Waiting for connection" or "Connected" before reporting ready.
- Minimizes the G-Earth window ONLY after readiness is confirmed.
- Leaves G-Earth visible with a status message if Windows cannot activate or
  verify Connect. The manual Connect method remains available.
- Never attaches the G-Python packet viewer during the AIR loading handshake.
  Open Habbo, enter a room, then attach the packet viewer.
- All saved chat settings, native bubble support, scrollback and packet rules
  are retained. Packet manipulation still starts OFF every session.

SETUP
- You must have selected the working G-Earth beta EXE in Companion previously.
- On Companion startup, approve the standard Windows administrator prompt.
- Wait for Companion's "G-Earth is ready" status before launching Habbo.
- Once G-Earth is waiting, launch Habbo normally and it will connect through it.
- If Windows accessibility doesn't expose the JavaFX Connect button, G-Earth
  stays visible so you can click Connect manually. This is still experimental.

LIMITS
- This was checked statically; it has not been verified running on your PC.
- Starting Habbo before G-Earth is ready can still lead to the 60% hang.
- Repeated UAC prompts are not bypassed; no permanently elevated scheduled
  task is installed or UAC disabled.
- Use Packet Viewer > Start and prepare G-Earth when Companion opens to turn
  auto-preparation off or back on after installing the update.
