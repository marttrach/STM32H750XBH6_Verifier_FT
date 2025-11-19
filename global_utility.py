from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from PySide6 import QtCore, QtGui, QtWidgets

# Default development credentials; replace with MIS integration when ready.
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "password"

# Persistent file for submitted results.
RESULTS_FILE = Path("test_results.csv")

# Baseline resolution for responsive scaling.
BASE_WIDTH = 1280
BASE_HEIGHT = 720


@dataclass
class TestResult:
    name: str
    status: str = "待測"
    detail: str = ""


class StatusLabel(QtWidgets.QLabel):
    """Small helper to color-code status labels."""

    COLORS = {
        "待測": "#808080",
        "進行中": "#1f5fbf",
        "PASS": "#1a7f37",
        "FAIL": "#c93c37",
    }

    def __init__(self, text: str = "待測", scale: float = 1.0) -> None:
        super().__init__(text)
        self.scale = scale
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFixedWidth(int(100 * self.scale))
        self.setStyleSheet(self._style_for(text))

    def update_status(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._style_for(text))

    def _style_for(self, text: str) -> str:
        color = self.COLORS.get(text, "#444")
        return (
            f"color: white; background: {color}; border-radius: 6px; "
            "padding: 4px; font-weight: bold;"
        )


def compute_scale() -> float:
    screen = QtWidgets.QApplication.primaryScreen()
    rect = (
        screen.availableGeometry()
        if screen
        else QtCore.QRect(0, 0, BASE_WIDTH, BASE_HEIGHT)
    )
    scale_x = rect.width() / BASE_WIDTH
    scale_y = rect.height() / BASE_HEIGHT
    return max(0.8, min(1.8, min(scale_x, scale_y)))


def apply_global_font(scale: float) -> None:
    app = QtWidgets.QApplication.instance()
    if not app:
        return
    font = app.font()
    font.setPointSizeF(max(10.0, 10.0 * scale))
    app.setFont(font)


def resize_by_scale(window: QtWidgets.QWidget, scale: float) -> None:
    screen = QtWidgets.QApplication.primaryScreen()
    rect = (
        screen.availableGeometry()
        if screen
        else QtCore.QRect(0, 0, BASE_WIDTH, BASE_HEIGHT)
    )
    width = int(rect.width() * 0.7)
    height = int(rect.height() * 0.7)
    window.resize(width, height)


def theme_stylesheet(mode: str) -> str:
    if mode == "dark":
        return """
            QWidget { background: #202124; color: #e8eaed; }
            QLineEdit { background: #2b2f36; color: #e8eaed; }
            QComboBox { background: #2b2f36; color: #e8eaed; }
            QPushButton { background: #3c4043; color: #e8eaed; }
            QGroupBox { border: 1px solid #3c4043; margin-top: 8px; }
            QPlainTextEdit { background: #0f1115; color: #d1d5db; }
        """
    return """
        QWidget { background: #f5f6fb; color: #1f2937; }
        QLineEdit { background: #ffffff; color: #111827; }
        QComboBox { background: #ffffff; color: #111827; }
        QPushButton { background: #e5e7eb; color: #111827; }
        QGroupBox { border: 1px solid #d1d5db; margin-top: 8px; }
        QPlainTextEdit { background: #ffffff; color: #111827; }
    """


def append_log(log_box: QtWidgets.QPlainTextEdit, message: str) -> None:
    now = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
    log_box.appendPlainText(f"[{now}] {message}")
    log_box.moveCursor(QtGui.QTextCursor.End)
