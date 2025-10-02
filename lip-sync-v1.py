#!/usr/bin/env python3
import time
import numpy as np
import sounddevice as sd
import obsws_python as obs
import threading
import tkinter as tk
from tkinter import ttk
import json
import os

OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "your_obs_password_here"

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
SMOOTH_FACTOR = 0.2

mouth_state = 0.0

CONFIG_FILE = "lipsync_config.json"

SAMPLE_RATE = 48000
EQUALIZER_GAINS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

def load_config():
    global THRESHOLD, SAMPLE_RATE, EQUALIZER_GAINS
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                THRESHOLD = cfg.get("threshold", THRESHOLD)
                SAMPLE_RATE = cfg.get("sample_rate", SAMPLE_RATE)
                EQUALIZER_GAINS = cfg.get("equalizer_gains", EQUALIZER_GAINS)
        except Exception as e:
            print("Failed to load config:", e)

def save_config():
    cfg = {
        "threshold": THRESHOLD,
        "sample_rate": SAMPLE_RATE,
        "equalizer_gains": EQUALIZER_GAINS
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print("Failed to save config:", e)

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
            if scene != last_warned_scene:
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
        if open_item_id is None or closed_item_id is None or loud_item_id is None:
            if scene != last_warned_scene:
                last_warned_scene = scene
    except Exception as e:
        print("Failed to update scene items:", e)

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

def get_valid_samplerate(device=None, test_rates=[16000, 44100, 48000, 96000]):
    for rate in test_rates:
        try:
            sd.check_input_settings(device=device, samplerate=rate, channels=1)
            return rate
        except Exception:
            continue
    raise RuntimeError("No valid sample rate found for this device.")

def apply_equalizer(audio_data):
    global EQUALIZER_GAINS
    gains_linear = [10 ** (gain / 20.0) for gain in EQUALIZER_GAINS]
    avg_gain = np.mean(gains_linear)
    return audio_data * avg_gain

def audio_callback(indata, frames, time_info, status):
    global cooldown_counter, current_volume, mouth_state
    
    if status:
        print("Audio warning:", status)

    processed_audio = apply_equalizer(indata.copy())
    
    volume_norm = np.linalg.norm(processed_audio) / np.sqrt(len(processed_audio))
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
    global THRESHOLD, cooldown_counter, current_volume, SMOOTH_FACTOR, SAMPLE_RATE, EQUALIZER_GAINS

    root = tk.Tk()
    root.title("Lipsync Control")
    root.geometry("600x600")

    bg_color = "#2b2b2b"
    fg_color = "white"
    accent_color = "#61afef"
    trough_color = "#3c3f41"
    slider_color = "#61afef"
    root.configure(bg=bg_color)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=bg_color, foreground=fg_color)
    style.configure("TFrame", background=bg_color)
    style.configure("TLabelFrame", background=bg_color, foreground=fg_color, font=("Segoe UI", 11, "bold"))
    style.configure("TLabelFrame.Label", background=bg_color, foreground=fg_color)
    style.configure("TLabel", background=bg_color, foreground=fg_color, font=("Segoe UI", 11))
    style.configure("TCombobox", fieldbackground=bg_color, background=bg_color, foreground=fg_color)

    style.configure("Horizontal.TScale",
                   background=bg_color,
                   troughcolor=trough_color,
                   bordercolor=bg_color,
                   darkcolor=slider_color,
                   lightcolor=slider_color)

    style.configure("Horizontal.TProgressbar",
                    troughcolor=trough_color,
                    background=accent_color,
                    bordercolor=bg_color,
                    lightcolor=accent_color,
                    darkcolor=accent_color)

    main_frame = ttk.Frame(root)
    main_frame.pack(fill="both", expand=True, padx=10, pady=10)

    audio_settings = ttk.LabelFrame(main_frame, text="Audio Settings", padding=10)
    audio_settings.pack(fill="x", pady=5)

    ttk.Label(audio_settings, text="Sample Rate").pack(anchor="w")
    sample_rate_var = tk.StringVar(value=str(SAMPLE_RATE))
    sample_rate_combo = ttk.Combobox(audio_settings, textvariable=sample_rate_var, 
                                    values=["16000", "44100", "48000", "96000"])
    sample_rate_combo.pack(fill="x", pady=5)
    sample_rate_combo.bind('<<ComboboxSelected>>', lambda e: update_sample_rate())

    ttk.Label(audio_settings, text="Equalizer Bands", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10,5))
    
    eq_bands = []
    eq_frequencies = ["80Hz", "250Hz", "500Hz", "1kHz", "2kHz", "4kHz", "8kHz"]
    
    for i, freq in enumerate(eq_frequencies):
        eq_frame = ttk.Frame(audio_settings)
        eq_frame.pack(fill="x", pady=2)
        
        ttk.Label(eq_frame, text=freq, width=8).pack(side="left")
        eq_slider = ttk.Scale(eq_frame, from_=-12, to=12, orient="horizontal",
                             value=EQUALIZER_GAINS[i], command=lambda v, idx=i: update_equalizer(idx, float(v)),
                             style="Horizontal.TScale")
        eq_slider.pack(side="left", fill="x", expand=True)
        
        eq_value_label = ttk.Label(eq_frame, text=f"{EQUALIZER_GAINS[i]:.1f} dB", width=8)
        eq_value_label.pack(side="right")
        
        eq_bands.append({"slider": eq_slider, "label": eq_value_label})

    controls = ttk.LabelFrame(main_frame, text="Lipsync Controls", padding=10)
    controls.pack(fill="x", pady=5)

    ttk.Label(controls, text="Threshold").pack(anchor="w")
    threshold_slider = ttk.Scale(controls, from_=0.00001, to=0.01,
                                 value=THRESHOLD, command=lambda v: update_threshold(float(v)),
                                 style="Horizontal.TScale")
    threshold_slider.pack(fill="x", pady=5)

    ttk.Label(controls, text="Fade Speed").pack(anchor="w")
    fade_slider = ttk.Scale(controls, from_=0.01, to=1.0,
                            value=SMOOTH_FACTOR, command=lambda v: update_fade(float(v)),
                            style="Horizontal.TScale")
    fade_slider.pack(fill="x", pady=5)

    stats = ttk.LabelFrame(main_frame, text="Live Stats", padding=10)
    stats.pack(fill="x", pady=5)

    volume_label = ttk.Label(stats, text="Current Volume: 0.000000")
    volume_label.pack(anchor="w", pady=2)

    volume_bar = ttk.Progressbar(stats, orient="horizontal", mode="determinate",
                                 length=400, maximum=1.0, style="Horizontal.TProgressbar")
    volume_bar.pack(fill="x", pady=5)

    threshold_label = ttk.Label(stats, text=f"Threshold: {THRESHOLD}")
    threshold_label.pack(anchor="w")
    cooldown_label = ttk.Label(stats, text=f"Cooldown: {cooldown_counter}")
    cooldown_label.pack(anchor="w")
    fade_label = ttk.Label(stats, text=f"Fade Speed: {SMOOTH_FACTOR:.2f}")
    fade_label.pack(anchor="w")
    sample_rate_label = ttk.Label(stats, text=f"Sample Rate: {SAMPLE_RATE} Hz")
    sample_rate_label.pack(anchor="w")

    def update_threshold(value):
        global THRESHOLD
        THRESHOLD = value
        save_config()

    def update_fade(value):
        global SMOOTH_FACTOR
        SMOOTH_FACTOR = value

    def update_sample_rate():
        global SAMPLE_RATE
        try:
            new_rate = int(sample_rate_var.get())
            SAMPLE_RATE = new_rate
            sample_rate_label.config(text=f"Sample Rate: {new_rate} Hz")
            save_config()
        except ValueError:
            pass

    def update_equalizer(band_idx, value):
        global EQUALIZER_GAINS
        EQUALIZER_GAINS[band_idx] = value
        eq_bands[band_idx]["label"].config(text=f"{value:.1f} dB")
        save_config()

    def refresh_labels():
        volume_label.config(text=f"Current Volume: {current_volume:.6f}")
        volume_bar["value"] = min(current_volume, 1.0)
        threshold_label.config(text=f"Threshold: {THRESHOLD:.6f}")
        cooldown_label.config(text=f"Cooldown: {cooldown_counter}")
        fade_label.config(text=f"Fade Speed: {SMOOTH_FACTOR:.2f}")
        root.after(100, refresh_labels)

    refresh_labels()
    root.mainloop()

def main():
    global ws, device_index, closed_item_id, open_item_id, loud_item_id, SAMPLE_RATE

    load_config()

    try:
        ws = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
    except Exception as e:
        print("Failed to connect to OBS:", e)
        ws = None

    device_index = select_mic_device(MIC_DEVICE_NAME)

    try:
        samplerate = SAMPLE_RATE
        sd.check_input_settings(device=device_index, samplerate=samplerate, channels=1)
    except Exception as e:
        try:
            samplerate = get_valid_samplerate(device=device_index)
        except Exception as e2:
            print("No valid audio input:", e2)
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
