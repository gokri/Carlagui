"""
Real-time vehicle dynamics HUD window.
Add any metric via dropdown. Each panel shows current value + sparkline chart.
Runs standalone (imported by exported .py scripts too).
"""

import time
import threading
import math
from collections import deque
from typing import Callable, Dict, List, Optional, Tuple

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QGridLayout, QSizePolicy,
    QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath

# ─────────────────────────────────────────────────────────────────────────────
# Metric definitions — (label, unit, getter(world, player) → float, warn, crit)
# ─────────────────────────────────────────────────────────────────────────────
def _ttc(world, player):
    """Time-to-collision with nearest vehicle ahead (seconds). -1 = no threat."""
    try:
        ego_t = player.get_transform()
        ego_v = player.get_velocity()
        ego_speed = math.sqrt(ego_v.x**2 + ego_v.y**2)
        if ego_speed < 0.5:
            return 999.0
        import math as _m
        fwd = ego_t.get_forward_vector()
        best = 999.0
        for actor in world.get_actors().filter("vehicle.*"):
            if actor.id == player.id:
                continue
            d = actor.get_transform().location - ego_t.location
            dot = d.x * fwd.x + d.y * fwd.y
            if dot < 0 or dot > 80:
                continue
            lateral = abs(d.x * fwd.y - d.y * fwd.x)
            if lateral > 2.0:
                continue
            other_v = actor.get_velocity()
            rel_speed = ego_speed - math.sqrt(other_v.x**2 + other_v.y**2)
            if rel_speed < 0.1:
                continue
            ttc = dot / rel_speed
            if ttc < best:
                best = ttc
        return round(best, 2)
    except Exception:
        return -1.0


METRIC_REGISTRY: Dict[str, Tuple[str, Callable, float, float]] = {
    # key: (unit, getter, warn_threshold, crit_threshold)
    "Speed (km/h)":        ("km/h",  lambda w, p: round(p.get_velocity().length() * 3.6, 1),         80,  120),
    "Speed (m/s)":         ("m/s",   lambda w, p: round(p.get_velocity().length(), 2),               22,   33),
    "Acceleration":        ("m/s²",  lambda w, p: round(p.get_acceleration().length(), 2),            5,   10),
    "Throttle":            ("",      lambda w, p: round(p.get_control().throttle, 3),                0.8,   1),
    "Brake":               ("",      lambda w, p: round(p.get_control().brake, 3),                   0.5,   1),
    "Steer":               ("",      lambda w, p: round(p.get_control().steer, 3),                   0.5,   1),
    "Gear":                ("",      lambda w, p: float(p.get_control().gear),                        5,   8),
    "Location X":          ("m",     lambda w, p: round(p.get_transform().location.x, 1),           500, 1000),
    "Location Y":          ("m",     lambda w, p: round(p.get_transform().location.y, 1),           500, 1000),
    "Location Z":          ("m",     lambda w, p: round(p.get_transform().location.z, 1),            10,   50),
    "Heading (yaw)":       ("°",     lambda w, p: round(p.get_transform().rotation.yaw, 1),         180,  360),
    "Pitch":               ("°",     lambda w, p: round(p.get_transform().rotation.pitch, 1),        10,   30),
    "Angular Vel Z":       ("°/s",   lambda w, p: round(p.get_angular_velocity().z, 2),             30,   90),
    "Vel X":               ("m/s",   lambda w, p: round(p.get_velocity().x, 2),                     22,   33),
    "Vel Y":               ("m/s",   lambda w, p: round(p.get_velocity().y, 2),                     22,   33),
    "Road ID":             ("",      lambda w, p: float(w.get_map().get_waypoint(p.get_transform().location).road_id), 999, 9999),
    "Lane ID":             ("",      lambda w, p: float(w.get_map().get_waypoint(p.get_transform().location).lane_id), 99, 999),
    "TTC":                 ("s",     _ttc,                                                            3,    1.5),
    "Hand Brake":          ("",      lambda w, p: float(p.get_control().hand_brake),                 1,    1),
    "Reverse":             ("",      lambda w, p: float(p.get_control().reverse),                    1,    1),
}

