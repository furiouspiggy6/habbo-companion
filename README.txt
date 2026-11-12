HABBO COMPANION v1.1.33 — AUTO PLAY ALL LOGIN PREFLIGHT
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
