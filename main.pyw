# ====================================================
# STT-CLI
# Version: 1.0 
# Build Date: October 28, 2025
# Author: Mantej Singh Dhanjal
# ====================================================

import speech_recognition as sr
from pynput import keyboard
import time
import threading
import logging
import os
import sys
import win32gui
import win32process
import psutil
from pynput.keyboard import Controller
from PIL import Image
import pystray

# --- Logging ---
logging.basicConfig(filename='app.log', filemode='w', format='%(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)

# --- Configuration ---
HOTKEY = keyboard.Key.alt_l  # Left Alt key
DOUBLE_PRESS_INTERVAL = 0.3  # Seconds

# --- State ---
last_press_time = 0
is_recording = False
recording_thread = None
keyboard_controller = Controller()

def is_cli_window(hwnd):
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

def recording_loop():
    global is_recording
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.2)
        while is_recording:
            try:
                audio = recognizer.listen(source, timeout=1)
                transcription = recognizer.recognize_google(audio)
                if transcription:
                    hwnd = win32gui.GetForegroundWindow()
                    if is_cli_window(hwnd):
                        keyboard_controller.type(transcription + " ")
            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                logging.error(f"API Error: {e}")
            except Exception as e:
                logging.error(f"An unexpected error occurred: {e}")
                is_recording = False

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

icon = None

def setup_tray():
    global icon
    image = Image.open(resource_path("stt-cli2.ico"))
    menu = pystray.Menu(pystray.MenuItem("Quit", quit_program))
    icon = pystray.Icon("speech-to-text-cli", image, "Speech-to-Text CLI", menu)
    icon.run()

def toggle_recording():
    global is_recording, recording_thread, icon
    is_recording = not is_recording
    if is_recording:
        if recording_thread is None or not recording_thread.is_alive():
            logging.info("--- Recording Started ---")
            if icon:
                icon.icon = Image.open(resource_path("stt-cli2.png"))
            recording_thread = threading.Thread(target=recording_loop)
            recording_thread.daemon = True
            recording_thread.start()
    else:
        logging.info("--- Recording Stopped ---")
        if icon:
            icon.icon = Image.open(resource_path("stt-cli2.ico"))

def quit_program():
    global is_recording, icon
    logging.info("Exiting application...")
    if icon:
        icon.stop()
    is_recording = False
    os._exit(0)

def on_press(key):
    global last_press_time
    if key == HOTKEY:
        current_time = time.time()
        if current_time - last_press_time < DOUBLE_PRESS_INTERVAL:
            # Double press detected
            toggle_recording()
            # Reset last_press_time to prevent rapid toggling
            last_press_time = 0
        else:
            # Single press
            last_press_time = current_time

def on_release(key):
    if key == keyboard.Key.esc:
        quit_program()

def main():
    global icon
    tray_thread = threading.Thread(target=setup_tray)
    tray_thread.daemon = True
    tray_thread.start()

    # Start the keyboard listener in a separate thread
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        quit_program()

if __name__ == "__main__":
    main()