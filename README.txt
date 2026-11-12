HABBO COMPANION v1.1.37 — MULTI-TAB SIGN-IN DETECTION
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
