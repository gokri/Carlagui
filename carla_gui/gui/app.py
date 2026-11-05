"""Main application window — CARLA 0.9.16 GUI Control Panel."""

import sys
import threading
import logging
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QGroupBox, QSlider, QTextEdit, QSplitter, QGridLayout, QSpinBox,
    QProgressBar, QListWidget, QMessageBox, QFrame,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QTextCursor

from carla_client.client import CarlaClient, scan_ports
from scenarios.pedestrian_crossing import ScenarioRunner, SCENARIO_LIST

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Signal bridge — emit from any thread, receive on Qt main thread
# ─────────────────────────────────────────────────────────────────────────────
class _Bridge(QObject):
    log_signal = pyqtSignal(str)
    blueprints_signal = pyqtSignal(list)
    weather_signal = pyqtSignal(list)
    status_signal = pyqtSignal(bool)   # connected T/F


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────
class CarlaGuiApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CARLA 0.9.16 — Control Panel")
        self.setMinimumSize(900, 680)

        self._bridge = _Bridge()
        self._bridge.log_signal.connect(self._append_log)
        self._bridge.blueprints_signal.connect(self._populate_blueprints)
        self._bridge.weather_signal.connect(self._populate_weather)
        self._bridge.status_signal.connect(self._on_connection_changed)

        self._carla = CarlaClient(on_log=lambda m: self._bridge.log_signal.emit(m))
        self._scenario_runner = None

        self._build_ui()
        self._set_connected(False)

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # ── status bar (top) ──────────────────────────────────────────────
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

        # ── tabs ─────────────────────────────────────────────────────────
        tabs = QTabWidget()
        root.addWidget(tabs, stretch=1)

        tabs.addTab(self._build_connection_tab(), "🔌 Connection")
        tabs.addTab(self._build_vehicle_tab(), "🚗 Vehicle")
        tabs.addTab(self._build_controls_tab(), "🎮 Controls")
        tabs.addTab(self._build_weather_tab(), "🌦 Weather")
        tabs.addTab(self._build_scenarios_tab(), "🗺 Scenarios")
        tabs.addTab(self._build_terminal_tab(), "🖥 Terminal")

    # ── Connection tab ───────────────────────────────────────────────────────
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

        grid.addWidget(QLabel("Available ports:"), 1, 0)
        self._port_list = QListWidget()
        self._port_list.setMaximumHeight(80)
        self._port_list.itemClicked.connect(
            lambda item: self._port_spin.setValue(int(item.text()))
        )
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

        # Server info
        info_grp = QGroupBox("Server Info")
        info_grid = QGridLayout(info_grp)
        self._info_map = QLabel("—")
        self._info_loc = QLabel("—")
        info_grid.addWidget(QLabel("Map:"), 0, 0)
        info_grid.addWidget(self._info_map, 0, 1)
        info_grid.addWidget(QLabel("Spectator:"), 1, 0)
        info_grid.addWidget(self._info_loc, 1, 1)
        v.addWidget(info_grp)

        # Refresh timer
        self._info_timer = QTimer()
        self._info_timer.timeout.connect(self._refresh_info)
        self._info_timer.start(2000)

        v.addStretch()
        return w

    # ── Vehicle tab ──────────────────────────────────────────────────────────
    def _build_vehicle_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # Blueprint selection
        bp_grp = QGroupBox("Blueprint")
        bp_layout = QHBoxLayout(bp_grp)
        bp_layout.addWidget(QLabel("Vehicle:"))
        self._bp_combo = QComboBox()
        self._bp_combo.setMinimumWidth(300)
        bp_layout.addWidget(self._bp_combo, stretch=1)
        self._refresh_bp_btn = QPushButton("↻")
        self._refresh_bp_btn.setFixedWidth(32)
        self._refresh_bp_btn.clicked.connect(self._load_blueprints)
        bp_layout.addWidget(self._refresh_bp_btn)
        v.addWidget(bp_grp)

        # Autopilot
        ap_grp = QGroupBox("Autopilot")
        ap_layout = QHBoxLayout(ap_grp)
        self._autopilot_check = QCheckBox("Enable autopilot on spawn")
        ap_layout.addWidget(self._autopilot_check)
        self._ap_toggle_btn = QPushButton("Toggle Autopilot (P)")
        self._ap_toggle_btn.clicked.connect(self._toggle_autopilot)
        ap_layout.addWidget(self._ap_toggle_btn)
        self._autopilot_state = False
        v.addWidget(ap_grp)

        # Spawn / Destroy
        spawn_row = QHBoxLayout()
        self._spawn_btn = QPushButton("Spawn Vehicle")
        self._spawn_btn.setFixedHeight(36)
        self._spawn_btn.clicked.connect(self._spawn_vehicle)
        self._destroy_btn = QPushButton("Destroy Vehicle")
        self._destroy_btn.setFixedHeight(36)
        self._destroy_btn.clicked.connect(self._destroy_vehicle)
        spawn_row.addWidget(self._spawn_btn)
        spawn_row.addWidget(self._destroy_btn)
        v.addLayout(spawn_row)

        # Lights
        lights_grp = QGroupBox("Lights")
        lights_layout = QHBoxLayout(lights_grp)
        lights_layout.addWidget(QLabel("Light state:"))
        self._lights_combo = QComboBox()
        self._lights_combo.addItems([
            "Off", "Position", "Low Beam", "High Beam", "Fog",
            "Interior", "Left Blinker", "Right Blinker", "All",
        ])
        self._lights_combo.currentTextChanged.connect(
            lambda t: threading.Thread(target=self._carla.set_light_state, args=(t,), daemon=True).start()
        )
        lights_layout.addWidget(self._lights_combo)
        v.addWidget(lights_grp)

        # Doors
        doors_grp = QGroupBox("Doors")
        doors_layout = QHBoxLayout(doors_grp)
        open_btn = QPushButton("Open All (O)")
        open_btn.clicked.connect(lambda: threading.Thread(
            target=self._carla.open_doors, args=(True,), daemon=True).start())
        close_btn = QPushButton("Close All")
        close_btn.clicked.connect(lambda: threading.Thread(
            target=self._carla.open_doors, args=(False,), daemon=True).start())
        doors_layout.addWidget(open_btn)
        doors_layout.addWidget(close_btn)
        v.addWidget(doors_grp)

        v.addStretch()
        return w

    # ── Controls tab ─────────────────────────────────────────────────────────
    def _build_controls_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        note = QLabel(
            "These replicate manual_control.py hotkeys. Vehicle must be spawned. "
            "Autopilot must be OFF for throttle/steer/brake."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        # Throttle / Brake / Steer sliders
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
        self._reverse_check = QCheckBox("Q — toggle reverse")
        self._reverse_check.stateChanged.connect(lambda _: self._send_control())
        g.addWidget(self._reverse_check, 4, 1)

        reset_btn = QPushButton("Reset all to 0")
        reset_btn.clicked.connect(self._reset_controls)
        g.addWidget(reset_btn, 5, 0, 1, 3)

        v.addWidget(drive_grp)

        # Action buttons row
        action_grp = QGroupBox("Actions (hotkeys from manual_control.py)")
        ag = QGridLayout(action_grp)

        actions = [
            ("Toggle Autopilot (P)", self._toggle_autopilot),
            ("Toggle Camera (TAB)", lambda: self._log_action("camera toggle — needs pygame window")),
            ("Next Weather (C)", self._next_weather),
            ("Prev Weather (Shift+C)", self._prev_weather),
            ("Toggle Radar (G)", lambda: self._log_action("Radar toggle — needs sensor setup")),
            ("Toggle Recording (R)", lambda: self._log_action("Recording toggle — CTRL+R in full client")),
            ("Open Doors (O)", lambda: threading.Thread(target=self._carla.open_doors, args=(True,), daemon=True).start()),
            ("Close Doors", lambda: threading.Thread(target=self._carla.open_doors, args=(False,), daemon=True).start()),
            ("High Beam (Shift+L)", lambda: threading.Thread(target=self._carla.set_light_state, args=("High Beam",), daemon=True).start()),
            ("Left Blinker (Z)", lambda: threading.Thread(target=self._carla.set_light_state, args=("Left Blinker",), daemon=True).start()),
            ("Right Blinker (X)", lambda: threading.Thread(target=self._carla.set_light_state, args=("Right Blinker",), daemon=True).start()),
            ("All Lights On", lambda: threading.Thread(target=self._carla.set_light_state, args=("All",), daemon=True).start()),
        ]

        for i, (label, fn) in enumerate(actions):
            btn = QPushButton(label)
            btn.clicked.connect(fn)
            ag.addWidget(btn, i // 3, i % 3)

        v.addWidget(action_grp)
        v.addStretch()
        return w

    # ── Weather tab ──────────────────────────────────────────────────────────
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
        prev_w = QPushButton("◀ Prev (Shift+C)")
        prev_w.clicked.connect(self._prev_weather)
        next_w = QPushButton("Next (C) ▶")
        next_w.clicked.connect(self._next_weather)
        nav_row.addWidget(prev_w)
        nav_row.addWidget(next_w)
        v.addLayout(nav_row)

        # Custom sliders
        custom_grp = QGroupBox("Custom Parameters")
        cg = QGridLayout(custom_grp)
        self._weather_sliders = {}
        params = [
            ("cloudiness", 0, 100),
            ("precipitation", 0, 100),
            ("precipitation_deposits", 0, 100),
            ("wind_intensity", 0, 100),
            ("sun_azimuth_angle", 0, 360),
            ("sun_altitude_angle", -90, 90),
            ("fog_density", 0, 100),
            ("fog_distance", 0, 100),
            ("wetness", 0, 100),
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

    # ── Scenarios tab ────────────────────────────────────────────────────────
    def _build_scenarios_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        note = QLabel(
            "Spawn open scenarios in the connected CARLA world. "
            "A vehicle must NOT need to be pre-spawned — scenarios handle their own actors."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        sc_grp = QGroupBox("Open Scenario")
        sh = QHBoxLayout(sc_grp)
        self._scenario_combo = QComboBox()
        self._scenario_combo.addItems(SCENARIO_LIST)
        sh.addWidget(QLabel("Scenario:"))
        sh.addWidget(self._scenario_combo, stretch=1)
        run_btn = QPushButton("Run Scenario")
        run_btn.clicked.connect(self._run_scenario)
        sh.addWidget(run_btn)
        clear_btn = QPushButton("Clear Actors")
        clear_btn.clicked.connect(self._clear_scenario)
        sh.addWidget(clear_btn)
        v.addWidget(sc_grp)

        v.addStretch()
        return w

    # ── Terminal tab ─────────────────────────────────────────────────────────
    def _build_terminal_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        label = QLabel("CARLA client log — errors, warnings, and status messages appear here.")
        v.addWidget(label)

        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setFont(QFont("Monospace", 9))
        self._terminal.setStyleSheet(
            "background:#111; color:#e0e0e0;"
        )
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

    def _log_action(self, msg: str):
        self._bridge.log_signal.emit(f"[INFO] {msg}")

    def _set_connected(self, connected: bool):
        color = "#2ecc71" if connected else "#e74c3c"
        self._status_dot.setStyleSheet(f"color: {color}; font-size:16px;")
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

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def _scan_ports(self):
        host = self._host_edit.text().strip()
        self._port_list.clear()
        self._append_log(f"[INFO] Scanning {host}:2000-2018 ...")

        def _do():
            ports = scan_ports(host)
            self._port_list.addItems([str(p) for p in ports])
            if ports:
                self._bridge.log_signal.emit(f"[OK] Found ports: {ports}")
            else:
                self._bridge.log_signal.emit("[WARN] No open CARLA ports found.")

        threading.Thread(target=_do, daemon=True).start()

    def _connect(self):
        host = self._host_edit.text().strip()
        port = self._port_spin.value()
        self._append_log(f"[INFO] Connecting to {host}:{port} ...")

        def _do():
            ok = self._carla.connect(host, port)
            self._bridge.status_signal.emit(ok)
            if ok:
                bps = self._carla.get_vehicle_blueprints()
                self._bridge.blueprints_signal.emit(bps)
                presets = self._carla.get_weather_presets()
                self._bridge.weather_signal.emit(presets)
                self._scenario_runner = ScenarioRunner(
                    self._carla, on_log=lambda m: self._bridge.log_signal.emit(m)
                )

        threading.Thread(target=_do, daemon=True).start()

    def _disconnect(self):
        self._carla.disconnect()
        self._bridge.status_signal.emit(False)

    def _load_blueprints(self):
        threading.Thread(
            target=lambda: self._bridge.blueprints_signal.emit(self._carla.get_vehicle_blueprints()),
            daemon=True,
        ).start()

    def _refresh_info(self):
        if self._carla.connected:
            self._info_map.setText(self._carla.get_map_name())
            self._info_loc.setText(self._carla.get_spectator_location())
            self._map_label.setText(f"Map: {self._carla.get_map_name()}")

    def _spawn_vehicle(self):
        bp = self._bp_combo.currentText()
        ap = self._autopilot_check.isChecked()
        threading.Thread(target=self._carla.spawn_vehicle, args=(bp, ap), daemon=True).start()

    def _destroy_vehicle(self):
        threading.Thread(target=self._carla.destroy_vehicle, daemon=True).start()

    def _toggle_autopilot(self):
        self._autopilot_state = not self._autopilot_state
        threading.Thread(target=self._carla.set_autopilot, args=(self._autopilot_state,), daemon=True).start()

    def _send_control(self):
        threading.Thread(
            target=self._carla.apply_control,
            kwargs=dict(
                throttle=self._throttle_slider.value() / 100.0,
                steer=self._steer_slider.value() / 100.0,
                brake=self._brake_slider.value() / 100.0,
                hand_brake=self._handbrake_check.isChecked(),
                reverse=self._reverse_check.isChecked(),
            ),
            daemon=True,
        ).start()

    def _reset_controls(self):
        for sl in (self._throttle_slider, self._brake_slider):
            sl.setValue(0)
        self._steer_slider.setValue(0)
        self._handbrake_check.setChecked(False)
        self._reverse_check.setChecked(False)

    # weather index tracker
    _weather_idx = 0

    def _next_weather(self):
        presets = [self._weather_combo.itemText(i) for i in range(self._weather_combo.count())]
        if not presets:
            return
        self._weather_idx = (self._weather_idx + 1) % len(presets)
        self._weather_combo.setCurrentIndex(self._weather_idx)
        threading.Thread(target=self._carla.set_weather, args=(presets[self._weather_idx],), daemon=True).start()

    def _prev_weather(self):
        presets = [self._weather_combo.itemText(i) for i in range(self._weather_combo.count())]
        if not presets:
            return
        self._weather_idx = (self._weather_idx - 1) % len(presets)
        self._weather_combo.setCurrentIndex(self._weather_idx)
        threading.Thread(target=self._carla.set_weather, args=(presets[self._weather_idx],), daemon=True).start()

    def _apply_weather_preset(self):
        preset = self._weather_combo.currentText()
        threading.Thread(target=self._carla.set_weather, args=(preset,), daemon=True).start()

    def _apply_custom_weather(self):
        params = {k: sl.value() for k, sl in self._weather_sliders.items()}
        threading.Thread(target=self._carla.set_weather_custom, args=(params,), daemon=True).start()

    def _run_scenario(self):
        if not self._scenario_runner:
            self._append_log("[ERR] Not connected to CARLA.")
            return
        self._scenario_runner.run(self._scenario_combo.currentText())

    def _clear_scenario(self):
        if self._scenario_runner:
            threading.Thread(target=self._scenario_runner.cleanup, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
def launch():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CarlaGuiApp()
    win.show()
    sys.exit(app.exec_())
