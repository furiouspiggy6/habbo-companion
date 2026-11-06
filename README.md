# Habbo Companion

Windows companion panel for Habbo AIR: viewport-filtered, screen-fixed chat overlay, scrollback, original chat-bubble image support, and an optional read-only G-Earth packet viewer.

## Version 1.0.1 — published

**[Download the Windows installer ZIP](https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/Habbo_Companion_Installer_v1.0.1.zip)**

Extract the ZIP and double-click `INSTALL_Habbo_Companion.cmd`. This is a per-user script-based installer, **not** a signed EXE/MSI. Windows needs Python 3 with Tkinter. The installer makes a desktop shortcut and leaves existing settings untouched.

### Updating from an installed v1.0.0

In **Habbo Companion > Updates**, enter this HTTPS feed once:

```
https://raw.githubusercontent.com/furiouspiggy6/habbo-companion/main/latest.json
```

Click **Save source**, then **Check online** and approve the update. Version 1.0.1 includes that feed as the default for new installations.

The update package is hosted at `Habbo_Companion_Update_v1.0.1.zip`. The feed supplies its SHA-256 checksum. The application backs up its prior version, preserves `%APPDATA%\HabboViewChat\settings.json` and offers rollback. An update never silently installs: you approve each release. Public GitHub hosting does not by itself authenticate a future package, so use only this repository as the source.

### Files and boundaries

- `Habbo_Companion.pyw`: Companion interface and chat overlay
- `Habbo_Update_Helper.py`: local ZIP verification, updating and rollback
- `Install_Habbo_Companion.py`, `INSTALL_Habbo_Companion.cmd`: first-time installer
- `latest.json`: version and SHA-256 feed for online updates
- `Habbo_Companion_Update_v1.0.1.zip`: update package
- `Habbo_Companion_Installer_v1.0.1.zip`: first-time install bundle

**Not included:** private settings, chat logs, credentials, the Habbo AIR game client or G-Earth binaries. The G-Earth connection is experimental, runs using your separately installed compatible G-Earth backend and is not a replacement for the G-Earth GUI. Gameplay and Windows interaction were not tested in this environment.

### Publishing future updates

New builds require incrementing the version, generating a verified update ZIP, and publishing it alongside an updated `latest.json` containing its exact SHA-256 and URL. Changing code without updating the release feed will **not** cause Companion to update.
