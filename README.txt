HABBO COMPANION v1.1.4 — NETWORK SAFETY AFTER CONNECTIVITY OUTAGE
================================================================
After a Brave internet outage which required Windows restart, all automatic
engine startup is disabled on this upgrade. Existing user settings remain
except this one-time engine autostart safety switch.

A new Check Windows network button inspects G-Earth-tagged Habbo redirects
and the current Windows manual proxy without making changes. G-Earth startup
is blocked if known stale Habbo redirects, an enabled local proxy, or an
inspection error is found.

Repair G-Earth hosts is explicitly opt-in, requires Windows administrator
permission, backs up the complete hosts file and removes ONLY exact
G-Earth-tagged game-*.habbo.com redirects. It does NOT reset Windows proxy,
DNS, firewall, DHCP, network adapters or unrelated hosts entries.
The repair refuses to run if the extension port is active.

The engine diagnostic warns before its launch-capable behavior, and automatic
startup requires a separate warning confirmation to re-enable.

This does not conclusively explain the prior outage, nor guarantee further
interception cannot affect the network. Leave automatic startup disabled
until the new safeguards have been tested on Windows.
