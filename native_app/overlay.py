"""Transparent, always-on-top, draggable + resizable camera viewfinder."""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QBrush

BORDER = 4
HANDLE = 14
TITLE_H = 22

_COLORS = ["#00e676", "#2979ff", "#ffab00", "#e040fb", "#00e5ff"]


class CameraOverlay(QWidget):
    geometry_changed = pyqtSignal(int, int, int, int, int)  # cam_id, x, y, w, h

    def __init__(self, cam_id: int):
        super().__init__()
        self.cam_id = cam_id
        self.streaming = False
        self._color = QColor(_COLORS[cam_id % len(_COLORS)])

        self._drag_off: QPoint | None = None
        self._resize_corner: str | None = None      # tl/tr/bl/br
        self._resize_geom: QRect | None = None
        self._resize_mouse: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(220, 100)
        self.resize(380, 110)

    def set_streaming(self, on: bool):
        self.streaming = on
        self.update()

    # ── paint ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        col = self._color if self.streaming else QColor("#ff1744")

        # Border
        pen = QPen(col, BORDER)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(BORDER, BORDER, -BORDER, -BORDER))

        # Title bar fill
        tb_col = QColor(col)
        tb_col.setAlpha(210)
        p.fillRect(BORDER, BORDER, self.width() - 2 * BORDER, TITLE_H, tb_col)

        # Title text
        p.setPen(QColor("#000000"))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        status = "● REC" if self.streaming else "○ OFF"
        p.drawText(
            BORDER + 5, BORDER,
            self.width() - 2 * BORDER - 5, TITLE_H,
            Qt.AlignmentFlag.AlignVCenter,
            f"CAM-{self.cam_id}  SW-0{self.cam_id + 1}  {status}  "
            f"{self.width()}×{self.height()}",
        )

        # Corner resize handles
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        for r in self._corners():
            p.drawRect(r)

    def _corners(self) -> list[QRect]:
        w, h, s = self.width(), self.height(), HANDLE
        return [
            QRect(0,     0,     s, s),
            QRect(w - s, 0,     s, s),
            QRect(0,     h - s, s, s),
            QRect(w - s, h - s, s, s),
        ]

    def _hit_corner(self, pos: QPoint) -> str | None:
        for name, rect in zip(("tl", "tr", "bl", "br"), self._corners()):
            if rect.contains(pos):
                return name
        return None

    def _in_title(self, pos: QPoint) -> bool:
        return BORDER <= pos.x() <= self.width() - BORDER and BORDER <= pos.y() <= BORDER + TITLE_H

    # ── mouse ───────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        local = e.position().toPoint()
        c = self._hit_corner(local)
        if c:
            self._resize_corner = c
            self._resize_geom  = self.geometry()
            self._resize_mouse = e.globalPosition().toPoint()
        elif self._in_title(local):
            self._drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        local = e.position().toPoint()
        if self._hit_corner(local):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif self._in_title(local):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        gpos = e.globalPosition().toPoint()

        if self._resize_corner and self._resize_geom:
            self._do_resize(gpos)
        elif self._drag_off:
            self.move(gpos - self._drag_off)
            self._emit()

    def mouseReleaseEvent(self, _e):
        self._drag_off = self._resize_corner = self._resize_geom = self._resize_mouse = None
        self._emit()

    def _do_resize(self, gpos: QPoint):
        g  = self._resize_geom
        dx = gpos.x() - self._resize_mouse.x()
        dy = gpos.y() - self._resize_mouse.y()
        c  = self._resize_corner
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        mw, mh = self.minimumWidth(), self.minimumHeight()

        if "r" in c: w = max(mw, w + dx)
        if "l" in c: nx = x + dx; w = max(mw, w - dx); x = nx
        if "b" in c: h = max(mh, h + dy)
        if "t" in c: ny = y + dy; h = max(mh, h - dy); y = ny

        self.setGeometry(x, y, w, h)
        self._emit()

    def _emit(self):
        pos = self.pos()
        self.geometry_changed.emit(self.cam_id, pos.x(), pos.y(), self.width(), self.height())

    def get_region(self) -> dict:
        pos = self.pos()
        return dict(left=pos.x(), top=pos.y(), width=self.width(), height=self.height())
