HABBO COMPANION v1.1.79 — LIVE ROOM SEARCH & COLLAPSING LAYOUT
=================================================================

AI RESPONDER: REPLY TO > SELECTED USERS
- Search people in this room: partial, case-insensitive username matching.
- Dropdown suggestions combine the current G-Earth room Users snapshot and
  actual speakers in your Habbo AIR room, including offscreen public chat.
- Click a suggested username to add it to the reply-only list and apply it.
- Select multiple names without duplicate entries, or click Clear.
- Refresh room reloads names, as does focusing/typing into the search field.
- Names from historical chat log files are NOT offered as current room users.
- Room changes, disconnections and departures clear stale detected players.
- Current reply targeting remains separate from writing-style imitation.

LAYOUT FIX
- AI Responder panel and Recent Activity log no longer expand vertically to
  fill empty canvas space. Collapsing Advanced options or search results
  restores a compact layout without the giant empty gap.
- Other app functions and the established G-Earth packet send are unchanged.


HABBO COMPANION v1.1.78 — CONTINUOUS PUBLIC CHAT LOGGING
==========================================================

NEW: Automatic background recording of every NEW public Habbo AIR room chat
message into a separate .txt file for each username, e.g. Cheesecake.txt.
Existing files are appended (not overwritten). The format remains:
[2026-11-23 13:26:00] Cheesecake: original public chat message

Archive path: %APPDATA%\HabboViewChat\persona_logs\users
The per-user archive stays at that path regardless of where historical
writing-style samples are loaded from.

- Enabled by default, independently of the AI responder and auto-send.
- Continues while Companion is on another page or minimized.
- Captures off-screen public chat and your own public chat.
- Excludes whispers/private messages.
- See a "Public chat auto-save: ON" status on the AI Responder page.
- Disable from Advanced options if needed.
- Press Refresh beside the style-search box to see newly logged usernames.
- No browser automation, keyboard coordinates, or change to G-Earth send.

CONDITIONS: The Companion process AND a live Habbo AIR chat feed must
continue running. Closing Companion, Habbo disconnecting, or Windows
sleep/PC shutdown will stop recording. No hidden Windows service or
login autostart is installed. Open Companion to resume recording.


HABBO COMPANION v1.1.77 — SEARCH USER CHAT LOGS FOR WRITING STYLE
===================================================================

AI RESPONDER CHANGES
- Removed the old TRY A REPLY / preview input and button from the screen.
- Added COPY WRITING STYLE FROM SAVED CHAT LOGS on the main screen.
- Search any part of a username; case-insensitive matching names appear
  immediately in a clickable dropdown sourced from username.txt files.
- Choose a username to apply that user's recorded way of speaking, including
  style, slang, spelling, typical length, and punctuation. Copies style only:
  does not claim to actually be that person and does not paste their logs.
- Selecting a user automatically switches to chat-log style, turns OFF
  automatic style rotation, and saves the new writing style.
- Use my own style returns to the custom personality text box.
- Choose log folder opens a saved username.txt folder, usually chat_logs/users;
  Refresh scans the folder again for newly saved names.
- Reply to (Everyone / Selected users / First active speaker) remains separate.
- Custom personality settings, G-Earth packet capture, and sending are not
  changed. Live AI and Auto-send remain OFF on startup.


HABBO COMPANION v1.1.76 — SIMPLIFIED AI RESPONDER
==================================================

The AI Responder now uses ONE page (no multiple configuration tabs):
- Enable AI responder.
- Send replies in Habbo (G-Earth): remains OFF on launch.
- Edit its personality in a single text box.
- Reply to Everyone, Selected users, or First active speaker.
  The username input appears only when Selected users is chosen.
- Save changes or Stop.
- Test reply (preview only): enter a pretend message; NEVER sends into Habbo.
- Recent activity: live drafts, send results and errors.

Click ADVANCED OPTIONS to reveal the less-used settings: reply frequency,
tone, humour, model, old chat-log style and local capture, test speaker,
manual sending, and G-Earth diagnostics.

Existing saved preferences remain compatible. The working G-Earth packet
capture and AI sending logic are unchanged from v1.1.75.


HABBO COMPANION v1.1.75 — OUTGOING AI CHAT CAPTURE FIX
=======================================================

FIXED: AI Responder could read live Habbo AIR chat and generate responses
but failed to learn outgoing Chat packets because it checked the legacy
G-Earth g_string output for a named {out:Chat} expression. The app now
checks the parsed g_expression output and validates the named Chat field.
It does not guess packet header IDs or use screen coordinates.

HOW TO TEST
1. Open Habbo AIR with G-Earth attached in Packet Viewer.
2. Enable AI Responder, leaving Auto-send OFF during initial testing.
3. Send one normal public message yourself through the Habbo game client.
4. Check Recent Decisions: "Outgoing Chat format learned from Habbo."
5. Click "Check G-Earth chat capture" if the message is not shown.
6. After it is learned, optionally enable Auto-send through G-Earth.

If G-Earth observes outgoing traffic but cannot name Chat, the app reports
that separately rather than pretending an outgoing format was learned.
No API/model or personality changes should be needed for this symptom.
AI and auto-send remain opt-in, and no browser is needed.


HABBO COMPANION v1.1.74 — CUSTOM AI PERSONALITY AND TARGETING
==============================================================

AI RESPONDER (NEW)
- Personality tab: default Custom personality. Write your own personality
  description, choose tone and humour 0–5. No copied person's chat logs needed.
