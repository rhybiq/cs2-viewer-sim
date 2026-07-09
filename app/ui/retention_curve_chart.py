"""Zone 2 of the AI Viewer panel results: a small hand-painted line chart of
the panel's real retention curve (see viewer_sim.build_persona_retention_curve)
-- % of the 100 personas still "watching" per ~1s bucket, plotted as-is
(a step function, not smoothed) with a dashed marker at the average
swipe-away time. No charting dependency: this mirrors the same x()/y()
mapping already used for the energy/retention SVG in viewer_sim.write_html,
just drawn with QPainter instead of emitted as SVG text.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui import colors

_PAD_L, _PAD_R, _PAD_T, _PAD_B = 34, 12, 16, 20


class RetentionCurveChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._points = []
        self._avg_swipe = None
        self._duration = 0.0

    def set_data(self, points, avg_swipe_second, duration_s):
        self._points = points or []
        self._avg_swipe = avg_swipe_second
        self._duration = duration_s or (self._points[-1][0] if self._points else 0.0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self._points or not self._duration:
            painter.setPen(QColor(colors.MUTED))
            painter.drawText(self.rect(), Qt.AlignCenter, "No retention data yet.")
            return

        plot_w = w - _PAD_L - _PAD_R
        plot_h = h - _PAD_T - _PAD_B

        def x(t):
            return _PAD_L + (t / self._duration) * plot_w

        def y(pct):
            return _PAD_T + (1 - pct / 100) * plot_h

        painter.setPen(QPen(QColor(colors.BORDER), 1))
        painter.drawLine(QPointF(_PAD_L, _PAD_T), QPointF(_PAD_L, _PAD_T + plot_h))
        painter.drawLine(QPointF(_PAD_L, _PAD_T + plot_h), QPointF(_PAD_L + plot_w, _PAD_T + plot_h))

        if self._avg_swipe is not None:
            mx = x(min(self._avg_swipe, self._duration))
            marker_pen = QPen(QColor(colors.WARN), 1, Qt.DashLine)
            painter.setPen(marker_pen)
            painter.drawLine(QPointF(mx, _PAD_T), QPointF(mx, _PAD_T + plot_h))

        pen = QPen(QColor(colors.ACCENT), 2)
        painter.setPen(pen)
        for (t0, p0), (t1, p1) in zip(self._points, self._points[1:]):
            # Step function, not interpolated: retention is only known at
            # each bucket boundary, so the honest shape holds flat within a
            # bucket and drops at the boundary -- see build_persona_retention_curve.
            painter.drawLine(QPointF(x(t0), y(p0)), QPointF(x(t1), y(p0)))
            painter.drawLine(QPointF(x(t1), y(p0)), QPointF(x(t1), y(p1)))

        painter.setPen(QColor(colors.MUTED))
        painter.drawText(QRectF(0, _PAD_T - 8, _PAD_L - 4, 16), Qt.AlignRight, "100%")
        painter.drawText(QRectF(0, _PAD_T + plot_h - 8, _PAD_L - 4, 16), Qt.AlignRight, "0%")
        painter.drawText(QRectF(_PAD_L, h - _PAD_B, 40, _PAD_B), Qt.AlignLeft, "0s")
        painter.drawText(
            QRectF(_PAD_L + plot_w - 50, h - _PAD_B, 50, _PAD_B), Qt.AlignRight,
            f"{self._duration:.0f}s")
        painter.drawText(
            QRectF(_PAD_L, 2, plot_w, 14), Qt.AlignRight,
            "retention (simulated)")
