HABBO COMPANION v1.1.23 — FIX UNKNOWN SELF ROOM INDEX
=======================================================
FIX: An avatar could be listed among 16+ room players but Companion
would still say "Your avatar room index: unknown after room change".

In v1.1.22 the new wait-for-pickup option needed to see your own
UserObject handshake packet, which sometimes arrived before G-Earth's
extension subscribed. Without that, the checkbox blocked the coffee loop.

v1.1.23 now requests the current Habbo identity on demand using the
normal, one-shot InfoRetrieve packet. When the Users roster is received
without the player's own account ID, Companion automatically makes one
identity request (throttled to once per five seconds). It then matches
your real account ID to the room's own avatar index.

There is also a "Detect my avatar" button next to "Refresh room players"
for a manual retry. The status reports if identity lookup fails or if
the account ID is known but the room index could not be decoded.
No identity or room index is invented.

IMPORTANT FALLBACK:
If "Wait for my avatar to receive/pass each cup" is checked but your
own room index is unavailable, Start now requests your identity and
asks if you want to use the ORIGINAL fixed-delay coffee mode for
this run. Choosing Yes turns the checkbox OFF and continues normally.
Choosing No sends nothing, so you can retry after the room index
appears.

The original mode remains pick up Cup 1 -> pass -> pick up Cup 2 ->
pass -> repeat at the selected delay. Its sends are not proof of
pickup or recipient receipt.

The optional verified mode still requires matching server CarryObject
events for your avatar. It stops if the server does not confirm that
you received a cup or emptied your hand after passing.

All previous features remain, including original Habbo chat PNGs,
whisper-right, opt-in group rotation, exclusion, delivery diagnostics
and unlimited 0-cycle loops.

INSTALL: Habbo Companion > Updates > Check online.
