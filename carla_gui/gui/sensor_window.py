"""
Live sensor feed window — separate floating QDialog.
Polls FrameQueue per sensor at ~30fps. Zero blocking of main thread.
"""

import queue
import time
import threading
import numpy as np
from typing import Dict, Optional, List

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QPushButton, QGridLayout, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QFont


# ─────────────────────────────────────────────────────────────────────────────
# Frame queue — maxsize=2 so old frames drop automatically
# ─────────────────────────────────────────────────────────────────────────────
class FrameQueue:
    def __init__(self):
        self._q = queue.Queue(maxsize=2)

    def put(self, arr: np.ndarray):
        try:
            self._q.put_nowait(arr)
        except queue.Full:
            try:
                self._q.get_nowait()   # discard stale frame
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(arr)
            except queue.Full:
                pass

    def get(self) -> Optional[np.ndarray]:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Single sensor panel
# ─────────────────────────────────────────────────────────────────────────────
class SensorPanel(QWidget):
    def __init__(self, sensor_name: str, sensor_type: str):
        super().__init__()
        self.sensor_name = sensor_name
        self.sensor_type = sensor_type
        self.frame_queue = FrameQueue()
        self._frame_times: List[float] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self._image_label = QLabel("Waiting for frames…")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("background:#111; color:#888;")
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image_label.setMinimumSize(320, 240)
        layout.addWidget(self._image_label, stretch=1)

        self._info_label = QLabel(f"{sensor_name} | {sensor_type} | — fps")
        self._info_label.setFont(QFont("Monospace", 8))
        self._info_label.setStyleSheet("color:#aaa; padding:2px;")
        layout.addWidget(self._info_label)

        # Poll timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._update)
        self._timer.start(33)   # ~30fps

    def _update(self):
        arr = self.frame_queue.get()
        if arr is None:
            return
        # FPS tracking
        now = time.monotonic()
        self._frame_times.append(now)
        self._frame_times = [t for t in self._frame_times if now - t < 1.0]
        fps = len(self._frame_times)

        h, w = arr.shape[:2]
        if arr.ndim == 2:
            # Grayscale (depth normalised)
            img = QImage(arr.tobytes(), w, h, w, QImage.Format_Grayscale8)
        elif arr.shape[2] == 4:
            img = QImage(arr.tobytes(), w, h, 4 * w, QImage.Format_ARGB32).rgbSwapped()
        else:
            img = QImage(arr.tobytes(), w, h, 3 * w, QImage.Format_RGB888)

        pix = QPixmap.fromImage(img).scaled(
            self._image_label.width(), self._image_label.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(pix)
        self._info_label.setText(f"{self.sensor_name} | {self.sensor_type} | {fps} fps")

    def stop(self):
        self._timer.stop()


# ─────────────────────────────────────────────────────────────────────────────
# CARLA sensor manager — creates/destroys actors, owns callbacks
# ─────────────────────────────────────────────────────────────────────────────
class SensorManager:
    """Thread-safe. All CARLA calls happen on the caller's thread."""

    def __init__(self, carla_client, log_fn=None):
        self._client = carla_client
        self._log = log_fn or print
        self._actors: Dict[str, object] = {}   # name → carla actor
        self._queues: Dict[str, FrameQueue] = {}

    def attach(self, handle, panel: SensorPanel) -> bool:
        """Spawn sensor actor and wire its callback to panel.frame_queue."""
        world = self._client.world
        player = self._client.player
        if not world or not player:
            self._log("[ERR] Need a connected world and spawned vehicle to attach sensors.")
            return False
        try:
            import carla  # noqa
            import weakref
            bp_id = handle.sensor_type.replace(".bev", "")  # strip BEV marker
            bp = world.get_blueprint_library().find(bp_id)
            if bp is None:
                self._log(f"[ERR] Blueprint not found: {bp_id}")
                return False

            # Set sensible defaults
            if bp.has_attribute("image_size_x"):
                bp.set_attribute("image_size_x", "800")
                bp.set_attribute("image_size_y", "600")
            if bp.has_attribute("fov"):
                bp.set_attribute("fov", "90")

            # BEV: override transform to top-down
            if handle.sensor_type.endswith(".bev"):
                transform = carla.Transform(
                    carla.Location(x=0, y=0, z=20),
                    carla.Rotation(pitch=-90, yaw=0, roll=0),
                )
            else:
                transform = handle.to_carla_transform()

            actor = world.spawn_actor(bp, transform, attach_to=player,
                                      attachment_type=carla.AttachmentType.Rigid)

            q = panel.frame_queue
            self._queues[handle.name] = q

            # Determine converter
            sensor_type = handle.sensor_type
            q_ref = weakref.ref(q)

            def _make_callback(stype):
                def _cb(image):
                    _q = q_ref()
                    if _q is None:
                        return
                    try:
                        import carla as _carla  # noqa
                        if stype == "sensor.camera.depth":
                            image.convert(_carla.ColorConverter.Depth)
                            arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                                (image.height, image.width, 4))
                            # Normalise to grayscale 0-255
                            depth_m = (arr[:, :, 2].astype(np.float32) +
                                       arr[:, :, 1].astype(np.float32) * 256 +
                                       arr[:, :, 0].astype(np.float32) * 65536) / 16777215.0 * 1000.0
                            grey = np.clip(depth_m / 100.0 * 255, 0, 255).astype(np.uint8)
                            _q.put(grey)
                        elif stype == "sensor.camera.semantic_segmentation":
                            image.convert(_carla.ColorConverter.CityScapesPalette)
                            arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                                (image.height, image.width, 4))
                            _q.put(arr)
                        elif stype == "sensor.lidar.ray_cast":
                            # Render lidar as a top-down point cloud image
                            pts = np.frombuffer(image.raw_data, dtype=np.float32).reshape(-1, 4)
                            img_size = 400
                            canvas = np.zeros((img_size, img_size, 3), dtype=np.uint8)
                            if len(pts) > 0:
                                x, y = pts[:, 0], pts[:, 1]
                                scale = img_size / 60.0
                                ix = np.clip((img_size // 2 + x * scale).astype(int), 0, img_size - 1)
                                iy = np.clip((img_size // 2 - y * scale).astype(int), 0, img_size - 1)
                                canvas[iy, ix] = [0, 220, 150]
                            _q.put(canvas)
                        else:
                            arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                                (image.height, image.width, 4))
                            _q.put(arr)
                    except Exception:
                        pass
                return _cb

            actor.listen(_make_callback(sensor_type))
            self._actors[handle.name] = actor
            self._log(f"[OK] Sensor '{handle.name}' ({sensor_type}) attached to vehicle.")
            return True

        except Exception as exc:
            self._log(f"[ERR] attach sensor '{handle.name}': {exc}")
            return False

    def detach(self, name: str):
        actor = self._actors.pop(name, None)
        if actor:
            try:
                actor.stop()
                actor.destroy()
                self._log(f"[OK] Sensor '{name}' removed.")
            except Exception as exc:
                self._log(f"[WARN] detach '{name}': {exc}")

    def detach_all(self):
        for name in list(self._actors.keys()):
            self.detach(name)


# ─────────────────────────────────────────────────────────────────────────────
# Floating sensor feed window
# ─────────────────────────────────────────────────────────────────────────────
class SensorFeedWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CARLA Sensor Feed")
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(900, 620)

        self._panels: Dict[str, SensorPanel] = {}
        self._manager: Optional[SensorManager] = None

        layout = QVBoxLayout(self)

        ctrl_row = QHBoxLayout()
        self._status_lbl = QLabel("No sensors attached. Configure sensors in the Sensors tab.")
        self._status_lbl.setStyleSheet("color:#aaa;")
        ctrl_row.addWidget(self._status_lbl)
        ctrl_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        ctrl_row.addWidget(close_btn)
        layout.addLayout(ctrl_row)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, stretch=1)

    def set_manager(self, manager: SensorManager):
        self._manager = manager

    def open_sensor(self, handle, manager: SensorManager):
        """Add a tab for this sensor and wire it up."""
        name = handle.name
        if name in self._panels:
            return  # already open
        panel = SensorPanel(name, handle.sensor_type)
        self._panels[name] = panel
        self._tabs.addTab(panel, f"{name} [{handle.sensor_type.split('.')[-1]}]")

        # Attach in background thread
        def _attach():
            ok = manager.attach(handle, panel)
            if not ok:
                self._status_lbl.setText(f"[ERR] Could not attach {name}")

        threading.Thread(target=_attach, daemon=True).start()
        self._status_lbl.setText(f"{len(self._panels)} sensor(s) active.")
        self.show()
        self.raise_()

    def close_sensor(self, name: str, manager: SensorManager):
        panel = self._panels.pop(name, None)
        if panel:
            panel.stop()
            idx = self._tabs.indexOf(panel)
            if idx >= 0:
                self._tabs.removeTab(idx)
        threading.Thread(target=manager.detach, args=(name,), daemon=True).start()

    def close_all(self, manager: SensorManager):
        for name in list(self._panels.keys()):
            self.close_sensor(name, manager)
        self._status_lbl.setText("All sensors closed.")

    def closeEvent(self, e):
        # Hide rather than destroy so it can reopen
        e.ignore()
        self.hide()
