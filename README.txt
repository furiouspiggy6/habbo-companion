HABBO COMPANION v1.1.5 — SAVED VS ACTIVE WINDOWS PROXY
==========================================================
The Windows network check may show a stored local proxy, for example
http=127.0.0.1:42822;https=127.0.0.1:42822, even when the Windows
manual proxy is DISABLED. A stored proxy address is NOT an active proxy.

- Check Windows network now distinguishes a stored localhost proxy from
  an ACTIVE one and explicitly says when no repair is needed.
- "Disable active local proxy" provides an opt-in recovery action ONLY
  when the current-user Windows manual proxy is enabled and configured
  to a local address. It warns about VPN/other-program interactions,
  backs up the registry values, rechecks for concurrent modifications,
  and only sets ProxyEnable=0, leaving ProxyServer unchanged.
- The Flash/AIR engine startup path monitors for unexpected activation
  of a local browser proxy for ten minutes after launch. If detected,
  it displays a warning and disables automatic G-Earth startup,
  WITHOUT silently changing Windows proxy settings.
- A stored but disabled localhost proxy is not considered a problem.
- New unit tests cover inactive-proxy detection and explicit consent.

IMPORTANT: This mitigates one plausible failure mode. It does not prove
that G-Earth caused the earlier Brave connection outage or that every
future networking problem can be prevented. Engine auto-start remains OFF
until the user explicitly enables it.