- Optional Chat-log style remains available, but is no longer the default.
- Who to reply to tab: Everyone, Selected users (comma-separated exact usernames),
  or First active speaker (60-second quiet lock). Natural/Chatty reply behaviour.
- Test without sending tab: enter a sample speaker + message, then press
  Test AI reply (preview only). Preview works even when the live bot is OFF;
  it never sends an in-game packet, even if Auto-send is checked.
- AI still requires Python package "openai" and environment variable
  OPENAI_API_KEY; network API usage applies to the test preview.
- For live messages, use the existing AIR chat feed and optional G-Earth send
  from an observed outgoing Chat packet. No browser automation involved.
- Both live responding and auto-send start OFF by default.


NEW IN v1.1.73: AI Responder is a separate, optional sidebar page. It reads the
existing Habbo AIR public chat feed and can reuse legacy chat_logs/users style
logs. Configure a style source and target (or automatic first-speaker lock),
enable the responder, then inspect SKIP/draft decisions. Style rotation, question
memory, cooldowns and blocked "dan" names are retained.

The OpenAI Python package is optional: py -m pip install openai. Set the
OPENAI_API_KEY environment variable before starting Companion. Enabling AI
sends selected historical style samples and recent public room chat to OpenAI.
AI starts OFF. Automatic sending starts OFF as a separate checkbox.

For automatic sending, connect the G-Earth Packet Viewer and type one ordinary
public chat message in the room first. The responder learns the actual outgoing
Chat packet shape for that session; it never guesses packet IDs, drives the
mouse, or uses Direct TCP sessions to send chat. Sending needs Windows/G-Earth
verification. Whispers never trigger public replies.

The Companion control window has been reorganised as a modern dark desktop
workspace. The original Habbo client overlays and bubble artwork are unchanged.

- Persistent left navigation for Overview, Accounts, Direct TCP, View Chat,
  Packet Viewer, Packet Manipulator, Direct Classic, Headless Test, Updates.
- Overview dashboard with real account counts, server-authenticated Direct
  TCP counts and current pending connection counts; no unverified login is
  labelled authenticated.
- Accounts uses a profile list on the left and grouped account details,
  login/security, G-Earth settings and launcher actions on the right.
- Shared dark surfaces, headings, fields, table rows, status text, tool buttons
  and clearly differentiated primary actions across every workspace.
- Page-specific vertical scrolling keeps long tool panels accessible; mouse
  wheel events inside packet tables and logs are left to their own controls.
- Larger default window (1120 x 820) and minimum (940 x 620) accommodate
  the sidebar and two-column Accounts editor.
- Existing settings keys, accounts, vault credentials, browser profiles,
  updater flow, Direct TCP, G-Earth, chat and packet tool callbacks remain
  unchanged. No migration or external UI dependencies are required.

Verification includes Python source/unit tests, a Windows Chromium Playwright
smoke test, and a separate Windows Tkinter UI construction/navigation smoke
test. Actual appearance on a user's monitor may vary with scaling, themes
and Windows display settings.

HABBO COMPANION v1.1.67 — COLD START BACKGROUND SESSION READINESS
=================================================================

The Direct TCP auto importer previously launched the private Brave/Chromium
profile in headless mode, then immediately inspected it after the local
debugging port opened. Browser startup is faster than Habbo's page load and
trusted-session restoration; a not-yet-ready page was mistaken for a failed
login, even though a later retry with an already-open browser succeeded.

When Auto-import session and connect starts a fresh browser process:
- Continue using the same isolated, persistent per-account browser profile.
- Allow Habbo to finish loading/restoring its signed-in session, checking
  all official Habbo tabs for PLAY/account UI during bounded readiness polling.
- Do not submit saved credentials or request repeated SSO tickets during
  this readiness phase; only observe the page.
- Once ready, request a new official ticket through the existing verified
  cookie-pair or authenticated-browser route; the game server must still
  confirm authentication.
- If readiness never completes, report whether a login form was seen and
  continue to the existing one-shot login/manual verification fallback.
- Close only an ephemeral headless browser spawned by this import, without
  deleting its profile or clearing cookies.

This improves cold-start timing, but cannot force Habbo to preserve an expired
session or suppress legitimate email/CAPTCHA verification. Live reliability
on a fresh restart has not yet been confirmed; automated tests are offline
and synthetic Windows-browser checks.

HABBO COMPANION v1.1.66 — BROWSER SESSION TO DIRECT TCP TICKET
================================================================

The official Habbo website can show a signed-in PLAY page without providing
the old session.id + browser_token cookie names required by Companion's
legacy Direct TCP importer. A valid signed-in browser session is not the same
as a completed game-server login.

Auto-import session and connect now:
- Tries the previous, strictly validated legacy cookie-pair route first.
- If that route is unavailable/rejected, asks the signed-in account browser
  directly for a ticket using the existing "Fetch from signed-in local session"
  first-party HTTPS method, scoped to that isolated account profile.
- Does NOT require legacy cookies when the official browser endpoint returns
  a correctly parsed game ticket. The browser profile stays persistent for
  subsequent attempts; the app does not save non-existent cookie values.
- Logs which ticket route was attempted and safe HTTP 401/403/429 or
  unsupported-response categories, never SSO tickets or browser secrets.
- Still waits for actual game-server authentication to confirm the connection.
  It never bypasses CAPTCHA, email verification, or a site's session expiry.

