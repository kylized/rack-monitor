"""Main camera control panel window."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

_COLORS = ["#00e676", "#2979ff", "#ffab00", "#e040fb", "#00e5ff"]

_BTN = (
    "QPushButton{{"
    "background:{bg};color:{fg};border:1px solid {bd};"
    "padding:5px 12px;font-family:'Courier New';font-size:9pt;font-weight:bold;}}"
    "QPushButton:hover{{filter:brightness(1.3);}}"
)


class ControlPanel(QWidget):
    def __init__(self, cameras, captures):
        super().__init__()
        self.cameras  = cameras
        self.captures = captures
        self.setWindowTitle("Rack Monitor — Camera Control")
        self.setFixedWidth(310)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("background:#0a0c0f; color:#cdd3db;")
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(4)
        root.setContentsMargins(10, 10, 10, 10)

        title = QLabel("RACK CAMERA CONTROL")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        title.setStyleSheet("color:#00e676;padding:6px;border-bottom:1px solid #1e2228;")
        root.addWidget(title)

        self._rows: list[tuple] = []
        for i in range(5):
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet("color:#333;font-size:11px;")
            dot.setFixedWidth(18)
            lbl = QLabel(f"CAM-{i}  →  SW-0{i + 1}")
            lbl.setFont(QFont("Courier New", 9))
            lbl.setStyleSheet("color:#888;")
            fps = QLabel("—")
            fps.setFont(QFont("Courier New", 9))
            fps.setStyleSheet("color:#555;")
            fps.setAlignment(Qt.AlignmentFlag.AlignRight)
            fps.setFixedWidth(52)
            row.addWidget(dot)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(fps)
            root.addLayout(row)
            self._rows.append((dot, fps, _COLORS[i]))

        root.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_start = QPushButton("▶ Start All")
        btn_stop  = QPushButton("■ Stop All")
        btn_start.setStyleSheet(_BTN.format(bg="#0d3320", fg="#66ffaa", bd="#1a5c38"))
        btn_stop.setStyleSheet(_BTN.format(bg="#3a0d0d", fg="#ff8888", bd="#6b1a1a"))
        btn_start.clicked.connect(self._start_all)
        btn_stop.clicked.connect(self._stop_all)
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_stop)
        root.addLayout(btn_row)

        hint = QLabel("Drag title bar to move  ·  Drag corner to resize")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color:#2e3540;font-size:8px;margin-top:4px;")
        root.addWidget(hint)

    def _start_all(self):
        for cam, cap in zip(self.cameras, self.captures):
            r = cam.get_region()
            cap.set_region(r["left"], r["top"], r["width"], r["height"])
            cap.start()
            cam.set_streaming(True)

    def _stop_all(self):
        for cam, cap in zip(self.cameras, self.captures):
            cap.stop()
            cam.set_streaming(False)

    def _refresh(self):
        for (dot, fps_lbl, color), cap in zip(self._rows, self.captures):
            if cap.running:
                dot.setStyleSheet(f"color:{color};font-size:11px;")
                fps_lbl.setText(f"{cap.actual_fps:.0f} fps")
                fps_lbl.setStyleSheet(f"color:{color};")
            else:
                dot.setStyleSheet("color:#333;font-size:11px;")
                fps_lbl.setText("—")
                fps_lbl.setStyleSheet("color:#555;")
