# Habbo Companion

Windows Habbo AIR companion with viewport-filtered chat, original bubble image support, scrollback, and a G-Earth packet viewer.

## v1.0.2 — Automatic G-Earth preparation

Open Habbo Companion BEFORE Habbo. Under Packet Viewer, choose the working beta G-Earth.exe once with Find G-Earth. The new "Automatically prepare G-Earth when Companion opens" option is enabled by default. Approve Windows administrator permission when requested.

Wait for G-Earth to say "Waiting for connection", then launch Habbo. Or select your Habbo launcher executable once and use "Launch Habbo (with G-Earth)" to start it after a warm-up delay.

This is experimental. G-Earth must be ready before the AIR handshake. Its beta automatic connection has not been tested in the user's Windows environment. If Habbo freezes at 60%, disable auto-preparation and use the known-working manual beta connection.

## Updating

Open Habbo Companion > Updates > Check online. Approve the new version.

Permanent update feed:
https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json

The feed specifies the latest version, verified package URL and SHA-256 checksum. Settings are preserved in %APPDATA%/HabboViewChat/settings.json. Updates do not overwrite G-Earth, the Habbo AIR client, private chat logs or credentials. Restore is available in Companion.

## First-time installation

Original [Windows installer ZIP](https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/Habbo_Companion_Installer_v1.0.1.zip), then Check online for v1.0.2. Requires Python 3 with Tkinter.

GitHub Actions now builds versioned update packages from source and publishes latest.json. Python syntax, package validation and rollback have been tested locally; live Windows connection behaviour still needs checking.


## v1.1.43 — Direct TCP experimental mode

The **Direct TCP** tab establishes a real socket to the official Habbo.com hotel
without starting Brave, Habbo.exe, G-Earth or a separate launcher. It implements
the legacy AIR RSA/Diffie-Hellman handshake and tracks distinct account sockets,
reporting **authenticated** only upon the actual server AuthenticationOK packet.

**Login requirement:** Habbo still requires a valid SSO ticket. You can either
paste a ticket or provide authenticated \`session.id\` and \`browser_token\`
values from **your own** Habbo.com session. To avoid opening a browser at each
launch, you may choose to save these session cookies in Windows Credential
Manager under the selected account profile. Companion requests fresh tickets
from Habbo's official HTTPS endpoint, then opens its own TCP socket. Sessions
can expire or be revoked, and there is no password-only authentication or
2FA/CAPTCHA bypass. Never put your cookies or tickets in GitHub issues.

This is a protocol integration and has offline tests only; real Habbo.com
authentication and live room behavior still require a Windows test with valid
tickets. The old Headless Test (loopback fake server) is retained and explicitly
separate. Original G-Earth packet tools are not automatically wired to these
direct TCP sessions; the Direct TCP tab displays packet IDs only.