This route is verified with synthetic/offline unit tests. Its success against
the current live Habbo.com session and game server must be verified separately.

HABBO COMPANION v1.1.65 — DETAILED LOGIN SERVER DIAGNOSTICS
===========================================================

The Playwright browser controller is unchanged. The login communication
monitor now distinguishes requests, HTTP responses, completed transfers and
real network failures. An aborted transfer after HTTP 200 is no longer reported
as though the server had never responded.

On each account's login attempt, the monitor now reports:
- Numbered HTTPS requests with safe, redacted endpoint paths and request types.
- HTTP statuses, redirects, rate-limit Retry-After seconds (when numeric),
  completed transfers, and safe Chromium transport failure categories.
- Application-level success=false, authenticated=false, or allowlisted
  failure/status results in official Habbo JSON, including HTTP 200 responses.
- Recognised generic server errors, including symbolic error codes.
- Classified browser JavaScript errors and visible login-page warnings,
  including incorrect credentials, verification and rate limits.
- Presence (not contents) of Habbo's two secure session cookies.
- Aggregate totals and explicit notices when diagnostic events were omitted.

External identity services are reported with an approved service label or
"external HTTPS", but their response bodies are never read. No raw URLs,
query strings, credentials, tokens, cookie values, SSO tickets, HTTP headers
or arbitrary server messages are printed. Some server responses may not
contain a meaningful reason; in those cases Companion reports the evidence
available without inventing a cause.

HABBO COMPANION v1.1.64 — PLAYWRIGHT BROWSER CONTROLLER
=====================================================

Habbo's login and Play/Launch website controls are now operated through
Playwright, not the previous hand-built CDP DOM/coordinate click system.
Playwright attaches to the account's existing private Brave/Chrome/Edge
browser profile through its LOCAL 127.0.0.1 debugging port. Separate accounts
still have separate profiles. Login credentials remain in the Windows
Credential Manager vault, not in the browser arguments or logs.

AUTOMATIC FIRST-RUN SETUP
=========================
The app automatically installs the pinned Python Playwright package into
this Windows user's LOCALAPPDATA/HabboCompanion/managed-playwright folder
when browser automation first needs it. The official PyPI package is a
substantial download (~43 MB for 64-bit Windows), so internet access and a
working pip module for the Python launching Companion are required on
first use. Companion does not separately download Playwright's browser
binaries: it attaches to the already installed Brave, Chrome or Edge.
The updater ZIP stays compatible with existing Companion installations.
If automatic setup fails, the app reports it and does not silently return
to coordinate automation or submit saved credentials.

LOGIN BEHAVIOUR
===============
- Playwright locators find the visible login form, fill the email/password
  fields, and auto-wait for a stable, enabled, unobstructed LET'S GO! button.
- Playwright clicks the real page control; it never uses force=True or
  bypasses website challenges, CAPTCHA or multi-factor verification.
- Website Play/Launch navigation also uses Playwright locators.
- Browser requests and server responses are logged with redacted paths and
  HTTP statuses; errors are classified without exposing credentials, raw
  page errors, cookies or SSO tickets.
- Successful sign-in is still VERIFIED using the existing official Habbo
  website cookies and HTTPS SSO ticket before Direct TCP authentication.
- A site verification prompt or unsupported login provider may still need
  manual completion in Accounts > Open account login.
- Playwright's CDP attachment has compatibility limits with some Chromium
  builds. If a connected browser refuses the session, the app reports the
  error rather than silently guessing or replaying game packets.
- Installed Playwright and its dependencies are third-party code maintained
  by Microsoft; the rest of Companion remains local.

This release has offline unit tests. Live Windows Habbo sign-in and
multi-account launch must still be verified on your own system.

HABBO COMPANION v1.1.42 — LOCAL SESSION TICKET FETCH
===================================================

Accounts > Open account login now opens that account's isolated browser
profile and signs in automatically when you have saved its login.
The existing Auto Play buttons can sign in, click Play / Launch and
log in, and attempt to select Classic from the Habbo Launcher.

SET UP ONCE FOR EACH ACCOUNT
============================
1. Open Accounts and select Account 1 (or create and select an account).
2. Enter its Habbo sign-in EMAIL and PASSWORD.
3. Click Save login securely.
4. Repeat for Account 2, Account 3, etc.
5. Click Open account login to open the profile and submit the login.
   This button does not launch Classic.
6. Click Auto Play selected or Auto Play all saved accounts to attempt
   the full website → launcher flow.

Saving a login stores the email/password as a Generic Credential in
Windows Credential Manager for your Windows user account. It DOES NOT
write it to Companion settings.json, a JSON file, browser command-line
arguments, GitHub or update packages. The password field is masked and
cleared immediately after saving. Forget saved login deletes the vault
entry; existing browser cookies remain until you clear that browser
profile separately. Removing an account also deletes its vault entry.

If you don't save a login, you can still sign in manually once in that
account's own browser profile. Browser cookies normally preserve the
session for subsequent launches. The app supports direct email/password
login; Google, Apple and Facebook sign-ins may need manual completion.
CAPTCHA, two-factor checks, sign-in errors and OS permission prompts
can still require you. Sign-in only targets the official habbo.com
domain over HTTPS. The app does not bypass verification or promise the
website will accept automated typing if its layout has changed.

AUTO PLAY
=========
1. Opens the selected isolated Brave/Chrome/Edge profile.
2. If the Habbo email/password form is shown and login is saved,
   types it through local browser input events and submits once.
