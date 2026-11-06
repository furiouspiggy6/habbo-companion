HABBO COMPANION v1.0.7 — DIRECT G-EARTH STARTUP
================================================

Open Habbo Companion BEFORE Habbo. Companion now starts the selected G-Earth
beta directly through Windows ShellExecuteW, requesting admin consent and
G-Earth's native --connect flash --host ... --port ... options.
No hidden PowerShell helper or unreliable JavaFX accessibility button clicks.

- Direct native launcher, with launch result and a real-window timeout status
- G-Earth version window titles detected more flexibly
- Auto-connect uses G-Earth's own native connection code, not a simulated click
- Packets remain blank before Habbo connects, which is normal
- Packet viewer NOT attached until after Habbo fully loads; no early G-Python
- All personal settings remain; packet rules always OFF at startup

Confirm that G-Earth shows Waiting for connection before starting Habbo.
This direct native auto-connect is experimental on this PC, because previous
CLI attempts coincided with a 60% hang. If that happens again, disable automatic
G-Earth launch and use Open G-Earth (safe), then click Connect manually.
G-Earth may still request Windows admin permission.
