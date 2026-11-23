# Habbo Companion

## v1.1.96 — One-click clientless profile launch (AIR-free)

Open **Clientless Bot**, select a saved profile in the dropdown (the
selection itself starts it), or click **Run selected profile**. The same
option is on **Accounts → Run selected profile (clientless, no AIR window)**.

Companion first attempts an existing saved website session, and falls back
to its already-implemented isolated private background browser if needed.
It requests an official SSO ticket, authenticates an independent Direct TCP
connection and **requests entry into the last saved numeric room ID** (Coffee
House **69118545** by default). The user must make the initial profile
selection; simply opening Companion never triggers an automatic room join.
Only the requested profile is targeted by the pending join, and stale login
generations or disconnects cancel it. Existing authenticated profiles skip
the login stage. Chat commands still have a manual 400ms send cooldown.

**No HabboAIR or G-Earth required for the pinned WIN63-202611041140-327405090
protocol baseline.** Bundled outgoing Chat, GetGuestRoom, Walk, Shout, Whisper,
Dance, Sign, Posture, and LookTo IDs (plus incoming chat IDs) come from the
Nov 7, 2026 source of
[Volt-Renderer](https://github.com/plus-emulator/Volt-Renderer/tree/c8f74ffdd9c3eeb27a532a705e09b665b76e67a1).
These are community source-derived compatibility mappings, **not confirmation
that Habbo's current live server uses them**. Unknown AIR releases fail
closed, with the older optional manual capture path retained. Leave room
is not included in the pinned map because its ID was not verified.

**Clientless-only mode** defaults ON, suppressing G-Earth automatic startup
and attachment. It does not uninstall G-Earth; turn the mode off to use
the advanced packet engine manually.

Manual official sign-in may still be required if session login expires,
CAPTCHA, MFA, or email verification is presented. A successful packet send
only confirms local socket transmission, not actual room entry or chat
display. Validate with a second account before relying on it.

## v1.1.95 — Saved Coffee House room shortcut

**Clientless Bot → Saved Room** now always shows **Coffee House**
(room **69118545**) with a one-click **Join Coffee House** button.
Clicking it selects the existing **Join room** action, fills room ID
69118545, and sends the same validated manual Direct TCP room-entry
requests as the ordinary **Send one action** button. No room is entered
automatically when Companion starts; the bot must already be authenticated.

The editable **Room ID** field is initialized to Coffee House on new installs.
If you manually join a different room, that last valid numerical room ID is
saved into Companion's settings and restored on restart. Using another ID
does not remove the permanent Coffee House shortcut. URLs are not accepted
as room IDs; enter the numeric ID only.

The settings loader now also preserves **saved clientless G-Earth packet
mappings** across restarts (it previously filtered out that setting).
Mappings remain tied to the configured WIN63 build; don't reuse them for
a different AIR release. No login credentials or live SSO tickets are
stored with rooms or mappings. A locally accepted join still does not
independently confirm server room entry.

## v1.1.94 — Fix clientless Say chat packet shape

**Clientless Bot → Say** now includes the third ChatMessageComposer field:
`{s:message}{i:bubble_style=0}{i:chat_tracking_id=-1}`.
The earlier v1.1.93 sent only the first two fields, leaving a malformed
chat request even though the socket reported a locally accepted send.
The serializer now matches the AIR ChatMessageComposer's documented
three-value array and default tracking ID.

**Shout** and **Whisper** remain two-field packets, matching their separate
AIR composers. Automatic and unmapped packet injection remain disabled.
The local send counter still does not establish server acceptance. Verify
with a second Habbo account that your text actually appears in the room.
If it still does not appear, investigate whether room entry has completed.

## v1.1.93 — Clientless Bot controls based on Habbo-Bot (experimental)

A **Clientless Bot** page extends the per-account **Direct TCP** connections
with manually initiated actions based on protocol structures in
[devlyresh/Habbo-Bot](https://github.com/devlyresh/Habbo-Bot):
**Join room**, **Leave room**, **Walk**, **Face tile**, **Say**, **Shout**,
**Whisper**, **Dance (0–4)**, **Sign (0–14)**, **Posture (0–1)**.
Incoming mapped Chat, Shout and Whisper packets can appear in a
text-only panel identified by room index. No game client is required
*after* a working Direct TCP game-server connection has authenticated.

**First-use setup:** (1) Choose an account and authenticate it under
**Direct TCP** using Companion's existing official Habbo SSO workflow and
Windows Credential Manager. (2) Connect a matching AIR client through
G-Earth and use **Clientless Bot → Capture action mappings from G-Earth**
to learn named outgoing and incoming headers. (3) Select the same account
in Clientless Bot, choose a single action, and click **Send one action**.
The action packet goes over that account's existing authenticated TCP socket,
not through G-Earth. Named mappings can be reused for the same WIN63 release
but different releases, missing names or ambiguous mappings fail closed.
Only public packet names and numeric IDs are saved; no login credentials.

Unlike the reference project's January 2026 sample, Companion does not
copy its older static packet IDs, store cookies in Python source, send through
untrusted proxies, automate bulk bot accounts, bypass membership restrictions,
or execute purchase/reward commands. Its actions use a whitelist and a
400 ms manual-send throttle. There are no automated or repeated bot actions.
G-Earth local send acceptance does not establish whether the Habbo server
applied the action. The original bubble chat overlay still uses the patched
AIR JSONL feed; the clientless view displays text only.

**Limitations:** The feature cannot repair an unauthenticated Direct TCP
handshake. Habbo protocol IDs are version-dependent; a G-Earth mapping
cannot independently prove that its AIR build matches your socket build.
Confirm the release before sending. This implementation uses independently
written, constrained code based on protocol structures in the Apache-2.0
devlyresh/Habbo-Bot source at commit
760e0ed355ff9a63c9382becb8d0f9b6529c5311.

## v1.1.92 — Dance Controller (four moves and auto-cycle)

Habbo Companion now includes a **Dance Controller** page in the sidebar,
with one-click playback of all four normal Habbo dance styles:
**Hab-Hop (1)**, **Pogo Mogo (2)**, **Duck Funk (3)** and **The Rollie (4)**.
The standard dance is open to everyone; Pogo Mogo, Duck Funk and The Rollie
usually require Habbo Club, enforced by the actual Habbo server. The app
does not bypass membership checks or claim a denied move worked.

**How to use:** connect through G-Earth and go to **Dance Controller**.
Choose a dance from the dropdown and press **Dance** to play it once.
For automatically changing dances, check at least two dance styles, enter
a **millisecond interval** between **1000 and 60000** (default **3000 ms**),
and click **Start cycling**. A **STOP DANCING** button immediately cancels
the scheduled cycle and sends the standard **Dance(0)** stop command when
the connection remains active.

All requests use **named** G-Earth **`{out:Dance}{i:ID}`** packets. No numeric
header is guessed or stored. The cycle starts only on user action and
stops automatically if a packet fails, the hotel disconnects, or the room
changes. Disconnect and shutdown do not attempt additional network sends.
Packet Viewer labels generated requests **Dance Controller**; the counts
mean local G-Earth send acceptance, **not** confirmation that the Habbo
server displayed the requested dance. Automatic cycling does not send
movement commands and never changes the avatar's square.

## v1.1.91 — Stationary 360° Face Rotator (eight LookTo directions)

A separate **Face Rotator** sidebar page rotates your avatar in place through
all eight facing directions (45° steps), clockwise or counterclockwise.
It uses **only named `LookTo` packets** with two tile-coordinate integers,
never `MoveAvatar` or any other walking packet. The outgoing header is
resolved from G-Earth's current mappings, rather than guessed from a fixed
numeric ID. The rotation runs only on explicit **Start 360° rotation**, with
an accessible **STOP** button.

**First use:** connect Habbo AIR through G-Earth, go to **Face Rotator**,
press **Capture my standing tile**, and click **your own avatar** in Habbo
within 30 seconds. The normal `LookTo` packet identifies its target tile;
clicking your own avatar is required so this target is your current square.
Companion verifies the mapped header and exact two-int packet shape but
cannot independently verify that the clicked avatar was yours. Never capture
by clicking a different player or floor square. If no `LookTo` packet is
produced, capture fails safely without sending anything.

Choose **Clockwise** or **Counterclockwise** and **150–60,000 milliseconds
per 45° step** (default **350 ms**). One full cycle is eight LookTo requests.
The rotation keeps your walking position unchanged; manual walking,
room changes, connection loss, and failed sends stop the loop. The captured
standing square is discarded when you move, change rooms or disconnect;
recapture in the new location. Neither the tile nor sending auto-starts
on application launch.

Packet Viewer labels local requests **Face Rotator**, and the page displays
local steps and completed eight-step cycles attempted. Local G-Earth sends
are *not* independently confirmed visible server-side rotations; the server
can rate-limit or ignore turns. The minimum interval avoids accidental
high-volume flooding of the official Habbo connection.

## v1.1.90 — Outfit Cycler speed in milliseconds, no artificial minimum

**Outfit Cycler → Milliseconds per outfit** replaces seconds.
The default is **300 ms** (the previous 0.3-second default).
Enter **0** to queue the next action immediately via the Tk event loop,
or enter any **non-negative fractional number of milliseconds**, such as
`0.1`, `0.01`, or `0.0001`. There is no app-imposed minimum interval,
including the previous 100 ms delay. A positive value below 0.5 ms
rounds to a 0 ms scheduling request because Tk's timers take integer
milliseconds.

The application migrates previously saved `outfit_delay` values from
**seconds** to **milliseconds** without silently changing their effective
pace. New choices are saved as `outfit_delay_ms`.

**Important:** A 0 ms scheduled delay is not proof of zero time between
actual sends; packet conversion, Windows event-loop scheduling, G-Earth,
network latency and Habbo's server-side rate limits still constrain the
speed of visible outfit changes. STOP and disconnect handling are retained.

## v1.1.89 — Rapid Outfit Cycler (manually captured looks)

A new **Outfit Cycler** page lets you capture up to eight different looks
from your own Habbo AIR client's **Looks → Save** actions and automatically
rotate them while connected through G-Earth.

- Press **Capture next outfit change**, change clothes normally in Habbo,
  and save/apply the look within 30 seconds. Repeat to capture two or more
  unique outfits. Only live, named `UpdateFigureData` outgoing packets
  with valid gender and figure tokens are accepted; no numeric header is
  guessed and no unrelated packets are stored.
- Set **Seconds per outfit** between **0.1 and 10** (default **0.3**).
  Press **Start cycling** or **STOP**. The cycler starts only on an explicit
  button click, never automatically on application or Habbo startup.
  It stops after a failed send or game disconnect.
- Validated gender/figure outfits and the configured interval persist in
  Companion's local settings. The current session's dynamically mapped
  named packet header is used for sending.
- Packet Viewer identifies the locally injected look-change requests as
  **Outfit Cycler**. Local G-Earth acceptance is **not** proof Habbo applied
  every update; server rate limiting may apply. Summaries cannot be loaded
  as arbitrary packet replay commands.

Capturing requires a live G-Earth-backed Habbo session and a manual
outfit save. Saved outfit parts may be rejected by Habbo if they are
not available on the currently connected account.

## v1.1.86 — Local Arcturus emulator packet fuzzing in Protocol Lab

The existing **Protocol Lab** now includes a separate **LOCAL ARCTURUS
EMULATOR** panel. It is part of the same Companion app and updater for all
users. The original synthetic mock-server fuzzing and authenticated remote
lab remain available and unchanged.

**Scope and safety**

- The new test always targets **127.0.0.1:30000**, a local emulator on your
  own machine. There is **no editable remote IP**, no connection to Habbo's
  production servers, no reuse of the live Direct TCP/G-Earth socket, and no
  SSO tickets or saved account credentials.
- Enter a **known 16-bit packet header ID** from the handler you are testing;
  Companion never guesses an ID. Choose **1–50 cases**. A confirmation
  prompt appears before any fuzz traffic.
- **Preview frame (offline)** builds and checks a sample without opening
  a socket. It displays the frame bytes, header ID and length.
- The boofuzz request uses `s_size(... output_format='binary')` covering
  exactly the header-and-body block, plus a 2-byte big-endian header ID.
  The sample body fuzzes a signed 32-bit integer through a custom
  callable **VL64Encoder** and a restricted signed single-digit value
  through a **B64Encoder**. Both encoders preserve the supplied character
  constraints; the B64 encoder intentionally refuses larger numbers
  because their digit ordering has **not** been confirmed.
- **TODO:** The supplied format does not identify the chosen handler's full
  body schema, required authentication handshake, or multidigit B64 rules.
  The minimal sample frame is not guaranteed to be accepted by Arcturus.
  A rejected packet does **not** imply the emulator is vulnerable.
- Each run records a local boofuzz SQLite test report under
  `%APPDATA%\\HabboViewChat\\fuzz_lab`. Reports are stored locally.
  Tests can crash or disconnect your emulator; use a restartable test server.

**Dependency:** Install boofuzz into Companion's Python environment:

```powershell
py -m pip install boofuzz==0.4.2
```

As of this update, 0.4.2 is the current published PyPI release; the
previous example mentioned 0.4.3, which could not be verified as a
published version. The new code uses the documented 0.4.2 block-encoder
and `s_size` APIs and is tested against that release in CI.

## v1.1.85 — Remove departed Habbo players from AI Reply To

The **AI Responder → Reply To** checklist no longer grows indefinitely
with usernames from earlier conversations in the room. It now combines
server-observed room members with **time-limited fallback evidence**:

- A player with a verified room index stays listed until Habbo's
  `UserRemove` packet confirms their departure. Departure packets are
  decoded from their raw packet string or G-Earth named expression, and
  confirmed departures immediately remove the checkbox and any explicit
  AI reply selection.
- A player seen **only in public AIR chat** or in a partially decoded
  `Users` packet with no room index is displayed for **up to 90 seconds
  after the last room-presence evidence**. A new public message or Users
  event refreshes that timestamp; an old chat message is not proof the
  speaker is still present. These fallback names can temporarily disappear
  while a quiet player is still in the room if their roster index was not
  decoded; this avoids showing departed players forever.
- Valid room indexes are preserved if a subsequent incomplete Users packet
  reports the same account ID with an unknown index. This makes future
  departure packets easier to match without affecting G-Earth sending.
- On confirmed room changes or disconnects, the room roster and any
  room-specific selected targets are cleared. The AI will not silently
  switch to Everyone or send to targets left over from a previous room.
- The list refreshes automatically while Companion is running; the
  **Refresh room** button also refreshes the displayed current roster.
  This does not erase saved persona chat histories or affect background
  public chat recording.

Your existing single shared application, auto-updates, AI personas and
G-Earth sender are unchanged. All users receive the same update.

## v1.1.84 — Persona-first AI Responder, fewer controls

AI Responder now prioritises **recreating a chat persona from saved room logs**.
Everything used regularly sits on one screen, and redundant controls have
been removed. **Your existing G-Earth packet sending still works.**

- **One switch:** **Enable AI responder (send in Habbo)**. There is no second
  "Send replies in Habbo (G-Earth)" switch. The responder starts OFF as before;
  enabling it automatically sends generated replies through the connected
  G-Earth/AIR session. Stop AI halts both generation and sending. A valid game
  connection and one observed outgoing public Chat packet are still necessary.
- **Reply Speed:** A working **0–30 second** slider for **both recreated and
  custom personas**, in one-second increments. Zero means no added cooldown;
  API generation, observation and G-Earth delivery still take some time. The
  default for new installations is 10 seconds. Older saved values above 30
  are clamped to 30 and updated when settings are saved. The previous persona
  30-second fixed gap is gone.
- **Persona search:** The application automatically scans its own
  `%APPDATA%\HabboViewChat\persona_logs\users` chat archive plus
  available existing/legacy log folders. Type part of a username to choose a
  recorded persona. No **Choose log folder** button is needed.
- **Custom personality:** Click **Use custom personality** to reveal the fully
  editable multiline personality box. The editor stays **hidden when a
  recorded persona is selected**, so its generic text cannot override the
  logged persona. Selecting a recorded persona hides it again.
- **Reply To:** A compact live-room checklist replaces the dropdown, manual
  comma-separated username field and suggestions list. Tick **Everyone
  (select all)** to include every detected room player, or untick it and
  select individual users. Search filters the displayed checkboxes without
  dropping selections. New room players are discovered automatically and
  by **Refresh room**; your own avatar is not offered.
- **Removed redundant interface:** There is no Advanced options menu,
  separate Reply frequency/Natural/Chatty control, Tone or Humour selector,
  style rotation toggle, manual "send latest draft" button, G-Earth capture
  diagnostic button, or chat-recording switch. The AI no longer includes
  Tone, Humour or Natural/Chatty in its prompts for either persona mode.
  Temporary instructions and the activity log remain available.
- **Chat recording always ON:** Every public AIR room-chat message continues
  to append to its sender's local `persona_logs/users/username.txt`,
  even with AI OFF and regardless of the selected persona. Whispers are not
  recorded as public chat. The on-screen message count remains informational.

This changes the interface and settings wiring **only**; the game proxy,
outgoing packet template, G-Earth sender, account manager and installer/update
format remain the same. The setting to enable AI is explicit and always starts
OFF, though it now also authorizes sending when a live session is available.

## v1.1.83 — Safer distribution for friends, same Companion for everyone

This release keeps **one app, one codebase and one update feed** for you and
your friends. No AI, G-Earth, Direct TCP, protocol tools, chat recording,
personality or account features were removed.

### Security improvements

- **Safer packet-log sharing.** The Packet Viewer export now asks whether to
  include packet contents. Choosing **No** (the recommended default) exports
  only timestamps, direction and a packet type when recognized; it omits
  **all** chat text and packet payloads, even credentials in unknown formats.
  Choosing **Yes** permits a private diagnostic content export after an
  explicit warning. Known token formats are redacted on that path but raw
  packet contents should still NEVER be posted publicly; redaction is not
  guaranteed to find all secret formats. The *live Packet Viewer*, G-Earth
  packet processing and manipulation tools are unchanged.
- **Redacted TCP diagnostics.** Common session-ticket, bearer-token and API
  key formats are masked in direct TCP diagnostic messages.
- **Online updater restricted to the official publisher.** The existing
  "Check online" flow now accepts only the canonical
  `https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json`
  feed, an exactly version-matched Companion ZIP from the same repository,
  and their SHA-256 checksums. HTTP(S) redirects and unrelated domains are
  rejected. Existing one-click update prompts, backups, rollback and ZIP
  format remain unchanged. Local **Install update ZIP** is still possible
  from another source but requires explicit confirmation and must be treated
  as untrusted executable code.
- **Local data excluded from Git.** A new `.gitignore` excludes saved
  settings, environment files, chat logs, browser profiles, packet captures
  and local backups so contributors are less likely to publish personal data.
- **Security checks on every PR and release.** `python
  scripts/security_audit.py` examines Git-tracked paths and text source for
  common real credential patterns and accidentally committed private files.
  This runs before GitHub Actions publishes an update. Additional regression
  tests exercise online-update trust checks, default payload-free exports,
  token redaction and the scanner.

**Remaining security limitations:** SHA-256 and trusted-source allowlisting
still cannot prove the publisher's identity if the GitHub account or release
workflow is compromised. Releases are **not cryptographically signed with a
separate offline key**. This is a practical hardening step, not an independent
penetration test or a guarantee that the application is vulnerability-free.
Each friend's local accounts, chat logs and credentials remain on their own
PC; selected chat examples are still sent to the OpenAI API when AI is enabled.

## v1.1.82 — Independent chat personas with temporary instructions

**Recreate a chat persona from saved logs** now uses only the selected
player's observed chat history and current room context to determine how
they react and speak. The custom **Personality** text, **Tone**, **Humour**,
**Reply frequency (Natural/Chatty)**, **Reply Speed** slider and **Rotate
styles** control are disabled when a recorded persona is selected. These
generic settings are **omitted from the AI request** in persona mode, not
just visually greyed out. Switching to **Use custom personality** restores
them. Persona mode keeps a 30-second minimum gap as an anti-spam safeguard.

**Temporary instructions** is a new text area on the main AI Responder page.
Enter one rule per line and click **Add instruction**. The app shows current
instructions and their remaining durations. Select an instruction and click
**Remove selected**, or **Clear all**. Examples:

- `be mean to Marc for 10mins`: temporarily use mildly cheeky teasing
  toward Marc in relevant conversations, without abuse or threats
- `type slow`: delay each generated outgoing G-Earth message by
  **10 seconds** until removed (G-Earth sends one complete chat packet;
  it cannot simulate individual keystrokes or display per-letter typing)
- `pretend to go afk for 2mins`: **send no AI replies** for two minutes;
  any pending generation/delayed send is cancelled immediately
- `talk about coffee for 3mins`: add an ordinary user-defined behaviour
  direction for three minutes. Other plain-language instructions are
  accepted as text directions for the model, not executed as code.

Supported time formats include seconds, mins/minutes and hours (up to
4 hours). Untimed generic or teasing directions default to ten minutes;
untimed AFK defaults to two minutes; untimed `type slow` remains active
until removed. Temporary instructions take precedence over the baseline
persona *only while active*. The main AI thread automatically expires them
and updates the list; these transient rules **do not persist after an
application restart**. Every rule change invalidates any old in-flight reply.

The existing **Reply to** room-player selector and safety filters,
background public-chat logging, G-Earth connection and packet sender are
unchanged. Both AI response generation and Auto-send still start OFF.

## v1.1.81 — Recreate a fuller conversational persona from chat logs

In **AI Responder**, the saved-user selector is now called **Recreate a chat
persona from saved logs** instead of Copy writing style. Selecting a username
now asks the AI to simulate a coherent *chat character* built from that
player's observed public messages, not just to copy their spelling.

The responder considers recurring patterns in the chosen player's:

- Conversational habits: typical replies, follow-up questions, conversation
  starters, messages where they simply ignore or dismiss a topic
- Humour, teasing, sarcasm, bluntness, warmth and social reactions
- Repeatedly mentioned interests or opinions **only when they appear in logs**
- Short versus long messages, laughter, slang, grammar, capitalization and
  punctuation

To improve consistency, it uses **up to 120 sampled messages** from recent
and older portions of the last **1,600 messages** for that selected player.
Unlike the previous random example selection, the same logs produce stable
references. A concise summary of observable length, question and laughter
habits accompanies the samples. Message text containing colons is preserved.

The status area explains when the evidence is limited. For example, five
recorded messages cannot reveal someone's full personality; capturing more
public chat will improve the *approximation*. The AI does **not** gain the
real player's identity, memories, private facts or ability to authenticate
as that person. It will not claim to literally *be* the selected player.

**Reply to** still independently controls which live room speakers can
trigger the bot. Existing G-Earth sending, reply-rate slider, background
logging and opt-in enable/auto-send controls are unchanged.

When AI is enabled, selected public chat history is sent to the configured
OpenAI API to generate responses, as with the previous chat-log mode.
Using more chat samples may increase input token usage.

## v1.1.80 — Adjustable AI reply speed

AI Responder now has a **Reply speed** slider on the main page. Drag toward
**Faster (5s)** or **Slower (2 min)** to set a minimum of 5–120 seconds
between AI-generated replies, in five-second increments. The default on
existing and new installations is **30 seconds**, replacing the previous
fixed four-second cooldown.

- Moving the slider changes the live responder's minimum interval immediately.
  The setting saves when you release the slider or click **Save changes**,
  and is restored after restarting Companion.
- The first reply may be generated as soon as a suitable message arrives.
  The interval is enforced **between subsequent generated replies**, not
  as a typing animation or guaranteed delay for every message.
- The normal AI decision logic can still choose to skip conversations.
  Slower settings mean *at most* one generated reply per interval, not a
  scheduled message every interval.
- Moving the slider does not enable AI or auto-send. Saved personalities,
  current-room target search, background chat logging, and working G-Earth
  packet sending are unchanged.

## v1.1.79 — Search live room users for reply targets; compact AI interface

**Reply to → Selected users** now has a **Search people in this room**
field with a list of matching players. The picker draws from the current
G-Earth `Users` snapshot and names observed speaking in the current AIR
room (including speakers outside the View Chat viewport), not the historical
per-user chat-log folder. Start typing any part of a name (case-insensitive),
select a suggestion, and the username is added to **Reply only to these users**.
You can select multiple people, edit the comma-separated list, or click
**Clear**. Selections are saved and applied immediately, while keeping the
existing AI and optional G-Earth sending switches unchanged.

Use **Refresh room** to reload currently detected names. The list also
refreshes on search focus or typing. Room changes, disconnections and player
departure packets remove old room entries. Users not yet identified by the
current feed/snapshot cannot appear in suggestions; entering a room with
G-Earth attached gives the best coverage. **Reply targets** remain separate
from **Copy writing style from saved chat logs**.

**UI layout fix:** Removed the `expand=True` vertical expansion on the
AI Responder's scrollable panel and Recent Activity log. Closing the
Advanced panel or hiding a username search dropdown now reclaims its
space rather than leaving a large empty region above the activity log.
The rest of Companion's working AIR/G-Earth sending logic is unchanged.

## v1.1.78 — Continuous public room-chat logging (independent of AI)

Companion now **automatically saves new public Habbo AIR room messages in the
background**, even when **Enable AI responder** is OFF, **Send replies** is
OFF, the AI Responder page is not open, or the Companion window is minimized.

- Logs are appended to separate files by username at
  `%APPDATA%\\HabboViewChat\\persona_logs\\users\\<username>.txt`.
  Each line retains the existing format:
  `[2026-11-23 13:26:00] Cheesecake: original message text`.
  Existing per-user files are appended to, not overwritten.
- Public messages from **all room speakers**, including your own account and
  those outside the View Chat display's visible-only filter, are archived.
  Whisper/private messages are excluded.
- The archived messages remain useful in the AI Responder's partial-username
  search: click **Refresh** to discover new user files and select a style.
- Public chat logging is **ON by default**, and the main AI Responder page
  shows the number of saved messages for the running session. A switch under
  **Advanced options** can disable it independently of the AI.
- Selecting a different folder to copy a historic writing style does **not**
  change the live archive destination.

**Important scope:** "Background" means Companion's normal polling loop
continues while the window is minimized or other tabs are open. Recording
requires **Companion to remain running** and **a live Habbo AIR chat feed to
be available**. It does not run after closing Companion, while Habbo is
disconnected, or during computer sleep/offline periods; no Windows service
or autostart task is installed.

The working G-Earth packet-sending logic has not been modified.
No additional browser/capture.py integration is required for this logger.

## v1.1.77 — Search saved chat-log users and copy their writing styles

The AI Responder's **Try a reply (preview only)** section has been removed.
In its place, the main screen now has **Copy writing style from saved chat logs**:

- Start typing any part of a username (case-insensitive), e.g. `mara`.
  A matching-username dropdown appears with clickable suggestions drawn from
  the available per-user `username.txt` chat-log files. No exact spelling
  or full username is needed.
- Select a result to **immediately switch** to that person's logged writing
  style. Companion reads their saved examples (word choice, slang, spelling,
  punctuation and typical message length), turns off style rotation, and
  saves the choice. The bot learns *style*, not factual identity, and does
  not reproduce or reveal private chat text verbatim.
- Click **Use my own style** to switch back to the editable custom personality.
  The custom editor is visually disabled while chat-log copying is active.
- Click **Choose log folder** and select your existing `chat_logs/users`
  directory (or its parent `chat_logs`) if the desired usernames are
  not listed. Use **Refresh** after additional logs are saved.
- The **Reply to** menu remains independent: choose Everyone, Selected
  users, or First active speaker. The selected writing style is how the
  bot replies; the selected target is whom it replies to.

The app still uses the existing AIR chat feed and optional connected G-Earth
sending. Both live AI and auto-send remain OFF after startup; no browser,
fixed mouse coordinates, or change to the working packet-sending code.
The previous advanced log-file username text field is removed to avoid
duplicating the searchable picker. Older saved styles and log paths remain
compatible.

## v1.1.76 — Simpler AI Responder screen

The AI Responder has been reorganised into **one straightforward page**
instead of three configuration tabs:

- **Enable AI responder** — listens to new room messages.
- **Send replies in Habbo (G-Earth)** — independent switch, OFF at startup.
- **Personality** — type how you want the bot to talk.
- **Reply to** — Everyone, Selected users (comma-separated names), or
  First active speaker. The usernames field only appears when needed.
- **Save changes / Stop** — save any edits or stop immediately.
- **Try a reply (preview only)** — type a test message and click **Test reply**;
  no game message is sent even if automatic sending is checked.
- **Recent activity** — shows the generated drafts, sends, and errors.

All less-frequently-used settings are still accessible through the collapsed
**Advanced options** section: reply frequency, model, tone, humour, optional
historical chat-log styling and rotation, local chat capture, test username,
manual send, and G-Earth capture diagnostics. Existing saved preferences
continue to load. Neither live AI nor automatic sending is enabled at startup.

**No changes were made to the working AIR/G-Earth live-chat or packet-sending
logic** in this version. Update through Companion's existing Updater.

## v1.1.75 — Fix AI outgoing Chat capture

Fixed an AI Responder send failure where live room messages were read and AI
drafts were generated but every send reported "type one normal public Habbo
chat line to learn its format". The outgoing G-Earth interceptor incorrectly
looked for an `{out:Chat}` header in `g_string()`, which is the legacy
byte representation rather than the parsed packet expression. The interceptor
now checks `g_expression()`, validates an explicitly named outgoing Chat
packet and stores its verified template for subsequent sending.

**How to verify:** connect the Habbo AIR client through G-Earth Packet Viewer,
enable AI Responder (Auto-send can remain off), and type one normal public
message directly in Habbo. The AI Responder decisions log should say
`Outgoing Chat format learned from Habbo.`. You can click
**Check G-Earth chat capture** for a diagnostic without sending a packet.
If outgoing packets are observed but the Chat format is not learned,
G-Earth may not have recognised its Chat packet name; no fallback packet ID
will be guessed. Use the Packet Viewer to inspect which outgoing messages
are actually being intercepted.

AI still starts disabled, and Auto-send remains a separate opt-in.
The client still uses the existing AIR feed and G-Earth, not a browser,
mouse clicks or `capture.py`. Live packet acceptance on an actual Habbo
session still requires testing on Windows.

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
