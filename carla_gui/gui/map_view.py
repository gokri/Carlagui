"""2D interactive map view — roads, spawn points, route overlay."""

import math
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsLineItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsRectItem,
)
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QPen, QBrush, QColor, QPainterPath, QFont, QTransform

ROAD_COLOR = QColor(60, 60, 70)
SPAWN_COLOR = QColor(46, 204, 113)
SPAWN_HOVER = QColor(39, 174, 96)
ROUTE_COLOR = QColor(52, 152, 219)
START_COLOR = QColor(46, 204, 113)
END_COLOR = QColor(231, 76, 60)
PED_COLOR = QColor(230, 126, 34)
NPC_COLOR = QColor(155, 89, 182)

SPAWN_R = 5      # radius of spawn dot in scene units
LABEL_FONT = QFont("Monospace", 6)


class SpawnDot(QGraphicsEllipseItem):
    def __init__(self, x, y, idx, transform, callback):
        r = SPAWN_R
        super().__init__(-r, -r, r * 2, r * 2)
        self.setPos(x, y)
        self._idx = idx
        self._transform = transform
        self._callback = callback
        self.setBrush(QBrush(SPAWN_COLOR))
        self.setPen(QPen(Qt.NoPen))
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"Spawn #{idx}\n({transform.location.x:.1f}, {transform.location.y:.1f})")
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(2)

    def hoverEnterEvent(self, e):
        self.setBrush(QBrush(SPAWN_HOVER))
        self.setScale(1.4)

    def hoverLeaveEvent(self, e):
        self.setBrush(QBrush(SPAWN_COLOR))
        self.setScale(1.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._callback(self._idx, self._transform)


class WaypointDot(QGraphicsEllipseItem):
    """Reusable dot for pedestrian or NPC placement on map."""
    def __init__(self, x, y, label, color, callback):
        r = SPAWN_R * 0.8
        super().__init__(-r, -r, r * 2, r * 2)
        self.setPos(x, y)
        self._callback = callback
        self.setBrush(QBrush(color))
        self.setPen(QPen(Qt.NoPen))
        self.setAcceptHoverEvents(True)
        self.setToolTip(label)
        self.setCursor(Qt.CrossCursor)
        self.setZValue(3)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._callback(self.pos().x(), self.pos().y())


class MapScene(QGraphicsScene):
    spawn_clicked = pyqtSignal(int, object)         # idx, carla.Transform
    waypoint_clicked = pyqtSignal(float, float)     # x, y (map coords)

    def __init__(self):
        super().__init__()
        self._road_pen = QPen(ROAD_COLOR, 1.5)
        self._route_pen = QPen(ROUTE_COLOR, 3)
        self._route_pen.setStyle(Qt.DashLine)
        self._spawn_items = []
        self._route_items = []
        self._marker_items = []
        self._placement_mode = None   # None | 'pedestrian' | 'npc'

    def set_placement_mode(self, mode):
        """mode: None, 'pedestrian', 'npc'"""
        self._placement_mode = mode

    def draw_roads(self, segments):
        for (x1, y1), (x2, y2) in segments:
            self.addLine(x1, -y1, x2, -y2, self._road_pen)

    def draw_spawn_points(self, transforms, callback):
        for item in self._spawn_items:
            self.removeItem(item)
        self._spawn_items.clear()
        for i, t in enumerate(transforms):
            dot = SpawnDot(t.location.x, -t.location.y, i, t,
                           lambda idx, tr: self.spawn_clicked.emit(idx, tr))
            self.addItem(dot)
            self._spawn_items.append(dot)
            # Road ID label
            if i % 5 == 0:  # thin out labels for dense maps
                lbl = QGraphicsTextItem(str(i))
                lbl.setFont(LABEL_FONT)
                lbl.setDefaultTextColor(QColor(180, 180, 180))
                lbl.setPos(t.location.x + SPAWN_R, -t.location.y - SPAWN_R)
                lbl.setZValue(4)
                self.addItem(lbl)
                self._spawn_items.append(lbl)

    def draw_route(self, waypoints):
        for item in self._route_items:
            self.removeItem(item)
        self._route_items.clear()
        if len(waypoints) < 2:
            return
        path = QPainterPath()
        x0, y0, _ = waypoints[0]
        path.moveTo(x0, -y0)
        for x, y, _ in waypoints[1:]:
            path.lineTo(x, -y)
        pi = QGraphicsPathItem(path)
        pi.setPen(self._route_pen)
        pi.setZValue(5)
        self.addItem(pi)
        self._route_items.append(pi)

    def add_marker(self, x, y, color, label=""):
        r = SPAWN_R * 1.5
        item = QGraphicsEllipseItem(-r, -r, r * 2, r * 2)
        item.setPos(x, -y)
        item.setBrush(QBrush(color))
        item.setPen(QPen(Qt.white, 1))
        item.setZValue(6)
        self.addItem(item)
        self._marker_items.append(item)
        if label:
            t = QGraphicsTextItem(label)
            t.setFont(LABEL_FONT)
            t.setDefaultTextColor(Qt.white)
            t.setPos(x + r + 1, -y - r)
            t.setZValue(7)
            self.addItem(t)
            self._marker_items.append(t)

    def clear_markers(self):
        for item in self._marker_items:
            self.removeItem(item)
        self._marker_items.clear()
        for item in self._route_items:
            self.removeItem(item)
        self._route_items.clear()

    def mousePressEvent(self, event):
        if self._placement_mode and event.button() == Qt.LeftButton:
            pos = event.scenePos()
            # Convert back: y is negated in draw
            self.waypoint_clicked.emit(pos.x(), -pos.y())
        super().mousePressEvent(event)


class MapView(QGraphicsView):
    def __init__(self, scene: MapScene):
        super().__init__(scene)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHint(0x01)  # Antialiasing
        self.setBackgroundBrush(QBrush(QColor(20, 20, 30)))
        self._zoom = 0

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom += (1 if event.angleDelta().y() > 0 else -1)
        self.scale(factor, factor)

    def fit_scene(self):
        self.fitInView(self.scene().itemsBoundingRect(), Qt.KeepAspectRatio)
