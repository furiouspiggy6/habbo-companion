HABBO COMPANION v1.1.29 — MULTIPLE HABBO LOGIN PROFILES
=========================================================

NEW: Accounts tab — independent browser sign-ins for multiple Habbo
accounts, plus an account-labelled G-Earth extension-port selector.

To open several Habbo logins:
1. Update Companion in the Updates tab to 1.1.29.
2. Open the Accounts tab and click Add account for each login.
3. Select an account, set its account label and login website URL,
   and click Save changes.
4. Click Open account login. Companion starts Brave (or Chrome/Edge)
   with a private, dedicated browser user-data directory for that
   account. Log in directly on Habbo's website.
5. Repeat for other accounts. Browser cookies and sessions are not
   shared between account profiles. Companion does NOT collect
   usernames, passwords, cookies or authentication tokens.

The browser profile directories are:
    %APPDATA%\HabboViewChat\account_browser_profiles\<internal ID>

Removing an account from the list DOES NOT delete its browser data.
Keep these directories private because browsers store session cookies.

G-EARTH PACKET CONNECTIONS
=========================
- Each account has an optional independent G-Earth extension-port
  assignment (e.g. main=9092, alternate=9093). Ports must be unique.
- "Check port" shows whether a local socket is listening there; it
  does NOT prove the G-Earth engine is connected to the account.
- "Use selected G-Earth port" changes the ONE packet-tools endpoint
  that this instance of Companion uses, provided it is not currently
  attached to a different endpoint. Changing the active endpoint while
  connected is refused to avoid mixing packets and account identities.
- Separate accounts must have independently configured G-Earth
  instances/proxies to be intercepted separately. Account browser
  login windows by themselves do NOT spawn additional proxies.
- The shipped G-Earth AIR proxy and the existing Companion packet
  worker are SINGLE-CONNECTION systems. This update does NOT make one
  G-Earth engine intercept multiple simultaneously connected clients
  or safely launch multiple AIR clients on the same hotel server/port.
  If the packet tools are already attached, restart Companion and
  select another port before attaching that account.
- No password fields or automated account sign-in are included.

This is a practical first phase for managing separate logins and
endpoint configurations in one window. Simultaneously intercepting
multiple AIR clients would require upstream G-Earth multi-proxy
support and independent per-account packet workers.

PREVIOUS FEATURES PRESERVED
===========================
- Coffee Pass loop with requested delay down to 0.0001 seconds;
  real Tk event-loop scheduling still has >=1ms floor.
- Complete loop cycles=0 runs until STOP.
- Auto-saved CSV and summary recording; own-avatar room-index repair.
- Optional verified pickup mode, finite 3-cycle speed testing,
  extra coffee/bookcase sources and opt-in group rotation.
- Original Habbo PNG chat bubble images, whisper-right alignment,
  chat overlay, packet viewer, and the one-click online updater.

Install through Updates > Check online. Automated tests are run in
GitHub Actions; multi-account browser/G-Earth behavior needs real
Windows/client verification.
