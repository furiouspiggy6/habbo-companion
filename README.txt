HABBO COMPANION 1.0.3 — INTEGRATED PACKET MANIPULATOR
===================================================

WHAT'S NEW
  * Packet Manipulator tab inside the existing Companion window.
  * Add up to 60 packet rules: incoming/outgoing/both, exact header ID (or *)
    and optional packet-text filter. Actions: Block or Replace.
  * Enable/disable the rule engine explicitly; it always starts OFF.
  * Manual packet send: enter a G-Earth packet expression and select direction.
    Confirmation is required before each send.
  * Select any captured packet in Packet Viewer and click
    'Load selected viewer packet' to prefill the send field.
  * Your packet rules, chat settings, and saved G-Earth beta path are preserved.

HOW TO USE
  1. Start Habbo Companion and the working G-Earth beta, connect Packet Viewer.
  2. Go to Packet Manipulator. A rule needs a header ID or contains filter.
  3. Add a rule, then explicitly enable manipulation for this session.
  4. Use your own session for testing. Malformed packets may disconnect Habbo.

SAFETY & LIMITATIONS
  Rules are local and OFF on each launch, even when previously saved. Rules
  are not scheduled or replayed. G-Earth itself is not bundled. Actual
  incoming/outgoing interception with your Windows beta has not been tested.
  Client-side chat overlay files and HabboAir.swf are unchanged.

UPDATING
  Use Updates > Check online with the previously configured repository.
  Your existing settings are stored in %APPDATA%\HabboViewChat\settings.json.