HABBO COMPANION — ONE-CLICK WINDOWS INSTALLER
=============================================

WHAT TO DO
1. CLOSE the old Habbo Companion panel (and its overlay) first.
2. Extract this entire ZIP into a folder (right-click ZIP > Extract All).
3. Double-click INSTALL_Habbo_Companion.cmd.
4. The installer opens the new Habbo Companion and creates desktop and
   Start-menu shortcuts. From now on, use the new Habbo Companion shortcut.

NO ADMINISTRATOR PERMISSION IS REQUIRED FOR THE INSTALLER.

WHAT THIS PRESERVES
- Your current chat settings in %APPDATA%\HabboViewChat\settings.json
- Your saved G-Earth beta executable path and game host settings
- Your existing Habbo client / HabboAir.swf
- Your previous Companion folder (the installer does not delete it)

WHERE IT INSTALLS
  %LOCALAPPDATA%\Programs\Habbo Companion

HOW FUTURE UPDATES WORK
- Open the new Companion > Updates > Install update ZIP.
- Select a trusted Habbo_Companion_Update_vX.Y.Z.zip.
- Confirm. The app backs up the old version, installs and restarts itself.
- Updates do not require manually copying .pyw files.
- Use Updates > Restore previous version if an update does not work.
- All application backups are stored in:
    %LOCALAPPDATA%\HabboCompanion\Backups

ONLINE UPDATES
The Updates tab also supports checking a trusted HTTPS manifest URL, but
there is no public update feed configured yet. That requires a publisher to
host future versions, e.g. in GitHub Releases. Nothing is auto-downloaded
or installed without your approval.

G-EARTH
The installer deliberately does not install or modify G-Earth. It preserves
which beta you selected previously. Because your beta worked when connected
manually, try Packet Viewer > Launch manually if automatic connection hangs.

REQUIREMENTS
Windows 10 or 11 with Python 3 and Tkinter (already on your PC).
It uses only Python standard library for the chat GUI/updater; G-Python is
used only for optional packet viewing.

SAFETY / LIMITATIONS
This is an unsigned, script-based Windows installer, not a signed .exe or MSI.
Review scripts if you wish before running them. Only install future update
ZIPs obtained from a source you trust. Hash verification checks file integrity
but cannot authenticate the publisher by itself.

For debugging, run DEBUG_Habbo_Companion.bat from the installed folder.