3. After authentication, follows visible Play / Launch and log in
   buttons using trusted browser click events.
4. Attempts Classic in a named Habbo Launcher window. Manual selection
   may be needed if its accessibility interface is unavailable.
5. "Auto Play all" processes profiles sequentially. If a launch
   cannot be confirmed, the chain stops instead of guessing which
   account is active.

SECURITY
========
Automatic browser control requires a local Chrome DevTools endpoint
on 127.0.0.1 for each dedicated Chromium profile. Other programs on
your PC could reach that endpoint; keep your Windows session secure,
do not use these isolated browser profiles for unrelated sensitive
browsing, and close them when finished. Some Brave/Chrome versions
may disable remote debugging on special/default profiles; Companion
uses non-default per-account profile directories to avoid that.
No credentials are sent to ChatGPT or into the repository.

G-EARTH LIMITATION
==================
Automating two browser sign-ins does not automatically create two
independent G-Earth proxies. Companion can control one attached G-Earth
extension port at a time, and additional clients still require
correctly separated proxies. The browser profile labels are not proof
that a given packet connection belongs to that account.

Other features retained: coffee controls, chat bubble rendering,
right-side whispers, packet tools and online updates.

This version has offline automated tests, but successful sign-in and
Classic launching need validation on a live Windows/Habbo install.


v1.1.32 — LAUNCH ACCOUNTS WHILE G-EARTH IS CONNECTED
====================================================
Fixed: Auto Play selected previously refused to launch Account 2 (extension
port 9093) whenever Account 1 was attached to G-Earth port 9092, even though
website sign-in/Classic launching does not use that G-Earth endpoint.

Open account login and Auto Play selected/all now operate independently of
the active packet endpoint. The G-Earth connection stays on its existing
port and packets are NOT reassigned to a second account. This is a browser/
launcher fix, NOT simultaneous packet interception for multiple accounts.

If Companion opens a blank login page rather than typing the saved email and
password, read the green status message. Older dedicated Brave windows for
that account may have started before browser automation was enabled. Close
THOSE separate account browser windows and click Open account login again.
Do not close or sign out of unrelated browser profiles.

Passwords saved in the Windows vault remain saved after restarting
Companion. A blank login-password input in the Accounts panel is intentional.
If the green status reports missing saved credentials, save them once with
Save login securely. A Habbo security challenge may still require you.


v1.1.33 — AUTO PLAY ALL: EVERY BROWSER FIRST
===========================================
Auto Play all saved accounts now executes two separate phases:
  PHASE 1: Open/check sign-in for every saved dedicated browser profile.
           One account with failed login or blocked browser automation will
           NOT prevent checking the remaining accounts.
  PHASE 2: Attempt Classic launch for each confirmed signed-in profile,
           sequentially. If the Habbo Launcher Classic button cannot be
           automatically selected, further native launches PAUSE so the
           launcher cannot consume the wrong account's login ticket.

The website Play button matching also handles a visible "PLAY H" badge
that may accompany PLAY in some Habbo layouts.

The bottom status now reports how many browser logins were confirmed,
how many Classic button selections occurred, and whether a manual native
launcher action is required. A browser login does NOT imply a client
started or packets were captured by G-Earth.

IMPORTANT: G-EARTH MULTI-CLIENT LIMITATION
==========================================
G-Earth's Flash proxy is a single-client interception path, with a
single connected HConnection proxy and extension connection. Port 9092
or 9093 in Companion denotes the extension socket, NOT per-account
proxy routing. G-Earth does not automatically assign a second Habbo AIR
client to an extension socket because its browser used a different profile.

Launching every Classic client THROUGH separate G-Earth connections needs
a proper per-client local network routing and proxy architecture change.
Simply starting two G-Earth executables against the same local game
server host/port risks both clients reaching the same proxy, or address/
port conflicts. This version deliberately does NOT claim to provide
independent G-Earth interception for multiple accounts.

Manual verification on a live Windows Habbo install is still necessary.


v1.1.34 — ALL BROWSER WINDOWS START BEFORE LOGIN
===============================================
Fixes a key delay in the prior Auto Play all order. v1.1.33 started
Account 1's browser and then checked its sign-in (potentially waiting
through many authentication polls) BEFORE it opened Account 2.

Auto Play all now attempts to start the isolated browser for EVERY
saved account BEFORE entering the per-account sign-in and Classic flow.
Existing profile windows are reused rather than launching duplicates.
This is not a guarantee that two windows will be visible side-by-side:
existing windows may overlap or be minimized.

The Accounts table includes a Browser / Classic status column. You can
see independently whether an account is:
- Opening browser / Browser already open
- Checking website login / Website signed in
- Sign-in needs attention / Browser control unavailable
- Requesting Classic launch / Classic selected; client unverified
- Needs manual Classic / permission; a later launch is paused

Where the native launcher requires manual permission or Classic selection,
the batch still pauses subsequent *native* client launches to avoid
accidentally consuming a different account's login ticket. Every browser
will already have been opened before that point. The status column shows
which account is waiting. Neither a website login nor a clicked Classic
button establishes a verified independent G-Earth packet interception.

The G-Earth per-game-client proxy routing described in issue #24 is
still outstanding. Different extension ports (9092/9093) are not a
solution by themselves.


