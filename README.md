# Habbo Companion

A Windows desktop companion for Habbo. It brings saved account profiles, launch modes, a chat overlay, and optional G-Earth integration into one window.

## Start on Windows

1. Install Python 3.12 for Windows with Tcl/Tk enabled.
2. Download and extract the [source ZIP](https://github.com/furiouspiggy6/habbo-companion/archive/refs/heads/main.zip), or clone this repository.
3. Open `START_Habbo_Companion.bat` from the extracted folder. Use `DEBUG_Habbo_Companion.bat` to see any startup errors.

## Find your way around

| Page | What to use it for |
| --- | --- |
| **Accounts** | Add a profile, open its Habbo sign-in, and select how it should launch. |
| **Clientless Bot** | Manage connected profiles and access room, chat, and Coffee Pass controls. |
| **View Chat** | Configure the overlay. Original bubble images come from a compatible patched Habbo AIR client. |
| **Packet Viewer** | Configure the optional G-Earth connection and view its status. |
| **Updates** | Choose **Check online**, **Install update ZIP…**, or **Restore previous version…**. |

Settings are stored in `%APPDATA%\HabboViewChat\settings.json`. Saved passwords are held in Windows Credential Manager. The [update manifest](./latest.json) lists the published version, package URL, and SHA-256 checksum.

## Development

Run these checks from the repository root with Python 3.12 and Tkinter.

```sh
python -m unittest discover -s tests
python scripts/security_audit.py
```

Run `python scripts/ui_smoke.py` with a graphical display to check workspace navigation with background connections disabled.

See the [update package format](./UPDATE_PACKAGE_FORMAT.txt) and [historical release notes](https://github.com/furiouspiggy6/habbo-companion/blob/98d648a9f3fc555b3e980a6d300442ff36ab37f0/README.md).
