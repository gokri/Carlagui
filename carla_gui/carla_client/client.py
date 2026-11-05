"""CARLA 0.9.16 client wrapper — connects, queries, and controls the server."""

import socket
import threading
import logging
from typing import Optional, List, Callable

log = logging.getLogger(__name__)

WEATHER_PRESETS = [
    "ClearNoon", "CloudyNoon", "WetNoon", "WetCloudyNoon", "SoftRainNoon",
    "MidRainyNoon", "HardRainNoon", "ClearSunset", "CloudySunset",
    "WetSunset", "WetCloudySunset", "SoftRainSunset", "MidRainSunset",
    "HardRainSunset", "ClearNight", "CloudyNight", "WetNight",
    "WetCloudyNight", "SoftRainNight", "MidRainyNight", "HardRainNight",
]


def scan_ports(host: str = "localhost", ports: range = range(2000, 2020, 2)) -> List[int]:
    """Return ports on host where something is listening (likely CARLA traffic manager or RPC)."""
    open_ports = []
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                open_ports.append(port)
        except (OSError, ConnectionRefusedError):
            pass
    return open_ports


class CarlaClient:
    """Thin wrapper around carla.Client. All heavy work stays on a background thread."""

    def __init__(self, on_log: Optional[Callable[[str], None]] = None):
        self.client = None
        self.world = None
        self.player = None
        self._on_log = on_log or (lambda msg: None)
        self._lock = threading.Lock()
        self.connected = False

    def _log(self, msg: str):
        log.info(msg)
        self._on_log(msg)

    # ------------------------------------------------------------------ connect
    def connect(self, host: str, port: int, timeout: float = 5.0) -> bool:
        try:
            import carla  # noqa: PLC0415
            self.client = carla.Client(host, port)
            self.client.set_timeout(timeout)
            self.world = self.client.get_world()
            self.connected = True
            self._log(f"[OK] Connected to CARLA {self.client.get_server_version()} @ {host}:{port}")
            return True
        except Exception as exc:
            self.connected = False
            self._log(f"[ERR] Connection failed: {exc}")
            return False

    def disconnect(self):
        self.client = None
        self.world = None
        self.player = None
        self.connected = False
        self._log("[INFO] Disconnected.")

    # ------------------------------------------------------------------ world queries
    def get_vehicle_blueprints(self) -> List[str]:
        """Return sorted list of vehicle blueprint IDs available in this world."""
        if not self.world:
            return []
        try:
            lib = self.world.get_blueprint_library().filter("vehicle.*")
            return sorted(bp.id for bp in lib)
        except Exception as exc:
            self._log(f"[ERR] get_vehicle_blueprints: {exc}")
            return []

    def get_weather_presets(self) -> List[str]:
        try:
            import carla  # noqa: PLC0415
            import re
            return [x for x in dir(carla.WeatherParameters) if re.match(r'[A-Z].+', x)]
        except Exception:
            return WEATHER_PRESETS

    def get_map_name(self) -> str:
        if not self.world:
            return "N/A"
        try:
            return self.world.get_map().name
        except Exception:
            return "N/A"

    def get_spectator_location(self) -> str:
        if not self.world:
            return "N/A"
        try:
            t = self.world.get_spectator().get_transform()
            return f"({t.location.x:.1f}, {t.location.y:.1f}, {t.location.z:.1f})"
        except Exception:
            return "N/A"

    # ------------------------------------------------------------------ vehicle
    def spawn_vehicle(self, blueprint_id: str, autopilot: bool = False) -> bool:
        if not self.world:
            self._log("[ERR] Not connected.")
            return False
        try:
            import carla  # noqa: PLC0415
            bp = self.world.get_blueprint_library().find(blueprint_id)
            if bp.has_attribute("role_name"):
                bp.set_attribute("role_name", "hero")
            spawn_points = self.world.get_map().get_spawn_points()
            if not spawn_points:
                self._log("[ERR] No spawn points on this map.")
                return False
            import random
            transform = random.choice(spawn_points)
            actor = self.world.try_spawn_actor(bp, transform)
            if actor is None:
                self._log("[ERR] Spawn failed — spawn point occupied.")
                return False
            self.player = actor
            if autopilot:
                actor.set_autopilot(True)
            self._log(f"[OK] Spawned {blueprint_id} (id={actor.id}), autopilot={autopilot}")
            return True
        except Exception as exc:
            self._log(f"[ERR] spawn_vehicle: {exc}")
            return False

    def destroy_vehicle(self):
        if self.player:
            try:
                self.player.destroy()
                self._log(f"[OK] Destroyed vehicle id={self.player.id}")
            except Exception as exc:
                self._log(f"[ERR] destroy_vehicle: {exc}")
            self.player = None

    def set_autopilot(self, enabled: bool):
        if not self.player:
            self._log("[ERR] No vehicle spawned.")
            return
        try:
            self.player.set_autopilot(enabled)
            self._log(f"[OK] Autopilot {'ON' if enabled else 'OFF'}")
        except Exception as exc:
            self._log(f"[ERR] set_autopilot: {exc}")

    def apply_control(self, throttle=0.0, steer=0.0, brake=0.0,
                      hand_brake=False, reverse=False):
        if not self.player:
            return
        try:
            import carla  # noqa: PLC0415
            ctrl = carla.VehicleControl(
                throttle=float(throttle), steer=float(steer),
                brake=float(brake), hand_brake=hand_brake, reverse=reverse,
            )
            self.player.apply_control(ctrl)
        except Exception as exc:
            self._log(f"[ERR] apply_control: {exc}")

    def set_light_state(self, state_name: str):
        if not self.player:
            self._log("[ERR] No vehicle spawned.")
            return
        try:
            import carla  # noqa: PLC0415
            state_map = {
                "Off": carla.VehicleLightState.NONE,
                "Position": carla.VehicleLightState.Position,
                "Low Beam": carla.VehicleLightState.LowBeam,
                "High Beam": carla.VehicleLightState.HighBeam,
                "Fog": carla.VehicleLightState.Fog,
                "Interior": carla.VehicleLightState.Interior,
                "Left Blinker": carla.VehicleLightState.LeftBlinker,
                "Right Blinker": carla.VehicleLightState.RightBlinker,
                "All": carla.VehicleLightState.All,
            }
            self.player.set_light_state(carla.VehicleLightState(state_map.get(state_name, 0)))
            self._log(f"[OK] Lights set to {state_name}")
        except Exception as exc:
            self._log(f"[ERR] set_light_state: {exc}")

    def open_doors(self, open_: bool):
        if not self.player:
            return
        try:
            import carla  # noqa: PLC0415
            if open_:
                self.player.open_door(carla.VehicleDoor.All)
            else:
                self.player.close_door(carla.VehicleDoor.All)
            self._log(f"[OK] Doors {'opened' if open_ else 'closed'}")
        except Exception as exc:
            self._log(f"[WARN] Doors not supported on this vehicle: {exc}")

    # ------------------------------------------------------------------ weather
    def set_weather(self, preset_name: str):
        if not self.world:
            self._log("[ERR] Not connected.")
            return
        try:
            import carla  # noqa: PLC0415
            preset = getattr(carla.WeatherParameters, preset_name, None)
            if preset is None:
                self._log(f"[ERR] Unknown weather preset: {preset_name}")
                return
            self.world.set_weather(preset)
            self._log(f"[OK] Weather set to {preset_name}")
        except Exception as exc:
            self._log(f"[ERR] set_weather: {exc}")

    def set_weather_custom(self, params: dict):
        """params keys match carla.WeatherParameters field names."""
        if not self.world:
            return
        try:
            import carla  # noqa: PLC0415
            wp = self.world.get_weather()
            for k, v in params.items():
                setattr(wp, k, float(v))
            self.world.set_weather(wp)
            self._log(f"[OK] Custom weather applied: {params}")
        except Exception as exc:
            self._log(f"[ERR] set_weather_custom: {exc}")

    # ------------------------------------------------------------------ map layers
    def load_map_layer(self, layer_name: str, load: bool = True):
        if not self.world:
            return
        try:
            import carla  # noqa: PLC0415
            layer = getattr(carla.MapLayer, layer_name, None)
            if layer is None:
                self._log(f"[ERR] Unknown layer: {layer_name}")
                return
            if load:
                self.world.load_map_layer(layer)
            else:
                self.world.unload_map_layer(layer)
            self._log(f"[OK] Map layer {layer_name} {'loaded' if load else 'unloaded'}")
        except Exception as exc:
            self._log(f"[ERR] load_map_layer: {exc}")