v1.1.35 — WEBSITE SIGN-IN DETECTION FIX AND DIAGNOSTICS
=====================================================
Previously an authenticated Habbo homepage could be rejected because
Companion only accepted a text-labelled Play/Launch/Download button.
The official website may render PLAY with a decorative H image or
custom-styled clickable wrapper, and on some layouts the control
isn't exposed as a semantic button at all.

The detector now:
1. Recognises visible PLAY / PLAY H and "Launch and log in" controls
   without relying on their exact HTML structure.
2. Uses the visible avatar-name dropdown at the top-right as an
   additional indication that the website session is signed in.
   A name on the page does not independently prove ownership of an
   intercepted game connection.
3. Never makes up a PLAY click if the control is not identifiable.
4. Reports a separate reason if browser DOM inspection fails or an
   HTTPS Habbo tab cannot be found.
5. Replaces the generic "No account logins confirmed" message with
   instructions to inspect each account's Browser / Classic status.

The login button and profile checks inspect only visible elements
on HTTPS *.habbo.com. No website cookies or authentication tickets
are read. Existing Windows Credential Manager storage is unchanged.

Note: if both profiles continue to report Browser control unavailable,
the issue is browser remote debugging rather than the visual page
recognition; close old Companion-created dedicated Brave windows and
retry. A CAPTCHA or two-factor check requires manual completion.
Native Classic launching remains sequential and multi-client G-Earth
routing is NOT yet implemented. Real Windows + Habbo verification is
still necessary.


v1.1.36 — CONTINUE UNFINISHED ACCOUNTS
=====================================
Added an "Continue unfinished accounts" button in the Accounts tab.

If the batch shows "1/2 website logins ready, 1 launch request, 0
Classic selections", it now preserves the other account in a small
in-memory queue of account profile IDs. It does NOT repeat the first
account's native launcher request or reuse a previously sent ticket.

If the first Habbo Launcher is waiting for a Classic choice or Brave
prompts "Open Habbo Launcher?", complete that manual step FIRST.
Then click Continue unfinished accounts. Companion asks you to confirm
you've handled the earlier prompt, then retries only the accounts that
never reached the native launch request step. The remaining profiles
are rechecked for valid sign-ins using their own stored browser
profiles and their saved login in Windows Credential Manager.

The resume queue is only in Companion's current process memory, not
in settings.json; it stores profile IDs, NEVER account passwords,
browser cookies or Habbo launch tickets. Closing Companion loses this
short queue; a fresh Auto Play all batch is still available.

If Classic was selected but the Windows program did not launch, the
account is NOT considered proof of a connected avatar or intercepted
packet feed. You may manually select that account to investigate, but
the Continue button deliberately avoids replaying the same request.

This is a recovery and diagnostics improvement, not a way to bypass
browser permission prompts, CAPTCHA, OS security controls, nor
Habbo's launcher itself. Multiple separately controlled G-Earth
proxy game connections are still not implemented.


v1.1.37 — SIGNED-IN HABBO TABS CAN NOW BE FOUND RELIABLY
======================================================
Fixes one reason for the false "No website logins confirmed" status:
the previous account_habbo_page() always chose the FIRST Habbo tab in
a dedicated browser profile. If an older tab was stale, login-only or
not responding to Chrome DevTools, Companion could overlook a visibly
signed-in tab showing an avatar and green PLAY button.

Now the per-account browser inspector:
- Scans up to 12 HTTPS Habbo tabs in that account's isolated profile.
- Prefers the valid Launch/PLAY/signed-in profile controls over stale
  login/loading tabs, without mixing browser profiles.
- Falls back to the next Habbo tab if one refuses a DevTools inspection.
- Reports an exact browser-control error category instead of treating
  a DevTools failure as an incorrect password or logged-out avatar.
- Shows the latest safe browser-control diagnostic in that account's
  Browser / Classic status column.

If status reports "Browser DevTools socket rejected handshake",
"Browser control endpoint failed" or "Browser inspection failed",
this is local browser automation (not your Habbo sign-in). It must be
resolved separately. Don't repeatedly re-enter credentials merely
because Companion can't read the tab. Close the old *dedicated*
Companion browser profile windows only, then retry; normal Brave
windows and other profiles can remain open.

A website sign-in is still not a Classic game client connection.
G-Earth's extension socket port does NOT redirect a second game client.
Per-client G-Earth proxy routing is still outstanding.


v1.1.38 — AUTO PLAY ALL CONTINUES WHEN THE GAME OPENS DIRECTLY
=============================================================
A real Windows report showed 2/2 website logins, one native game
(HabboAirPlus [OOM] | dan.alt100) visibly running, but "0 Classic
selections" and a halted Account 2. The Classic button is not visible
or exposed to Windows UI Automation on some launcher versions, because
"Launch and log in" can create the HabboAirPlus client directly.

Auto Play all now records visible native HabboAir/HabboAirPlus game
windows (window handle + process ID) BEFORE each individual profile's
Launch and log in request. If a NEW game window appears after that
request, Companion reports "New HabboAir window (account unverified)"
and proceeds to the next signed-in account without insisting on a
separate Classic button that no longer exists.

If no new game window appears, Companion still searches for the
accessible Classic button. If the button is unavailable but a new
game window appears during that search, the batch can still continue.
If neither is verified, it keeps the previous safe pause/recovery
behaviour and "Continue unfinished accounts" remains available.

Important limitations:
- An existing game client/window never counts as a newly launched
  client for another account, preventing false successes.
