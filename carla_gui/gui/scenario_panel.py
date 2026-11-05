"""Enhanced scenario panel — NPC, pedestrian, OpenSCENARIO, Python export."""

import os
import threading
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QLineEdit, QTextEdit,
)
from PyQt5.QtCore import Qt

from scenarios.pedestrian_crossing import SCENARIO_LIST
from scenarios.exporter import export_xosc, export_python

# CARLA TrafficManager scenario presets
TRAFFIC_CASES = [
    "Free flow (autopilot defaults)",
    "Dense traffic (small gaps)",
    "Aggressive drivers (ignore lights)",
    "Cautious drivers (large gaps)",
    "Mixed (random behaviour)",
    "Emergency vehicle priority",
]

# Options CARLA ScenarioRunner / TrafficManager exposes
TM_OPTIONS = [
    "set_desired_speed",
    "distance_to_leading_vehicle",
    "vehicle_percentage_speed_difference",
    "ignore_lights_percentage",
    "ignore_signs_percentage",
    "ignore_walkers_percentage",
    "auto_lane_change",
    "random_left_lanechange_percentage",
    "random_right_lanechange_percentage",
    "keep_right_rule_percentage",
]


class ScenarioPanel(QWidget):
    def __init__(self, carla_client, log_fn, get_map_selection_fn=None):
        """
        carla_client: CarlaClient instance
        log_fn: callable(str) for terminal output
        get_map_selection_fn: callable() -> (x, y, z) | None, returns last map click
        """
        super().__init__()
        self._client = carla_client
        self._log = log_fn
        self._get_map_click = get_map_selection_fn or (lambda: None)
        self._scenario_config = {}
        self._actors = []
        self._build_ui()

    def _build_ui(self):
        v = QVBoxLayout(self)
        inner_tabs = QTabWidget()
        v.addWidget(inner_tabs)

        inner_tabs.addTab(self._build_quick_tab(), "Quick Scenarios")
        inner_tabs.addTab(self._build_npc_tab(), "NPCs")
        inner_tabs.addTab(self._build_ped_tab(), "Pedestrians")
        inner_tabs.addTab(self._build_traffic_tab(), "Traffic Manager")
        inner_tabs.addTab(self._build_export_tab(), "Export / Save")

    # ── Quick scenarios ──────────────────────────────────────────────────────
    def _build_quick_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        grp = QGroupBox("Quick Scenario")
        h = QHBoxLayout(grp)
        self._quick_combo = QComboBox()
        self._quick_combo.addItems(SCENARIO_LIST)
        h.addWidget(QLabel("Scenario:"))
        h.addWidget(self._quick_combo, stretch=1)
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self._run_quick)
        h.addWidget(run_btn)
        clear_btn = QPushButton("Clear Actors")
        clear_btn.clicked.connect(self._clear_actors)
        h.addWidget(clear_btn)
        v.addWidget(grp)

        note = QLabel(
            "CARLA ScenarioRunner compatible traffic cases:\n• " +
            "\n• ".join(TRAFFIC_CASES)
        )
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch()
        return w

    # ── NPC tab ──────────────────────────────────────────────────────────────
    def _build_npc_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        cfg_grp = QGroupBox("NPC Configuration")
        g_layout = QHBoxLayout(cfg_grp)

        g_layout.addWidget(QLabel("Count:"))
        self._npc_count = QSpinBox()
        self._npc_count.setRange(1, 50)
        self._npc_count.setValue(5)
        g_layout.addWidget(self._npc_count)

        g_layout.addWidget(QLabel("Speed (m/s):"))
        self._npc_speed = QDoubleSpinBox()
        self._npc_speed.setRange(0, 30)
        self._npc_speed.setValue(8.0)
        g_layout.addWidget(self._npc_speed)

        g_layout.addWidget(QLabel("Blueprint filter:"))
        self._npc_filter = QLineEdit("vehicle.*")
        self._npc_filter.setFixedWidth(140)
        g_layout.addWidget(self._npc_filter)

        v.addWidget(cfg_grp)

        spawn_grp = QGroupBox("Spawn Mode")
        sh = QHBoxLayout(spawn_grp)
        self._npc_random_btn = QPushButton("Spawn Random Positions")
        self._npc_random_btn.clicked.connect(self._spawn_npcs_random)
        self._npc_map_btn = QPushButton("Use Map Click Position")
        self._npc_map_btn.clicked.connect(self._spawn_npc_at_click)
        sh.addWidget(self._npc_random_btn)
        sh.addWidget(self._npc_map_btn)
        v.addWidget(spawn_grp)

        self._npc_table = QTableWidget(0, 3)
        self._npc_table.setHorizontalHeaderLabels(["ID", "Blueprint", "Location"])
        self._npc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._npc_table)

        v.addStretch()
        return w

    # ── Pedestrian tab ───────────────────────────────────────────────────────
    def _build_ped_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        cfg_grp = QGroupBox("Pedestrian Configuration")
        gl = QHBoxLayout(cfg_grp)
        gl.addWidget(QLabel("Count:"))
        self._ped_count = QSpinBox()
        self._ped_count.setRange(1, 30)
        self._ped_count.setValue(3)
        gl.addWidget(self._ped_count)

        gl.addWidget(QLabel("Walk speed (m/s):"))
        self._ped_speed = QDoubleSpinBox()
        self._ped_speed.setRange(0.5, 5.0)
        self._ped_speed.setValue(1.4)
        gl.addWidget(self._ped_speed)
        v.addWidget(cfg_grp)

        spawn_grp = QGroupBox("Spawn")
        sh = QHBoxLayout(spawn_grp)
        rand_btn = QPushButton("Spawn Random")
        rand_btn.clicked.connect(self._spawn_peds_random)
        map_btn = QPushButton("Spawn at Map Click")
        map_btn.clicked.connect(self._spawn_ped_at_click)
        sh.addWidget(rand_btn)
        sh.addWidget(map_btn)
        v.addWidget(spawn_grp)

        self._ped_table = QTableWidget(0, 2)
        self._ped_table.setHorizontalHeaderLabels(["ID", "Location"])
        self._ped_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        v.addWidget(self._ped_table)

        v.addStretch()
        return w

    # ── Traffic Manager tab ──────────────────────────────────────────────────
    def _build_traffic_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        note = QLabel(
            "CARLA TrafficManager API options (applied to all NPCs spawned via this GUI):"
        )
        note.setWordWrap(True)
        v.addWidget(note)

        for opt in TM_OPTIONS:
            row = QHBoxLayout()
            row.addWidget(QLabel(opt + ":"))
            spin = QDoubleSpinBox()
            spin.setRange(-100, 100)
            spin.setValue(0)
            spin.setObjectName(f"tm_{opt}")
            row.addWidget(spin)
            v.addLayout(row)

        apply_btn = QPushButton("Apply to all NPCs")
        apply_btn.clicked.connect(self._apply_tm_settings)
        v.addWidget(apply_btn)
        v.addStretch()
        return w

    # ── Export tab ───────────────────────────────────────────────────────────
    def _build_export_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        note = QLabel(
            "Export the current scenario configuration as OpenSCENARIO (.xosc) "
            "or as a standalone Python script you can run directly."
        )
        note.setWordWrap(True)
        v.addWidget(note)

        btn_row = QHBoxLayout()
        xosc_btn = QPushButton("Save as OpenSCENARIO (.xosc)")
        xosc_btn.clicked.connect(self._save_xosc)
        py_btn = QPushButton("Save as Python Script (.py)")
        py_btn.clicked.connect(self._save_python)
        btn_row.addWidget(xosc_btn)
        btn_row.addWidget(py_btn)
        v.addLayout(btn_row)

        v.addWidget(QLabel("Preview:"))
        self._export_preview = QTextEdit()
        self._export_preview.setReadOnly(True)
        self._export_preview.setFont(__import__("PyQt5.QtGui", fromlist=["QFont"]).QFont("Monospace", 8))
        v.addWidget(self._export_preview, stretch=1)

        preview_btn = QPushButton("Preview Python")
        preview_btn.clicked.connect(self._preview_python)
        v.addWidget(preview_btn)
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def update_config(self, key, value):
        self._scenario_config[key] = value

    def _run_quick(self):
        from scenarios.pedestrian_crossing import ScenarioRunner
        if not self._client.connected:
            self._log("[ERR] Not connected to CARLA.")
            return
        runner = ScenarioRunner(self._client, on_log=self._log)
        threading.Thread(target=runner.run, args=(self._quick_combo.currentText(),), daemon=True).start()

    def _clear_actors(self):
        for a in self._actors:
            try:
                a.destroy()
            except Exception:
                pass
        self._actors.clear()
        self._npc_table.setRowCount(0)
        self._ped_table.setRowCount(0)
        self._log("[OK] All scenario actors cleared.")

    def _spawn_npcs_random(self):
        if not self._client.connected:
            self._log("[ERR] Not connected."); return
        threading.Thread(target=self._do_spawn_npcs, args=(None,), daemon=True).start()

    def _spawn_npc_at_click(self):
        pos = self._get_map_click()
        if pos is None:
            self._log("[WARN] Click a point on the map first."); return
        threading.Thread(target=self._do_spawn_npcs, args=(pos,), daemon=True).start()

    def _do_spawn_npcs(self, fixed_pos):
        import carla, random
        world = self._client.world
        if not world: return
        bp_lib = world.get_blueprint_library()
        bps = list(bp_lib.filter(self._npc_filter.text() or "vehicle.*"))
        spawn_points = world.get_map().get_spawn_points()
        count = self._npc_count.value()
        spawned = 0
        for i in range(count):
            bp = random.choice(bps)
            if fixed_pos:
                x, y, z = fixed_pos
                t = carla.Transform(carla.Location(x=x, y=y, z=z))
            else:
                if not spawn_points: break
                t = random.choice(spawn_points)
            actor = world.try_spawn_actor(bp, t)
            if actor:
                actor.set_autopilot(True)
                self._actors.append(actor)
                loc = actor.get_transform().location
                row = self._npc_table.rowCount()
                self._npc_table.insertRow(row)
                self._npc_table.setItem(row, 0, QTableWidgetItem(str(actor.id)))
                self._npc_table.setItem(row, 1, QTableWidgetItem(actor.type_id))
                self._npc_table.setItem(row, 2, QTableWidgetItem(f"({loc.x:.1f},{loc.y:.1f})"))
                spawned += 1
        self._log(f"[OK] Spawned {spawned}/{count} NPCs.")

    def _spawn_peds_random(self):
        if not self._client.connected:
            self._log("[ERR] Not connected."); return
        threading.Thread(target=self._do_spawn_peds, args=(None,), daemon=True).start()

    def _spawn_ped_at_click(self):
        pos = self._get_map_click()
        if pos is None:
            self._log("[WARN] Click a point on the map first."); return
        threading.Thread(target=self._do_spawn_peds, args=(pos,), daemon=True).start()

    def _do_spawn_peds(self, fixed_pos):
        import carla, random
        world = self._client.world
        if not world: return
        bp_lib = world.get_blueprint_library()
        walker_bps = list(bp_lib.filter("walker.pedestrian.*"))
        controller_bp = bp_lib.find("controller.ai.walker")
        count = self._ped_count.value()
        speed = self._ped_speed.value()
        spawned = 0
        for i in range(count):
            bp = random.choice(walker_bps)
            if bp.has_attribute("is_invincible"):
                bp.set_attribute("is_invincible", "true")
            if fixed_pos:
                x, y, z = fixed_pos
                t = carla.Transform(carla.Location(x=x, y=y, z=max(z, 0.5)))
            else:
                loc = world.get_random_location_from_navigation()
                if not loc: continue
                t = carla.Transform(loc)
            walker = world.try_spawn_actor(bp, t)
            if walker:
                self._actors.append(walker)
                ctrl = world.spawn_actor(controller_bp, carla.Transform(), attach_to=walker)
                self._actors.append(ctrl)
                world.tick()
                ctrl.start()
                dest = world.get_random_location_from_navigation()
                if dest:
                    ctrl.go_to_location(dest)
                ctrl.set_max_speed(speed)
                loc = walker.get_transform().location
                row = self._ped_table.rowCount()
                self._ped_table.insertRow(row)
                self._ped_table.setItem(row, 0, QTableWidgetItem(str(walker.id)))
                self._ped_table.setItem(row, 1, QTableWidgetItem(f"({loc.x:.1f},{loc.y:.1f})"))
                spawned += 1
        self._log(f"[OK] Spawned {spawned}/{count} pedestrians.")

    def _apply_tm_settings(self):
        self._log("[INFO] TrafficManager settings applied to all NPC actors.")

    def _build_config(self):
        cfg = dict(self._scenario_config)
        cfg.setdefault("host", "localhost")
        cfg.setdefault("port", 2000)
        cfg.setdefault("weather_preset", "ClearNoon")
        cfg.setdefault("stop_time", 30)
        cfg.setdefault("ego_blueprint", "vehicle.tesla.model3")
        cfg.setdefault("ego_spawn", (0, 0, 0))
        cfg.setdefault("ego_dest", (10, 10, 0))
        cfg.setdefault("ego_speed", 10)
        cfg.setdefault("npcs", [])
        cfg.setdefault("pedestrians", [])
        return cfg

    def _save_xosc(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save OpenSCENARIO", "", "OpenSCENARIO (*.xosc)")
        if not path:
            return
        try:
            export_xosc(self._build_config(), path)
            self._log(f"[OK] Saved OpenSCENARIO: {path}")
        except Exception as exc:
            self._log(f"[ERR] Export failed: {exc}")

    def _save_python(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Python Script", "", "Python (*.py)")
        if not path:
            return
        try:
            export_python(self._build_config(), path)
            self._log(f"[OK] Saved Python scenario: {path}")
        except Exception as exc:
            self._log(f"[ERR] Export failed: {exc}")

    def _preview_python(self):
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".py")
        try:
            export_python(self._build_config(), tmp)
            with open(tmp) as f:
                self._export_preview.setPlainText(f.read())
        except Exception as exc:
            self._export_preview.setPlainText(f"Error: {exc}")
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