HISTORY_LEN = 120   # samples to keep per metric


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline canvas
# ─────────────────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    def __init__(self, history: deque, warn: float, crit: float, low_is_bad=False):
        super().__init__()
        self.history = history
        self.warn = warn
        self.crit = crit
        self.low_is_bad = low_is_bad
        self.setMinimumHeight(50)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(18, 18, 24))

        data = list(self.history)
        if len(data) < 2:
            return

        mn, mx = min(data), max(data)
        span = mx - mn or 1.0

        # Warn/crit zones
        def _y(v):
            return h - int((v - mn) / span * (h - 4)) - 2

        # Determine line colour from latest value
        last = data[-1]
        if self.low_is_bad:
            color = QColor(231, 76, 60) if last < self.crit else QColor(241, 196, 15) if last < self.warn else QColor(46, 204, 113)
        else:
            color = QColor(231, 76, 60) if last > self.crit else QColor(241, 196, 15) if last > self.warn else QColor(46, 204, 113)

        path = QPainterPath()
        step = w / max(len(data) - 1, 1)
        path.moveTo(0, _y(data[0]))
        for i, v in enumerate(data[1:], 1):
            path.lineTo(i * step, _y(v))

        pen = QPen(color, 1.5)
        p.setPen(pen)
        p.drawPath(path)

        # Min/max labels
        p.setPen(QPen(QColor(90, 90, 110)))
        p.setFont(QFont("Monospace", 6))
        p.drawText(2, h - 2, f"{mn:.1f}")
        p.drawText(2, 10, f"{mx:.1f}")


# ─────────────────────────────────────────────────────────────────────────────
# Single metric panel
# ─────────────────────────────────────────────────────────────────────────────
class MetricPanel(QFrame):
    remove_requested = pyqtSignal(str)

    def __init__(self, metric_name: str):
        super().__init__()
        self.metric_name = metric_name
        unit, getter, warn, crit = METRIC_REGISTRY[metric_name]
        self.unit = unit
        self.getter = getter
        self.warn = warn
        self.crit = crit
        self.history = deque(maxlen=HISTORY_LEN)
        self._last_val = 0.0
        low_is_bad = metric_name == "TTC"

        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("QFrame { background:#1a1a24; border:1px solid #333; border-radius:4px; }")
        self.setMinimumWidth(160)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(2)

        hdr = QHBoxLayout()
        name_lbl = QLabel(metric_name)
        name_lbl.setFont(QFont("Monospace", 8, QFont.Bold))
        name_lbl.setStyleSheet("color:#aaa; border:none;")
        hdr.addWidget(name_lbl)
        hdr.addStretch()
        rm_btn = QPushButton("✕")
        rm_btn.setFixedSize(16, 16)
        rm_btn.setStyleSheet("background:transparent;color:#666;border:none;font-size:10px;")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self.metric_name))
        hdr.addWidget(rm_btn)
        v.addLayout(hdr)

        self._value_lbl = QLabel("—")
        self._value_lbl.setFont(QFont("Monospace", 20, QFont.Bold))
        self._value_lbl.setAlignment(Qt.AlignCenter)
        self._value_lbl.setStyleSheet("color:#e0e0e0; border:none;")
        v.addWidget(self._value_lbl)

        self._unit_lbl = QLabel(unit or "")
        self._unit_lbl.setAlignment(Qt.AlignCenter)
        self._unit_lbl.setFont(QFont("Monospace", 8))
        self._unit_lbl.setStyleSheet("color:#888; border:none;")
        v.addWidget(self._unit_lbl)

        self._spark = Sparkline(self.history, warn, crit, low_is_bad)
        v.addWidget(self._spark)

    def update_value(self, world, player):
        try:
            val = self.getter(world, player)
            self._last_val = val
            self.history.append(val)
            # Colour by threshold
            low_is_bad = self.metric_name == "TTC"
            if low_is_bad:
                color = "#e74c3c" if val < self.crit else "#f1c40f" if val < self.warn else "#2ecc71"
            else:
                color = "#e74c3c" if val > self.crit else "#f1c40f" if val > self.warn else "#2ecc71"
            self._value_lbl.setText(f"{val:.2f}" if isinstance(val, float) else str(val))
            self._value_lbl.setStyleSheet(f"color:{color}; border:none;")
            self._spark.update()
        except Exception as exc:
            self._value_lbl.setText("ERR")
            self._value_lbl.setStyleSheet("color:#e74c3c; border:none;")

    def get_last(self):
        return self._last_val