- A native window alone does NOT prove the particular avatar identity
  or G-Earth interception. Only the timing of the launch request is
  correlated with the new window.
- Window checks are Windows-only, read title/process/window handle
  metadata, never passwords, session cookies or launcher tickets.
- Multiple independent G-Earth packet proxies are still NOT provided
  by this patch; separate browser accounts do not automatically route
  through separate G-Earth connections.
- Windows/Habbo integration still requires verification on the user's
  actual machine.


v1.1.39 — HEADLESS LOCAL CONNECTION ENGINE (TEST SERVER ONLY)
============================================================
The new "Headless Test" tab demonstrates multiple independent network
sessions with zero Brave/Classic windows. It does not connect to Habbo.com.

TEST IT
-------
1. Go to Accounts and create or retain 2–3 saved account profiles.
2. Switch to "Headless Test".
3. Click "Start/reset local test server". It binds ONLY to 127.0.0.1
   on an available port selected by Windows.
4. Click "Connect all (local test)". Every account gets its own TCP
   socket, random single-use local TEST ticket and independent reply
   validation. No website password or cookie is used.
5. Click "Ping all test sessions" to verify each account's local
   socket is still alive; click Disconnect all to close them.
6. Refresh profiles if you change accounts.

This is a controlled test server and test protocol, NOT the production
Habbo protocol. A "Local test authenticated" status does NOT imply that
the avatar is online in Habbo. This is independent of G-Earth, G-Python
and the existing official browser/Classic launch workflow.

NEXT TECHNICAL REQUIREMENT FOR A REAL HEADLESS HABBO CLIENT
-----------------------------------------------------------
A supported or authorised way to obtain official session credentials
without website UI automation; the exact live handshake, encryption,
packet versions and account identity validation. None of those have
been established as supported. Companion therefore REFUSES to direct
this prototype at any external server or replay an official login
ticket. It never submits actual Habbo passwords or session cookies.

Habbo's current rules restrict unauthorised bots and automation. Do
not interpret this local test as permission to run custom clients
against Habbo.com. The existing Accounts/Auto Play functionality
remains available as before and is NOT replaced by an unverified
live authentication implementation.

SOURCE AND UPDATE SAFETY
------------------------
headless_transport.py ships with the release ZIP and is SHA-256 checked
by the normal updater; the Windows installer payload also includes it.
No user settings are reset or migrated. Per-account test secrets exist
only in memory. All local test sessions are closed on Companion exit.
No separate client download, Chromium startup or Java install is
needed for this local test feature.


v1.1.40 — LOCAL DIRECT CLASSIC, NO BOBBA SERVICES
=================================================
New "Direct Classic" tab in the SAME Habbo Companion application. This
feature implements the executable-launch method independently in
Python. We did not copy Bobba-Packet GPL code, install its launcher,
connect to its API/backend, or introduce any Bobba network endpoints.

WHAT IT DOES
------------
- Uses a Habbo.exe file that YOU choose from your existing local PC.
- Accepts user-supplied official Habbo.com (hhus) SSO launch tickets in
  hhus.<opaque>.V4[.username] or
  habbo://hab?server=hhus&token=<opaque>.V4[.username] form.
- Holds distinct tickets for distinct saved Companion account profiles
  IN MEMORY ONLY. Paste into the masked ticket field, then click
  "Queue ticket locally". No credential/ticket content is written
  to settings.json, a log, or GitHub.
- Launches the selected account or every queued account as separate
  native Habbo.exe processes using the normal Classic -server/-ticket
  arguments. There are no website button clicks, Brave windows, or
  Bobba services involved in this feature.
- Includes no downloader and makes no outbound network connections
  itself. The actual launched official Habbo.exe still contacts the
  official Habbo.com servers to authenticate and play.
- Keeps the old Accounts Auto Play and Headless Test workflows intact.

HOW TO USE
----------
1. Get a valid login ticket from Habbo's normal login process. The
   ticket must still be valid. THIS UPDATE DOES NOT GENERATE TICKETS.
2. In Companion's new "Direct Classic" tab, click Browse and select
   your ALREADY INSTALLED local Habbo.exe.
3. Select a saved account row.
4. Paste the account's own official Habbo.com launch ticket into the
   masked field; click "Queue ticket locally".
5. Repeat for other account rows with their OWN tickets.
6. Click "Launch selected" or "Launch all queued". Tickets are
   discarded from Companion memory before process launch and will not
   be silently replayed; reacquire expired/used tickets as necessary.
7. The status reports only whether the local Habbo.exe process was
   STARTED. Authentication, avatar identity and G-Earth interception
   are not inferred from a PID.

IMPORTANT LIMITS
----------------
- Getting tickets still requires a valid official authentication
  flow; this is not a headless Habbo.com login implementation.
- Per-account AIR application identity / independent machine IDs are
  NOT modified. Starting multiple executables may or may not allow
  simultaneous AIR sessions depending on the client's installed build.
- This does not create per-account G-Earth proxies. 9092/9093 remain
  extension ports, not isolated game proxies.
- A valid-looking ticket could be invalid or expired on Habbo.com.
- The official Classic runtime's -ticket argument is visible in
  Windows process arguments to sufficiently privileged local software.
  Do not share tickets, screenshots of ticket-bearing commands or
  process information. This is a limitation of the launch convention.
- Habbo's terms may restrict unauthorised automation and modified
  clients. Do not assume a ticket or local process grants permission.
- Windows live integration is not verified by offline GitHub tests.

