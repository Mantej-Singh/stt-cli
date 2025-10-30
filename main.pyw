# ====================================================
# STT-CLI
# Version: 1.3.1
# Build Date: October 30, 2025
# Author: Mantej Singh Dhanjal
# ====================================================

__version__ = "1.3.1"

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
from typing import Optional

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


def recording_loop() -> None:
    """
    Main recording loop that continuously listens to microphone input
    and transcribes speech to the active CLI window.

    Uses Google Web Speech API via SpeechRecognition library.
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
                audio = recognizer.listen(source, timeout=1)
                transcription = recognizer.recognize_google(audio)

                if transcription:
                    logging.debug(f"Transcribed: {transcription}")

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
            except Exception as e:
                logging.error(f"Unexpected error in recording loop: {e}")
                # Don't break loop on unexpected errors, let it continue

    logging.info("Recording loop ended")


def setup_tray() -> None:
    """
    Initialize and run the system tray icon with menu.
    Runs in a separate daemon thread.
    """
    global icon

    if idle_icon_image is None:
        logging.error("Cannot setup tray: idle icon not loaded")
        return

    menu = pystray.Menu(pystray.MenuItem("Quit", quit_program))
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

            # Show notification
            if icon and NOTIFICATION_ENABLED:
                icon.notify(
                    title="Recording Started",
                    message="Double-tap Left Alt to stop recording"
                )

            # Start new recording thread if needed
            if recording_thread is None or not recording_thread.is_alive():
                recording_thread = threading.Thread(target=recording_loop, daemon=True)
                recording_thread.start()


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


def main() -> None:
    """
    Application entry point.
    Initializes all resources and starts background threads.
    """
    global icon

    # Handle command-line arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--version", "-v"]:
            print(f"STT-CLI v{__version__}")
            print("Speech-to-Text CLI for Windows")
            print("Author: Mantej Singh Dhanjal")
            print("License: MIT")
            print("GitHub: https://github.com/Mantej-Singh/stt-cli")
            sys.exit(0)
        elif arg in ["--help", "-h"]:
            print(f"STT-CLI v{__version__} - Speech-to-Text CLI for Windows")
            print("\nUsage:")
            print("  speech-to-text-cli.exe        Start the application")
            print("  speech-to-text-cli.exe -v     Show version information")
            print("  speech-to-text-cli.exe -h     Show this help message")
            print("\nHotkey:")
            print("  Double-tap Left Alt           Toggle recording on/off")
            print("\nThe application runs in the system tray.")
            print("Right-click the tray icon to quit.")
            print(f"\nLogs are saved to: %TEMP%\\stt-cli\\app.log")
            sys.exit(0)
        else:
            print(f"Unknown argument: {sys.argv[1]}")
            print("Use --help for usage information")
            sys.exit(1)

    logging.info(f"=== STT-CLI v{__version__} Starting ===")

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
