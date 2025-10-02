#!/usr/bin/env python3
import time
import numpy as np
import sounddevice as sd
import obsws_python as obs
import threading
import tkinter as tk
import json
import os

OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = ""

CLOSED_MOUTH_SOURCE = "Avatar_Closed"
OPEN_MOUTH_SOURCE = "Avatar_Open"
LOUD_MOUTH_SOURCE = "Avatar_Ahh"

THRESHOLD = 0.0005
MAX_COOLDOWN = 4
MIC_DEVICE_NAME = "Mic/Aux"

cooldown_counter = 0
ws = None
scene = None
open_item_id = None
closed_item_id = None
loud_item_id = None
device_index = None
last_warned_scene = None
current_volume = 0.0
VOLUME_MULTIPLIER = 1.0
SMOOTH_FACTOR = 0.2
mouth_state = 0.0

CONFIG_FILE = "lipsync_config.json"

def load_config():
    global THRESHOLD, VOLUME_MULTIPLIER
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                THRESHOLD = cfg.get("threshold", THRESHOLD)
                VOLUME_MULTIPLIER = cfg.get("multiplier", VOLUME_MULTIPLIER)
        except Exception:
            pass

def save_config():
    cfg = {"threshold": THRESHOLD, "multiplier": VOLUME_MULTIPLIER}
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def select_mic_device(name_substr=""):
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] > 0:
            if name_substr.lower() in dev['name'].lower():
                return i
    return None

def update_scene_items():
    global ws, scene, open_item_id, closed_item_id, loud_item_id, last_warned_scene
    open_item_id = None
    closed_item_id = None
    loud_item_id = None
    if ws is None:
        return
    try:
        scene_info = ws.get_current_program_scene()
        if scene_info is None:
            return
        scene = scene_info.current_program_scene_name
        scene_items_response = ws.get_scene_item_list(scene)
        if scene_items_response is None or not hasattr(scene_items_response, 'scene_items'):
            last_warned_scene = scene
            return
        scene_items = scene_items_response.scene_items
        for item in scene_items:
            if item['sourceName'] == OPEN_MOUTH_SOURCE:
                open_item_id = item['sceneItemId']
            elif item['sourceName'] == CLOSED_MOUTH_SOURCE:
                closed_item_id = item['sceneItemId']
            elif item['sourceName'] == LOUD_MOUTH_SOURCE:
                loud_item_id = item['sceneItemId']
    except Exception:
        pass

def toggle_mouth_smooth(state: float):
    global ws, scene, open_item_id, closed_item_id, loud_item_id
    if not ws or not scene:
        return
    try:
        if state >= 0.75 and loud_item_id:
            ws.set_scene_item_enabled(scene, loud_item_id, True)
            if open_item_id:
                ws.set_scene_item_enabled(scene, open_item_id, False)
            if closed_item_id:
                ws.set_scene_item_enabled(scene, closed_item_id, False)
        elif state >= 0.25 and open_item_id:
            ws.set_scene_item_enabled(scene, open_item_id, True)
            if loud_item_id:
                ws.set_scene_item_enabled(scene, loud_item_id, False)
            if closed_item_id:
                ws.set_scene_item_enabled(scene, closed_item_id, False)
        else:
            if open_item_id:
                ws.set_scene_item_enabled(scene, open_item_id, False)
            if loud_item_id:
                ws.set_scene_item_enabled(scene, loud_item_id, False)
            if closed_item_id:
                ws.set_scene_item_enabled(scene, closed_item_id, True)
    except Exception:
        pass

def get_valid_samplerate(device=None, test_rates=[16000, 44100, 48000]):
    for rate in test_rates:
        try:
            sd.check_input_settings(device=device, samplerate=rate, channels=1)
            return rate
        except Exception:
            continue
    raise RuntimeError("No valid sample rate found for this device.")

def audio_callback(indata, frames, time_info, status):
    global cooldown_counter, current_volume, mouth_state
    volume_norm = (np.linalg.norm(indata) / np.sqrt(len(indata))) * VOLUME_MULTIPLIER
    current_volume = volume_norm
    if volume_norm >= 0.1:
        target = 1.0
    elif volume_norm > THRESHOLD:
        target = 0.5
    else:
        target = 0.0
    mouth_state += (target - mouth_state) * SMOOTH_FACTOR
    toggle_mouth_smooth(mouth_state)