FILES / UPDATES
---------------
local_classic_launch.py is included in the verified update ZIP and
the local Windows installer. It uses Python's standard library only.
No additional applications, developer tools, GitHub repositories or
Bobba services are needed by this feature. Your existing saved
accounts, credential vault and G-Earth configuration are preserved.


v1.1.41 — FIX "UNEXPECTED FILES IN UPDATE PACKAGE"
==================================================
Older Companion update helpers only allowed the original three files:
Habbo_Companion.pyw, Habbo_Update_Helper.py and README.txt (plus the
habbo-update.json package manifest). Adding headless_transport.py in
v1.1.39 and local_classic_launch.py in v1.1.40 caused the installed OLD
updater to reject the ZIP before it could install the NEW helper.

THIS RELEASE FIXES THE UPGRADE PATH:
The ZIP contains only the three original application files and the
manifest, so an old updater can verify and install it. Code for both
Headless Test and Direct Classic is embedded into the shipped
Habbo_Companion.pyw itself during release packaging. Both features are
included and run without needing separate companion Python modules.
The archive is still SHA-256 checked against the release manifest, and
its file-level hashes are verified by the installed updater.

This update preserves Windows Credential Manager logins, browser
profiles, settings.json, G-Earth configuration and user files. No
manual ZIP downloads, file replacement or reinstall is needed.
Use Updates > Check online on any supported older installation.

Fresh source installs may still ship the separate Python source
modules. The verified ZIP update is self-contained by design, so
future new Python modules must not add files to that legacy update
archive without an explicit migration mechanism.

There are still no Bobba third-party network services, tools, cloned
clients or endpoints in the Direct Classic feature. The official
Habbo.exe itself must connect to official Habbo game servers to play.
This update does not implement credentialless headless live gameplay,
per-client G-Earth proxy routing or avatar verification.


v1.1.42 — REQUEST SSO WITHOUT COPYING A BROWSER LOGIN CODE
==========================================================
New optional button in the existing "Direct Classic" tab:
    Fetch from signed-in local session

Select the appropriate saved account profile and click the button.
Companion uses that account's already-running, previously signed-in
isolated Chromium profile (127.0.0.1 debugging socket) to issue an
authenticated HTTPS request to HABBO.COM ONLY:
    POST https://www.habbo.com/api/client/clientnative/url

This is an *undocumented* website endpoint; it may stop working, deny
the request, or return an incompatible ticket format. Successful
login or server acceptance has NOT been verified on a live account.

SECURITY AND LIMITS
-------------------
- No manual SSO code copy is required if the account's Habbo website
  session is already signed in and the browser control port works.
- No new browser window is opened by this operation, and no account
  password is sent by Companion. The browser itself supplies its
  existing session credentials to Habbo.com over HTTPS.
- Browser cookies, tokens, saved passwords and response bodies are
  not logged or stored in settings.json. Only a format-validated
  launch ticket is returned to Companion memory temporarily.
- Companion does not send account credentials to Bobba-Packet or any
  third party. The browser request goes only to official Habbo.com.
- This is NOT a fully browserless email/password login. A previously
  authenticated site session is still required, and if it expires
  you must re-authenticate through the official login method.
- If no account browser is running with a working 127.0.0.1 DevTools
  endpoint, the button reports that the local session is unavailable
  instead of launching a browser or silently guessing account identity.
- A ticket is associated with the local browser profile you selected,
  not independently proved to belong to the account label. Confirm
  the correct profile was signed in.
- The separate local Headless Test tab continues to be a test-only
  socket server. It still does not connect avatars to Habbo.com.
- Direct Classic still launches the native game, not a headless game
  protocol implementation. Multiple G-Earth game proxies remain
  unimplemented.

The optional manual "Queue ticket locally" path remains unchanged.
The verified ZIP updater still uses the original three application
files and includes this change inside the bundled .pyw, avoiding
the legacy "Unexpected files" rejection.


Version 1.1.43 - Experimental Direct TCP
------------------------------------------
Direct TCP is a separate tab which can connect directly to the real official
Habbo.com AIR game TCP endpoint, with no Brave/Habbo.exe/G-Earth process.
It never claims a connected socket is authenticated before receiving Habbo's
AuthenticationOK packet. A genuine short-lived SSO ticket is required.
For repeated sessions, authenticated session.id and browser_token cookies may
be stored locally in Windows Credential Manager, with explicit user consent.
An expired website session still needs a fresh official login; saved password
login and captcha/2FA bypass are not supported by this tab.
Use the original Headless Test tab ONLY for fake local socket tests.
The live protocol can change. No live authentication has been verified in CI.


Version 1.1.44 - Start saved Direct TCP accounts automatically
---------------------------------------------------------------
To avoid repeated clicks, choose Direct TCP > Automatically connect saved
TCP accounts when Companion opens. This is opt-in and uses the separate
website sessions stored in Windows Credential Manager for each Habbo account.
No Brave, game launcher, or G-Earth is launched by this TCP feature.
The separate TCP connections still need live Habbo AuthenticationOK.
Expired or revoked website sessions require a new official sign-in.


Version 1.1.45 — Robust direct TCP frame reassembly
----------------------------------------------------
Prevent fragmented incoming TCP packet headers and bodies being lost if
socket reads time out during the handshake or authenticated session. Cipher
position is preserved on resume. Separate saved accounts have stable,
different client identifiers across reconnects. More specific handshake
timeout messages.
No Bobba code, Bobba API, AIR client assets or third-party dependency is added.
This does not remove the need for a legitimate Habbo login/session or prove
live Habbo protocol compatibility.

