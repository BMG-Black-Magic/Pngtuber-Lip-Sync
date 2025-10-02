PNGTuber Lip Sync
By Goddamnit on twitch
written in python

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
