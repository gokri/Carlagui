"""
Three-view sensor placement widget (Top / Front / Side + isometric).
Click in any view to place a sensor. Drag placed sensor dot to reposition.
Right-drag on dot to rotate orientation arrow.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QComboBox, QPushButton, QDoubleSpinBox, QGroupBox, QFrame,
)
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QFont, QPainterPath

# Vehicle approximate dimensions (metres, used in all views)
VEH_L = 4.5   # X axis (front-back)
VEH_W = 2.0   # Y axis (left-right)
VEH_H = 1.5   # Z axis (up-down)

SENSOR_COLORS = {
    "sensor.camera.rgb":                   QColor(46, 204, 113),
    "sensor.camera.depth":                 QColor(52, 152, 219),
    "sensor.camera.semantic_segmentation": QColor(155, 89, 182),
    "sensor.camera.rgb.bev":               QColor(230, 126, 34),
    "sensor.camera.instance_segmentation": QColor(231, 76, 60),
    "sensor.camera.optical_flow":          QColor(241, 196, 15),
    "sensor.lidar.ray_cast":               QColor(26, 188, 156),
    "sensor.camera.dvs":                   QColor(236, 112, 99),
    "sensor.other.radar":                  QColor(174, 214, 241),
    "default":                             QColor(200, 200, 200),
}


@dataclass
class SensorHandle:
    name: str
    sensor_type: str
    x: float = 0.0    # relative to ego vehicle centre
    y: float = 0.0
    z: float = 1.5
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0

    @property
    def color(self) -> QColor:
        return SENSOR_COLORS.get(self.sensor_type, SENSOR_COLORS["default"])

    def to_carla_transform(self):
        """Return a carla.Transform if carla is available, else a dict."""
        try:
            import carla  # noqa
            return carla.Transform(
                carla.Location(x=self.x, y=self.y, z=self.z),
                carla.Rotation(pitch=self.pitch, yaw=self.yaw, roll=self.roll),
            )
        except ImportError:
            return {"x": self.x, "y": self.y, "z": self.z,
                    "pitch": self.pitch, "yaw": self.yaw, "roll": self.roll}


# ─────────────────────────────────────────────────────────────────────────────
# Single orthographic view
# ─────────────────────────────────────────────────────────────────────────────
class OrthoView(QWidget):
    """
    axis_h: which SensorHandle field is the horizontal axis  ('x','y')
    axis_v: which SensorHandle field is the vertical axis    ('z','y','x')
    label:  display name
    """
    sensor_moved = pyqtSignal()

    # vehicle rect extents in this view's (h, v) axes
    VEH_EXTENTS = {
        # (axis_h, axis_v): (half_w, half_h)
        ("x", "y"): (VEH_L / 2, VEH_W / 2),   # top view  XY
        ("x", "z"): (VEH_L / 2, VEH_H / 2),   # front/side XZ
        ("y", "z"): (VEH_W / 2, VEH_H / 2),   # side view YZ
    }

    def __init__(self, axis_h: str, axis_v: str, label: str, sensors: List[SensorHandle]):
        super().__init__()
        self.axis_h = axis_h
        self.axis_v = axis_v
        self.label = label
        self.sensors = sensors
        self._scale = 40.0      # px per metre
        self._pan = QPointF(0, 0)
        self._drag_sensor: Optional[SensorHandle] = None
        self._drag_offset = QPointF(0, 0)
        self._rot_sensor: Optional[SensorHandle] = None
        self._rot_start: Optional[QPointF] = None
        self.setMinimumSize(180, 180)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

        self._bg = QColor(28, 28, 36)
        self._grid_pen = QPen(QColor(50, 50, 60), 1, Qt.DotLine)
        self._veh_pen = QPen(QColor(100, 100, 120), 2)
        self._veh_brush = QBrush(QColor(40, 40, 55))
        self._axis_pen = QPen(QColor(80, 80, 90), 1)
        self._label_font = QFont("Monospace", 7)
        self._title_font = QFont("Monospace", 8, QFont.Bold)

    # World ↔ screen
    def _w2s(self, wh: float, wv: float) -> QPointF:
        cx = self.width() / 2 + self._pan.x()
        cy = self.height() / 2 + self._pan.y()
        return QPointF(cx + wh * self._scale, cy - wv * self._scale)

    def _s2w(self, px: QPointF):
        cx = self.width() / 2 + self._pan.x()
        cy = self.height() / 2 + self._pan.y()
        return (px.x() - cx) / self._scale, -(px.y() - cy) / self._scale

    def _sensor_pos(self, s: SensorHandle):
        return getattr(s, self.axis_h), getattr(s, self.axis_v)

    def _set_sensor_pos(self, s: SensorHandle, wh: float, wv: float):
        setattr(s, self.axis_h, round(wh, 2))
        setattr(s, self.axis_v, round(wv, 2))

    def _sensor_at(self, px: QPointF) -> Optional[SensorHandle]:
        for s in self.sensors:
            wh, wv = self._sensor_pos(s)
            sp = self._w2s(wh, wv)
            if (px - sp).manhattanLength() < 10:
                return s
        return None

    # ── painting ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # background
        p.fillRect(self.rect(), self._bg)

        # grid
        p.setPen(self._grid_pen)
        step = self._scale
        cx = self.width() / 2 + self._pan.x()
        cy = self.height() / 2 + self._pan.y()
        x = cx % step
        while x < self.width():
            p.drawLine(int(x), 0, int(x), self.height())
            x += step
        y = cy % step
        while y < self.height():
            p.drawLine(0, int(y), self.width(), int(y))
            y += step

        # axes
        p.setPen(QPen(QColor(70, 70, 90), 1))
        p.drawLine(int(cx), 0, int(cx), self.height())
        p.drawLine(0, int(cy), self.width(), int(cy))

        # vehicle box
        hext, vext = self.VEH_EXTENTS.get((self.axis_h, self.axis_v), (2.0, 1.0))
        tl = self._w2s(-hext, vext)
        br = self._w2s(hext, -vext)
        p.setPen(self._veh_pen)
        p.setBrush(self._veh_brush)
        p.drawRect(QRectF(tl, br))

        # sensors
        for s in self.sensors:
            wh, wv = self._sensor_pos(s)
            sp = self._w2s(wh, wv)
            r = 6
            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(s.color))
            p.drawEllipse(sp, r, r)
            # orientation arrow (yaw in top view, pitch in front view)
            angle_deg = s.yaw if self.axis_v != "z" else s.pitch if self.axis_h == "x" else s.yaw
            angle_rad = math.radians(angle_deg)
            arrow_len = 18
            ep = QPointF(sp.x() + arrow_len * math.cos(angle_rad),
                         sp.y() - arrow_len * math.sin(angle_rad))
            p.setPen(QPen(s.color, 2))
            p.drawLine(sp, ep)
            # label
            p.setPen(QPen(Qt.white, 1))
            p.setFont(self._label_font)
            p.drawText(int(sp.x() + 9), int(sp.y() - 4), s.name)

        # title
        p.setPen(QPen(QColor(160, 160, 180), 1))
        p.setFont(self._title_font)
        p.drawText(6, 14, self.label)

    # ── mouse ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        pos = QPointF(e.pos())
        hit = self._sensor_at(pos)
        if e.button() == Qt.LeftButton:
            if hit:
                self._drag_sensor = hit
                self._drag_offset = pos - self._w2s(*self._sensor_pos(hit))
            else:
                # Place new sensor — parent will create it; just emit coords
                wh, wv = self._s2w(pos)
                self._new_click_world = (wh, wv)
        elif e.button() == Qt.RightButton and hit:
            self._rot_sensor = hit
            self._rot_start = pos
        elif e.button() == Qt.MiddleButton:
            self._pan_start = pos

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        if self._drag_sensor:
            wh, wv = self._s2w(pos - self._drag_offset)
            self._set_sensor_pos(self._drag_sensor, wh, wv)
            self.sensor_moved.emit()
            self.update()
        elif self._rot_sensor and self._rot_start:
            delta = pos.x() - self._rot_start.x()
            if self.axis_v == "z":
                self._rot_sensor.yaw = round((self._rot_sensor.yaw + delta * 0.5) % 360, 1)
            else:
                self._rot_sensor.pitch = round((self._rot_sensor.pitch + delta * 0.5) % 360, 1)
            self._rot_start = pos
            self.sensor_moved.emit()
            self.update()
        elif hasattr(self, "_pan_start"):
            d = pos - self._pan_start
            self._pan += d
            self._pan_start = pos
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag_sensor = None
        self._rot_sensor = None
        self._rot_start = None
        if hasattr(self, "_pan_start"):
            del self._pan_start
        # If it was a click (no drag), notify parent
        if hasattr(self, "_new_click_world"):
            wh, wv = self._new_click_world
            del self._new_click_world
            self.parent_place_sensor(wh, wv)

    def parent_place_sensor(self, wh, wv):
        # Bubble up to SensorPlacerWidget
        p = self.parent()
        if p and hasattr(p, "_request_new_sensor"):
            p._request_new_sensor(self, wh, wv)

    def wheelEvent(self, e):
        factor = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        self._scale = max(10.0, min(200.0, self._scale * factor))
        self.update()

    def add_sensor(self, s: SensorHandle):
        self.update()

    def refresh(self):
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Isometric read-only perspective view
# ─────────────────────────────────────────────────────────────────────────────
class IsoView(QWidget):
    def __init__(self, sensors: List[SensorHandle]):
        super().__init__()
        self.sensors = sensors
        self.setMinimumSize(180, 180)
        self._angle = 30.0   # deg, draggable
        self._elev  = 25.0
        self._drag_last = None
        self._scale = 28.0
        self._bg = QColor(28, 28, 36)

    def _project(self, x, y, z):
        """Simple isometric projection."""
        a = math.radians(self._angle)
        e = math.radians(self._elev)
        px = (x * math.cos(a) - y * math.cos(a)) * math.cos(e)
        py = (x * math.sin(a) + y * math.sin(a)) * math.cos(e) - z * math.sin(e)
        cx = self.width() / 2
        cy = self.height() / 2
        return QPointF(cx + px * self._scale, cy - py * self._scale)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), self._bg)

        # Vehicle box edges
        hw, hl, hh = VEH_W / 2, VEH_L / 2, VEH_H / 2
        corners = [
            (-hl, -hw, 0), (hl, -hw, 0), (hl, hw, 0), (-hl, hw, 0),
            (-hl, -hw, VEH_H), (hl, -hw, VEH_H), (hl, hw, VEH_H), (-hl, hw, VEH_H),
        ]
        pts = [self._project(*c) for c in corners]
        pen = QPen(QColor(90, 90, 120), 1)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(35, 35, 50)))
        # bottom face
        bottom = [pts[0], pts[1], pts[2], pts[3]]
        path = QPainterPath()
        path.moveTo(bottom[0])
        for pt in bottom[1:]: path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
        # vertical edges
        for i in range(4):
            p.drawLine(pts[i], pts[i + 4])
        # top face
        top = [pts[4], pts[5], pts[6], pts[7]]
        path2 = QPainterPath()
        path2.moveTo(top[0])
        for pt in top[1:]: path2.lineTo(pt)
        path2.closeSubpath()
        p.setBrush(QBrush(QColor(45, 45, 65)))
        p.drawPath(path2)

        # Sensors
        for s in self.sensors:
            sp = self._project(s.x, s.y, s.z)
            r = 5
            p.setPen(QPen(Qt.white, 1))
            p.setBrush(QBrush(s.color))
            p.drawEllipse(sp, r, r)
            yaw_rad = math.radians(s.yaw)
            ep = self._project(s.x + 0.8 * math.cos(yaw_rad),
                               s.y + 0.8 * math.sin(yaw_rad), s.z)
            p.setPen(QPen(s.color, 2))
            p.drawLine(sp, ep)

        # Label
        p.setPen(QPen(QColor(160, 160, 180)))
        p.setFont(QFont("Monospace", 8, QFont.Bold))
        p.drawText(6, 14, "3D Iso")

        # Drag hint
        p.setFont(QFont("Monospace", 6))
        p.setPen(QPen(QColor(90, 90, 110)))
        p.drawText(6, self.height() - 4, "drag to orbit")

    def mousePressEvent(self, e):
        self._drag_last = QPointF(e.pos())

    def mouseMoveEvent(self, e):
        if self._drag_last:
            d = QPointF(e.pos()) - self._drag_last
            self._angle = (self._angle + d.x() * 0.4) % 360
            self._elev = max(-80, min(80, self._elev + d.y() * 0.4))
            self._drag_last = QPointF(e.pos())
            self.update()

    def mouseReleaseEvent(self, _):
        self._drag_last = None

    def refresh(self):
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Main placer widget
# ─────────────────────────────────────────────────────────────────────────────
SENSOR_TYPES = [
    "sensor.camera.rgb",
    "sensor.camera.rgb.bev",
    "sensor.camera.depth",
    "sensor.camera.semantic_segmentation",
    "sensor.camera.instance_segmentation",
    "sensor.camera.optical_flow",
    "sensor.lidar.ray_cast",
    "sensor.other.radar",
    "sensor.camera.dvs",
]


class SensorPlacerWidget(QWidget):
    sensor_list_changed = pyqtSignal(list)   # emits full list of SensorHandle

    def __init__(self):
        super().__init__()
        self.sensors: List[SensorHandle] = []
        self._counter = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Type selector
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Sensor type:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems(SENSOR_TYPES)
        top_bar.addWidget(self._type_combo)
        top_bar.addWidget(QLabel("  Click any view to place →"))
        top_bar.addStretch()
        clear_btn = QPushButton("Clear all")
        clear_btn.clicked.connect(self._clear_all)
        top_bar.addWidget(clear_btn)
        root.addLayout(top_bar)

        # 2×2 grid of views
        grid = QGridLayout()
        grid.setSpacing(2)
        self._top_view   = OrthoView("x", "y", "TOP  (X→ / Y↑)", self.sensors)
        self._front_view = OrthoView("x", "z", "FRONT (X→ / Z↑)", self.sensors)
        self._side_view  = OrthoView("y", "z", "SIDE  (Y→ / Z↑)", self.sensors)
        self._iso_view   = IsoView(self.sensors)

        for v in (self._top_view, self._front_view, self._side_view):
            v.sensor_moved.connect(self._on_sensor_moved)

        grid.addWidget(self._top_view,   0, 0)
        grid.addWidget(self._front_view, 0, 1)
        grid.addWidget(self._side_view,  1, 0)
        grid.addWidget(self._iso_view,   1, 1)
        root.addLayout(grid, stretch=1)

        # Coordinate readout
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)
        coord_grp = QGroupBox("Selected sensor transform (relative to ego)")
        cg = QHBoxLayout(coord_grp)
        self._coord_labels = {}
        for field in ("name", "x", "y", "z", "pitch", "yaw", "roll"):
            lbl = QLabel(f"{field}: —")
            lbl.setFont(QFont("Monospace", 8))
            cg.addWidget(lbl)
            self._coord_labels[field] = lbl
        root.addWidget(coord_grp)

        # Sensor list
        list_grp = QGroupBox("Placed sensors")
        lg = QHBoxLayout(list_grp)
        self._sensor_combo = QComboBox()
        self._sensor_combo.setMinimumWidth(200)
        self._sensor_combo.currentIndexChanged.connect(self._on_selection_changed)
        lg.addWidget(self._sensor_combo)
        del_btn = QPushButton("Remove")
        del_btn.clicked.connect(self._remove_selected)
        lg.addWidget(del_btn)
        root.addWidget(list_grp)

    def _request_new_sensor(self, view: OrthoView, wh: float, wv: float):
        """Called by OrthoView when user clicks empty space."""
        self._counter += 1
        s = SensorHandle(
            name=f"cam{self._counter}",
            sensor_type=self._type_combo.currentText(),
        )
        setattr(s, view.axis_h, round(wh, 2))
        setattr(s, view.axis_v, round(wv, 2))
        self.sensors.append(s)
        self._sensor_combo.addItem(s.name)
        self._sensor_combo.setCurrentIndex(len(self.sensors) - 1)
        self._refresh_all()
        self.sensor_list_changed.emit(self.sensors)

    def _on_sensor_moved(self):
        self._refresh_all()
        self._update_readout()
        self.sensor_list_changed.emit(self.sensors)

    def _on_selection_changed(self, idx):
        self._update_readout()

    def _update_readout(self):
        idx = self._sensor_combo.currentIndex()
        if 0 <= idx < len(self.sensors):
            s = self.sensors[idx]
            for field, lbl in self._coord_labels.items():
                val = getattr(s, field)
                lbl.setText(f"{field}: {val:.2f}" if isinstance(val, float) else f"{field}: {val}")

    def _refresh_all(self):
        for v in (self._top_view, self._front_view, self._side_view, self._iso_view):
            v.refresh()

    def _remove_selected(self):
        idx = self._sensor_combo.currentIndex()
        if 0 <= idx < len(self.sensors):
            self.sensors.pop(idx)
            self._sensor_combo.removeItem(idx)
            self._refresh_all()
            self.sensor_list_changed.emit(self.sensors)

    def _clear_all(self):
        self.sensors.clear()
        self._sensor_combo.clear()
        self._refresh_all()
        self.sensor_list_changed.emit(self.sensors)

    def get_handles(self) -> List[SensorHandle]:
        return list(self.sensors)
