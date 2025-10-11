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
import math
import sys
from typing import Optional, Tuple, List, Dict

OBS_HOST = "localhost"
OBS_PORT = 4455
OBS_PASSWORD = "OBS_Password"

CLOSED_MOUTH_SOURCE = "Avatar_Closed"
OPEN_MOUTH_SOURCE = "Avatar_Open"
AVATAR_BASE_SOURCE = "Avatar_Base"

THRESHOLD = 0.0005
MIC_DEVICE_NAME = "Mic/Aux"

ws = None
scene = None
stream = None
stream_active = False
lipsync_running = False
open_item_id = None
closed_item_id = None
base_item_id = None
device_index = None
last_warned_scene = None
current_volume = 0.0
VOLUME_MULTIPLIER = 1.0
SMOOTH_FACTOR = 0.2
mouth_state = 0.0
CONFIG_FILE = "lipsync_config.json"
SAMPLE_RATE = 48000
EQUALIZER_GAINS = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
LIPSYNC_ENABLED = True
BOBBING_ENABLED = True
BOBBING_INTENSITY = 5.0
bobbing_phase = 0.0
_original_positions = {}

available_mics = []
available_scenes = []
available_sources = []
current_mic_device = None
current_mic_name = None
selected_closed_source = CLOSED_MOUTH_SOURCE
selected_open_source = OPEN_MOUTH_SOURCE
selected_base_source = AVATAR_BASE_SOURCE
ui_warnings = []

def load_config():
    global THRESHOLD, VOLUME_MULTIPLIER, SAMPLE_RATE, EQUALIZER_GAINS, LIPSYNC_ENABLED, BOBBING_ENABLED, BOBBING_INTENSITY
    global selected_closed_source, selected_open_source, selected_base_source, current_mic_device, current_mic_name
    if not os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
            THRESHOLD = cfg.get("threshold", THRESHOLD)
            VOLUME_MULTIPLIER = cfg.get("multiplier", VOLUME_MULTIPLIER)
            SAMPLE_RATE = cfg.get("sample_rate", SAMPLE_RATE)
            EQUALIZER_GAINS = cfg.get("equalizer_gains", EQUALIZER_GAINS)
            LIPSYNC_ENABLED = cfg.get("lipsync_enabled", LIPSYNC_ENABLED)
            BOBBING_ENABLED = cfg.get("bobbing_enabled", BOBBING_ENABLED)
            BOBBING_INTENSITY = cfg.get("bobbing_intensity", BOBBING_INTENSITY)
            selected_closed_source = cfg.get("closed_source", CLOSED_MOUTH_SOURCE)
            selected_open_source = cfg.get("open_source", OPEN_MOUTH_SOURCE)
            selected_base_source = cfg.get("base_source", AVATAR_BASE_SOURCE)
            current_mic_name = cfg.get("mic_device_name", None)
            if current_mic_name:
                try:
                    current_mic_device = find_mic_by_name(current_mic_name)
                except Exception:
                    current_mic_device = None
    except Exception as e:
        print(f"Config load error: {e}")

