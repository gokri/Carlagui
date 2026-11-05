# CARLA 0.9.16 — GUI Control Panel

A PyQt5 desktop GUI that replaces `manual_control.py` keyboard shortcuts with dropdowns, sliders, and buttons.

## Features

| Tab | What it does |
|---|---|
| 🔌 Connection | Enter host/port, **scan for open CARLA ports automatically**, connect/disconnect |
| 🚗 Vehicle | Pick blueprint from dropdown (only vehicles the server has), spawn, destroy, autopilot toggle |
| 🎮 Controls | Throttle / brake / steer sliders, handbrake, reverse, all hotkey actions as buttons |
| 🌦 Weather | Preset dropdown (populated from live server), ◀/▶ cycle, custom sliders per parameter |
| 🗺 Scenarios | Pedestrian Crossing, Sudden Brake, Junction Conflict, Parked Car — one click to run/clear |
| 🖥 Terminal | Live log of all CARLA API calls, errors, and warnings in a dark terminal panel |

## Setup

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Install the CARLA Python API (get the .whl from your CARLA 0.9.16 release folder)
pip install /path/to/carla-0.9.16-cp38-cp38-linux_x86_64.whl

# 3. Start your CARLA server
./CarlaUE4.sh -carla-rpc-port=2000

# 4. Launch the GUI
python main.py
```

## How it handles custom maps

When you connect, the blueprint dropdown is **populated live from the server** — if your custom map only has 4 vehicle types, the dropdown shows exactly those 4. Same for weather presets.

The port scanner checks ports 2000–2018 and lists every open one, so you can click to select without typing.

## Notes

- Autopilot must be OFF for the control sliders to have effect.
- The terminal tab shows `[ERR]` in red, `[WARN]` in yellow, `[OK]` in green.
- Scenario actors can be cleared with the "Clear Actors" button.
