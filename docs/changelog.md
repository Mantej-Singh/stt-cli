# Changelog

All notable changes to STT-CLI are documented here. See [README.md](../README.md) for the latest release.

---

## v1.4.0 (November 21, 2025)

**Auto-Start & Enhanced User Experience**

- ✨ **Auto-Start on Windows Boot** - Right-click system tray icon to enable/disable automatic startup
- 🎈 **First-Run Welcome Notification** - Friendly greeting when you launch STT-CLI for the first time
- ✅ **Checkable Menu Items** - Visual feedback in tray menu shows auto-start status
- 💾 **Settings Persistence** - Your preferences are remembered across sessions
- Settings stored in `%APPDATA%\stt-cli\settings.json` for better persistence
- Windows Startup shortcut management using pywin32 COM interface
- Enhanced error handling for permission issues
- Better first-run experience with guided setup

**Why This Matters:**
No more manually starting the app every time you boot Windows! Set it once, forget it forever. Perfect for power users who want STT-CLI ready the moment they log in.

---

## v1.3.1 (October 30, 2025)

**Winget Readiness - Package Manager Distribution**

- ✅ Added `--version` flag to display version information
- ✅ Added `--help` flag to show usage instructions
- ✅ Added programmatic `__version__` variable for better version management
- 📖 Documented log file location in README (`%TEMP%\stt-cli\app.log`)
- 🎯 Prepared for Windows Package Manager (Winget) submission

**Why This Matters:**
This release made STT-CLI ready for distribution via Winget (Windows Package Manager). Users can now install with a simple `winget install Mantej-Singh.STT-CLI` command!

---

## v1.3 (October 29, 2025)

**Balloon Notifications - Visual Feedback**

- 🔔 **Balloon notifications** appear when recording starts/stops
- ✅ **Start message** reminds you how to stop recording ("Double-tap Left Alt to stop recording")
- ✅ **Stop message** confirms recording has ended
- 🎨 Professional Windows notification system integration
- ⚙️ Configurable - can be disabled in code if needed

**Bug Fixes:**
- Fixed multi-toggle issue where rapid Alt key presses would cause recording to flash on/off
- Added 800ms cooldown period after toggle to prevent accidental multi-toggles
- Added exception handling to keyboard callbacks to prevent listener crashes
- Recording now reliably stops when you want it to!

**Technical Improvements:**
- Improved thread safety with proper event synchronization
- Better error handling and logging
- Resource optimization (icons cached at startup)
- Type hints for better code maintainability
- Version: 1.0 → 1.3

---

*Built Together with Gemini CLI, Enhanced Further with Claude Code*