def save_config():
    cfg = {
        "threshold": THRESHOLD,
        "multiplier": VOLUME_MULTIPLIER,
        "sample_rate": SAMPLE_RATE,
        "equalizer_gains": EQUALIZER_GAINS,
        "lipsync_enabled": LIPSYNC_ENABLED,
        "bobbing_enabled": BOBBING_ENABLED,
        "bobbing_intensity": BOBBING_INTENSITY,
        "closed_source": selected_closed_source,
        "open_source": selected_open_source,
        "base_source": selected_base_source,
        "mic_device_name": current_mic_name
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Config save error: {e}")

def find_mic_by_name(name: str) -> Optional[int]:
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0 and name.lower() in dev['name'].lower():
                return i
    except Exception as e:
        print(f"Error finding mic by name: {e}")
    return None

def add_warning(message: str):
    global ui_warnings
    if message not in ui_warnings:
        ui_warnings.append(message)
        print(f"WARNING: {message}")
        if len(ui_warnings) > 50:
            ui_warnings.pop(0)

def clear_warnings():
    global ui_warnings
    ui_warnings = []

def get_audio_devices() -> List[Tuple[int, str]]:
    global available_mics
    available_mics = []
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                available_mics.append((i, dev['name']))
        print(f"Found {len(available_mics)} audio input devices")
    except Exception as e:
        add_warning(f"Error getting audio devices: {e}")
    return available_mics

def get_obs_scenes() -> List[str]:
    global available_scenes, ws
    available_scenes = []
    if not ws:
        return available_scenes
    try:
        scenes = ws.get_scene_list()
        if hasattr(scenes, 'scenes'):
            for s in scenes.scenes:
                name = getattr(s, 'sceneName', getattr(s, 'name', None))
                if name:
                    available_scenes.append(name)
        elif isinstance(scenes, dict):
            for s in scenes.get('scenes', []):
                name = s.get('sceneName') or s.get('name')
                if name:
                    available_scenes.append(name)
    except Exception as e:
        add_warning(f"Error getting OBS scenes: {e}")
    return available_scenes

def _normalize_scene_name(value) -> str:
    if isinstance(value, str):
        return value
    
    attributes = ["scene_name", "sceneName", "current_program_scene_name", "currentSceneName"]
    if hasattr(value, "__dict__"):
        for attr in attributes:
            v = getattr(value, attr, None)
            if isinstance(v, str):
                return v
    
    if isinstance(value, dict):
        for key in attributes:
            v = value.get(key)
            if isinstance(v, str):
                return v
    
    return str(value)

def _ensure_scene_name(scene_candidate=None, fallback_scene: str = "test avatar") -> str:
    global ws, scene
    
    if isinstance(scene_candidate, str) and scene_candidate:
        return scene_candidate
    
    try:
        if scene_candidate is not None:
            name = _normalize_scene_name(scene_candidate)
            if isinstance(name, str) and name:
                return name
    except Exception:
        pass
    
    try:
        if isinstance(scene, str) and scene:
            return scene
        if ws is not None:
            try:
                resp = ws.get_current_program_scene()
                name = _normalize_scene_name(resp)
                if isinstance(name, str) and name:
                    return name
            except Exception:
                try:
                    resp = ws.get_current_scene()
                    name = _normalize_scene_name(resp)
                    if isinstance(name, str) and name:
                        return name
                except Exception:
                    pass
    except Exception:
        pass
    
    return fallback_scene

def safe_get_scene_item_list(scene_candidate=None):
    global ws
    scene_name = _ensure_scene_name(scene_candidate)
    if ws is None:
        add_warning("OBS not connected (get_scene_item_list)")
        return []
    try:
        return ws.get_scene_item_list(scene_name)
    except Exception as e:
        add_warning(f"Could not get scene item list for scene '{scene_name}': {e}")
        return None

def safe_get_scene_item_transform(scene_candidate, item_id: int):
    global ws
    scene_name = _ensure_scene_name(scene_candidate)
    if ws is None:
        add_warning("OBS not connected (get_scene_item_transform)")
        return None
    try:
        return ws.get_scene_item_transform(scene_name, item_id)
    except Exception as e:
        add_warning(f"Could not get scene item transform for scene '{scene_name}', item '{item_id}': {e}")
        return None

def safe_set_scene_item_enabled(scene_candidate, item_id: int, enabled: bool) -> bool:
    global ws
    if item_id is None:
        return False
    scene_name = _ensure_scene_name(scene_candidate)
    if ws is None:
        add_warning("OBS not connected (set_scene_item_enabled)")
        return False
    try:
        ws.set_scene_item_enabled(scene_name, item_id, enabled)
        return True
    except Exception as e:
        add_warning(f"Could not set scene item enabled for scene '{scene_name}', item '{item_id}': {e}")
        return False

def safe_set_scene_item_transform(scene_candidate, item_id: int, transform) -> bool:
    global ws
    if item_id is None:
        return False
    scene_name = _ensure_scene_name(scene_candidate)
    if ws is None:
        add_warning("OBS not connected (set_scene_item_transform)")
        return False
    try:
        ws.set_scene_item_transform(scene_name, item_id, transform)
        return True
    except Exception as e:
        add_warning(f"Could not set scene item transform for scene '{scene_name}', item '{item_id}': {e}")
        return False

def get_obs_sources() -> List[str]:
    global available_sources, ws, scene
    available_sources = []
    if not ws:
        return available_sources

    scene_name = _normalize_scene_name(scene)
    if not isinstance(scene_name, str) or not scene_name:
        try:
            update_scene_items()
            scene_name = _normalize_scene_name(scene)
        except Exception:
            return available_sources

    try:
        scene_items_resp = safe_get_scene_item_list(scene_name)
        items = []
        if scene_items_resp is None:
            return available_sources
        if hasattr(scene_items_resp, 'scene_items'):
            items = scene_items_resp.scene_items
        elif isinstance(scene_items_resp, dict):
            items = scene_items_resp.get('sceneItems') or scene_items_resp.get('scene_items') or []
        
        for item in items:
            if isinstance(item, dict):
                name = item.get('sourceName') or item.get('source_name') or item.get('name')
            else:
                name = getattr(item, 'sourceName', getattr(item, 'source_name', getattr(item, 'name', None)))
            if name:
                available_sources.append(name)
    except Exception as e:
        add_warning(f"Error getting OBS sources: {e}")
    return available_sources

def _extract_transform(transform_resp):
    if transform_resp is None:
        return None
    if hasattr(transform_resp, 'scene_item_transform'):
        return transform_resp.scene_item_transform
    if isinstance(transform_resp, dict):
        return (transform_resp.get('scene_item_transform') or 
                transform_resp.get('sceneItemTransform') or 
                transform_resp)
    for name in ('sceneItemTransform', 'scene_item_transform'):
        if hasattr(transform_resp, name):
            return getattr(transform_resp, name)
    return None

def update_scene_items():
    global ws, scene, open_item_id, closed_item_id, base_item_id, last_warned_scene
    open_item_id = closed_item_id = base_item_id = None
    
    if ws is None:
        add_warning("OBS WebSocket not connected")
        return
    
    try:
        scene_name = None
        try:
            scene_resp = ws.get_current_program_scene()
            scene_name = _normalize_scene_name(scene_resp)
        except Exception:
            try:
                scene_resp = ws.get_current_scene()
                scene_name = _normalize_scene_name(scene_resp)
            except Exception:
                scene_name = None

        if not scene_name:
            if scene != last_warned_scene:
                add_warning("Could not get current scene from OBS")
                last_warned_scene = scene
            return

        scene = scene_name

        scene_items_resp = safe_get_scene_item_list(scene_name)
        items = []
        
        if hasattr(scene_items_resp, 'scene_items'):
            items = scene_items_resp.scene_items
        elif isinstance(scene_items_resp, dict):
            items = scene_items_resp.get('sceneItems') or scene_items_resp.get('scene_items') or []
        elif isinstance(scene_items_resp, list):
            items = scene_items_resp

        for item in items:
            if isinstance(item, dict):
                src_name = item.get('sourceName') or item.get('source_name') or item.get('name')
                sid = item.get('sceneItemId') or item.get('scene_item_id') or item.get('id')
            else:
                src_name = getattr(item, 'sourceName', getattr(item, 'source_name', getattr(item, 'name', None)))
                sid = getattr(item, 'sceneItemId', getattr(item, 'scene_item_id', getattr(item, 'id', None)))
            
            if src_name == selected_open_source:
                open_item_id = sid
            elif src_name == selected_closed_source:
                closed_item_id = sid
            elif src_name == selected_base_source:
                base_item_id = sid

        if not any([open_item_id, closed_item_id]):
            add_warning(f"Could not find mouth sources in scene: {scene}")
            
    except Exception as e:
        add_warning(f"Failed to update scene items: {e}")

def update_bobbing_motion():
    global ws, scene, base_item_id, open_item_id, closed_item_id, bobbing_phase, mouth_state, _original_positions
    
    if not ws or not scene or not BOBBING_ENABLED:
        return
    
    try:
        bobbing_phase += 0.3
        offset = math.sin(bobbing_phase) * BOBBING_INTENSITY * mouth_state

        items = [base_item_id, open_item_id, closed_item_id]
        
        for item_id in items:
            if not item_id:
                continue
            
            try:
                key = f"{scene}:{item_id}"
                transform_resp = safe_get_scene_item_transform(scene, item_id)
                transform = _extract_transform(transform_resp)
                
                if not transform:
                    continue

                def tget(o, name, default=0):
                    if o is None:
                        return default
                    if isinstance(o, dict):
                        return o.get(name, default)
                    return getattr(o, name, default)

                def tset(o, name, value):
                    if isinstance(o, dict):
                        o[name] = value
                    else:
                        try:
                            setattr(o, name, value)
                        except Exception:
                            pass

                if key not in _original_positions:
                    _original_positions[key] = tget(transform, 'positionY', 0)

                orig_y = _original_positions[key]

                if isinstance(transform, dict):
                    transform = transform.copy()
                    if transform.get('boundsWidth', 0) < 1.0:
                        transform['boundsWidth'] = max(transform.get('boundsWidth', 1.0), 1.0)
                    if transform.get('boundsHeight', 0) < 1.0:
                        transform['boundsHeight'] = max(transform.get('boundsHeight', 1.0), 1.0)
                    transform['positionY'] = orig_y + offset
                    safe_set_scene_item_transform(scene, item_id, transform)
                else:
                    if tget(transform, 'boundsWidth', 0) < 1.0:
                        tset(transform, 'boundsWidth', max(tget(transform, 'boundsWidth', 1.0), 1.0))
                    if tget(transform, 'boundsHeight', 0) < 1.0:
                        tset(transform, 'boundsHeight', max(tget(transform, 'boundsHeight', 1.0), 1.0))
                    tset(transform, 'positionY', orig_y + offset)
                    safe_set_scene_item_transform(scene, item_id, transform)
                    
            except Exception:
                continue
    except Exception:
        pass

def apply_equalizer(audio_data: np.ndarray) -> np.ndarray:
    try:
        gains_linear = [10 ** (gain / 20.0) for gain in EQUALIZER_GAINS]
        avg_gain = np.mean(gains_linear) if gains_linear else 1.0
        return audio_data * avg_gain
    except Exception:
        return audio_data

def audio_callback(indata, frames, time_info, status):
    global current_volume, mouth_state
    
    if not lipsync_running or not stream_active:
        return
    
    if status:
        add_warning(f"Audio warning: {status}")
    
    try:
        processed_audio = apply_equalizer(indata.copy())
        flat = processed_audio.ravel()
        
        if flat.size == 0:
            return
        
        volume_norm = (np.linalg.norm(flat) / math.sqrt(flat.size)) * VOLUME_MULTIPLIER
        
        if not isinstance(volume_norm, (int, float)) or math.isnan(volume_norm) or math.isinf(volume_norm):
            volume_norm = 0.0
        
        volume_norm = min(volume_norm, 10.0)
        current_volume = min(1.0, max(0.0, float(volume_norm)))

        target = 1.0 if volume_norm > THRESHOLD else 0.0
        mouth_state += (target - mouth_state) * SMOOTH_FACTOR
        
        toggle_mouth_smooth(mouth_state)
        
        if BOBBING_ENABLED:
            update_bobbing_motion()
            
    except Exception as e:
        add_warning(f"Audio callback error: {e}")

def start_gui():
    global THRESHOLD, VOLUME_MULTIPLIER, SMOOTH_FACTOR, SAMPLE_RATE, EQUALIZER_GAINS
    global LIPSYNC_ENABLED, BOBBING_ENABLED, BOBBING_INTENSITY
    global selected_closed_source, selected_open_source, selected_base_source

    root = tk.Tk()
    root.title("🎙️ Lipsync Control")
    root.geometry("700x800")
    root.minsize(520, 480)

    bg_color = "#2b2b2b"
    fg_color = "white"
    accent_color = "#61afef"
    trough_color = "#3c3f41"
    warning_color = "#e06c75"
    root.configure(bg=bg_color)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    
    style.configure(".", background=bg_color, foreground=fg_color)
    style.configure("TFrame", background=bg_color)
    style.configure("TLabelFrame", background=bg_color, foreground=fg_color, font=("Segoe UI", 11, "bold"))
    style.configure("TLabelFrame.Label", background=bg_color, foreground=fg_color)
    style.configure("TLabel", background=bg_color, foreground=fg_color, font=("Segoe UI", 11))
    style.configure("TButton", background=accent_color, foreground=fg_color, font=("Segoe UI", 10))
    style.configure("Horizontal.TScale", background=bg_color, troughcolor=trough_color, 
                   bordercolor=bg_color, darkcolor=accent_color, lightcolor=accent_color)
    style.configure("Horizontal.TProgressbar", troughcolor=trough_color, background=accent_color, 
                   bordercolor=bg_color, lightcolor=accent_color, darkcolor=accent_color)
    style.configure("TCombobox", fieldbackground=bg_color, background=bg_color, foreground=fg_color)
    style.map("TCombobox",
              fieldbackground=[('readonly', bg_color), ('!readonly', bg_color)],
              background=[('readonly', bg_color), ('!readonly', bg_color)],
              foreground=[('readonly', fg_color), ('!readonly', fg_color)])

    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)

    canvas = tk.Canvas(container, bg=bg_color, highlightthickness=0)
    vsb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)

    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    main_frame = ttk.Frame(canvas)
    main_frame_id = canvas.create_window((0, 0), window=main_frame, anchor="nw")

    def on_frame_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
    main_frame.bind("<Configure>", on_frame_configure)

    def on_canvas_configure(event):
        canvas.itemconfigure(main_frame_id, width=event.width)
    canvas.bind("<Configure>", on_canvas_configure)

    def on_mousewheel(event):
        delta = 0
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        elif hasattr(event, 'delta'):
            delta = -1 * int(event.delta / 120)
        canvas.yview_scroll(delta, "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)
    canvas.bind_all("<Button-4>", on_mousewheel)
    canvas.bind_all("<Button-5>", on_mousewheel)

    device_frame = ttk.LabelFrame(main_frame, text="Device Configuration", padding=10)
    device_frame.pack(fill="x", pady=5)

    ttk.Label(device_frame, text="Microphone").pack(anchor="w")
    mic_var = tk.StringVar()
    mic_combo = ttk.Combobox(device_frame, textvariable=mic_var, state="readonly")
    mic_combo.pack(fill="x", pady=5)

    def refresh_mics():
        global current_mic_name
        mics = get_audio_devices()
        mic_combo['values'] = [name for _, name in mics]
        
        if current_mic_name and mics:
            for idx, name in mics:
                if name == current_mic_name:
                    mic_var.set(name)
                    break
            else:
                if mics:
                    mic_var.set(mics[0][1])
                    select_mic_device(dev_index=mics[0][0])
        elif mics:
            mic_var.set(mics[0][1])
            select_mic_device(dev_index=mics[0][0])
        else:
            mic_var.set("No input devices")

    def on_mic_select(event):
        selected_name = mic_var.get()
        for idx, name in available_mics:
            if name == selected_name:
                select_mic_device(dev_index=idx)
                print(f"Selected microphone: {name} (index {idx})")
                break

    mic_combo.bind('<<ComboboxSelected>>', on_mic_select)
    ttk.Button(device_frame, text="Refresh Microphones", command=refresh_mics).pack(pady=5)
    
    control_button_frame = ttk.Frame(device_frame)
    control_button_frame.pack(fill="x", pady=5)
    
    start_button = ttk.Button(control_button_frame, text="▶ Start Lipsync", command=lambda: start_lipsync())
    start_button.pack(side="left", padx=5, fill="x", expand=True)
    
    stop_button = ttk.Button(control_button_frame, text="⏸ Stop Lipsync", command=lambda: stop_lipsync(), state="disabled")
    stop_button.pack(side="left", padx=5, fill="x", expand=True)
    
    status_label = ttk.Label(device_frame, text="Status: Stopped", font=("Segoe UI", 10, "bold"))
    status_label.pack(pady=5)
    
    refresh_mics()

    source_frame = ttk.LabelFrame(main_frame, text="Source Configuration", padding=10)
    source_frame.pack(fill="x", pady=5)

    ttk.Label(source_frame, text="Closed Mouth Source").pack(anchor="w")
    closed_source_var = tk.StringVar(value=selected_closed_source)
    closed_source_combo = ttk.Combobox(source_frame, textvariable=closed_source_var, state="normal")
    closed_source_combo.pack(fill="x", pady=2)

    ttk.Label(source_frame, text="Open Mouth Source").pack(anchor="w")
    open_source_var = tk.StringVar(value=selected_open_source)
    open_source_combo = ttk.Combobox(source_frame, textvariable=open_source_var, state="normal")
    open_source_combo.pack(fill="x", pady=2)

    ttk.Label(source_frame, text="Base Avatar Source").pack(anchor="w")
    base_source_var = tk.StringVar(value=selected_base_source)
    base_source_combo = ttk.Combobox(source_frame, textvariable=base_source_var, state="normal")
    base_source_combo.pack(fill="x", pady=2)

    def refresh_sources():
        sources = get_obs_sources()
        if sources:
            closed_source_combo['values'] = sources
            open_source_combo['values'] = sources
            base_source_combo['values'] = sources
        else:
            closed_source_combo.set(selected_closed_source)
            open_source_combo.set(selected_open_source)
            base_source_combo.set(selected_base_source)

    def on_source_change(*args):
        global selected_closed_source, selected_open_source, selected_base_source
        selected_closed_source = closed_source_var.get()
        selected_open_source = open_source_var.get()
        selected_base_source = base_source_var.get()
        save_config()
        update_scene_items()

    closed_source_var.trace('w', on_source_change)
    open_source_var.trace('w', on_source_change)
    base_source_var.trace('w', on_source_change)
    ttk.Button(source_frame, text="Refresh Sources", command=refresh_sources).pack(pady=5)

    audio_settings = ttk.LabelFrame(main_frame, text="Audio Settings", padding=10)
    audio_settings.pack(fill="x", pady=5)

    ttk.Label(audio_settings, text="Sample Rate").pack(anchor="w")
    sample_rate_var = tk.StringVar(value=str(SAMPLE_RATE))
    sample_rate_combo = ttk.Combobox(audio_settings, textvariable=sample_rate_var, 
                                     values=["16000", "44100", "48000", "96000"], state="readonly")
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
                             value=EQUALIZER_GAINS[i], 
                             command=lambda v, idx=i: update_equalizer(idx, float(v)), 
                             style="Horizontal.TScale")
        eq_slider.pack(side="left", fill="x", expand=True)
        eq_value_label = ttk.Label(eq_frame, text=f"{EQUALIZER_GAINS[i]:.1f} dB", width=8)
        eq_value_label.pack(side="right")
        eq_bands.append({"slider": eq_slider, "label": eq_value_label})

    controls = ttk.LabelFrame(main_frame, text="Lipsync Controls", padding=10)
    controls.pack(fill="x", pady=5)

    lipsync_var = tk.BooleanVar(value=LIPSYNC_ENABLED)
    lipsync_check = ttk.Checkbutton(controls, text="Enable Lip Sync", 
                                     variable=lipsync_var, command=lambda: toggle_lipsync())
    lipsync_check.pack(anchor="w", pady=(5,5))

    ttk.Label(controls, text="Threshold").pack(anchor="w")
    threshold_slider = ttk.Scale(controls, from_=0.00001, to=0.01, orient="horizontal", 
                                value=THRESHOLD, command=lambda v: update_threshold(float(v)), 
                                style="Horizontal.TScale")
    threshold_slider.pack(fill="x", pady=5)
    threshold_label = ttk.Label(controls, text=f"{THRESHOLD:.5f}")
    threshold_label.pack(anchor="w")

    ttk.Label(controls, text="Volume Multiplier").pack(anchor="w")
    multiplier_slider = ttk.Scale(controls, from_=0.1, to=10.0, orient="horizontal", 
                                 value=VOLUME_MULTIPLIER, command=lambda v: update_multiplier(float(v)), 
                                 style="Horizontal.TScale")
    multiplier_slider.pack(fill="x", pady=5)
    multiplier_label = ttk.Label(controls, text=f"{VOLUME_MULTIPLIER:.1f}")
    multiplier_label.pack(anchor="w")

    bobbing_frame = ttk.LabelFrame(main_frame, text="Bobbing Controls", padding=10)
    bobbing_frame.pack(fill="x", pady=5)

    bobbing_var = tk.BooleanVar(value=BOBBING_ENABLED)
    bobbing_check = ttk.Checkbutton(bobbing_frame, text="Enable Bobbing", 
                                     variable=bobbing_var, command=lambda: toggle_bobbing())
    bobbing_check.pack(anchor="w", pady=(5,5))

    ttk.Label(bobbing_frame, text="Bobbing Intensity").pack(anchor="w")
    bobbing_slider = ttk.Scale(bobbing_frame, from_=0.0, to=20.0, orient="horizontal", 
                               value=BOBBING_INTENSITY, command=lambda v: update_bobbing_intensity(float(v)), 
                               style="Horizontal.TScale")
    bobbing_slider.pack(fill="x", pady=5)
    bobbing_label = ttk.Label(bobbing_frame, text=f"{BOBBING_INTENSITY:.1f}")
    bobbing_label.pack(anchor="w")

    volume_frame = ttk.LabelFrame(main_frame, text="Volume Display", padding=10)
    volume_frame.pack(fill="x", pady=5)

    volume_bar = ttk.Progressbar(volume_frame, orient="horizontal", length=100, 
                                 mode="determinate", style="Horizontal.TProgressbar")
    volume_bar.pack(fill="x", pady=5)

    volume_label = ttk.Label(volume_frame, text="0.00", font=("Segoe UI", 16, "bold"))
    volume_label.pack(pady=5)

    warnings_frame = ttk.LabelFrame(main_frame, text="Warnings", padding=10)
    warnings_frame.pack(fill="both", expand=True, pady=5)

    warnings_text = tk.Text(warnings_frame, height=8, bg="#1e1e1e", fg=warning_color, 
                           font=("Consolas", 9), wrap="word", relief="flat")
    warnings_text.pack(fill="both", expand=True)
    warnings_scrollbar = ttk.Scrollbar(warnings_frame, orient="vertical", command=warnings_text.yview)
    warnings_scrollbar.pack(side="right", fill="y")
    warnings_text.configure(yscrollcommand=warnings_scrollbar.set)

    def update_ui():
        try:
            volume_bar['value'] = current_volume * 100
            volume_label['text'] = f"{current_volume:.2f}"
            threshold_label['text'] = f"{THRESHOLD:.5f}"
            multiplier_label['text'] = f"{VOLUME_MULTIPLIER:.1f}"
            bobbing_label['text'] = f"{BOBBING_INTENSITY:.1f}"
            for i, band in enumerate(eq_bands):
                band["label"]["text"] = f"{EQUALIZER_GAINS[i]:.1f} dB"
            warnings_text.delete(1.0, tk.END)
            warnings_text.insert(1.0, "\n".join(ui_warnings))
            
            if lipsync_running:
                status_label['text'] = "Status: Running"
                status_label['foreground'] = "#98c379"
                start_button['state'] = "disabled"
                stop_button['state'] = "normal"
            else:
                status_label['text'] = "Status: Stopped"
                status_label['foreground'] = warning_color
                start_button['state'] = "normal"
                stop_button['state'] = "disabled"
                
        except Exception as e:
            print(f"UI update error: {e}")
        root.after(100, update_ui)

    def update_threshold(value):
        global THRESHOLD
        THRESHOLD = value
        save_config()

    def update_multiplier(value):
        global VOLUME_MULTIPLIER
        VOLUME_MULTIPLIER = value
        save_config()

    def update_equalizer(band_index, value):
        global EQUALIZER_GAINS
        EQUALIZER_GAINS[band_index] = value
        save_config()

    def update_sample_rate():
        global SAMPLE_RATE, stream
        try:
            SAMPLE_RATE = int(sample_rate_var.get())
            save_config()
            if stream and stream.active:
                stream.stop()
                stream.close()
                stream = sd.InputStream(device=device_index, channels=1, 
                                       callback=audio_callback, samplerate=SAMPLE_RATE, blocksize=512)
                stream.start()
        except Exception as e:
            add_warning(f"Failed to update sample rate: {e}")

    def toggle_lipsync():
        global LIPSYNC_ENABLED
        LIPSYNC_ENABLED = lipsync_var.get()
        save_config()

    def toggle_bobbing():
        global BOBBING_ENABLED
        BOBBING_ENABLED = bobbing_var.get()
        save_config()

    def update_bobbing_intensity(value):
        global BOBBING_INTENSITY
        BOBBING_INTENSITY = value
        save_config()

    def select_mic_device(dev_index=None):
        global device_index, current_mic_device, current_mic_name, stream, stream_active
        
        try:
            if stream and stream.active:
                stream.stop()
                stream.close()
                stream = None
                stream_active = False
        except Exception:
            pass
        
        if dev_index is not None:
            device_index = dev_index
            current_mic_device = dev_index
            
            try:
                devices = sd.query_devices()
                if dev_index < len(devices):
                    current_mic_name = devices[dev_index]['name']
                else:
                    current_mic_name = f"Device {dev_index}"
            except Exception:
                current_mic_name = f"Device {dev_index}"
        else:
            device_index = None
            current_mic_device = None
            current_mic_name = None
        
        save_config()
        
        if device_index is not None and lipsync_running:
            try:
                stream = sd.InputStream(device=device_index, channels=1, 
                                       callback=audio_callback, samplerate=SAMPLE_RATE, blocksize=512)
                stream.start()
                stream_active = True
                print(f"Started audio stream on device {device_index} ({current_mic_name})")
            except Exception as e:
                add_warning(f"Failed to start audio stream: {e}")
                stream_active = False

    def start_lipsync():
        global lipsync_running, stream, stream_active, mouth_state, current_volume
        
        if lipsync_running:
            return
        
        if not ws:
            add_warning("OBS not connected. Cannot start lipsync.")
            return
        
        if device_index is None:
            add_warning("No microphone selected. Please select a microphone.")
            return
        
        try:
            lipsync_running = True
            mouth_state = 0.0
            current_volume = 0.0
            
            update_scene_items()
            
            if not open_item_id or not closed_item_id:
                add_warning("Mouth sources not found in scene. Please check source configuration.")
                lipsync_running = False
                return
            
            safe_set_scene_item_enabled(scene, closed_item_id, True)
            safe_set_scene_item_enabled(scene, open_item_id, False)
            
            stream = sd.InputStream(device=device_index, channels=1, 
                                   callback=audio_callback, samplerate=SAMPLE_RATE, blocksize=512)
            stream.start()
            stream_active = True
            
            print(f"Lipsync started on device {device_index} ({current_mic_name})")
            add_warning("Lipsync started successfully")
            
        except Exception as e:
            add_warning(f"Failed to start lipsync: {e}")
            lipsync_running = False
            stream_active = False

    def stop_lipsync():
        global lipsync_running, stream, stream_active, mouth_state, bobbing_phase
        
        if not lipsync_running:
            return
        
        try:
            lipsync_running = False
            stream_active = False
            
            if stream and stream.active:
                stream.stop()
                stream.close()
                stream = None
            
            mouth_state = 0.0
            bobbing_phase = 0.0
            
            if ws and scene and closed_item_id:
                safe_set_scene_item_enabled(scene, closed_item_id, True)
                safe_set_scene_item_enabled(scene, open_item_id, False)
                
                for key in list(_original_positions.keys()):
                    if key.startswith(f"{scene}:"):
                        item_id = int(key.split(":")[1])
                        orig_y = _original_positions[key]
                        try:
                            transform_resp = safe_get_scene_item_transform(scene, item_id)
                            transform = _extract_transform(transform_resp)
                            if transform:
                                if isinstance(transform, dict):
                                    transform['positionY'] = orig_y
                                else:
                                    setattr(transform, 'positionY', orig_y)
                                safe_set_scene_item_transform(scene, item_id, transform)
                        except Exception:
                            pass
            
            print("Lipsync stopped")
            add_warning("Lipsync stopped")
            
        except Exception as e:
            add_warning(f"Error stopping lipsync: {e}")
            lipsync_running = False
            stream_active = False

    refresh_sources()
    update_ui()
    root.mainloop()

def toggle_mouth_smooth(mouth_state):
    global ws, scene, open_item_id, closed_item_id
    
    if not ws or not scene or not LIPSYNC_ENABLED:
        return
    
    try:
        if mouth_state > 0.5:
            safe_set_scene_item_enabled(scene, closed_item_id, False)
            safe_set_scene_item_enabled(scene, open_item_id, True)
        else:
            safe_set_scene_item_enabled(scene, closed_item_id, True)
            safe_set_scene_item_enabled(scene, open_item_id, False)
    except Exception:
        pass

def connect_obs():
    global ws
    try:
        ws = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
        print("Connected to OBS")
        update_scene_items()
    except Exception as e:
        add_warning(f"Failed to connect to OBS: {e}")
        ws = None

def main():
    print("Starting Lipsync Controller...")
    load_config()
    connect_obs()
    start_gui()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down...")
        if stream and stream.active:
            stream.stop()
            stream.close()
        sys.exit(0)
