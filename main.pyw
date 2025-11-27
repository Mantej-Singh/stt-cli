# ====================================================
# STT-CLI
# Version: 2.0.0-beta
# Build Date: November 26, 2025
# Author: Mantej Singh Dhanjal
# Description: Hybrid Speech-to-Text with Whisper + Google
# ====================================================

__version__ = "2.0.0-beta"

import speech_recognition as sr
from pynput import keyboard
from pynput.keyboard import Controller, Key
import time
import threading
import logging
import os
import sys
import win32gui
import win32process
import psutil
from PIL import Image
import pystray
from typing import Optional, Literal, TYPE_CHECKING
import json
import win32com.client
import io
import numpy as np

# NEW: Whisper integration imports
if TYPE_CHECKING:
    from faster_whisper import WhisperModel

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    WhisperModel = None  # Define as None for runtime
    logging.warning("faster-whisper not installed. Only Google Web Speech API will be available.")

# --- Logging Configuration ---
# Create log directory in Windows TEMP folder to avoid permission issues
log_dir = os.path.join(os.getenv('TEMP', '.'), 'stt-cli')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'app.log')
logging.basicConfig(
    filename=log_file,
    filemode='w',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logging.info(f"STT-CLI started. Log file: {log_file}")

# --- Configuration ---
HOTKEY: Key = keyboard.Key.alt_l  # Left Alt key
DOUBLE_PRESS_INTERVAL: float = 0.3  # Seconds
COOLDOWN_AFTER_TOGGLE: float = 0.8  # Ignore Alt presses for 0.8s after successful toggle
NOTIFICATION_ENABLED: bool = True  # Show balloon tooltips on start/stop
NOTIFICATION_DURATION: float = 2.0  # Seconds to show notification

# --- Shared Resources (initialized once at startup) ---
keyboard_controller: Controller = Controller()
recognizer: sr.Recognizer = sr.Recognizer()
microphone: sr.Microphone = sr.Microphone()

# Cached image resources (loaded once, reused throughout app lifecycle)
idle_icon_image: Optional[Image.Image] = None
listening_icon_image: Optional[Image.Image] = None

# --- Thread-Safe State Management ---
recording_event: threading.Event = threading.Event()  # Replaces is_recording boolean
state_lock: threading.Lock = threading.Lock()  # Protects shared state modifications
last_press_time: float = 0
last_toggle_time: float = 0  # Track when last toggle occurred (for cooldown)
recording_thread: Optional[threading.Thread] = None
icon: Optional[pystray.Icon] = None

# --- NEW: Whisper Integration State ---
STTEngineType = Literal["whisper", "google", "auto"]
current_engine: STTEngineType = "whisper"  # Default to Whisper (offline-first)
whisper_model: Optional["WhisperModel"] = None  # String literal for type hint
whisper_model_lock: threading.Lock = threading.Lock()  # Protect model loading


def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for both dev and PyInstaller.

    Args:
        relative_path: Path relative to the script or bundle root

    Returns:
        Absolute path to the resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Running in normal Python environment
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def load_icon_resources() -> None:
    """
    Load and cache icon images at startup to avoid repeated file I/O.
    Prevents resource leaks from opening images on every state toggle.
    """
    global idle_icon_image, listening_icon_image

    try:
        idle_icon_image = Image.open(resource_path("stt-cli2.ico"))
        listening_icon_image = Image.open(resource_path("stt-cli2.png"))
        logging.info("Icon resources loaded successfully")
    except Exception as e:
        logging.error(f"Failed to load icon resources: {e}")
        # Fallback to None will be handled gracefully


def is_cli_window(hwnd: int) -> bool:
    """
    Check if the given window handle belongs to a CLI application.

    Args:
        hwnd: Windows window handle

    Returns:
        True if window is a recognized CLI (cmd, PowerShell, Windows Terminal)
    """
    if not hwnd:
        return False
    try:
        pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return False
        process = psutil.Process(pid[-1])
        process_name = process.name().lower()
        return process_name in ["cmd.exe", "powershell.exe", "windowsterminal.exe", "wt.exe"]
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


# ============================================================================
# WHISPER INTEGRATION
# ============================================================================

def get_whisper_model() -> Optional["WhisperModel"]:
    """
    Lazy-load Whisper model on first use.
    Uses tiny model with INT8 CPU optimization for maximum speed.
    Thread-safe with lock to prevent multiple simultaneous loads.

    Returns:
        WhisperModel instance, or None if Whisper is not available
    """
    global whisper_model

    if not WHISPER_AVAILABLE:
        return None

    if whisper_model is None:
        with whisper_model_lock:
            # Double-check after acquiring lock
            if whisper_model is None:
                try:
                    logging.info("Loading Whisper tiny model (first use, ~5-10s delay)...")

                    # Store models in AppData for persistence
                    model_cache = os.path.join(os.getenv('APPDATA', '.'), 'stt-cli', 'models')
                    os.makedirs(model_cache, exist_ok=True)

                    whisper_model = WhisperModel(
                        "tiny",  # 39M parameters, ~70MB download
                        device="cpu",
                        compute_type="int8",  # Fastest CPU inference with quantization
                        download_root=model_cache,
                        num_workers=1  # Single worker for lower memory usage
                    )

                    logging.info("Whisper model loaded successfully")

                except Exception as e:
                    logging.error(f"Failed to load Whisper model: {e}")
                    return None

    return whisper_model


def has_internet() -> bool:
    """
    Quick internet connectivity check.
    Tries to connect to Google DNS (8.8.8.8:53) with 2-second timeout.

    Returns:
        True if internet is available, False otherwise
    """
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False


def transcribe_with_whisper(audio: sr.AudioData) -> str:
    """
    Transcribe audio using Whisper model.
    Converts SpeechRecognition audio format to numpy array for Whisper.

    Speed optimizations:
    - beam_size=1: Greedy decoding (no beam search)
    - temperature=0.0: Deterministic output
    - language="en": Skip auto-detection
    - INT8 model: ~3x faster inference

    Args:
        audio: SpeechRecognition AudioData object

    Returns:
        Transcribed text, or empty string on error
    """
    try:
        model = get_whisper_model()
        if model is None:
            logging.error("Whisper model not available")
            return ""

        # Convert audio to WAV format (16-bit PCM)
        wav_data = audio.get_wav_data(
            convert_rate=16000,  # Whisper expects 16kHz
            convert_width=2       # 16-bit audio
        )

        # Convert bytes to numpy array
        audio_array = np.frombuffer(wav_data, dtype=np.int16).astype(np.float32) / 32768.0

        # Transcribe with speed-optimized settings
        segments, info = model.transcribe(
            audio_array,
            language="en",       # Force English (remove this line for auto-detect)
            beam_size=1,         # Greedy search (fastest)
            best_of=1,           # No sampling (fastest)
            temperature=0.0,     # Deterministic (fastest)
            vad_filter=False,    # Disable VAD (we handle silence detection elsewhere)
            word_timestamps=False # Disable word timestamps (faster)
        )

        # Collect transcription text from segments
        text = " ".join(segment.text for segment in segments).strip()

        return text

    except Exception as e:
        logging.error(f"Whisper transcription error: {e}", exc_info=True)
        return ""


def get_current_engine() -> STTEngineType:
    """
    Determine which STT engine to use based on settings and connectivity.

    Returns:
        "whisper" or "google" (never "auto" - auto is resolved here)
    """
    global current_engine

    if current_engine == "auto":
        # Auto-detect: prefer Google if online, fallback to Whisper
        if has_internet():
            return "google"
        else:
            return "whisper" if WHISPER_AVAILABLE else "google"

    return current_engine


# ============================================================================
# SETTINGS PERSISTENCE
# ============================================================================

def get_settings_path() -> str:
    """
    Get the path to settings.json file in %APPDATA%.

    Returns:
        Absolute path to settings.json
    """
    appdata = os.getenv('APPDATA', os.path.expanduser('~'))
    settings_dir = os.path.join(appdata, 'stt-cli')
    os.makedirs(settings_dir, exist_ok=True)
    return os.path.join(settings_dir, 'settings.json')


def load_settings() -> dict:
    """
    Load settings from JSON file.
    Creates default settings if file doesn't exist.

    Returns:
        Dictionary containing user settings
    """
    settings_path = get_settings_path()
    default_settings = {
        "auto_start": False,
        "first_run": True,
        "stt_engine": "whisper",  # NEW: "whisper" (offline-first), "google", or "auto"
        "whisper_model": "tiny",  # NEW: For future use (tiny, base, small)
        "version": __version__
    }

    try:
        if os.path.exists(settings_path):
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Merge with defaults in case new settings were added
                for key, value in default_settings.items():
                    if key not in settings:
                        settings[key] = value
                # Update version to current
                settings["version"] = __version__
                return settings
        else:
            # First run - create default settings
            logging.info("Creating default settings (first run)")
            save_settings(default_settings)
            return default_settings
    except Exception as e:
        logging.error(f"Failed to load settings: {e}")
        return default_settings


def save_settings(settings: dict) -> bool:
    """
    Save settings to JSON file.

    Args:
        settings: Dictionary containing settings to save

    Returns:
        True if successful, False otherwise
    """
    settings_path = get_settings_path()
    try:
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        logging.info(f"Settings saved to {settings_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")
        return False


def is_first_run() -> bool:
    """
    Check if this is the first time the app is running.

    Returns:
        True if first run, False otherwise
    """
    settings = load_settings()
    return settings.get("first_run", True)


# ============================================================================
# STARTUP SHORTCUT MANAGEMENT
# ============================================================================

def get_startup_folder() -> str:
    """
    Get the Windows Startup folder path for current user.

    Returns:
        Absolute path to user's Startup folder
    """
    appdata = os.getenv('APPDATA', os.path.expanduser('~'))
    startup_folder = os.path.join(
        appdata,
        'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'
    )
    return startup_folder


def get_exe_path() -> str:
    """
    Get the full path to the current executable or script.

    Returns:
        Absolute path to speech-to-text-cli.exe or main.pyw
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable (PyInstaller)
        return sys.executable
    else:
        # Running from Python source
        return os.path.abspath(__file__)


def get_shortcut_path() -> str:
    """
    Get the full path to the startup shortcut file.

    Returns:
        Absolute path to STT-CLI.lnk in Startup folder
    """
    return os.path.join(get_startup_folder(), 'STT-CLI.lnk')


def create_startup_shortcut() -> bool:
    """
    Create a shortcut in the Windows Startup folder.
    Uses Windows Script Host (WScript.Shell) COM interface.

    Returns:
        True if successful, False otherwise
    """
    try:
        shortcut_path = get_shortcut_path()
        target_path = get_exe_path()

        # Create WScript.Shell COM object
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(shortcut_path)

        # Configure shortcut properties
        shortcut.TargetPath = target_path
        shortcut.WorkingDirectory = os.path.dirname(target_path)
        shortcut.Description = "STT-CLI - Speech-to-Text for Command Line"
        shortcut.IconLocation = target_path  # Use exe's embedded icon

        # Save the shortcut
        shortcut.Save()

        logging.info(f"Startup shortcut created: {shortcut_path}")
        return True

    except Exception as e:
        logging.error(f"Failed to create startup shortcut: {e}")
        return False


def delete_startup_shortcut() -> bool:
    """
    Remove the shortcut from the Windows Startup folder.

    Returns:
        True if successful, False otherwise
    """
    try:
        shortcut_path = get_shortcut_path()

        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
            logging.info(f"Startup shortcut deleted: {shortcut_path}")
        else:
            logging.info("Startup shortcut does not exist (already deleted)")

        return True

    except Exception as e:
        logging.error(f"Failed to delete startup shortcut: {e}")
        return False


def is_startup_enabled() -> bool:
    """
    Check if the startup shortcut exists.

    Returns:
        True if shortcut exists, False otherwise
    """
    shortcut_path = get_shortcut_path()
    return os.path.exists(shortcut_path)


# ============================================================================
# RECORDING & SPEECH RECOGNITION
# ============================================================================

def recording_loop() -> None:
    """
    Main recording loop that continuously listens to microphone input
    and transcribes speech to the active CLI window.

    NEW: Hybrid engine support - uses Whisper or Google based on settings.
    Runs in a separate daemon thread.
    """
    global recognizer, microphone

    logging.info("Recording loop started")

    # Adjust for ambient noise once at the start of recording session
    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            logging.debug("Ambient noise adjustment completed")
    except Exception as e:
        logging.error(f"Failed to adjust for ambient noise: {e}")
        return

    # Main recording loop - continues until recording_event is cleared
    with microphone as source:
        while recording_event.is_set():
            try:
                # Listen for audio (timeout=1 to allow quick interruption)
                audio = recognizer.listen(source, timeout=1)

                # Determine which engine to use
                engine = get_current_engine()

                # Transcribe based on selected engine
                transcription = ""
                if engine == "whisper":
                    transcription = transcribe_with_whisper(audio)
                else:  # "google"
                    try:
                        transcription = recognizer.recognize_google(audio)
                    except sr.RequestError as e:
                        # Google API failed - fallback to Whisper if available
                        logging.warning(f"Google API error, falling back to Whisper: {e}")
                        if WHISPER_AVAILABLE:
                            transcription = transcribe_with_whisper(audio)

                if transcription:
                    logging.debug(f"[{engine.upper()}] Transcribed: {transcription}")

                    # Only type into CLI windows for security
                    hwnd = win32gui.GetForegroundWindow()
                    if is_cli_window(hwnd):
                        keyboard_controller.type(transcription + " ")
                    else:
                        logging.debug("Active window is not a CLI, skipping transcription")

            except sr.WaitTimeoutError:
                # No speech detected within timeout - this is normal
                pass
            except sr.UnknownValueError:
                # Speech was unintelligible - this is normal
                pass
            except sr.RequestError as e:
                logging.error(f"Google Speech API error: {e}")
                # Note: Fallback to Whisper is handled in the try block above
            except Exception as e:
                logging.error(f"Unexpected error in recording loop: {e}", exc_info=True)
                # Don't break loop on unexpected errors, let it continue

    logging.info("Recording loop ended")


def set_engine(engine: STTEngineType) -> None:
    """
    Change the speech-to-text engine and save to settings.
    Called when user selects an engine from the tray menu.

    Args:
        engine: The engine to use ("whisper", "google", or "auto")
    """
    global current_engine, icon

    current_engine = engine

    # Save to settings
    settings = load_settings()
    settings["stt_engine"] = engine
    save_settings(settings)

    logging.info(f"STT engine changed to: {engine}")

    # Show notification
    engine_names = {
        "whisper": "Whisper (Offline)",
        "google": "Google (Online)",
        "auto": "Auto-Detect (Smart)"
    }

    if icon and NOTIFICATION_ENABLED:
        icon.notify(
            title="Engine Changed",
            message=f"Now using: {engine_names.get(engine, engine)}"
        )

    # Update menu to reflect new state
    if icon:
        icon.update_menu()


def toggle_auto_start(icon_param: Optional[pystray.Icon], item: pystray.MenuItem) -> None:
    """
    Toggle the auto-start functionality.
    Called when user clicks "Start on Windows Boot" menu item.

    Args:
        icon_param: System tray icon (passed by pystray menu callback)
        item: The menu item that was clicked
    """
    global icon

    current_state = is_startup_enabled()

    if current_state:
        # Disable auto-start
        success = delete_startup_shortcut()
        if success:
            logging.info("Auto-start disabled by user")
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Auto-Start Disabled",
                    message="STT-CLI will no longer start automatically"
                )
            # Update settings
            settings = load_settings()
            settings["auto_start"] = False
            save_settings(settings)
        else:
            logging.error("Failed to disable auto-start")
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Auto-Start Error",
                    message="Failed to disable auto-start. Check logs for details."
                )
    else:
        # Enable auto-start
        success = create_startup_shortcut()
        if success:
            logging.info("Auto-start enabled by user")
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Auto-Start Enabled",
                    message="STT-CLI will now start automatically when Windows boots"
                )
            # Update settings
            settings = load_settings()
            settings["auto_start"] = True
            save_settings(settings)
        else:
            logging.error("Failed to enable auto-start")
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Auto-Start Error",
                    message="Failed to enable auto-start. Check permissions."
                )

    # Update menu to reflect new state
    if icon:
        icon.update_menu()


def setup_tray() -> None:
    """
    Initialize and run the system tray icon with enhanced menu.
    Runs in a separate daemon thread with engine selection submenu.
    """
    global icon

    if idle_icon_image is None:
        logging.error("Cannot setup tray: idle icon not loaded")
        return

    # UPDATED [2025-11-26]: Added nested submenu for engine selection
    # Create engine selection submenu with radio-button style checkmarks
    engine_menu = pystray.Menu(
        pystray.MenuItem(
            "Auto-Detect (Smart)",
            lambda: set_engine("auto"),
            checked=lambda item: current_engine == "auto"
        ),
        pystray.MenuItem(
            "Whisper (Offline)",
            lambda: set_engine("whisper"),
            checked=lambda item: current_engine == "whisper"
        ),
        pystray.MenuItem(
            "Google (Online)",
            lambda: set_engine("google"),
            checked=lambda item: current_engine == "google"
        )
    )

    # UPDATED [2025-11-26]: Added About menu item
    # Create main menu with engine submenu and about section
    menu = pystray.Menu(
        pystray.MenuItem(
            "🎙️ Engine",
            engine_menu  # Nested submenu
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Start on Windows Boot",
            toggle_auto_start,
            checked=lambda item: is_startup_enabled()  # Dynamic state check
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("About", show_about),
        pystray.MenuItem("Quit", quit_program)
    )

    icon = pystray.Icon("speech-to-text-cli", idle_icon_image, "Speech-to-Text CLI", menu)
    icon.run()


def toggle_recording() -> None:
    """
    Toggle recording state on/off.
    Called when user double-presses the hotkey (Left Alt by default).

    Shows balloon notification to provide visual feedback to user.
    Thread-safe: Uses event and lock to coordinate state changes.
    """
    global recording_thread, icon

    with state_lock:
        if recording_event.is_set():
            # Stop recording
            recording_event.clear()
            logging.info("--- Recording Stopped ---")

            # Update tray icon to idle state
            if icon and idle_icon_image:
                icon.icon = idle_icon_image

            # Show notification
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Recording Stopped",
                    message="Speech-to-text recording has stopped"
                )

        else:
            # Start recording
            recording_event.set()
            logging.info("--- Recording Started ---")

            # Update tray icon to listening state
            if icon and listening_icon_image:
                icon.icon = listening_icon_image

            # Show notification with engine info
            if icon and NOTIFICATION_ENABLED:
                engine_name = {
                    "whisper": "Whisper (Offline)",
                    "google": "Google (Online)",
                    "auto": "Auto-Detect"
                }.get(current_engine, current_engine)

                icon.notify(
                    title="Recording Started",
                    message=f"Using: {engine_name}\nDouble-tap Left Alt to stop"
                )

            # Start new recording thread if needed
            if recording_thread is None or not recording_thread.is_alive():
                recording_thread = threading.Thread(target=recording_loop, daemon=True)
                recording_thread.start()


def show_about(icon_param: Optional[pystray.Icon] = None) -> None:
    """
    Show About information in a notification.
    Displays version, author, and engine status.

    Args:
        icon_param: System tray icon (passed by pystray menu callback)
    """
    global icon

    # Get current engine info
    engine_name = {
        "whisper": "Whisper (Offline)",
        "google": "Google (Online)",
        "auto": "Auto-Detect"
    }.get(current_engine, current_engine)

    # Check Whisper availability
    whisper_status = "Available" if WHISPER_AVAILABLE else "Not Installed"

    if icon:
        icon.notify(
            title=f"STT-CLI v{__version__}",
            message=f"Speech-to-Text CLI\n"
                   f"Author: Mantej Singh Dhanjal\n"
                   f"\nCurrent Engine: {engine_name}\n"
                   f"Whisper: {whisper_status}\n"
                   f"\nGitHub: github.com/Mantej-Singh/stt-cli"
        )

    logging.info("Showed About notification")


def quit_program(icon_param: Optional[pystray.Icon] = None) -> None:
    """
    Gracefully shut down the application.
    Can be called from tray menu click or keyboard event.

    Args:
        icon_param: System tray icon (passed by pystray menu callback)
    """
    global icon

    logging.info("Exiting application...")

    # Stop recording gracefully
    recording_event.clear()

    # Give recording thread a moment to finish
    if recording_thread and recording_thread.is_alive():
        recording_thread.join(timeout=1.0)

    # Stop system tray icon
    if icon:
        icon.stop()

    os._exit(0)


def on_press(key: Key) -> None:
    """
    Keyboard event handler for key presses.
    Detects double-press of hotkey to toggle recording.

    Implements cooldown period after toggle to prevent accidental multi-toggles
    from rapid Alt key presses (e.g., quad-tapping triggers 2 toggles).

    Args:
        key: The key that was pressed
    """
    global last_press_time, last_toggle_time

    try:
        if key == HOTKEY:
            current_time = time.time()

            # Check if we're in cooldown period after a recent toggle
            if current_time - last_toggle_time < COOLDOWN_AFTER_TOGGLE:
                logging.debug(f"Ignoring Alt press during cooldown period")
                return

            if current_time - last_press_time < DOUBLE_PRESS_INTERVAL:
                # Double press detected - toggle recording
                toggle_recording()
                # Record toggle time for cooldown
                last_toggle_time = current_time
                # Reset to prevent rapid triple-press from toggling again
                last_press_time = 0
            else:
                # Single press - start the double-press timer
                last_press_time = current_time

    except Exception as e:
        logging.error(f"Error in on_press handler: {e}", exc_info=True)
        # Don't let exception kill the keyboard listener


def on_release(key: Key) -> Optional[bool]:
    """
    Keyboard event handler for key releases.

    ESC key provides a hidden quick-exit for debugging/development.
    In production, users should quit via system tray right-click menu.

    Note: ESC key may have side effects in the active window (e.g., clearing
    terminal) since we don't suppress key events.

    Args:
        key: The key that was released

    Returns:
        False to stop the listener, None to continue
    """
    try:
        if key == keyboard.Key.esc:
            logging.info("ESC key pressed - quitting application")
            quit_program()
            return False  # Stop listener

    except Exception as e:
        logging.error(f"Error in on_release handler: {e}", exc_info=True)
        # Don't let exception kill the keyboard listener


def show_welcome_notification() -> None:
    """
    Show first-run welcome notification to help new users get started.
    Called 2 seconds after app launch to ensure tray icon is ready.
    """
    global icon
    if icon and NOTIFICATION_ENABLED:
        icon.notify(
            title="STT-CLI is Running!",
            message="Double-tap Left Alt to start recording. Right-click tray icon for settings."
        )
        logging.info("First-run welcome notification shown")


def main() -> None:
    """
    Application entry point.
    Initializes all resources and starts background threads.
    """
    global icon, current_engine

    # Handle command-line arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--version", "-v"]:
            print(f"STT-CLI v{__version__}")
            print("Hybrid Speech-to-Text CLI for Windows")
            print("Engines: Whisper (offline) + Google Web Speech API")
            print("Author: Mantej Singh Dhanjal")
            print("License: MIT")
            print("GitHub: https://github.com/Mantej-Singh/stt-cli")
            sys.exit(0)
        elif arg in ["--help", "-h"]:
            print(f"STT-CLI v{__version__} - Hybrid Speech-to-Text CLI for Windows")
            print("\nUsage:")
            print("  speech-to-text-cli.exe        Start the application")
            print("  speech-to-text-cli.exe -v     Show version information")
            print("  speech-to-text-cli.exe -h     Show this help message")
            print("\nHotkey:")
            print("  Double-tap Left Alt           Toggle recording on/off")
            print("\nEngines:")
            print("  Whisper (offline) [default]   100% offline, works anywhere")
            print("  Google (online)               Cloud-based, requires internet")
            print("  Auto-Detect                   Smart selection based on connectivity")
            print("\nThe application runs in the system tray.")
            print("Right-click the tray icon to change engine or quit.")
            print(f"\nLogs are saved to: %TEMP%\\stt-cli\\app.log")
            sys.exit(0)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use --help for usage information")
            sys.exit(1)

    logging.info(f"=== STT-CLI v{__version__} Starting ===")

    # Load settings and initialize engine preference
    settings = load_settings()
    current_engine = settings.get("stt_engine", "whisper")  # Default to Whisper
    logging.info(f"STT Engine preference: {current_engine}")

    # Check Whisper availability
    if WHISPER_AVAILABLE:
        logging.info("faster-whisper is available (offline mode supported)")
    else:
        logging.warning("faster-whisper not installed - only Google Web Speech API available")

    # Load icon resources once at startup
    load_icon_resources()

    # Initialize audio resources once (reused throughout app lifecycle)
    # Note: recognizer and microphone are already initialized globally
    logging.info("Audio resources initialized")

    # Start system tray icon in daemon thread
    tray_thread = threading.Thread(target=setup_tray, daemon=True)
    tray_thread.start()

    # Start keyboard listener in separate thread
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    logging.info("All threads started, entering main loop")

    # Check for first run and show welcome notification
    if is_first_run():
        logging.info("First run detected, will show welcome notification")
        # Update settings to mark first run complete
        settings["first_run"] = False
        save_settings(settings)

        # Schedule welcome notification after 2 seconds to ensure tray icon is ready
        welcome_timer = threading.Timer(2.0, show_welcome_notification)
        welcome_timer.daemon = True
        welcome_timer.start()

    # Keep the main thread alive
    # This prevents the process from exiting while daemon threads run
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received")
        quit_program()


if __name__ == "__main__":
    main()
