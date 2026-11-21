# Carlagui — CARLA 0.9.16 GUI Control Panel

A PyQt5-based graphical control panel for the [CARLA](https://carla.org/) autonomous driving simulator (0.9.16).

Fills the gap left by CARLA's Python-API-only interface — no terminal required for common tasks.

## Features

- **Connection** — connect to any CARLA server (host/port), port scanner, map switcher
- **Vehicle** — spawn/destroy vehicles, blueprint picker, autopilot toggle
- **Map & Route** — 2D top-down map view, click to set spawn/route/pedestrian/NPC waypoints
- **Controls** — throttle/brake/steer sliders, lights, doors, hotkey actions
- **Weather** — preset picker, custom parameter sliders, cycle through presets
- **Scenarios** — pedestrian crossing scenario builder with configurable parameters
- **Sensors** — camera/lidar/radar placement UI with live feed window
- **HUD** — real-time vehicle metrics (speed, TTC, throttle, etc.) with sparkline charts
- **Terminal** — in-app log output

## Requirements

- Python 3.8+
- CARLA 0.9.x Python API (`pip install carla` or from your CARLA install's `PythonAPI/`)
- PyQt5 (`pip install PyQt5`)
- A running CARLA server (`CarlaUE4.exe` or `./CarlaUE4.sh`)

## Getting Started

```bash
git clone https://github.com/gokri/Carlagui.git
cd Carlagui
pip install PyQt5
python carla_gui/main.py
```

**Windows:** double-click `launch_carlagui.bat`

**Linux:** right-click `carla_gui/main.py` → Run as Program, or:
```bash
python3 carla_gui/main.py
```

## Connecting to CARLA

1. Start your CARLA server (`CarlaUE4.exe -windowed`)
2. Launch Carlagui
3. Go to **🔌 Connection** tab → set host/port → click **Connect**
4. The map dropdown auto-populates — use **Load Map** to switch maps

## Project Structure

```
Carlagui/
├── carla_gui/
│   ├── main.py               # Entry point
│   ├── gui/
│   │   ├── app.py            # Main window and tabs
│   │   ├── map_view.py       # 2D map canvas
│   │   ├── scenario_panel.py # Scenario builder UI
│   │   ├── sensor_placer.py  # Sensor placement widget
│   │   ├── sensor_window.py  # Live sensor feed
│   │   └── hud_window.py     # Real-time HUD metrics
│   ├── carla_client/
│   │   ├── client.py         # CARLA client wrapper
│   │   └── route_planner.py  # Waypoint/route utilities
│   └── scenarios/
│       └── pedestrian_crossing.py
├── launch_carlagui.bat       # Windows one-click launcher
└── README.md
```

## License

MIT
