"""Main application window — CARLA 0.9.16 GUI Control Panel."""

import sys
import threading
import logging
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QGroupBox, QSlider, QTextEdit, QSplitter, QGridLayout, QSpinBox,
    QDoubleSpinBox, QListWidget, QMessageBox, QProgressBar,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QTextCursor

from carla_client.client import CarlaClient, scan_ports
from carla_client.route_planner import RoutePlanner
from gui.map_view import MapScene, MapView, START_COLOR, END_COLOR, PED_COLOR, NPC_COLOR
from gui.scenario_panel import ScenarioPanel
from gui.sensor_placer import SensorPlacerWidget, SENSOR_TYPES
from gui.sensor_window import SensorFeedWindow, SensorManager
from scenarios.pedestrian_crossing import ScenarioRunner

log = logging.getLogger(__name__)


class _Bridge(QObject):
    log_signal = pyqtSignal(str)
    blueprints_signal = pyqtSignal(list)
    weather_signal = pyqtSignal(list)
    status_signal = pyqtSignal(bool)
    map_loaded_signal = pyqtSignal(list, list)   # segments, spawn_transforms


class CarlaGuiApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CARLA 0.9.16 — Control Panel")
        self.setMinimumSize(1050, 740)

        self._bridge = _Bridge()
        self._bridge.log_signal.connect(self._append_log)
        self._bridge.blueprints_signal.connect(self._populate_blueprints)
        self._bridge.weather_signal.connect(self._populate_weather)
        self._bridge.status_signal.connect(self._on_connection_changed)
        self._bridge.map_loaded_signal.connect(self._draw_map)

        self._carla = CarlaClient(on_log=lambda m: self._bridge.log_signal.emit(m))
        self._route_planner = None
        self._spawn_transforms = []     # list of carla.Transform
        self._route_start = None        # carla.Transform
        self._route_end = None
        self._last_map_click = None     # (x, y, z)
        self._placement_mode = None
        self._run_timer = None
        self._run_elapsed = 0
        self._sensor_manager: SensorManager = None
        self._sensor_feed_window: SensorFeedWindow = None

        # Map scene (created early so scenario panel can reference it)
        self._map_scene = MapScene()
        self._map_scene.spawn_clicked.connect(self._on_spawn_clicked)
        self._map_scene.waypoint_clicked.connect(self._on_waypoint_clicked)

        self._build_ui()
        self._set_connected(False)

    # ─────────────────────────────────────────────────────────────────────────
    # UI
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # Status bar
        status_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(18)
        self._status_label = QLabel("Disconnected")
        self._status_label.setFont(QFont("Monospace", 9))
        self._map_label = QLabel("Map: —")
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._map_label)
        root.addLayout(status_row)

        tabs = QTabWidget()
        root.addWidget(tabs, stretch=1)

        tabs.addTab(self._build_connection_tab(), "🔌 Connection")
        tabs.addTab(self._build_vehicle_tab(), "🚗 Vehicle")
        tabs.addTab(self._build_map_tab(), "🗺 Map & Route")
        tabs.addTab(self._build_controls_tab(), "🎮 Controls")
        tabs.addTab(self._build_weather_tab(), "🌦 Weather")
        tabs.addTab(self._build_scenarios_full_tab(), "🎭 Scenarios")
        tabs.addTab(self._build_sensors_tab(), "📷 Sensors")
        tabs.addTab(self._build_terminal_tab(), "🖥 Terminal")

    # ── Connection ───────────────────────────────────────────────────────────
    def _build_connection_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        grp = QGroupBox("Server")
        grid = QGridLayout(grp)
        grid.addWidget(QLabel("Host:"), 0, 0)
        self._host_edit = QLineEdit("localhost")
        grid.addWidget(self._host_edit, 0, 1)
        grid.addWidget(QLabel("Port:"), 0, 2)
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(2000)
        grid.addWidget(self._port_spin, 0, 3)
        self._scan_btn = QPushButton("Scan ports")
        self._scan_btn.clicked.connect(self._scan_ports)
        grid.addWidget(self._scan_btn, 0, 4)
        grid.addWidget(QLabel("Available:"), 1, 0)
        self._port_list = QListWidget()
        self._port_list.setMaximumHeight(70)
        self._port_list.itemClicked.connect(
            lambda item: self._port_spin.setValue(int(item.text())))
        grid.addWidget(self._port_list, 1, 1, 1, 4)
        v.addWidget(grp)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedHeight(36)
        self._connect_btn.clicked.connect(self._connect)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setFixedHeight(36)
        self._disconnect_btn.clicked.connect(self._disconnect)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        v.addLayout(btn_row)

        info_grp = QGroupBox("Server Info")
        ig = QGridLayout(info_grp)
        self._info_map = QLabel("—")
        self._info_loc = QLabel("—")
        ig.addWidget(QLabel("Map:"), 0, 0); ig.addWidget(self._info_map, 0, 1)
        ig.addWidget(QLabel("Spectator:"), 1, 0); ig.addWidget(self._info_loc, 1, 1)
        v.addWidget(info_grp)

        self._info_timer = QTimer()
        self._info_timer.timeout.connect(self._refresh_info)
        self._info_timer.start(2000)

        v.addStretch()
        return w

    # ── Vehicle ──────────────────────────────────────────────────────────────
    def _build_vehicle_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        bp_grp = QGroupBox("Blueprint")
        bph = QHBoxLayout(bp_grp)
        bph.addWidget(QLabel("Vehicle:"))
        self._bp_combo = QComboBox()
        self._bp_combo.setMinimumWidth(300)
        bph.addWidget(self._bp_combo, stretch=1)
        ref_btn = QPushButton("↻")
        ref_btn.setFixedWidth(32)
        ref_btn.clicked.connect(self._load_blueprints)
        bph.addWidget(ref_btn)
        v.addWidget(bp_grp)

        ap_grp = QGroupBox("Autopilot")
        aph = QHBoxLayout(ap_grp)
        self._autopilot_check = QCheckBox("Enable on spawn")
        aph.addWidget(self._autopilot_check)
        self._ap_toggle_btn = QPushButton("Toggle Autopilot (P)")
        self._ap_toggle_btn.clicked.connect(self._toggle_autopilot)
        aph.addWidget(self._ap_toggle_btn)
        self._autopilot_state = False
        v.addWidget(ap_grp)

        spawn_row = QHBoxLayout()
        self._spawn_btn = QPushButton("Spawn at selected map point")
        self._spawn_btn.setFixedHeight(36)
        self._spawn_btn.clicked.connect(self._spawn_vehicle)
        self._destroy_btn = QPushButton("Destroy Vehicle")
        self._destroy_btn.setFixedHeight(36)
        self._destroy_btn.clicked.connect(self._destroy_vehicle)
        spawn_row.addWidget(self._spawn_btn)
        spawn_row.addWidget(self._destroy_btn)
        v.addLayout(spawn_row)

        self._spawn_location_lbl = QLabel("Spawn: random (click map to set)")
        v.addWidget(self._spawn_location_lbl)

        lights_grp = QGroupBox("Lights")
        lh = QHBoxLayout(lights_grp)
        lh.addWidget(QLabel("State:"))
        self._lights_combo = QComboBox()
        self._lights_combo.addItems([
            "Off", "Position", "Low Beam", "High Beam", "Fog",
            "Interior", "Left Blinker", "Right Blinker", "All",
        ])
        self._lights_combo.currentTextChanged.connect(
            lambda t: threading.Thread(target=self._carla.set_light_state, args=(t,), daemon=True).start())
        lh.addWidget(self._lights_combo)
        v.addWidget(lights_grp)

        doors_grp = QGroupBox("Doors")
        dh = QHBoxLayout(doors_grp)
        ob = QPushButton("Open All (O)")
        ob.clicked.connect(lambda: threading.Thread(target=self._carla.open_doors, args=(True,), daemon=True).start())
        cb = QPushButton("Close All")
        cb.clicked.connect(lambda: threading.Thread(target=self._carla.open_doors, args=(False,), daemon=True).start())
        dh.addWidget(ob); dh.addWidget(cb)
        v.addWidget(doors_grp)

        v.addStretch()
        return w

    # ── Map & Route ──────────────────────────────────────────────────────────
    def _build_map_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # Toolbar
        toolbar = QHBoxLayout()
        load_map_btn = QPushButton("Load Map")
        load_map_btn.clicked.connect(self._load_map)
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self._map_view.fit_scene())

        self._placement_combo = QComboBox()
        self._placement_combo.addItems(["Click = Set Spawn/Route", "Click = Place Pedestrian", "Click = Place NPC"])
        self._placement_combo.currentIndexChanged.connect(self._on_placement_mode_changed)

        clear_route_btn = QPushButton("Clear Route")
        clear_route_btn.clicked.connect(self._clear_route)

        toolbar.addWidget(load_map_btn)
        toolbar.addWidget(fit_btn)
        toolbar.addWidget(QLabel("Click mode:"))
        toolbar.addWidget(self._placement_combo)
        toolbar.addWidget(clear_route_btn)
        toolbar.addStretch()
        v.addLayout(toolbar)

        # Map canvas
        self._map_view = MapView(self._map_scene)
        v.addWidget(self._map_view, stretch=1)

        # Route / Run controls
        run_grp = QGroupBox("Route & Scenario Run")
        rg = QGridLayout(run_grp)

        rg.addWidget(QLabel("Start:"), 0, 0)
        self._route_start_lbl = QLabel("— (click map)")
        rg.addWidget(self._route_start_lbl, 0, 1)

        rg.addWidget(QLabel("End:"), 0, 2)
        self._route_end_lbl = QLabel("— (click map)")
        rg.addWidget(self._route_end_lbl, 0, 3)

        rg.addWidget(QLabel("Speed limit (m/s):"), 1, 0)
        self._speed_limit_spin = QDoubleSpinBox()
        self._speed_limit_spin.setRange(1, 50)
        self._speed_limit_spin.setValue(10.0)
        rg.addWidget(self._speed_limit_spin, 1, 1)

        rg.addWidget(QLabel("Stop after (s):"), 1, 2)
        self._stop_time_spin = QSpinBox()
        self._stop_time_spin.setRange(1, 3600)
        self._stop_time_spin.setValue(30)
        rg.addWidget(self._stop_time_spin, 1, 3)

        self._run_btn = QPushButton("▶ RUN")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setStyleSheet("background:#2ecc71;color:white;font-weight:bold;")
        self._run_btn.clicked.connect(self._run_scenario)
        rg.addWidget(self._run_btn, 2, 0, 1, 2)

        self._stop_btn = QPushButton("■ STOP")
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setStyleSheet("background:#e74c3c;color:white;font-weight:bold;")
        self._stop_btn.clicked.connect(self._stop_scenario)
        self._stop_btn.setEnabled(False)
        rg.addWidget(self._stop_btn, 2, 2, 1, 2)

        self._run_progress = QProgressBar()
        self._run_progress.setRange(0, 100)
        self._run_progress.setValue(0)
        rg.addWidget(self._run_progress, 3, 0, 1, 4)

        v.addWidget(run_grp)
        return w

    # ── Controls ─────────────────────────────────────────────────────────────
    def _build_controls_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("Autopilot must be OFF for sliders to take effect.")
        note.setWordWrap(True)
        v.addWidget(note)

        drive_grp = QGroupBox("Drive Controls")
        g = QGridLayout(drive_grp)

        g.addWidget(QLabel("Throttle (W):"), 0, 0)
        self._throttle_slider = self._make_slider(0, 100, 0)
        g.addWidget(self._throttle_slider, 0, 1)
        self._throttle_val = QLabel("0")
        g.addWidget(self._throttle_val, 0, 2)
        self._throttle_slider.valueChanged.connect(
            lambda v: (self._throttle_val.setText(str(v)), self._send_control()))

        g.addWidget(QLabel("Brake (S):"), 1, 0)
        self._brake_slider = self._make_slider(0, 100, 0)
        g.addWidget(self._brake_slider, 1, 1)
        self._brake_val = QLabel("0")
        g.addWidget(self._brake_val, 1, 2)
        self._brake_slider.valueChanged.connect(
            lambda v: (self._brake_val.setText(str(v)), self._send_control()))

        g.addWidget(QLabel("Steer (A/D):"), 2, 0)
        self._steer_slider = self._make_slider(-100, 100, 0)
        g.addWidget(self._steer_slider, 2, 1)
        self._steer_val = QLabel("0")
        g.addWidget(self._steer_val, 2, 2)
        self._steer_slider.valueChanged.connect(
            lambda v: (self._steer_val.setText(str(v)), self._send_control()))

        g.addWidget(QLabel("Handbrake:"), 3, 0)
        self._handbrake_check = QCheckBox("SPACE")
        self._handbrake_check.stateChanged.connect(lambda _: self._send_control())
        g.addWidget(self._handbrake_check, 3, 1)

        g.addWidget(QLabel("Reverse:"), 4, 0)
        self._reverse_check = QCheckBox("Q")
        self._reverse_check.stateChanged.connect(lambda _: self._send_control())
        g.addWidget(self._reverse_check, 4, 1)

        reset_btn = QPushButton("Reset all")
        reset_btn.clicked.connect(self._reset_controls)
        g.addWidget(reset_btn, 5, 0, 1, 3)
        v.addWidget(drive_grp)

        action_grp = QGroupBox("Hotkey Actions")
        ag = QGridLayout(action_grp)
        actions = [
            ("Toggle Autopilot (P)", self._toggle_autopilot),
            ("Next Weather (C)", self._next_weather),
            ("Prev Weather (Shift+C)", self._prev_weather),
            ("Open Doors (O)", lambda: threading.Thread(target=self._carla.open_doors, args=(True,), daemon=True).start()),
            ("Close Doors", lambda: threading.Thread(target=self._carla.open_doors, args=(False,), daemon=True).start()),
            ("High Beam (Shift+L)", lambda: threading.Thread(target=self._carla.set_light_state, args=("High Beam",), daemon=True).start()),
            ("Left Blinker (Z)", lambda: threading.Thread(target=self._carla.set_light_state, args=("Left Blinker",), daemon=True).start()),
            ("Right Blinker (X)", lambda: threading.Thread(target=self._carla.set_light_state, args=("Right Blinker",), daemon=True).start()),
            ("All Lights On", lambda: threading.Thread(target=self._carla.set_light_state, args=("All",), daemon=True).start()),
            ("Lights Off", lambda: threading.Thread(target=self._carla.set_light_state, args=("Off",), daemon=True).start()),
        ]
        for i, (label, fn) in enumerate(actions):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            ag.addWidget(btn, i // 3, i % 3)
        v.addWidget(action_grp)
        v.addStretch()
        return w

    # ── Weather ──────────────────────────────────────────────────────────────
    def _build_weather_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        preset_grp = QGroupBox("Weather Preset")
        ph = QHBoxLayout(preset_grp)
        self._weather_combo = QComboBox()
        self._weather_combo.setMinimumWidth(220)
        ph.addWidget(QLabel("Preset:"))
        ph.addWidget(self._weather_combo, stretch=1)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_weather_preset)
        ph.addWidget(apply_btn)
        v.addWidget(preset_grp)

        nav_row = QHBoxLayout()
        nav_row.addWidget(QPushButton("◀ Prev", clicked=self._prev_weather))
        nav_row.addWidget(QPushButton("Next ▶", clicked=self._next_weather))
        v.addLayout(nav_row)

        custom_grp = QGroupBox("Custom Parameters")
        cg = QGridLayout(custom_grp)
        self._weather_sliders = {}
        params = [
            ("cloudiness", 0, 100), ("precipitation", 0, 100),
            ("precipitation_deposits", 0, 100), ("wind_intensity", 0, 100),
            ("sun_azimuth_angle", 0, 360), ("sun_altitude_angle", -90, 90),
            ("fog_density", 0, 100), ("fog_distance", 0, 100), ("wetness", 0, 100),
        ]
        for row, (name, lo, hi) in enumerate(params):
            cg.addWidget(QLabel(name.replace("_", " ").title() + ":"), row, 0)
            sl = self._make_slider(lo, hi, 0)
            lbl = QLabel("0")
            sl.valueChanged.connect(lambda v, l=lbl: l.setText(str(v)))
            cg.addWidget(sl, row, 1)
            cg.addWidget(lbl, row, 2)
            self._weather_sliders[name] = sl
        apply_custom = QPushButton("Apply Custom")
        apply_custom.clicked.connect(self._apply_custom_weather)
        cg.addWidget(apply_custom, len(params), 0, 1, 3)
        v.addWidget(custom_grp)
        v.addStretch()
        return w

    # ── Scenarios ────────────────────────────────────────────────────────────
    def _build_scenarios_full_tab(self):
        self._scenario_panel = ScenarioPanel(
            self._carla,
            log_fn=lambda m: self._bridge.log_signal.emit(m),
            get_map_selection_fn=lambda: self._last_map_click,
        )
        return self._scenario_panel

    # ── Sensors ──────────────────────────────────────────────────────────────
    def _build_sensors_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        note = QLabel(
            "Place sensors on the vehicle using the views below.\n"
            "Top/Front/Side: left-click to place, drag to reposition, right-drag to rotate.\n"
            "3D iso: drag to orbit. Click 'Show Live Feed' to open the sensor window."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        self._sensor_placer = SensorPlacerWidget()
        v.addWidget(self._sensor_placer, stretch=1)

        btn_row = QHBoxLayout()
        show_btn = QPushButton("▶ Show Live Feed Window")
        show_btn.setFixedHeight(36)
        show_btn.setStyleSheet("background:#2980b9;color:white;font-weight:bold;")
        show_btn.clicked.connect(self._open_sensor_feed)
        btn_row.addWidget(show_btn)

        detach_btn = QPushButton("■ Detach All Sensors")
        detach_btn.setFixedHeight(36)
        detach_btn.clicked.connect(self._detach_all_sensors)
        btn_row.addWidget(detach_btn)
        v.addLayout(btn_row)
        return w

    def _open_sensor_feed(self):
        if not self._carla.connected:
            self._append_log("[ERR] Connect to CARLA before opening sensor feed.")
            return
        if not self._carla.player:
            self._append_log("[ERR] Spawn a vehicle first — sensors attach to the ego vehicle.")
            return

        handles = self._sensor_placer.get_handles()
        if not handles:
            self._append_log("[WARN] No sensors placed. Click in a view to place one first.")
            return

        # Create manager and window once
        if self._sensor_manager is None:
            self._sensor_manager = SensorManager(
                self._carla,
                log_fn=lambda m: self._bridge.log_signal.emit(m),
            )
        if self._sensor_feed_window is None:
            self._sensor_feed_window = SensorFeedWindow()

        for handle in handles:
            self._sensor_feed_window.open_sensor(handle, self._sensor_manager)

        self._sensor_feed_window.show()
        self._sensor_feed_window.raise_()
        self._append_log(f"[OK] Opening sensor feed for {len(handles)} sensor(s).")

    def _detach_all_sensors(self):
        if self._sensor_feed_window and self._sensor_manager:
            self._sensor_feed_window.close_all(self._sensor_manager)
        self._append_log("[OK] All sensors detached.")

    # ── Terminal ─────────────────────────────────────────────────────────────
    def _build_terminal_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setFont(QFont("Monospace", 9))
        self._terminal.setStyleSheet("background:#111; color:#e0e0e0;")
        v.addWidget(self._terminal, stretch=1)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._terminal.clear)
        v.addWidget(clear_btn)
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _make_slider(lo, hi, default):
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(default)
        return sl

    def _append_log(self, msg: str):
        self._terminal.moveCursor(QTextCursor.End)
        color = "#ff6b6b" if "[ERR]" in msg else "#ffd700" if "[WARN]" in msg else "#a8e6a3" if "[OK]" in msg else "#e0e0e0"
        self._terminal.insertHtml(f'<span style="color:{color}">{msg}</span><br>')
        self._terminal.moveCursor(QTextCursor.End)

    def _set_connected(self, connected: bool):
        color = "#2ecc71" if connected else "#e74c3c"
        self._status_dot.setStyleSheet(f"color:{color};font-size:16px;")
        self._status_label.setText("Connected" if connected else "Disconnected")
        self._connect_btn.setEnabled(not connected)
        self._disconnect_btn.setEnabled(connected)

    def _on_connection_changed(self, connected: bool):
        self._set_connected(connected)

    def _populate_blueprints(self, bps: list):
        self._bp_combo.clear()
        self._bp_combo.addItems(bps)

    def _populate_weather(self, presets: list):
        self._weather_combo.clear()
        self._weather_combo.addItems(presets)

    def _draw_map(self, segments, transforms):
        self._map_scene.clear()
        self._map_scene.draw_roads(segments)
        self._map_scene.draw_spawn_points(transforms, callback=None)
        self._spawn_transforms = transforms
        self._map_view.fit_scene()

    # ─────────────────────────────────────────────────────────────────────────
    # Map interactions
    # ─────────────────────────────────────────────────────────────────────────
    def _on_placement_mode_changed(self, idx):
        modes = [None, 'pedestrian', 'npc']
        self._placement_mode = modes[idx]
        self._map_scene.set_placement_mode(self._placement_mode)

    def _on_spawn_clicked(self, idx: int, transform):
        """Green dot on map clicked — depends on current placement mode."""
        mode = self._placement_mode
        x = transform.location.x
        y = transform.location.y
        z = transform.location.z

        if mode is None:
            # First click = start, second = end
            if self._route_start is None:
                self._route_start = transform
                self._route_start_lbl.setText(f"({x:.1f}, {y:.1f})")
                self._map_scene.add_marker(x, y, START_COLOR, "S")
                self._spawn_location_lbl.setText(f"Spawn: ({x:.1f}, {y:.1f}, {z:.1f})")
                self._append_log(f"[INFO] Route start set: spawn #{idx}")
            else:
                self._route_end = transform
                self._route_end_lbl.setText(f"({x:.1f}, {y:.1f})")
                self._map_scene.add_marker(x, y, END_COLOR, "E")
                self._append_log(f"[INFO] Route end set: spawn #{idx} — computing route...")
                threading.Thread(target=self._compute_route, daemon=True).start()
        elif mode == 'pedestrian':
            self._last_map_click = (x, y, z)
            self._map_scene.add_marker(x, y, PED_COLOR, "P")
            self._append_log(f"[INFO] Pedestrian waypoint set at ({x:.1f}, {y:.1f}). Use 'Spawn at Map Click' in Scenarios.")
        elif mode == 'npc':
            self._last_map_click = (x, y, z)
            self._map_scene.add_marker(x, y, NPC_COLOR, "N")
            self._append_log(f"[INFO] NPC waypoint set at ({x:.1f}, {y:.1f}). Use 'Use Map Click Position' in Scenarios.")

    def _on_waypoint_clicked(self, x: float, y: float):
        """Blank map area clicked in pedestrian/npc mode."""
        self._last_map_click = (x, y, 0.5)
        color = PED_COLOR if self._placement_mode == 'pedestrian' else NPC_COLOR
        label = "P" if self._placement_mode == 'pedestrian' else "N"
        self._map_scene.add_marker(x, y, color, label)
        self._append_log(f"[INFO] Waypoint set at ({x:.1f}, {y:.1f})")

    def _compute_route(self):
        if not self._route_planner:
            self._append_log("[WARN] Route planner not ready. Connect first.")
            return
        waypoints = self._route_planner.plan(self._route_start, self._route_end)
        if waypoints:
            self._map_scene.draw_route(waypoints)
            self._append_log(f"[OK] Route computed: {len(waypoints)} waypoints.")
        else:
            self._append_log("[WARN] Could not compute route — GlobalRoutePlanner may not be available.")

    def _clear_route(self):
        self._route_start = None
        self._route_end = None
        self._route_start_lbl.setText("— (click map)")
        self._route_end_lbl.setText("— (click map)")
        self._map_scene.clear_markers()
        self._append_log("[INFO] Route cleared.")

    # ─────────────────────────────────────────────────────────────────────────
    # Run / Stop
    # ─────────────────────────────────────────────────────────────────────────
    def _run_scenario(self):
        if not self._carla.connected:
            self._append_log("[ERR] Not connected to CARLA.")
            return
        # Set autopilot + speed for ego
        if self._carla.player:
            speed = self._speed_limit_spin.value()
            self._carla.set_autopilot(True)
            try:
                tm = self._carla.client.get_trafficmanager()
                tm.set_desired_speed(self._carla.player, speed)
            except Exception as exc:
                self._append_log(f"[WARN] Could not set TM speed: {exc}")

        stop_time = self._stop_time_spin.value()
        self._run_elapsed = 0
        self._run_progress.setRange(0, stop_time)
        self._run_progress.setValue(0)
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        self._run_timer = QTimer()
        self._run_timer.timeout.connect(lambda: self._tick_run(stop_time))
        self._run_timer.start(1000)
        self._append_log(f"[OK] ▶ Scenario running — stop after {stop_time}s.")

    def _tick_run(self, stop_time: int):
        self._run_elapsed += 1
        self._run_progress.setValue(self._run_elapsed)
        if self._run_elapsed >= stop_time:
            self._stop_scenario()

    def _stop_scenario(self):
        if self._run_timer:
            self._run_timer.stop()
            self._run_timer = None
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._run_progress.setValue(0)
        if self._carla.player:
            threading.Thread(target=self._carla.set_autopilot, args=(False,), daemon=True).start()
        self._append_log("[INFO] ■ Scenario stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Connection actions
    # ─────────────────────────────────────────────────────────────────────────
    def _scan_ports(self):
        host = self._host_edit.text().strip()
        self._port_list.clear()
        self._append_log(f"[INFO] Scanning {host}:2000-2018 ...")

        def _do():
            ports = scan_ports(host)
            self._port_list.addItems([str(p) for p in ports])
            self._bridge.log_signal.emit(
                f"[OK] Found: {ports}" if ports else "[WARN] No CARLA ports found.")

        threading.Thread(target=_do, daemon=True).start()

    def _connect(self):
        host = self._host_edit.text().strip()
        port = self._port_spin.value()
        self._append_log(f"[INFO] Connecting to {host}:{port} ...")

        def _do():
            ok = self._carla.connect(host, port)
            self._bridge.status_signal.emit(ok)
            if ok:
                self._route_planner = RoutePlanner(self._carla)
                self._bridge.blueprints_signal.emit(self._carla.get_vehicle_blueprints())
                self._bridge.weather_signal.emit(self._carla.get_weather_presets())
                # Load map topology for 2D view
                segments = self._route_planner.get_map_topology()
                transforms = self._route_planner.get_spawn_points()
                self._bridge.map_loaded_signal.emit(segments, transforms)
                # Update scenario config
                self._scenario_panel.update_config("host", host)
                self._scenario_panel.update_config("port", port)

        threading.Thread(target=_do, daemon=True).start()

    def _disconnect(self):
        self._carla.disconnect()
        self._bridge.status_signal.emit(False)
        self._route_planner = None

    def _load_map(self):
        if not self._carla.connected:
            self._append_log("[ERR] Not connected.")
            return
        threading.Thread(target=self._do_load_map, daemon=True).start()

    def _do_load_map(self):
        if not self._route_planner:
            return
        segments = self._route_planner.get_map_topology()
        transforms = self._route_planner.get_spawn_points()
        self._bridge.map_loaded_signal.emit(segments, transforms)
        self._bridge.log_signal.emit(f"[OK] Map loaded: {len(transforms)} spawn points, {len(segments)} road segments.")

    # ─────────────────────────────────────────────────────────────────────────
    # Vehicle
    # ─────────────────────────────────────────────────────────────────────────
    def _load_blueprints(self):
        threading.Thread(
            target=lambda: self._bridge.blueprints_signal.emit(self._carla.get_vehicle_blueprints()),
            daemon=True).start()

    def _refresh_info(self):
        if self._carla.connected:
            m = self._carla.get_map_name()
            self._info_map.setText(m)
            self._info_loc.setText(self._carla.get_spectator_location())
            self._map_label.setText(f"Map: {m}")

    def _spawn_vehicle(self):
        bp = self._bp_combo.currentText()
        ap = self._autopilot_check.isChecked()
        # Use route_start as spawn if set
        if self._route_start:
            import carla
            def _do():
                if not self._carla.world:
                    return
                bp_obj = self._carla.world.get_blueprint_library().find(bp)
                if bp_obj.has_attribute("role_name"):
                    bp_obj.set_attribute("role_name", "hero")
                actor = self._carla.world.try_spawn_actor(bp_obj, self._route_start)
                if actor:
                    self._carla.player = actor
                    if ap:
                        actor.set_autopilot(True)
                    self._bridge.log_signal.emit(f"[OK] Spawned {bp} at selected map point.")
                else:
                    self._bridge.log_signal.emit("[ERR] Spawn failed at selected point.")
            threading.Thread(target=_do, daemon=True).start()
        else:
            threading.Thread(target=self._carla.spawn_vehicle, args=(bp, ap), daemon=True).start()

    def _destroy_vehicle(self):
        threading.Thread(target=self._carla.destroy_vehicle, daemon=True).start()

    def _toggle_autopilot(self):
        self._autopilot_state = not self._autopilot_state
        threading.Thread(target=self._carla.set_autopilot, args=(self._autopilot_state,), daemon=True).start()

    def _send_control(self):
        threading.Thread(target=self._carla.apply_control, kwargs=dict(
            throttle=self._throttle_slider.value() / 100.0,
            steer=self._steer_slider.value() / 100.0,
            brake=self._brake_slider.value() / 100.0,
            hand_brake=self._handbrake_check.isChecked(),
            reverse=self._reverse_check.isChecked(),
        ), daemon=True).start()

    def _reset_controls(self):
        self._throttle_slider.setValue(0)
        self._brake_slider.setValue(0)
        self._steer_slider.setValue(0)
        self._handbrake_check.setChecked(False)
        self._reverse_check.setChecked(False)

    # ─────────────────────────────────────────────────────────────────────────
    # Weather
    # ─────────────────────────────────────────────────────────────────────────
    _weather_idx = 0

    def _next_weather(self):
        presets = [self._weather_combo.itemText(i) for i in range(self._weather_combo.count())]
        if not presets: return
        self._weather_idx = (self._weather_idx + 1) % len(presets)
        self._weather_combo.setCurrentIndex(self._weather_idx)
        threading.Thread(target=self._carla.set_weather, args=(presets[self._weather_idx],), daemon=True).start()

    def _prev_weather(self):
        presets = [self._weather_combo.itemText(i) for i in range(self._weather_combo.count())]
        if not presets: return
        self._weather_idx = (self._weather_idx - 1) % len(presets)
        self._weather_combo.setCurrentIndex(self._weather_idx)
        threading.Thread(target=self._carla.set_weather, args=(presets[self._weather_idx],), daemon=True).start()

    def _apply_weather_preset(self):
        threading.Thread(
            target=self._carla.set_weather,
            args=(self._weather_combo.currentText(),), daemon=True).start()
        self._scenario_panel.update_config("weather_preset", self._weather_combo.currentText())

    def _apply_custom_weather(self):
        params = {k: sl.value() for k, sl in self._weather_sliders.items()}
        threading.Thread(target=self._carla.set_weather_custom, args=(params,), daemon=True).start()


def launch():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CarlaGuiApp()
    win.show()
    sys.exit(app.exec_())
