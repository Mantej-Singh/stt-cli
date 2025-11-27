# STT-CLI v2.0 Architecture Documentation

**Version:** 2.0.0
**Last Updated:** November 26, 2025
**Author:** Mantej Singh Dhanjal

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Layers](#architecture-layers)
3. [Component Diagram](#component-diagram)
4. [Data Flow](#data-flow)
5. [Technology Stack](#technology-stack)
6. [Design Decisions](#design-decisions)
7. [Security Considerations](#security-considerations)

---

## System Overview

STT-CLI v2.0 is a **Windows-only**, **background-running**, **hybrid speech-to-text** application with support for:
- **Offline mode**: OpenAI Whisper (MIT licensed)
- **Online mode**: Google Web Speech API
- **Auto-detect mode**: Intelligent switching based on internet connectivity

### Key Characteristics

- **Single-file executable**: No installation required (~150MB with Whisper dependencies)
- **System tray application**: No visible window, GUI-less operation
- **Event-driven architecture**: Global hotkey triggers recording
- **Multi-threaded**: Main thread, tray thread, recording thread
- **Security-focused**: Only types into CLI windows (cmd.exe, powershell.exe, WindowsTerminal.exe)

---

## Architecture Layers

### Layer 1: User Interface (System Tray)

**Component:** `pystray.Icon`
**Thread:** Daemon thread (tray_thread)

**Responsibilities:**
- Display system tray icon (idle vs listening states)
- Provide context menu with:
  - 🎙️ Engine submenu (Auto/Whisper/Google)
  - Start on Windows Boot (checkable)
  - About (version info)
  - Quit
- Show balloon notifications for:
  - Recording start/stop
  - Engine changes
  - First-run welcome
  - About information

**Icons:**
- `stt-cli2.ico` - Idle state (blue microphone)
- `stt-cli2.png` - Listening state (red/active microphone)

---

### Layer 2: Input Layer (Global Hotkey)

**Component:** `pynput.keyboard.Listener`
**Thread:** Background keyboard listener

**Responsibilities:**
- Listen for **Left Alt** key presses globally
- Detect **double-press** within 0.3s window
- Implement **cooldown** (0.8s) to prevent multi-toggles
- Trigger `toggle_recording()` on valid double-press
- Support ESC key for emergency quit

**State Management:**
- `last_press_time` - Timestamp for double-press detection
- `last_toggle_time` - Timestamp for cooldown enforcement
- `recording_event` - Threading.Event() for recording state

---

### Layer 3: Audio Capture

**Component:** `speech_recognition.Microphone`
**Thread:** Recording thread (spawned on-demand)

**Responsibilities:**
- Adjust for ambient noise (0.2s calibration)
- Continuous listening with 1-second timeout
- Convert audio to WAV format (16kHz, 16-bit)
- Pass audio data to transcription layer

**Audio Flow:**
```
Microphone → SpeechRecognition → AudioData → Transcription Engine
```

---

### Layer 4: Transcription Layer (Hybrid Engine)

**Components:**
- **Whisper Engine**: `faster-whisper` with CTranslate2 backend
- **Google Engine**: `speech_recognition.recognize_google()`

#### 4A: Whisper Engine (Offline)

**Library:** `faster-whisper` v1.2.1
**Model:** Systran/faster-whisper-tiny (39M parameters, ~75MB)
**Backend:** CTranslate2 with INT8 quantization

**Configuration:**
```python
model = WhisperModel(
    "tiny",
    device="cpu",
    compute_type="int8",  # 2-3x speedup on CPU
    download_root="%APPDATA%/stt-cli/models",
    num_workers=1
)

segments, info = model.transcribe(
    audio_array,
    language="en",          # Skip auto-detection (~200ms saved)
    beam_size=1,            # Greedy decoding (no beam search)
    best_of=1,              # No sampling
    temperature=0.0,        # Deterministic output
    vad_filter=False,       # Disable VAD (we handle silence)
    word_timestamps=False   # Skip timestamp calculation
)
```

**Performance:**
- **Latency:** 1-2 seconds for typical speech (2-5 seconds audio)
- **Accuracy:** Fair (tiny model trades accuracy for speed)
- **First-run:** 5-10s initial load + model download
- **Subsequent:** Instant (model cached in memory)

#### 4B: Google Engine (Online)

**Library:** `speech_recognition` v3.14.3
**API:** Google Web Speech API (free tier)

**Configuration:**
```python
text = recognizer.recognize_google(audio)
```

**Performance:**
- **Latency:** 0.5 seconds (faster than Whisper)
- **Accuracy:** Excellent (cloud-powered)
- **Requires:** Active internet connection

#### 4C: Engine Selection Logic

**Auto-Detect Mode** (Default behavior before v2.0):
```python
def get_current_engine() -> STTEngineType:
    if current_engine == "auto":
        if has_internet():
            return "google"  # Fast + accurate
        else:
            return "whisper" if WHISPER_AVAILABLE else "google"
    return current_engine
```

**Manual Mode** (v2.0+):
- User selects engine via system tray menu
- Choice saved to `%APPDATA%\stt-cli\settings.json`
- Persists across app restarts

---

### Layer 5: Output Layer (CLI Window Detection)

**Component:** Win32 API + `pynput.keyboard.Controller`

**Responsibilities:**
- Detect foreground window using `win32gui.GetForegroundWindow()`
- Get process name via `win32process` + `psutil`
- Validate against CLI whitelist:
  - `cmd.exe`
  - `powershell.exe`
  - `WindowsTerminal.exe`
  - `wt.exe` (Windows Terminal alias)
- Type transcription + space character only if CLI is active

**Security Rationale:**
Prevents accidental typing of sensitive transcriptions into browsers, text editors, or other applications.

---

### Layer 6: Configuration & Persistence

**Component:** JSON-based settings in `%APPDATA%\stt-cli\`

**Settings File:** `settings.json`
```json
{
  "auto_start": true,
  "first_run": false,
  "stt_engine": "whisper",
  "whisper_model": "tiny",
  "version": "2.0.0"
}
```

**Auto-Start Management:**
- Creates shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`
- Uses `win32com.client` COM interface for shortcut creation
- Persists across Windows reboots

---

## Component Diagram

<div align="center">
  <img src="screens/STT-CLI-Architecture.drawio.png" alt="STT-CLI Architecture Diagram" width="800" />
  <p><i>Visual flow diagram showing component interactions and data flow</i></p>
</div>


See [STT-CLI-Architecture.drawio](./STT-CLI-Architecture.drawio) for the editable draw.io source file.

**Key Components:**

```
┌─────────────────────────────────────────────────────┐
│                   USER INTERACTION                   │
│  (Double-tap Left Alt, Right-click tray menu)       │
└─────────────────────┬───────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│             SYSTEM TRAY (pystray)                    │
│  - Icon updates (idle/listening)                    │
│  - Menu: Engine, Auto-start, About, Quit            │
│  - Notifications (balloon tooltips)                  │
└─────────────────────┬───────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│         GLOBAL HOTKEY LISTENER (pynput)              │
│  - Detects double-press Left Alt                    │
│  - Cooldown enforcement (0.8s)                       │
│  - Calls toggle_recording()                          │
└─────────────────────┬───────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│            RECORDING THREAD (daemon)                 │
│  - Adjust for ambient noise                          │
│  - Continuous listening (1s timeout)                 │
│  - Convert audio → AudioData                         │
└─────────────────────┬───────────────────────────────┘
                      ▼
          ┌───────────┴────────────┐
          ▼                        ▼
┌──────────────────┐     ┌──────────────────┐
│  WHISPER ENGINE  │     │  GOOGLE ENGINE   │
│  (Offline)       │     │  (Online)        │
│  - faster-whisper│     │  - Web Speech    │
│  - CTranslate2   │     │  - API call      │
│  - INT8 quant    │     │  - 0.5s latency  │
│  - 1-2s latency  │     └────────┬─────────┘
└────────┬─────────┘              │
         └────────────┬────────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│           CLI WINDOW DETECTION (Win32)               │
│  - Get foreground window                             │
│  - Check process name                                │
│  - Whitelist: cmd, powershell, WindowsTerminal       │
└─────────────────────┬───────────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────────┐
│         OUTPUT (pynput keyboard controller)          │
│  - Type transcription + space                        │
│  - Only if CLI window is active                      │
└─────────────────────────────────────────────────────┘
```

---

## Data Flow

### Recording Start Flow

```
1. User double-taps Left Alt
   ↓
2. on_press() detects double-press (within 0.3s)
   ↓
3. Check cooldown (must be > 0.8s since last toggle)
   ↓
4. toggle_recording() called
   ↓
5. recording_event.set() → State = RECORDING
   ↓
6. Icon changes to "listening" (stt-cli2.png)
   ↓
7. Notification shown: "Recording Started - Using: Whisper (Offline)"
   ↓
8. recording_thread spawned (daemon=True)
   ↓
9. recording_loop() starts continuous listening
```

### Transcription Flow (Whisper)

```
1. recording_loop() captures audio
   ↓
2. recognizer.listen(source, timeout=1) → AudioData
   ↓
3. get_current_engine() → "whisper"
   ↓
4. transcribe_with_whisper(audio)
   ↓
5. get_whisper_model() - lazy load with thread lock
   ↓
6. Audio conversion: WAV → numpy array (16kHz, float32)
   ↓
7. model.transcribe(audio_array, language="en", beam_size=1...)
   ↓
8. Segments joined → text string
   ↓
9. Log: "[WHISPER] Transcribed: {text}"
   ↓
10. is_cli_window() → Check foreground window
   ↓
11. If CLI: Type text + space using keyboard_controller
    If NOT CLI: Log "Active window is not a CLI, skipping"
```

### Engine Switching Flow

```
1. User right-clicks tray icon
   ↓
2. Hovers over "🎙️ Engine"
   ↓
3. Selects "Whisper (Offline)"
   ↓
4. set_engine("whisper") called
   ↓
5. current_engine = "whisper" (global state update)
   ↓
6. save_settings() → Persist to settings.json
   ↓
7. Notification: "Engine Changed - Now using: Whisper (Offline)"
   ↓
8. icon.update_menu() → Checkmark moves to "Whisper"
```

---

## Technology Stack

### Core Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `faster-whisper` | 1.2.1 | Offline speech recognition (4x faster than vanilla Whisper) |
| `av` (PyAV) | 16.0.1 | Audio decoding for Whisper (FFmpeg bindings) |
| `ctranslate2` | 4.6.1 | Fast inference engine for Whisper (INT8 quantization) |
| `numpy` | Latest | Audio array processing |
| `SpeechRecognition` | 3.14.3 | Google Web Speech API integration + microphone access |
| `pynput` | 1.8.1 | Global keyboard listener + controller |
| `PyAudio` | 0.2.14 | Microphone capture (SpeechRecognition dependency) |
| `pystray` | 0.19.5 | System tray icon + menu |
| `Pillow` | 10.4.0 | Image handling for tray icons |
| `pywin32` | 311 | Windows API access (COM, Win32GUI) |
| `psutil` | 7.1.1 | Cross-platform process utilities |

### Build Tools

| Tool | Purpose |
|------|---------|
| `PyInstaller` | Single-file .exe packaging with hidden imports |
| `certutil` | SHA256 hash calculation for winget manifests |
| `draw.io` | Architecture diagram creation |

---

## Design Decisions

### 1. Why Hybrid Architecture?

**Problem:** Corporate laptops often have:
- Win+H disabled by IT policies
- Restricted/intermittent internet access
- Firewall blocks to cloud speech APIs

**Solution:** Hybrid approach provides:
- **Offline fallback**: Whisper works without internet
- **Accuracy when available**: Google is faster + more accurate online
- **User control**: Manual engine selection for specific scenarios

### 2. Why "tiny" Whisper Model?

**Rationale:**
- **Speed > Accuracy** for CLI use case (quick commands, short dictation)
- **Small download** (75MB vs 460MB for "small" model)
- **Low RAM** (~1.5GB vs 2GB+ for larger models)
- **Corporate laptop friendly** (many users have limited resources)

**Trade-off:** Fair accuracy vs excellent speed. Users can upgrade to "base" by editing settings.json.

### 3. Why Lazy Model Loading?

**Rationale:**
- **Fast startup** (app starts in <2s, no Whisper delay)
- **Memory efficient** (model only loaded when needed)
- **Google-first users** (those who never use Whisper don't pay the cost)

**Implementation:** Thread lock ensures single model instance, loaded on first Whisper transcription.

### 4. Why CLI-Only Output?

**Security Rationale:**
- Prevents typing sensitive transcriptions into:
  - Web browsers (could expose passwords, personal info)
  - Text editors (unintended file modifications)
  - Chat applications (accidental messages)
- CLI windows are explicit targets (Windows Terminal, PowerShell, CMD)

**User Benefit:** Confidence that speech won't leak into wrong applications.

### 5. Why Global State Instead of Classes?

**Rationale:**
- **Simplicity**: Single-file application with ~800 lines
- **Threading compatibility**: Global state with locks is clearer than class state
- **Maintainability**: Easier to understand for small projects

**Trade-off:** Not scalable for large projects, but appropriate for STT-CLI's scope.

---

## Security Considerations

### 1. CLI Window Whitelist

**Threat:** Accidental typing into sensitive applications
**Mitigation:** Hardcoded whitelist of CLI process names
**Code Location:** `main.pyw:is_cli_window()` (line ~460)

### 2. Audio Privacy (Whisper Mode)

**Threat:** Audio transmitted to cloud without user knowledge
**Mitigation:**
- Whisper runs 100% locally (no network calls)
- User can verify via network monitoring
- Clear UI indication of engine in use

### 3. Model Download Security

**Threat:** Man-in-the-middle attack during model download
**Mitigation:**
- Downloads from Hugging Face CDN (HTTPS)
- Model integrity checked via hash (Hugging Face built-in)
- One-time download, cached locally

### 4. Settings File Access

**Threat:** Unauthorized modification of settings.json
**Mitigation:**
- Stored in `%APPDATA%` (user-only access)
- No sensitive data stored (only UI preferences)
- JSON schema validation on load

---

## Related Documentation

- [WHISPER_MODEL.md](./WHISPER_MODEL.md) - Model download, caching, lifecycle
- [THREADING.md](./THREADING.md) - Threading model and synchronization
- [STT-CLI-Architecture.drawio](./STT-CLI-Architecture.drawio) - Visual flow diagrams

---

**End of Architecture Documentation**