# ─────────────────────────────────────────────────────────────────────────────
# HUD window
# ─────────────────────────────────────────────────────────────────────────────
class HudWindow(QDialog):
    def __init__(self, carla_client=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vehicle Dynamics HUD")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(880, 460)
        self._client = carla_client
        self._panels: Dict[str, MetricPanel] = {}
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(100)   # 10Hz

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Add metric:"))
        self._metric_combo = QComboBox()
        self._metric_combo.addItems(sorted(METRIC_REGISTRY.keys()))
        self._metric_combo.setMinimumWidth(200)
        toolbar.addWidget(self._metric_combo)
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_metric)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        self._rate_spin = QSpinBox()
        self._rate_spin.setRange(1, 60)
        self._rate_spin.setValue(10)
        self._rate_spin.setSuffix(" Hz")
        self._rate_spin.valueChanged.connect(
            lambda v: self._poll_timer.setInterval(int(1000 / v)))
        toolbar.addWidget(QLabel("Poll rate:"))
        toolbar.addWidget(self._rate_spin)
        root.addLayout(toolbar)

        # Scroll area for panels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._panel_container = QWidget()
        self._panel_grid = QGridLayout(self._panel_container)
        self._panel_grid.setSpacing(6)
        scroll.setWidget(self._panel_container)
        root.addWidget(scroll, stretch=1)

        # Status bar
        self._status_lbl = QLabel("No vehicle connected.")
        self._status_lbl.setFont(QFont("Monospace", 8))
        self._status_lbl.setStyleSheet("color:#888;")
        root.addWidget(self._status_lbl)

    def _add_metric(self, metric_name: str = None):
        name = metric_name or self._metric_combo.currentText()
        if name in self._panels:
            return
        panel = MetricPanel(name)
        panel.remove_requested.connect(self._remove_metric)
        self._panels[name] = panel
        # Layout in a 4-column grid
        idx = len(self._panels) - 1
        self._panel_grid.addWidget(panel, idx // 4, idx % 4)

    def _remove_metric(self, name: str):
        panel = self._panels.pop(name, None)
        if panel:
            self._panel_grid.removeWidget(panel)
            panel.deleteLater()
        # Re-layout remaining
        for i, p in enumerate(self._panels.values()):
            self._panel_grid.addWidget(p, i // 4, i % 4)

    def _poll(self):
        if not self._client:
            return
        world = getattr(self._client, "world", None)
        player = getattr(self._client, "player", None)
        if not world or not player:
            self._status_lbl.setText("Waiting for vehicle…")
            return
        self._status_lbl.setText(
            f"Polling at {self._rate_spin.value()} Hz — {len(self._panels)} metric(s)")
        for panel in self._panels.values():
            panel.update_value(world, player)

    def add_metrics(self, names: List[str]):
        """Convenience: add multiple metrics at once."""
        for n in names:
            if n in METRIC_REGISTRY:
                self._add_metric(n)

    def closeEvent(self, e):
        e.ignore()
        self.hide()


# ─────────────────────────────────────────────────────────────────────────────
# Standalone runner (called by exported .py scripts)
# ─────────────────────────────────────────────────────────────────────────────
class _StandaloneClient:
    """Minimal carla_client duck-type for standalone use."""
    def __init__(self, host, port):
        import carla
        self.client = carla.Client(host, port)
        self.client.set_timeout(10.0)
        self.world = self.client.get_world()
        self.player = None
        # Find hero vehicle
        for a in self.world.get_actors().filter("vehicle.*"):
            if a.attributes.get("role_name") == "hero":
                self.player = a
                break
        if not self.player:
            actors = list(self.world.get_actors().filter("vehicle.*"))
            if actors:
                self.player = actors[0]


def run_standalone_hud(host="localhost", port=2000, metrics=None):
    """
    Open the HUD window as a standalone app.
    metrics: list of metric names from METRIC_REGISTRY (None = default set)
    """
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    client = _StandaloneClient(host, port)
    win = HudWindow(carla_client=client)
    default_metrics = metrics or [
        "Speed (km/h)", "TTC", "Throttle", "Brake", "Steer",
        "Location X", "Location Y", "Heading (yaw)",
    ]
    win.add_metrics(default_metrics)
    win.setWindowFlag(Qt.WindowCloseButtonHint, True)
    win.closeEvent = lambda e: app.quit()
    win.show()
    sys.exit(app.exec_())
