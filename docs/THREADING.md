# Threading Model and Synchronization

**Version:** 2.0.0
**Last Updated:** November 26, 2025
**Author:** Mantej Singh Dhanjal

---

## Table of Contents

1. [Overview](#overview)
2. [Thread Architecture](#thread-architecture)
3. [Synchronization Primitives](#synchronization-primitives)
4. [Thread Lifecycle](#thread-lifecycle)
5. [Race Condition Prevention](#race-condition-prevention)
6. [Deadlock Prevention](#deadlock-prevention)
7. [Thread Safety Analysis](#thread-safety-analysis)

---

## Overview

STT-CLI uses a **multi-threaded architecture** with three concurrent threads:
1. **Main Thread** - Keeps application alive
2. **Tray Thread** - System tray icon and UI (daemon)
3. **Recording Thread** - Audio capture and transcription (daemon, spawned on-demand)

**Design Philosophy:** Use threading for concurrency, not parallelism (Python GIL limitations accepted).

---

## Thread Architecture

### Thread 1: Main Thread

**Created By:** Python interpreter (entry point)
**Lifecycle:** App start → App exit
**Purpose:** Keep application alive and handle graceful shutdown

```python
def main() -> None:
    # Initialize resources
    load_icon_resources()

    # Start daemon threads
    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    keyboard_listener.start()

    # Keep main thread alive (infinite loop)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        quit_program()
```

**Key Characteristics:**
- **Blocks forever:** `while True: time.sleep(1)` prevents main thread exit
- **Signal handler:** Catches Ctrl+C (KeyboardInterrupt) for clean shutdown
- **Thread spawner:** Starts tray and keyboard threads
- **Exit path:** Only exits via `quit_program()` → `os._exit(0)`

---

### Thread 2: Tray Thread (pystray)

**Created By:** `threading.Thread(target=setup_tray, daemon=True)`
**Lifecycle:** App start → App exit (daemon, terminates with main thread)
**Purpose:** System tray icon, menu, and notifications

```python
def setup_tray() -> None:
    global icon

    # Create menu
    menu = pystray.Menu(...)

    # Create icon
    icon = pystray.Icon("speech-to-text-cli", idle_icon_image, "Speech-to-Text CLI", menu)

    # Run icon (BLOCKS this thread)
    icon.run()  # Infinite event loop
```

**Key Characteristics:**
- **Event-driven:** `icon.run()` is a blocking event loop (similar to `app.exec()` in Qt)
- **Daemon thread:** Automatically terminated when main thread exits
- **UI thread:** Handles all tray menu clicks and notifications
- **Global state access:** Uses `global icon` to allow other threads to update icon/menu

**Thread-Safe Operations:**
```python
# Safe: icon.icon = listening_icon_image (thread-safe in pystray)
# Safe: icon.notify(...) (thread-safe in pystray)
# Safe: icon.update_menu() (thread-safe in pystray)
```

---

### Thread 3: Recording Thread (Audio Capture)

**Created By:** `threading.Thread(target=recording_loop, daemon=True)`
**Lifecycle:** Spawned on recording start → Exits on recording stop (daemon)
**Purpose:** Continuous audio capture and transcription

```python
def recording_loop() -> None:
    global recording_thread

    logging.info("Recording loop started")

    # Adjust for ambient noise (one-time calibration)
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.2)

    # Continuous listening loop
    while recording_event.is_set():
        try:
            with microphone as source:
                audio = recognizer.listen(source, timeout=1)

            # Transcribe based on engine
            engine = get_current_engine()
            transcription = ...

            # Type into CLI if active
            if transcription and is_cli_window():
                keyboard_controller.type(transcription)
                keyboard_controller.press(Key.space)
                keyboard_controller.release(Key.space)

        except sr.WaitTimeoutError:
            pass  # No speech detected, continue

    logging.info("Recording loop ended")
```

**Key Characteristics:**
- **Daemon thread:** Auto-terminates if main thread exits
- **Event-driven exit:** Checks `recording_event.is_set()` each iteration
- **Blocks on I/O:** `recognizer.listen()` blocks until audio captured
- **Single instance:** Only one recording thread active at a time (enforced by `toggle_recording()`)

---

## Synchronization Primitives

### 1. threading.Event (recording_event)

**Purpose:** Signal recording state (started/stopped)
**Type:** Binary semaphore (set/clear)

```python
recording_event: threading.Event = threading.Event()

# Start recording
recording_event.set()    # recording_event.is_set() → True

# Stop recording
recording_event.clear()  # recording_event.is_set() → False
```

**Thread Access:**
- **Main Thread:** Reads (indirectly via keyboard listener)
- **Keyboard Listener Thread:** Writes (calls `toggle_recording()`)
- **Recording Thread:** Reads (loop condition: `while recording_event.is_set()`)

**Why Event Instead of Boolean?**
```python
# ❌ BAD: Race condition possible
is_recording = False  # No memory barrier

# ✅ GOOD: Thread-safe with memory barriers
recording_event = threading.Event()  # Proper synchronization
```

**Memory Semantics:**
- `set()` → Full memory barrier (all threads see update)
- `clear()` → Full memory barrier
- `is_set()` → Read with acquire semantics

---

### 2. threading.Lock (state_lock)

**Purpose:** Protect shared state modifications during toggle
**Type:** Mutual exclusion lock (mutex)

```python
state_lock: threading.Lock = threading.Lock()

def toggle_recording() -> None:
    global recording_event, recording_thread

    # Acquire lock (blocks if another thread holds it)
    with state_lock:
        if not recording_event.is_set():
            # START recording
            recording_event.set()
            # ... update icon, notifications ...
            if recording_thread is None or not recording_thread.is_alive():
                recording_thread = threading.Thread(target=recording_loop, daemon=True)
                recording_thread.start()
        else:
            # STOP recording
            recording_event.clear()
            # ... update icon, notifications ...
    # Lock automatically released here
```

**Why Lock Needed?**

**Without Lock (Race Condition):**
```python
# Thread A (keyboard listener)
if not recording_event.is_set():
    recording_event.set()  # ← Context switch here!
    # Thread B also sets recording_event
    recording_thread = Thread(...)  # Spawn thread 1
    recording_thread.start()

# Thread B (keyboard listener, rapid double-tap)
if not recording_event.is_set():  # ← Sees False (old value)
    recording_event.set()
    recording_thread = Thread(...)  # Spawn thread 2 (overwrites!)
    recording_thread.start()

# RESULT: Two recording threads running! Memory leak!
```

**With Lock (Safe):**
```python
with state_lock:  # Only one thread can execute this block
    if not recording_event.is_set():
        recording_event.set()
        recording_thread = Thread(...)
        recording_thread.start()
# RESULT: Atomic check-and-set, no race
```

---

### 3. threading.Lock (whisper_model_lock)

**Purpose:** Ensure single Whisper model instance (lazy initialization)
**Type:** Mutual exclusion lock (double-checked locking pattern)

```python
whisper_model_lock: threading.Lock = threading.Lock()

def get_whisper_model() -> Optional["WhisperModel"]:
    global whisper_model

    # Fast path: Model already loaded
    if whisper_model is not None:
        return whisper_model

    # Slow path: Load model (thread-safe)
    with whisper_model_lock:
        # Double-check (another thread may have loaded it)
        if whisper_model is None:
            whisper_model = WhisperModel("tiny", ...)

    return whisper_model
```

**Why Double-Checked Locking?**

**Without Double-Check:**
```python
# Every call acquires lock (even after model loaded)
with whisper_model_lock:  # ← Contention on every transcription!
    if whisper_model is None:
        whisper_model = WhisperModel(...)
```

**With Double-Check:**
```python
# Fast path: No lock if model already loaded
if whisper_model is not None:  # ← No contention
    return whisper_model

# Slow path: Lock only on first call
with whisper_model_lock:
    if whisper_model is None:  # ← Check again (another thread may have loaded)
        whisper_model = WhisperModel(...)
```

**Performance Impact:**
- **First call:** ~8 seconds (model load + lock overhead ~1ms)
- **Subsequent calls:** <1ms (no lock, direct return)

---

## Thread Lifecycle

### Startup Sequence

```
Main Thread Created (Python interpreter)
   ↓
main() function called
   ↓
load_icon_resources() - Load tray icons (main thread)
   ↓
Spawn Tray Thread:
   - threading.Thread(target=setup_tray, daemon=True)
   - tray_thread.start()
   - Tray thread enters icon.run() event loop
   ↓
Spawn Keyboard Listener:
   - keyboard.Listener(on_press=on_press, on_release=on_release)
   - keyboard_listener.start()
   - Background thread listens for keyboard events
   ↓
Main Thread Enters Infinite Loop:
   - while True: time.sleep(1)
   - Keeps app alive (daemon threads would exit if main exits)
```

**Timeline:**
- 0ms: Main thread starts
- 50ms: Icons loaded
- 100ms: Tray thread spawned
- 150ms: Keyboard listener spawned
- 200ms: App ready (system tray icon visible)

---

### Recording Start Sequence

```
User double-taps Left Alt
   ↓
Keyboard Listener Thread:
   - on_press() detects double-press
   - Calls toggle_recording()
   ↓
toggle_recording() (in keyboard listener thread):
   - Acquires state_lock
   - Checks recording_event.is_set() → False
   - recording_event.set() → State = RECORDING
   - Updates icon.icon = listening_icon_image
   - Shows notification (icon.notify)
   - Spawns recording thread:
       recording_thread = Thread(target=recording_loop, daemon=True)
       recording_thread.start()
   - Releases state_lock
   ↓
Recording Thread:
   - recording_loop() starts
   - Adjusts for ambient noise (0.2s)
   - Enters loop: while recording_event.is_set()
   - Captures audio (blocking I/O, 1s timeout)
   - Transcribes with Whisper/Google
   - Types into CLI window
   - Repeats until recording_event cleared
```

---

### Recording Stop Sequence

```
User double-taps Left Alt again
   ↓
Keyboard Listener Thread:
   - on_press() detects double-press
   - Calls toggle_recording()
   ↓
toggle_recording() (in keyboard listener thread):
   - Acquires state_lock
   - Checks recording_event.is_set() → True
   - recording_event.clear() → State = STOPPED
   - Updates icon.icon = idle_icon_image
   - Shows notification (icon.notify)
   - Releases state_lock
   ↓
Recording Thread:
   - Loop condition: while recording_event.is_set() → False
   - Exits loop
   - Logs "Recording loop ended"
   - Thread terminates (daemon, auto-cleanup)
```

**Thread Exit Time:**
- Recording thread exits within 1 second (timeout on `recognizer.listen()`)
- No explicit `join()` needed (daemon thread)

---

### Shutdown Sequence

```
User right-clicks tray → Quit
   ↓
Tray Thread (pystray event loop):
   - Menu callback: quit_program()
   ↓
quit_program() (in tray thread):
   - recording_event.clear() → Stop recording
   - if recording_thread.is_alive():
       recording_thread.join(timeout=1.0) → Wait for recording thread
   - icon.stop() → Stop tray thread event loop
   - os._exit(0) → Terminate process immediately
   ↓
OS:
   - All threads terminated (daemon + main)
   - Memory released (including Whisper model)
   - Process exit code: 0
```

**Timeline:**
- 0ms: quit_program() called
- 10ms: recording_event cleared
- 100-1000ms: Recording thread exits (join timeout)
- 1010ms: icon.stop() returns
- 1015ms: os._exit(0) → Process terminated

---

## Race Condition Prevention

### Race 1: Double-Toggle (Fixed in v1.2)

**Problem:**
```
User rapidly taps Left Alt 4 times (intending 2 double-taps)
   ↓
Press 1 & 2: Start recording (toggle 1)
Press 3 & 4: Stop recording (toggle 2) ← Should happen
BUT: Press 2 & 3: Accidental toggle 3 (flashing icon!)
```

**Solution: Cooldown Period**
```python
COOLDOWN_AFTER_TOGGLE = 0.8  # seconds
last_toggle_time = 0.0

def toggle_recording():
    global last_toggle_time

    current_time = time.time()
    if current_time - last_toggle_time < COOLDOWN_AFTER_TOGGLE:
        logging.debug("Ignoring toggle (cooldown period)")
        return  # Ignore rapid toggles

    last_toggle_time = current_time
    # ... proceed with toggle
```

---

### Race 2: Multiple Recording Threads

**Problem:**
```
Thread A: Check recording_thread.is_alive() → False
   ↓ Context switch!
Thread B: Check recording_thread.is_alive() → False
   ↓
Thread A: recording_thread = Thread(...); start()
Thread B: recording_thread = Thread(...); start()  # Overwrites!
   ↓
RESULT: Two threads running, but only one reference!
```

**Solution: State Lock**
```python
with state_lock:  # Atomic check-and-spawn
    if recording_thread is None or not recording_thread.is_alive():
        recording_thread = Thread(target=recording_loop, daemon=True)
        recording_thread.start()
```

---

### Race 3: Whisper Model Loading

**Problem:**
```
Thread A: if whisper_model is None:
   ↓ Context switch!
Thread B: if whisper_model is None:  # Sees None
   ↓
Thread A: whisper_model = WhisperModel(...)  # 8 seconds
Thread B: whisper_model = WhisperModel(...)  # Another 8 seconds! Overwrites!
```

**Solution: Double-Checked Locking**
```python
if whisper_model is not None:
    return whisper_model  # Fast path, no lock

with whisper_model_lock:
    if whisper_model is None:  # Double-check inside lock
        whisper_model = WhisperModel(...)  # Only one thread loads
return whisper_model
```

---

## Deadlock Prevention

**Potential Deadlock Scenario:**
```
Thread A: Acquires state_lock → Tries to acquire whisper_model_lock
Thread B: Acquires whisper_model_lock → Tries to acquire state_lock
   ↓
DEADLOCK: Both threads blocked forever!
```

**STT-CLI Solution: Lock Hierarchy**
```
state_lock (Level 1) → Used in toggle_recording()
whisper_model_lock (Level 2) → Used in get_whisper_model()

Rule: NEVER acquire state_lock while holding whisper_model_lock
```

**Code Verification:**
- `toggle_recording()` → Acquires state_lock → Does NOT call get_whisper_model()
- `recording_loop()` → Does NOT hold state_lock → Calls get_whisper_model() safely

**Result:** No circular wait → No deadlock possible.

---

## Thread Safety Analysis

### Thread-Safe Components

| Component | Thread-Safe? | Why? |
|-----------|--------------|------|
| `recording_event` | ✅ Yes | threading.Event with memory barriers |
| `state_lock` | ✅ Yes | threading.Lock (mutex) |
| `whisper_model_lock` | ✅ Yes | threading.Lock (mutex) |
| `pystray.Icon` methods | ✅ Yes | Library provides thread-safe API |
| `speech_recognition.Recognizer` | ✅ Yes | Each thread uses own instance (no sharing) |
| `pynput.Controller` | ⚠️ Partial | Safe for typing, but global state |

### Thread-Unsafe Components (Acceptable)

| Component | Thread-Unsafe? | Mitigation |
|-----------|----------------|------------|
| `last_press_time` | ❌ Yes (float write not atomic) | Only written by keyboard listener (single-threaded) |
| `last_toggle_time` | ❌ Yes (float write not atomic) | Only written by keyboard listener (single-threaded) |
| `recording_thread` | ❌ Yes (reference assignment not atomic) | Protected by state_lock |
| `icon` (global) | ❌ Yes (reference assignment not atomic) | Only assigned once in setup_tray() |

**Why Acceptable?**
- Variables only written by single thread (no concurrent writes)
- Protected by locks where necessary (recording_thread)
- Reads are safe (tearing impossible for pointer-sized values on x64)

---

## Related Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - System architecture overview
- [WHISPER_MODEL.md](./WHISPER_MODEL.md) - Model download, caching, lifecycle
- [STT-CLI-Architecture.drawio](./STT-CLI-Architecture.drawio) - Visual flow diagrams

---

**End of Threading Documentation**
