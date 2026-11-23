# Habbo Companion

## v1.1.74 — Create your own AI personality and test responses safely

The **AI Responder** page has **Personality**, **Who to reply to**, and
**Test without sending** tabs.

- **Custom personality** is the default: describe how the bot talks and behaves
  in your own words, select a tone (Casual, Friendly, Playful, Dry, Sarcastic,
  Serious) and humour from 0–5. No named persona, log file, or captured
  writing style is needed. The old **Chat-log style** option is still available
  explicitly if wanted.
- **Everyone**, **Selected users**, and **First active speaker** target modes.
  Selected users accepts a comma-separated set of exact usernames (ignoring
  case); non-selected speakers provide room context but cannot trigger replies.
  First active speaker locks to one speaker for 60 seconds of silence.
  **Natural** vs **Chatty** determines how often the AI decides to participate;
  all modes retain the short anti-spam cooldown and repeated-question checks.
- **Test AI reply (preview only)** accepts a test speaker and message. It sends
  that sample to OpenAI and displays a preview under Recent Decisions. It works
  even when the live responder is OFF and when Habbo/G-Earth are disconnected.
  Test responses **never** enter auto-send, even if Auto-send is checked. A
  valid `OPENAI_API_KEY` and the optional `openai` Python package are required.
- Live reading still uses the AIR chat feed. Auto-send still requires the
  connected G-Earth session and an observed outgoing public Chat packet.
  Live responder and automatic sending are both OFF when Companion starts.

To try it: update to **v1.1.74**, open AI Responder → Personality, edit the
description, open Test without sending, type a sample message and click
**Test AI reply**. Next, in Who to reply to, choose Everyone or Selected
users, then Apply settings and enable the live responder. Avoid enabling
Auto-send until previews and live draft decisions behave as intended.

## v1.1.73 — Optional AI Responder

The **AI Responder** has its own sidebar workspace. It listens to **new** public
room messages through Companion's existing Habbo AIR chat feed; the older
`Responder_Single.py`/ `capture.py` pair and hard-coded chat coordinates are
not needed. It can load style examples from your old `chat_logs/users` folder,
lock onto the first eligible speaker for 60 seconds (or use a named target),
rotate styles every five minutes, generate short replies and choose `SKIP`.
The name filter containing `dan`, repeated-question checks, and four-second
minimum reply interval are retained. Whisper messages are never triggers.

**Setup:** Install the optional API client with `py -m pip install openai`
using the Python interpreter that runs Companion. In PowerShell, set
`$env:OPENAI_API_KEY = "<your-key>"` before launching Companion from that
same shell (or configure a secure user environment variable). Your key is
not written to Companion settings. Open **AI Responder**, select the style
log folder, click **Apply settings**, then enable the responder. AI is **OFF
by default**, and automatic in-game sending is **separately OFF by default**.
While enabled, the selected historical chat samples and recent room context
are sent to the OpenAI API for generation. Leave disabled if you do not want
chat content sent to a third-party service.

For automatic sending, attach **Packet Viewer → G-Earth** to the Habbo AIR
session and type one ordinary public chat message yourself. The Companion
learns that live session's outgoing Chat packet expression and changes only
its message-text field; it will **not** invent packet IDs or use screen
coordinates. With automatic sending off, you can inspect drafts and send the
latest one manually. This path requires a working G-Earth session and needs
live Windows verification; Direct TCP connections are not a chat-send backend.

The update ZIP still contains only the three application files accepted by
older Companion update helpers. Both responder modules are bundled into the
application at release-build time. No additional network traffic is generated
until you enable AI.

## Protocol Lab connected server status (read-only)

Protocol Lab displays an authenticated Direct TCP socket's observed peer IP/port,
or the configured G-Earth game endpoint when its AIR session is active. G-Earth's
configured address is **not proof of the actual remote peer IP**. Use **Refresh
connected server** or watch the status update when sessions connect/disconnect.
This feature never transmits packets or handles passwords or SSO tickets.

