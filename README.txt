HABBO COMPANION v1.1.25 — AUTOMATIC COFFEE LOOP RECORDINGS
==========================================================

WHAT CHANGED
------------
Every coffee session now automatically records a local timestamped CSV,
including the original FAST 0.1-second loop. You do not need to watch
the packet viewer, save any packet screenshots, run the slower confirmed
speed test or record results manually.

Auto-recording starts when you confirm Give 1 cup, Start coffee pass
loop, or Test speed (3 cycles). The NORMAL 0.1-second loop continues
at its configured 0.1s packet delay. The recorder does not wait for
server replies and never changes that delay.

Automatic events saved:
- Each successfully issued local UseFurniture pickup request with
  the exact room furniture ID and chronological action number.
- Each successfully issued PassCarryItem request with account ID,
  participant name (when known) and chronological action number.
- The observed server CarryObject event for YOUR avatar, including
  item type (positive for held-item, 0 for empty hand), when the
  game supplied your room avatar index.
- The observed CarryObject event for the CURRENT recipient when the
  recipient's room avatar index is known.
- Session start/end time, selected sources, configured action delay,
  and why the loop stopped or encountered a send/logging error.

The CSV contains timestamps with milliseconds and elapsed milliseconds.
All session events are buffered and written to disk as they occur.
The app synchronizes writer access for server events arriving from
the G-Earth interception thread, and flushes frequently. If logging
fails or reaches its 64MB per-session safety cap, the loop STOPS
instead of silently continuing unrecorded.

WHEN YOU PRESS STOP
-------------------
A final human-readable .summary.txt file is saved beside the CSV,
reporting configured delay, elapsed time, pickup requests, pass
requests, own carrying and empty-hand updates, target carrying and
empty-hand updates, per-furniture pickup requests, requests/minute
and server holding-item events/minute.

Files are automatically created in:

  %APPDATA%\HabboViewChat\coffee_sessions\

Click "Open saved coffee results" on the Coffee Pass tab to open
that folder directly. Files remain local: Companion does not upload
anything to GitHub, ChatGPT or any external analytics service.
You can share a CSV or summary voluntarily if you want deeper analysis.

IMPORTANT: The fast sender loop cannot confirm every recipient received
a hand item. These logs identify requests sent locally, incoming
server carrying-item updates and their timestamps, NOT private
recipient-side HandItemReceived events. If the recipient's room
index is unavailable, the CSV still records all local coffee requests
and your own carrying-item events, but there can be no target-side
observations. Even when target-side events arrive, each one is not
a guaranteed receipt for a specific request.

Your original chat bubbles, whisper alignment, all sources including
the bookcase, timed and acknowledged loops, group mode, opt-out
and update workflow are otherwise unchanged.

INSTALL: Habbo Companion > Updates > Check online.
