HABBO COMPANION v1.1.30 — ONE-CLICK ACCOUNT AUTO PLAY
=====================================================

The new Accounts tab has TWO additional buttons:
  Auto Play selected
  Auto Play all saved accounts

WHAT AUTO PLAY DOES
===================
1. Selects or launches that account's isolated Brave/Chrome/Edge
   browser profile. Every profile keeps its own cookies and sign-in.
2. If already signed into www.habbo.com, tries to follow the website's
   visible Play Now / Play / Download / Launch and log in buttons
   using trusted browser input events.
3. After Launch and log in, tries to select the accessible Classic
   button from an identified Habbo Launcher window via Windows
   UI Automation. If the button is not accessible or the browser
   prompts for permission to open an external app, asks you to
   complete the step manually.
4. If Auto Play all is selected, processes profiles SEQUENTIALLY,
   not all at once. To protect account/login token identity, it stops
   rather than triggering subsequent client launches if the previous
   Classic launcher was not independently selected.

ONE-TIME SETUP
==============
1. Install v1.1.30 via Updates > Check online.
2. In Accounts, add a label for each account (e.g. Main, Alt).
3. Click Open account login and sign into Habbo in each profile ONCE.
   You enter credentials ONLY into the official Habbo website.
4. If the browser asks to allow Habbo Launcher to open, choose whether
   to allow it yourself. Windows may remember your choice.
5. Next time, click Auto Play selected or Auto Play all saved accounts
   to reuse the browser's signed-in sessions.

If Habbo requests a new login or two-factor verification, Auto Play
stops and asks you to finish the sign-in in the matching browser.
Companion does NOT collect, store or autofill usernames, passwords,
two-factor codes, tokens or session cookies.

LOCAL BROWSER AUTOMATION SECURITY
=================================
For browser control Companion starts each dedicated Chromium profile
with a local 127.0.0.1 DevTools endpoint bound to a stable profile
specific port. This endpoint is accessible to other software on the
same PC. Don't use these profiles for unrelated sensitive browsing;
close the profile windows when finished. Existing browser windows
created by pre-v1.1.30 versions may need to be closed once to restart
with local automation enabled. No remote debugging connection is made
to an external IP address.

G-EARTH LIMITATION
==================
Auto Play manages BROWSER sign-in and desktop launch, not the
G-Earth proxy architecture. The current Companion session can only
intercept ONE G-Earth extension connection at a time. Multiple browser
logins and multiple AIR clients are not automatically multiple G-Earth
proxies. A second account using a different extension port still
needs its own independently working proxy setup. The feature refuses
to silently switch between already attached G-Earth packet sessions.
The ordinary managed engine is started automatically when supported
for the selected account's default extension port 9092.

Other features continue as before: 0.0001s requested coffee-delay
input (Tk minimum 1ms), cycles=0 until STOP, automatic CSV summaries,
confirmed hand-item updates, account ID/room-index decoding, chat
bubble PNG preservation, right-hand whispers and in-app updates.

This update passed offline unit tests but requires real Windows/Habbo
website/client testing to confirm the current page labels and that
the Habbo Launcher exposes a Classic button to Windows accessibility.