def start_gui():
    global THRESHOLD, VOLUME_MULTIPLIER, cooldown_counter, current_volume, SMOOTH_FACTOR

    root = tk.Tk()
    root.title("Lipsync Control")

    tk.Label(root, text="Threshold").pack()
    threshold_slider = tk.Scale(root, from_=0.00001, to=0.01, resolution=0.00001,
                                orient=tk.HORIZONTAL, length=400, command=lambda v: update_threshold(float(v)))
    threshold_slider.set(THRESHOLD)
    threshold_slider.pack()

    tk.Label(root, text="Volume Multiplier").pack()
    multiplier_slider = tk.Scale(root, from_=0.1, to=100, resolution=0.1,
                                 orient=tk.HORIZONTAL, length=400, command=lambda v: update_multiplier(float(v)))
    multiplier_slider.set(VOLUME_MULTIPLIER)
    multiplier_slider.pack()

    tk.Label(root, text="Fade Speed").pack()
    fade_slider = tk.Scale(root, from_=0.01, to=1.0, resolution=0.01,
                           orient=tk.HORIZONTAL, length=400, command=lambda v: update_fade(float(v)))
    fade_slider.set(SMOOTH_FACTOR)
    fade_slider.pack()

    volume_label = tk.Label(root, text=f"Current Volume: {current_volume:.6f}")
    volume_label.pack()
    threshold_label = tk.Label(root, text=f"Threshold: {THRESHOLD}")
    threshold_label.pack()
    multiplier_label = tk.Label(root, text=f"Multiplier: {VOLUME_MULTIPLIER}")
    multiplier_label.pack()
    cooldown_label = tk.Label(root, text=f"Cooldown: {cooldown_counter}")
    cooldown_label.pack()
    fade_label = tk.Label(root, text=f"Fade Speed: {SMOOTH_FACTOR:.2f}")
    fade_label.pack()

    def update_threshold(value):
        global THRESHOLD
        THRESHOLD = value
        save_config()

    def update_multiplier(value):
        global VOLUME_MULTIPLIER
        VOLUME_MULTIPLIER = value
        save_config()

    def update_fade(value):
        global SMOOTH_FACTOR
        SMOOTH_FACTOR = value

    def refresh_labels():
        volume_label.config(text=f"Current Volume: {current_volume:.6f}")
        threshold_label.config(text=f"Threshold: {THRESHOLD}")
        multiplier_label.config(text=f"Multiplier: {VOLUME_MULTIPLIER}")
        cooldown_label.config(text=f"Cooldown: {cooldown_counter}")
        fade_label.config(text=f"Fade Speed: {SMOOTH_FACTOR:.2f}")
        root.after(100, refresh_labels)

    refresh_labels()
    root.mainloop()

def main():
    global ws, device_index, closed_item_id, open_item_id, loud_item_id
    load_config()
    try:
        ws = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
    except Exception:
        ws = None

    device_index = select_mic_device(MIC_DEVICE_NAME)
    try:
        samplerate = get_valid_samplerate(device=device_index)
    except Exception:
        return

    update_scene_items()
    if closed_item_id:
        ws.set_scene_item_enabled(scene, closed_item_id, True)
    if open_item_id:
        ws.set_scene_item_enabled(scene, open_item_id, False)
    if loud_item_id:
        ws.set_scene_item_enabled(scene, loud_item_id, False)

    threading.Thread(target=start_gui, daemon=True).start()

    with sd.InputStream(callback=audio_callback, channels=1,
                        samplerate=samplerate, device=device_index):
        try:
            while True:
                if ws is not None:
                    try:
                        update_scene_items()
                    except Exception:
                        try:
                            ws = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
                            update_scene_items()
                        except Exception:
                            ws = None
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            if ws is not None:
                try:
                    ws.disconnect()
                except Exception:
                    pass

if __name__ == "__main__":
    main()