Version 1.1.46 — Direct TCP authentication troubleshooting
----------------------------------------------------------
- Fix sending username metadata as part of the game-server SSO token.
- Separate connect/DH handshake/SSO stages and show redacted, timestamped
  diagnostics with packet IDs and optional numeric disconnect reason code.
- Keep actual SSO tokens and session cookies out of logs; old stored website
  sessions are unchanged.
- Live Habbo login acceptance remains unverified. No need to re-enter saved
  cookies unless Habbo expired the official website session.

Version 1.1.47 — Correct initial TCP handshake headers
------------------------------------------------------
The first live test connected to the socket but received Disconnection
packet 4000 / reason code 122 before SSO authentication. Investigation
showed that the previous hard-coded packet IDs came from a standalone
bot and did not match a documented AIR client message registry.

This update uses documented AIR handshake identifiers, retrieves public
variables from the current official Habbo.com endpoint, and updates the
compatibility release baseline to the public 2026-11-04 AIR build.
The 2026 game server's exact protocol remains unverified. It never
tries alternate packet IDs automatically. Credentials are not logged.


Version 1.1.48 — More precise initial TCP handshake diagnosis
---------------------------------------------------------------
- Return from the 2016 retro-emulator packet mapping (silent timeouts)
  to the newer community AIR mapping (previously received disconnect),
  retaining the documented November 2026 AIR version baseline. Current
  game-server header compatibility is still not verified.
- Official public external_variables fetch now follows a tightly scoped,
  same-site content-hashed redirect and supports larger configuration files.
- SSO ticket HTTP endpoint still disallows redirects.
- Handshake timeout reports how many socket bytes arrived (counts only,
  no packet payloads or secrets).
This is not a confirmed live login fix. Do not retry repeatedly if rejected.


Version 1.1.49 — Read-only Habbo Classic WebSocket diagnostic
--------------------------------------------------------------
The newer Habbo Classic desktop client (September 2026) uses
wss://game-us.habbo.com:30001/websocket and the "habbo-classic" WebSocket
subprotocol rather than the legacy AIR TCP endpoint.

Use Direct TCP > Test Classic WSS connection (no login).
It tests secure TLS/WebSocket upgrade only, then closes normally.
It NEVER fetches or sends SSO, cookies, account identifiers, game
packets, passwords or local game credentials. No Brave or Habbo launcher.
This is NOT a Classic login or multi-account connection feature.
A successful 101 upgrade proves reachability only. Existing AIR TCP
mode is unchanged and still experimental.


Version 1.1.50 — Respond to 2935 server keepalive in AIR TCP
-------------------------------------------------------------
Observed official Habbo TCP packet: six bytes, header 2935, no payload.
A November 4 2026 third-party AIR header registry associates 2935 with
CLIENT_PING and 923 with CLIENT_PONG. Companion now replies with a single
empty Pong and logs that event during handshake. It also aligns its
handshake-related numeric IDs to the same revision, updates obsolete
FLASH25 to October 2026 AIR's FLASH31, and uses the three-field AIR
machine ID format. No extra cookies or game launcher required for testing.

Warning: This mapping is sourced from a third-party renderer and the
November official AIR platform marker is not yet verified. Passing tests
does NOT guarantee successful Habbo.com login. Test Account 1 only;
share the redacted log, not cookies or SSO tickets.


Version 1.1.51 — Automatically import Habbo session cookies
-----------------------------------------------------------
Direct TCP now has "Auto-import session and connect (selected account)"
and "Auto-import and connect all" actions.

Instead of finding session.id and browser_token in Brave DevTools,
Companion reuses the appropriate account's own saved browser profile or
starts it headlessly. If the user saved login credentials in Accounts,
Companion attempts the ordinary Habbo website login automatically,
reads ONLY the two official Habbo.com cookies via local browser
automation, verifies them against Habbo.com's official ticket endpoint,
and stores them in per-account Windows Credential Manager. It then
starts normal direct AIR TCP login. An expired saved session (401/403)
gets a single automatic renewal attempt.

No cookies, passwords, SSO tickets or other site data go into app
settings, account labels, command lines, logs or GitHub. All browser
profiles and session storage are isolated by account. Headless helper
browsers started by Companion are closed after import.

One-time setup: Accounts -> Save login securely for each profile. When
Habbo requires CAPTCHA, MFA or verification, use Accounts -> Open
account login and complete it normally. No login/security bypass.


Version 1.1.52 — Fix automatic Direct TCP account sign-in
---------------------------------------------------------
The first account can authenticate to Habbo via direct TCP; the second
account's background browser was getting rejected before cookie capture.

Auto-import now checks existing first-party Habbo.com cookies in the
selected account's ISOLATED browser profile and asks the official SSO
endpoint whether they are valid, without requiring a recognised Play
button/avatar menu. Only verified cookies are stored in Windows vault.

If the profile has no valid session, Companion can try a normal website
login using credentials saved under Accounts. A missing saved login,
unrecognised sign-in page, CAPTCHA/2FA requirement or browser-control
failure now gets a specific next-step message.

No broad cookie extraction from regular browser profiles, no bypassing
Habbo verification, and no extra packets for the already-authenticated
account. The feature is tested offline; live second-account validation
still depends on that account's normal Habbo login.
