HABBO COMPANION v1.1.28 — 0.0001s COFFEE DELAY INPUT
===================================================

Coffee Pass now accepts requested "Delay per action" values down to
0.0001 seconds (100 microseconds / 0.1 milliseconds).

The program's Tkinter event loop schedules callbacks in WHOLE
milliseconds. Therefore, a requested 0.0001 seconds is scheduled at
the smallest nonzero Tk delay of 1 millisecond, not an actual
100-microsecond interval. Packet encoding, G-Earth sends, Windows
scheduling and any server processing can make actual intervals longer.
The confirmation dialog now displays both the requested delay and the
effective Tk scheduling floor.

Examples:
  Requested 0.1s    => 100ms Tk scheduling floor
  Requested 0.05s   =>  50ms Tk scheduling floor
  Requested 0.01s   =>  10ms Tk scheduling floor
  Requested 0.001s  =>   1ms Tk scheduling floor
  Requested 0.0001s =>   1ms Tk scheduling floor (not 0.1ms)

There is no total cycle-count limit in the regular loop when
Complete loop cycles = 0. The user can stop the loop at any time.
The existing G-Earth connection, rate limits imposed by the server
and send errors still apply, and no specific recipient receipt rate
is guaranteed.

Automatic local CSV logging continues unchanged. The timestamps in
the saved CSV tell you actual local send intervals and any available
CarryObject observations. The normal timed loop does not wait for server
acknowledgements; the optional confirmed-hand mode and the finite
three-cycle speed test still do.

The minimum 10-second per-action delay for multi-recipient opt-in group
mode is unchanged. The generic packet repeater keeps its 0.1s minimum.
Existing recipient exclusions, native chat bubbles, bookcase sources,
whisper placement and other app features remain unchanged.

INSTALL: Habbo Companion > Updates > Check online.