**Boofuzz remains limited to the synthetic server on your own PC.** Discovering
a live peer does not make it a permitted fuzz target.

## v1.1.71 — Fuzz a test server on another machine (authenticated)

**Protocol Lab → Remote test machine** now accepts the IPv4 address and port of
another computer or VM that you control, including a public IP. The other
machine must run the included [lab_remote_server.py](lab_remote_server.py)
helper and you must know its independently generated lab key.
Companion authenticates **each** TCP connection with a fresh HMAC challenge
*before* it sends any synthetic test packet. An unrecognised remote service
never receives a fuzz payload. It is not an unrestricted network fuzzer.

On the **test server machine**, download `lab_remote_server.py` from this
repository, install Python 3, and in PowerShell run:

```powershell
$env:HABBO_LAB_KEY = (python -c "import secrets; print(secrets.token_hex(24))")
$env:HABBO_LAB_KEY  # Copy this lab-only key privately to the Companion PC
python lab_remote_server.py --listen 0.0.0.0 --port 39099
```

Using `0.0.0.0` deliberately exposes the authenticated test helper on all
network interfaces of that test machine; prefer a specific address and restrict
access to your Companion PC in its firewall. The key is not a Habbo credential.

On the **Companion PC**, open Protocol Lab, enter the remote machine's numeric
IPv4 address, TCP port (`39099` here), and the same lab-only key. Click
**Run 20 remote lab fuzz cases**. boofuzz writes its test database under
`%APPDATA%\HabboViewChat\fuzz_lab`. Click **Analyse results with local
Ollama** for an optional explanation.

The remote helper uses a deliberately small synthetic packet grammar.
These tests cannot find vulnerabilities in the live Habbo service. Real
Habbo SSO tickets, browser cookies and encrypted Direct TCP connections
remain pinned to official endpoints and are **never forwarded to the
remote lab**. If the helper or key is unavailable, fuzzing refuses to start.


## v1.1.70 — Select the IP on your own PC for the local protocol test

