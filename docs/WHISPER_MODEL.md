# Whisper Model: Download, Caching, and Lifecycle

**Version:** 2.0.0
**Last Updated:** November 26, 2025
**Author:** Mantej Singh Dhanjal

---

## Table of Contents

1. [Overview](#overview)
2. [Model Download Process](#model-download-process)
3. [Caching Strategy](#caching-strategy)
4. [Lifecycle Management](#lifecycle-management)
5. [Shutdown Behavior](#shutdown-behavior)
6. [Storage Locations](#storage-locations)
7. [Troubleshooting](#troubleshooting)

---

## Overview

STT-CLI v2.0 uses **OpenAI Whisper** via the `faster-whisper` library for offline speech recognition. The model is downloaded once and cached locally for subsequent uses.

### Model Specifications

| Property | Value |
|----------|-------|
| **Model Name** | Systran/faster-whisper-tiny |
| **Repository** | Hugging Face (https://huggingface.co/Systran) |
| **License** | MIT (100% free, commercial use allowed) |
| **Size** | ~75MB (model.bin + tokenizer + vocab files) |
| **Parameters** | 39 million (smallest Whisper model) |
| **Quantization** | INT8 (2-3x speedup on CPU) |
| **Backend** | CTranslate2 (optimized inference engine) |

---

## Model Download Process

### First-Time Download Flow

```
User starts STT-CLI (first run with Whisper mode)
   ↓
User double-taps Left Alt (start recording)
   ↓
recording_loop() captures audio
   ↓
transcribe_with_whisper(audio) called
   ↓
get_whisper_model() - FIRST CALL
   ↓
Check: Is whisper_model already loaded in memory?
   NO → Proceed with download
   ↓
Thread Lock Acquired (whisper_model_lock)
   ↓
WhisperModel("tiny", device="cpu", compute_type="int8", download_root=...)
   ↓
faster-whisper checks: Is model cached locally?
   NO → Download from Hugging Face CDN
   ↓
Download Progress (via huggingface_hub library):
   1. config.json (~1KB)
   2. tokenizer.json (~2MB)
   3. vocabulary.txt (~450KB)
   4. model.bin (~75MB) ← Main file, takes 5-10s on broadband
   ↓
Files saved to: %APPDATA%\stt-cli\models\models--Systran--faster-whisper-tiny\
   ↓
Model loaded into memory (whisper_model global variable)
   ↓
Thread Lock Released
   ↓
Model ready for transcription (~8-12 seconds total for first use)
```

### Subsequent Use Flow

```
User starts STT-CLI (model already downloaded)
   ↓
User double-taps Left Alt (start recording)
   ↓
transcribe_with_whisper(audio) called
   ↓
get_whisper_model() - SUBSEQUENT CALL
   ↓
Check: Is whisper_model already loaded in memory?
   YES → Return cached model (INSTANT, no disk access)
   ↓
Model ready for transcription (~0ms overhead)
```

**Key Insight:** The model is loaded **once per app session** and kept in memory. No disk I/O or download on subsequent transcriptions.

---

## Caching Strategy

### Memory Cache (whisper_model global variable)

**Code Location:** `main.pyw:whisper_model` (line ~74)

```python
whisper_model: Optional["WhisperModel"] = None  # Global in-memory cache
```

**Lifecycle:**
- **Created:** On first call to `get_whisper_model()`
- **Exists:** Throughout app lifetime (never unloaded)
- **Destroyed:** When app quits (automatic garbage collection)

**Benefits:**
- **Fast repeated transcriptions** (no reload penalty)
- **Low latency** after first use (<1s transcription time)

**Trade-off:**
- **High RAM usage** (~1.5GB while model in memory)
- Not suitable for memory-constrained devices

### Disk Cache (%APPDATA%\stt-cli\models\)

**Purpose:** Persistent storage of downloaded model files

**Directory Structure:**
```
%APPDATA%\stt-cli\models\
└── models--Systran--faster-whisper-tiny\
    ├── blobs\
    │   ├── [hash1] → config.json
    │   ├── [hash2] → tokenizer.json
    │   ├── [hash3] → vocabulary.txt
    │   └── [hash4] → model.bin (75MB)
    ├── refs\
    │   └── main → points to specific commit
    └── snapshots\
        └── [commit-hash]\
            ├── config.json → symlink to blob
            ├── tokenizer.json → symlink to blob
            ├── vocabulary.txt → symlink to blob
            └── model.bin → symlink to blob
```

**Managed By:** `huggingface_hub` library (automatic)

**Benefits:**
- **One-time download** (subsequent runs skip download)
- **Version tracking** (commit-based, can update model)
- **Atomic updates** (blob + snapshot design prevents corruption)

---

## Lifecycle Management

### App Startup

```python
# At startup, NO model loading occurs
# Model is loaded LAZILY on first Whisper transcription
```

**Why Lazy Loading?**
- **Fast startup** (<2s to system tray)
- **Efficient for Google-only users** (don't pay Whisper cost)
- **Reduced memory footprint** (model only loaded when needed)

### During Execution

**Scenario 1: User switches to Whisper mode**
```
1. User: Right-click tray → Engine → Whisper
2. set_engine("whisper") updates global current_engine
3. Settings saved to %APPDATA%\stt-cli\settings.json
4. Next recording uses Whisper (model loaded if not already)
```

**Scenario 2: User switches from Whisper to Google**
```
1. User: Right-click tray → Engine → Google
2. set_engine("google") updates global current_engine
3. Model REMAINS in memory (not unloaded)
4. Next recording uses Google (Whisper model idle but ready)
```

**Memory Optimization Insight:**
Even if user switches away from Whisper, the model stays in RAM for fast re-activation. This is acceptable because:
- Model loading is expensive (~5s)
- RAM is cheaper than latency
- Users may switch back frequently

---

## Shutdown Behavior

### Normal Shutdown (User clicks "Quit")

```python
def quit_program(icon_param: Optional[pystray.Icon] = None) -> None:
    logging.info("Exiting application...")

    # 1. Stop recording gracefully
    recording_event.clear()

    # 2. Wait for recording thread (max 1s)
    if recording_thread and recording_thread.is_alive():
        recording_thread.join(timeout=1.0)

    # 3. Stop system tray icon
    if icon:
        icon.stop()

    # 4. Exit process
    os._exit(0)  # Immediate exit, no Python cleanup
```

**What Happens to Whisper Model:**
- ❌ **NOT explicitly unloaded** (no `model.close()` or `del whisper_model`)
- ✅ **Automatic cleanup** by `os._exit(0)` → Process terminates → OS reclaims all memory
- ✅ **Disk cache preserved** → Model files remain in `%APPDATA%\stt-cli\models\`

**Why `os._exit(0)` instead of `sys.exit()`?**
- `sys.exit()` → Raises SystemExit exception → Python cleanup → Slower (1-2s)
- `os._exit(0)` → Immediate process termination → OS cleanup → Fast (<100ms)

### Windows Shutdown / PC Restart

```
User shuts down Windows
   ↓
Windows sends WM_QUERYENDSESSION to all apps
   ↓
STT-CLI (as a GUI app with no window) receives signal
   ↓
Python process terminated by OS (no custom handler)
   ↓
All memory released (including Whisper model)
   ↓
Disk cache remains intact (%APPDATA% persists)
   ↓
Next boot: Model loads instantly from disk cache
```

**Key Points:**
- ✅ **No data loss** (model cache is on disk)
- ✅ **No corruption** (huggingface_hub uses atomic writes)
- ✅ **Auto-start works** (if enabled, app restarts on login)

### Crash / Task Manager Kill

```
User force-kills pythonw.exe via Task Manager
   ↓
Process terminated immediately (no cleanup)
   ↓
Whisper model unloaded (OS reclaims memory)
   ↓
Disk cache MAY be incomplete if download was in progress
   ↓
Next run: faster-whisper detects incomplete download → Re-downloads
```

**Safety:** Hugging Face Hub uses `.incomplete` files during download. If interrupted, next run detects and resumes/restarts.

---

## Storage Locations

### Model Cache Directory

**Location:** `%APPDATA%\stt-cli\models\`

**Typical Path:**
```
C:\Users\<username>\AppData\Roaming\stt-cli\models\
```

**Size:** ~75MB for tiny model

**Can I Delete It?**
- ✅ **Yes** - App will re-download on next Whisper use
- ⚠️ **Trade-off** - Re-download takes 5-10 seconds on broadband

**How to Clear:**
```bash
rmdir /s /q "%APPDATA%\stt-cli\models"
```

### Settings File

**Location:** `%APPDATA%\stt-cli\settings.json`

**Contains:**
```json
{
  "stt_engine": "whisper",
  "whisper_model": "tiny",
  "auto_start": true,
  "first_run": false,
  "version": "2.0.0"
}
```

**If Deleted:** App recreates with defaults on next run.

### Logs

**Location:** `%TEMP%\stt-cli\app.log`

**Typical Path:**
```
C:\Users\<username>\AppData\Local\Temp\stt-cli\app.log
```

**Log Messages Related to Whisper:**
```
INFO - Whisper model loaded successfully
DEBUG - [WHISPER] Transcribed: hello world
WARNING - faster-whisper not installed. Only Google Web Speech API will be available.
```

---

## Troubleshooting

### Issue 1: Model Download Fails

**Symptoms:**
```
ERROR - Failed to load Whisper model: HTTPError 404
```

**Causes:**
- No internet connection during first use
- Corporate firewall blocks Hugging Face CDN
- Antivirus quarantines downloaded files

**Solutions:**
1. **Check internet:** Ensure connection during first Whisper use
2. **Try different network:** Use personal hotspot if corporate firewall blocks
3. **Whitelist in antivirus:** Add `%APPDATA%\stt-cli\models\` to exclusions
4. **Manual download:**
   ```python
   # Run in Python console:
   from faster_whisper import WhisperModel
   model = WhisperModel("tiny")  # Forces download
   ```

### Issue 2: Model Not Found After Download

**Symptoms:**
```
WARNING - faster-whisper not installed
```

**Cause:** `faster-whisper` library not installed in Python environment

**Solution:**
```bash
pip install -r requirements.txt --force-reinstall
```

### Issue 3: Slow Transcription (>3s)

**Symptoms:**
```
INFO - Whisper transcription took 4.2s
```

**Causes:**
- CPU overloaded (other applications)
- Model not using INT8 quantization
- Antivirus scanning model files

**Solutions:**
1. Close other applications (free CPU)
2. Verify INT8 in logs: `compute_type="int8"`
3. Exclude `%APPDATA%\stt-cli\models\` from real-time scanning
4. Upgrade to "base" model (better accuracy, slightly slower)

### Issue 4: High RAM Usage (>3GB)

**Symptoms:**
- Task Manager shows pythonw.exe using 3GB+ RAM
- System becomes sluggish

**Causes:**
- Whisper model in memory (~1.5GB)
- Multiple recording sessions (memory not released)
- Memory leak (rare)

**Solutions:**
1. **Normal:** Whisper uses 1.5GB RAM (expected)
2. **Switch to Google mode:** Uses <100MB RAM
3. **Restart app:** Right-click tray → Quit → Restart
4. **Upgrade RAM:** 8GB minimum recommended for Whisper mode

### Issue 5: Model Cache Corrupt

**Symptoms:**
```
ERROR - Failed to load model: FileNotFoundError
```

**Solution:**
Delete cache and re-download:
```bash
rmdir /s /q "%APPDATA%\stt-cli\models"
# Restart STT-CLI, will re-download automatically
```

---

## Model Upgrade Path (Future)

**Current:** Only "tiny" model supported

**Planned (v2.1):**
- **User-selectable models:** tiny, base, small
- **Settings menu:** Change model without editing JSON
- **Hot-swapping:** Unload old model, load new model
- **Trade-off UI:** Show size, speed, accuracy comparison

**How to Upgrade Model Manually (Advanced):**
```json
// Edit %APPDATA%\stt-cli\settings.json
{
  "whisper_model": "base"  // Change from "tiny" to "base"
}
// Restart STT-CLI → Will download 140MB "base" model
```

**Model Comparison:**
| Model | Size | RAM | Speed | Accuracy |
|-------|------|-----|-------|----------|
| tiny  | 75MB | 1.5GB | ⚡⚡⚡ | ⭐⭐ |
| base  | 140MB| 2GB   | ⚡⚡ | ⭐⭐⭐ |
| small | 460MB| 2.5GB | ⚡ | ⭐⭐⭐⭐ |

---

## Related Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture overview
- [THREADING.md](./THREADING.md) - Threading model and synchronization
- [STT-CLI-Architecture.drawio](./STT-CLI-Architecture.drawio) - Visual flow diagrams

---

**End of Whisper Model Documentation**
