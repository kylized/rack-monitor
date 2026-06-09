"""Entry point for the native camera overlay app."""

import sys
from PyQt6.QtWidgets import QApplication
from overlay import CameraOverlay
from control_panel import ControlPanel
from capture import CameraCapture

RTSP_BASE = "rtsp://localhost:8554"
CAP_FPS   = 10
NUM_CAMS  = 5


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Rack Monitor Cameras")

    captures = [CameraCapture(i, f"{RTSP_BASE}/cam{i}", CAP_FPS) for i in range(NUM_CAMS)]
    cameras  = [CameraOverlay(i) for i in range(NUM_CAMS)]

    # When overlay is moved/resized while streaming, update capture region live
    for cam, cap in zip(cameras, captures):
        def _on_geom(cam_id, x, y, w, h, _cap=cap):
            if _cap.running:
                _cap.update_region(x, y, w, h)
        cam.geometry_changed.connect(_on_geom)

    # Place overlays in a horizontal row near the top-third of the primary screen
    screen   = app.primaryScreen().geometry()
    ow, oh   = 380, 110
    gap      = 8
    total_w  = NUM_CAMS * ow + (NUM_CAMS - 1) * gap
    start_x  = max(0, (screen.width() - total_w) // 2)
    start_y  = screen.height() // 3

    for i, cam in enumerate(cameras):
        cam.move(start_x + i * (ow + gap), start_y)
        cam.show()

    panel = ControlPanel(cameras, captures)
    panel.move(screen.width() - 330, 60)
    panel.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