Protocol Lab now has a **Your PC test IP** field. Use `127.0.0.1` or a
private IPv4 address actually assigned to your Windows computer (for example,
your machine's `192.168.x.x` LAN address). The mock server binds **to that
same IP on this computer**, on a random port, and boofuzz talks only to that
mock server. Public IPs, DNS names, wildcard binds, and other machines are
not accepted. There is **no remote target** setting.

**Official Habbo SSO is different.** The existing Direct TCP page can use a
ticket from your normal signed-in account and attempt the official encrypted
game handshake, but it stays pinned to Habbo's official endpoint.
The official SSO ticket is **not** sent to the test IP. A random IP cannot
authenticate your Habbo identity or produce a valid Habbo AIR encrypted
handshake without running a compatible authorised game server.

For a local-IP fuzz test, install `boofuzz==0.4.2` in Companion's Python,
open Protocol Lab, enter your PC's address, and run the mock-server cases.
Local results do not establish vulnerabilities in Habbo's real servers.


## Protocol Lab — passive G-Earth reader + local boofuzz (v1.1.69)

Open **Protocol Lab** in the Companion sidebar. Start the usual G-Earth engine and
Habbo AIR session through **Packet Viewer**, then click **Start / Stop passive
reader**. The new reader reuses Companion's existing G-Python extension: it
records only direction, numerical message ID, and in-memory byte count.
It never records raw payloads, usernames, messages, SSO tickets, or passwords.
Export the aggregated, redacted metadata as JSON when useful.

For automated tests, install the optional dependency into **the same Python
interpreter running Companion**:

```powershell
python -m pip install boofuzz==0.4.2
```

Click **Run 60 local boofuzz cases** to create a temporary synthetic TCP server
bound to `127.0.0.1` on a random port. boofuzz mutates a synthetic
4-byte frame length / 2-byte message ID / 2-byte text length format. The numeric
seed can come from passively observed outgoing packet IDs, but **no captured
payload is ever replayed or forwarded to the fuzzer**. The boofuzz database
is saved under `%APPDATA%\HabboViewChat\fuzz_lab`. Click **Analyse results
with local Ollama** to send only aggregate *mock-server* results to
`http://127.0.0.1:11434`, using `qwen2.5-coder:7b`.

**Safety boundary:** This mode has no setting for a remote test target. It does
not send malformed packets to G-Earth or Habbo and cannot establish a finding
about Habbo's production infrastructure. No separate extension port is required.
It does not alter the existing Packet Viewer, Manipulator or Coffee Pass Loop.


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
paste a ticket or provide authenticated `session.id` and `browser_token`
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


## v1.1.44 — Automatically connect saved Direct TCP accounts

Open the **Direct TCP** tab, save an authenticated Habbo.com session separately
for each account in the Windows Credential Manager vault, then check
**Automatically connect saved TCP accounts when Companion opens**. Next time
you open Companion, it attempts a separate TCP connection for all configured
accounts with saved sessions — no game executable or browser window.

You can also choose **Connect all saved** at any time. This is not a
password-based, everlasting login: when Habbo expires or revokes a stored
website session, the account must be signed into Habbo again through the
official authentication flow before direct TCP can connect. Verification
codes, MFA and server authentication checks are not bypassed. A positive
connection status requires the live server AuthenticationOK packet.


## v1.1.45 — More reliable direct TCP packet reads

Reviewed the architecture of [Bobba Launcher](https://github.com/Bobba-Packet/bobba-launcher)
and [Bobba Client](https://github.com/Bobba-Packet/bobba-client) as external
references. Both projects require an official Habbo SSO ticket for game login;
neither provides a password-only headless authentication method. Their GPL-3.0
code, AIR client assets, and Bobba-specific backend connection are **not** used.

For our independent Direct TCP adapter, fix a real transport problem:
an incomplete incoming TCP header or payload must survive a socket timeout
without losing bytes or moving the RC4 keystream ahead twice. Each account
now preserves the partial frame and completes it on a later read. Separate
accounts also keep a distinct stable non-secret client fingerprint rather
than generating a new one on every reconnect. The original per-account sessions
and official-only authentication boundaries remain unchanged. New offline tests cover fragmented plaintext and encrypted frames,
timeouts mid-packet, and malformed length rejection. Timeouts now indicate
which handshake/authentication phase failed.

**Still experimental:** CI cannot verify live Habbo server acceptance.
The website session must still be authenticated through Habbo's normal login
flow, then Companion can request SSO from its own HTTPS connection. No
third-party Bobba server, client or launcher is required.


## v1.1.46 — Direct TCP login troubleshooting

Fix an SSO formatting mismatch found after the first real Habbo.com test:
the user-facing `.username` part of an `hhus.<opaque>.V4.username`
launch ticket is display metadata. Companion now sends only
`<opaque>.V4` in the actual game-server SSO packet, matching the
normal AIR launcher invocation. No token values are logged.

Improve rejection diagnostics so the Direct TCP tab shows a **timestamped
connection-step log** and identifies whether a disconnect/denial arrived
during initial Diffie-Hellman, key confirmation, or SSO authentication.
A numeric disconnection reason may be shown when provided; server payload
bytes, website cookies, SSO tickets, and passwords are never logged.
Unknown incoming packet IDs may appear on handshake timeout to help identify
protocol drift. Existing saved website sessions stay in Windows Credential
Manager and can be reused.

This patch is tested offline with simulated network packets and does **not**
confirm that Habbo's current live game-server protocol accepts a login.
If your saved session is expired, sign in normally to renew it. Do not
publish session cookies or SSO tickets in issue reports.


## v1.1.47 — First-handshake compatibility fix

The first real test showed that Habbo accepted the TCP socket and Companion
fetched an SSO ticket, but then received **DisconnectReason (4000), code 122**
before the first Diffie-Hellman exchange. No evidence suggests that the game
server ever reached SSO authentication.

Root-cause investigation found that the initial `habbo_tcp.py` implementation
used packet identifiers from a standalone bot which *do not match* the AIR
client's checked-in `HabboMessages.as` registry. Notably the bot's outbound
`1445` corresponds to `Game2ExitGameMessageComposer` in that AIR registry,
while `3110` is `InitDiffieHandshakeMessageComposer`.

This release replaces the unverified handshake-related IDs with the
**documented AIR registry** IDs (source:
https://github.com/habbo-cc/Habbo-Sky/blob/feature-air/src/com/sulake/habbo/communication/HabboMessages.as),
and stops treating unverified `1510` as a "banned" response. The official
external-variables lookup uses the current supported
`https://www.habbo.com/gamedata/external_variables` URL. Because that data
does not provide a reliably parseable WIN63 release number, the compatibility
fallback is now the publicly documented **2026-11-04 AIR build**
`WIN63-202611041140-327405090` from
https://github.com/LilithRainbows/HabboAirPlus/blob/main/README.txt.
This fallback is not claimed to be the latest server-supported version.

**Still unverified on the live 2026 Habbo hotel:** The AIR registry used to
correct the identifiers is an earlier client snapshot, and the server may
have changed its protocol since. The app does not brute-force headers,
replay rejected tickets, bypass official login or use third-party servers.
If the connection still fails, report only the redacted Direct TCP status
and packet ID / handshake stage log, not any credentials.


## v1.1.48 — Public-config redirect and handshake byte diagnostics

Two live tests with the `2016 PRODUCTION`/Habbo-Sky message registry
timed out without a recognised first Diffie-Hellman response. The
Habbo-Sky registry comes from a **2016 retro emulator**, not a current
Habbo.com 2026 client. It must not be represented as authoritative for
the live hotel.

This release restores the newer **community AIR mapping** from
devlyresh/Habbo-Bot (which previously produced a server disconnect packet
instead of a silent timeout) while retaining the publicly reported
`WIN63-202611041140-327405090` compatibility build. This is a **single
hypothesis for live testing**, not verified current packet IDs. No automatic
cycling, repeat retries or protocol probing is implemented.

The public Habbo game-data endpoint
`https://www.habbo.com/gamedata/external_variables`
now follows only an official same-origin SHA-1-style content-hash redirect.
Previously it rejected all redirects. Its response can exceed 64KiB;
the new bounded 512KiB limit allows fetching the full document.
The SSO-ticket HTTP endpoint **continues to reject all redirects**.
The public variables may contain Flash asset versions but do not reliably
state the active AIR `WIN63` version, so a successful data fetch must not
be labelled a verified game version.

For a first-handshake timeout, the log now distinguishes
**zero socket bytes received**, **partial frame header/body**, and
**unexpected packet IDs** without logging payload bytes or credentials.
This helps distinguish a completely unresponsive game service from a
packet-format mismatch. Offline tests cover these cases.

**Still experimental:** TCP connection and a genuine SSO ticket do
not prove the game handshake, authentication or room interaction. A single
real test on a user's machine is required. If the server still rejects
the client, stop retrying and compare its protocol with an authorised
capture from the genuine current AIR client. No Brave/Habbo.exe/G-Earth
process is launched by Direct TCP.


## v1.1.49 — Habbo Classic WSS connectivity probe (no account required)

After v1.1.48 produced **zero game-server bytes** during the raw
`game-us.habbo.com:30000` AIR handshake, inspection of September 2026
Habbo Classic client source found a **different transport**:
`wss://game-us.habbo.com:30001/websocket`, with required
`Sec-WebSocket-Protocol: habbo-classic`. Its packaged release manifest
identifies `FLASH29`. Sources:
- [Habbo Classic Hotels.json](https://github.com/SimoLeoLife/habbo-decompiled/blob/main/habbo-classic-win/02_app_estratto/Hotels.json)
- [WebSocket transport implementation](https://github.com/SimoLeoLife/habbo-decompiled/blob/main/habbo-classic-win/05_sorgenti_per_classe/_unmatched/UnkEventDispatcherWrapperSubclass_28a7b5.js)
- [AIR versus Classic comparison](https://github.com/SimoLeoLife/habbo-decompiled/blob/main/habbo-classic-win/CHANGES_AIR15_CLASSIC.md)

The **Direct TCP** tab now includes **Test Classic WSS connection (no
login)**. The probe uses only the standard Python library, establishes
certificate-verified TLS, sends a single WebSocket HTTP Upgrade request
to that fixed Habbo.com hostname, validates the HTTP 101 response,
`Sec-WebSocket-Accept` and negotiated `habbo-classic` subprotocol,
then sends a correctly masked WebSocket close and disconnects.

**No cookies, SSO tickets, saved accounts, game packets or passwords are
read or transmitted by this test.** It doesn't launch any browser,
game executable, G-Earth, or Bobba service. The app uses distinct,
static error categories rather than exposing server response bodies.
The raw AIR TCP mode remains unchanged, and its authentication remains
unverified.

**A successful WSS upgrade proves endpoint and protocol reachability
only**. It does NOT prove game login, correct `FLASH29` packet IDs,
cryptographic negotiation, room state, or multi-account support. These
would require separately implementing and testing the modern Classic
binary protocol before offering a full headless login. No private
session is uploaded or kept by this probe.


## v1.1.50 — Handle live 2026 Habbo AIR keepalive and aligned packet headers

In a real November 17, 2026 test, Companion fetched a valid Habbo.com
SSO ticket, connected to the official AIR TCP endpoint and received a
**six-byte, zero-payload packet with header 2935**, then timed out while
waiting for the initial Diffie-Hellman reply.

A repository using the **same November 4, 2026 WIN63 build identifier**
labels incoming `2935` as **CLIENT_PING** and outgoing `923` as
**CLIENT_PONG**:
- [November 2026 incoming header registry](https://github.com/plus-emulator/Volt-Renderer/blob/main/packages/communication/src/messages/incoming/IncomingHeader.ts)
- [November 2026 outgoing header registry](https://github.com/plus-emulator/Volt-Renderer/blob/main/packages/communication/src/messages/outgoing/OutgoingHeader.ts)
- [Pong composer (empty payload)](https://github.com/plus-emulator/Volt-Renderer/blob/main/packages/communication/src/messages/outgoing/handshake/PongMessageComposer.ts)

Companion now responds to the empty keepalive with a single empty pong and
logs it without exposing packet payloads or cookies. The full set of initial
handshake, version, identity, SSO and authentication IDs is aligned with
this same November 2026 mapping rather than mixing older version mappings.
These numeric mappings were **independently implemented**, not copied
source code.

The previously hardcoded `FLASH25` platform label (observed in a 2025 AIR
client) has been replaced with `FLASH31`, the platform label seen in the
latest publicly inspected official AIR October 2026 client source:
[Oct 15 ClientHello](https://github.com/habbonoob/Client/blob/main/packages/client-WIN63-202610151745-318700621/src/com/sulake/habbo/communication/messages/outgoing/handshake/ClientHelloMessageComposer.ts).
The exact platform label for the November 4 official AIR build has **not**
been independently verified. The updated device identity now sends the
three string fields expected by October 2026 AIR instead of two.

**Critical limitation:** the November mapping comes from the independently
developed Volt renderer (which explicitly warns it does not imply native
AIR protocol compatibility). Automated tests simulate a valid initial
handshake and the early server keepalive. The change **does not confirm a
successful real login to the official Habbo.com server**. The code does not
cycle unknown headers, brute-force packets, repeatedly retry rejected
tickets, or bypass official login/MFA. Test with one account once; the
subsequent log will show whether the DH handshake progresses.


## v1.1.51 — Automatic session import for Direct TCP

Direct TCP can now collect the exact two Habbo.com website cookies
(`session.id` and `browser_token`) **without asking the user to find or
paste them in browser Developer Tools**.

With **Auto-import session and connect (selected account)** or
**Auto-import and connect all**, Companion:
1. Uses this account's own isolated Brave/Chrome/Edge browser profile.
   An already-running profile is reused. Otherwise it opens a temporary
   `--headless=new` browser from that account's private profile folder,
   with a loopback-only Chrome DevTools debugging port.
2. Reuses the logged-in website session or attempts a *single* ordinary
   official-site sign-in using credentials previously saved in the
   **Accounts → Save login securely** Windows vault feature.
3. Confirms the website shows authenticated controls, then calls
   Chrome DevTools `Network.getCookies` scoped **only** to
   `https://www.habbo.com/`. It extracts only the exact named,
   HTTPS-secure Habbo cookies, ignoring other sites' entries.
4. Validates both tokens through Habbo.com's official HTTPS SSO endpoint.
   Only a valid ticket causes them to be saved in the account-specific
   Windows Credential Manager session target, then starts the verified
   direct AIR TCP handshake. Cookies/passwords/tickets are never emitted
   in UI logs, settings.json, command-line args or GitHub.
5. Closes only the temporary headless browser it opened; an existing
   user-opened account browser is left alone. A stale saved cookie on a
   normal **Connect selected / Connect all saved** attempt gets one
   automatic refresh if Habbo explicitly returns 401/403.

The existing **Connect selected** also attempts automatic import when
no session has yet been saved. **Connect all saved** and opt-in startup
auto-connect remain limited to accounts with saved sessions, but
explicit 401/403 expiration can trigger the same one-time refresh.

**Initial setup:** in **Accounts**, save that profile's actual Habbo
login once. If Habbo requires 2FA, CAPTCHA, consent, or another
human verification, use **Accounts → Open account login** and complete
the official sign-in. Headless mode does **not** bypass those checks.
The feature only accesses Companion's separate per-account profiles,
**not** the user's normal unrestricted Brave/Chrome profiles.
Sessions can expire again. No login is guaranteed without valid
website authentication; successful TCP login is reported only after the
actual game-server AuthenticationOK packet.

The new session-import flow is validated with offline CDP, profile
isolation, headless-launch, and vault-write tests. Live new-login
capture still needs testing on Windows with Habbo.com.


## v1.1.52 — Fix automatic second-account session import

Live v1.1.51 logs confirmed one direct TCP account was authenticated and
receiving regular keepalive/game packets for minutes, while a second account
(`5991c2` prefix in the user's local log) created an isolated background
browser and **immediately** failed the website-sign-in check. It did
not reach direct TCP at all.

The old auto-import checked for a visible Habbo Play/avatar menu *before*
trying existing session cookies, so an unrecognised site layout could
incorrectly appear unsigned-in. The revised flow:

1. Start or reuse only this profile's isolated browser on its existing
   loopback-only DevTools port.
2. Read only `session.id` and `browser_token` from an HTTPS
   `www.habbo.com` page in that isolated profile via
   `Network.getCookies`. A matching website UI is no longer required
   **for this recovery step**.
3. Immediately verify the cookies with a fresh ticket from the official
   Habbo.com HTTPS SSO API. Only valid first-party cookies are written
   to the per-profile Windows Credential Manager vault; no unverified
   cookie is stored or passed to direct TCP.
4. If the cookies do not produce an official ticket, attempt a normal
   website sign-in using that account's previously saved credentials.
   If none are saved, report a clear message directing the user to
   **Accounts → Open account login** (one-time manual sign-in) or
   **Accounts → Save login securely**. If login controls are unrecognised,
   a CAPTCHA or MFA is required, or the isolated profile fails to open,
   show a distinct actionable error rather than one generic message.
5. Only after successful SSO issuance does Companion start that account's
   normal direct AIR TCP connection. Existing authenticated sockets are
   not modified.

The feature does **not** read the main unrestricted Brave/Chrome profile,
extract cookies from unrelated websites, bypass website CAPTCHA/MFA,
automatically retry failed sign-ins indefinitely, or log session
cookies/passwords/tickets. Automated tests cover cookie-first recovery
from an unrecognised signed-in page, saved-login fallback, vault-write
ordering, missing saved credentials, and cross-profile isolation.

**Live Windows validation of the new account recovery branch is pending.**
