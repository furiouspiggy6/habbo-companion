HABBO COMPANION v1.1.27 — FASTER COFFEE DELAYS; UNLIMITED CYCLES
=================================================================

The Coffee Pass Loop's "Delay per action" now accepts values BELOW 0.1s:
  0.1 = 100 milliseconds
  0.05 = 50 milliseconds
  0.02 = 20 milliseconds
  0.01 = 10 milliseconds (fastest selectable)

The interval is between outgoing actions, so each handoff needs at
least two actions: pick up from furniture, then pass the carried item.
The physical/software/server timing may be longer than the selected
delay. Shorter request intervals do NOT imply that Habbo accepted or
delivered more items. The Habbo server can reject or rate-limit them.

Why there is a 10ms floor:
This is a Windows/Tk event-loop application. A 0-millisecond
continuously rescheduled send could monopolize the user interface,
make STOP unresponsive, or overwhelm the client. A minimum of 10ms
allows controlled sub-100ms timing; it is not a confirmed Habbo
server-side minimum. No claim of unlimited packets per second is made.

TOTAL NUMBER OF SENDS IS ALREADY UNLIMITED:
Set "Complete loop cycles" = 0. Companion keeps cycling until STOP,
disconnect or a normal safety condition; no hard maximum count applies.
The cap of 10000 applies only when the user chooses a specific finite
number of cycles.

The optional Wait for my avatar to receive/pass each cup mode still
waits for actual server updates between actions. It may therefore
run slower. The finite three-cycle speed test still uses confirmations.

Opt-in group mode continues to require 10 seconds between individual
packet actions, and excluded/blocked recipients are not automatically
re-added. The generic packet repeater also keeps its existing
0.1-second minimum; this change is limited to Coffee Pass.

Everything else remains: original Habbo bubble PNGs, automatic local
coffee-session CSV and summary recordings, bookcase/multiple hand-item
sources, whisper-right positioning, username identification, and
normal in-app updates.

Install via Habbo Companion > Updates > Check online.
