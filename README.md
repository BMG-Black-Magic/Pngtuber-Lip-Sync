PNGTuber Lip Sync
By Goddamnit on Twitch
written in python
--------------------------------------------------------------------------------------
Usage

Start OBS and make sure the obs-websocket plugin is enabled.

If needed, update the script with your own OBS_HOST, OBS_PORT, and OBS_PASSWORD.

In your OBS scene, set up three sources named exactly:

Avatar_Closed

Avatar_Open

Avatar_Ahh (yelling over 0.1)

Run the script with:
--------------------------------------------------------------------------------------
- Real-time microphone volume detection  
- Smooth mouth transition (fade-in/out effect)  
- Adjustable **threshold**, **volume multiplier**, and **fade speed** via a GUI  (Gui is not my strong suite im happy to update this in the future.)
- Saves user preferences to a config file (`lipsync_config.json`)  
- Integrates with OBS via [obs-websocket](https://github.com/obsproject/obs-websocket)

---------------------------------------------------------------------------------------

## Requirements
- Python 3.8+
- OBS Studio with obs-websocket plugin enabled  
- Dependencies:
  ```bash
  pip install sounddevice numpy obsws-python tkinter

----------------------------------------------------------------------------------------
# Lipsync - Windows Setup

1. **Install Python** from python.org (check "Add to PATH")
2. **Install OBS Studio** from obsproject.com
3. **Get OBS WebSocket Plugin**:
   - Download from github.com/obsproject/obs-websocket/releases
   - Extract `obs-websocket.dll` to `C:\Program Files\obs-studio\obs-plugins\64bit\`
   - Restart OBS

## OBS Setup

1. In OBS: `Tools` → `WebSocket Server Settings`
2. Enable server, set:
   - Port: `4455`
   - Password: `your_password_here`
3. Create three image sources named exactly:
   - `Avatar_Closed`
   - `Avatar_Open`
   - `Avatar_Ahh`

## Install Script Dependencies

Open Command Prompt as Admin, run:
```cmd
pip install numpy sounddevice obsws-python
```

(if you need updates let me know <3)
