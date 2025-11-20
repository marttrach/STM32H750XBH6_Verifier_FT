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
    status: str = "IDLE"
    detail: str = ""


class StatusLabel(QtWidgets.QLabel):
    """Small helper to color-code status labels."""

    COLORS = {
        "IDLE": "#808080",
        "RUNNING": "#1f5fbf",
        "PASS": "#1a7f37",
        "FAIL": "#c93c37",
    }

    def __init__(self, text: str = "IDLE", scale: float = 1.0) -> None:
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
            QWidget {
                background: #202124;
                color: #e8eaed;
                font-family: "Microsoft JhengHei", "Segoe UI", "Noto Sans", sans-serif;
            }
            QLineEdit, QComboBox {
                background: #2b2f36;
                color: #e8eaed;
                border: 1px solid #3c4043;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QLineEdit:disabled, QComboBox:disabled {
                background: #1f2227;
                color: #8e9399;
            }
            QPushButton {
                background: #3c4043;
                color: #e8eaed;
                border: 1px solid #5f6368;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton:enabled:hover {
                background: #4a4f55;
            }
            QPushButton:enabled:pressed {
                background: #5f6368;
            }
            QPushButton:disabled {
                background: #2b2f36;
                color: #7b8087;
                border-color: #3a3d42;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #5f6368;
                background: #2b2f36;
            }
            QCheckBox::indicator:checked {
                background: #4a90e2;
                border-color: #6aa3ec;
            }
            QCheckBox::indicator:disabled {
                background: #1f2227;
                border-color: #3a3d42;
            }
            QCheckBox::indicator:disabled:checked {
                background: #3a4a63;
                border-color: #55667d;
            }
            QGroupBox {
                border: 1px solid #3c4043;
                border-radius: 12px;
                margin-top: 16px;
                padding: 16px;
            }
            QPlainTextEdit {
                background: #0f1115;
                color: #d1d5db;
                border-radius: 10px;
                padding: 8px;
            }
        """
    return """
        QWidget {
            background: #f5f6fb;
            color: #1f2937;
            font-family: "Microsoft JhengHei", "Segoe UI", "Noto Sans", sans-serif;
        }
        QLineEdit, QComboBox {
            background: #ffffff;
            color: #111827;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            padding: 4px 8px;
        }
        QLineEdit:disabled, QComboBox:disabled {
            background: #f3f4f6;
            color: #9ca3af;
        }
        QPushButton {
            background: #e5e7eb;
            color: #111827;
            border: 1px solid #cfd5df;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: 600;
        }
        QPushButton:enabled:hover {
            background: #d5dbeb;
        }
        QPushButton:enabled:pressed {
            background: #c1c9dd;
        }
            QPushButton:disabled {
                background: #f3f4f6;
                color: #b0b5c2;
                border-color: #e5e7eb;
            }
            QCheckBox {
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #cfd5df;
                background: #ffffff;
            }
            QCheckBox::indicator:checked {
                background: #2563eb;
                border-color: #1d4ed8;
            }
            QCheckBox::indicator:disabled {
                background: #f3f4f6;
                border-color: #d1d5db;
            }
            QCheckBox::indicator:disabled:checked {
                background: #9cb5f1;
                border-color: #7c91d6;
            }
            QGroupBox {
                border: 1px solid #d1d5db;
                border-radius: 12px;
                margin-top: 16px;
                padding: 16px;
        }
        QPlainTextEdit {
            background: #ffffff;
            color: #111827;
            border-radius: 10px;
            padding: 8px;
        }
    """


def append_log(log_box: QtWidgets.QPlainTextEdit, message: str) -> None:
    now = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
    log_box.appendPlainText(f"[{now}] {message}")
    log_box.moveCursor(QtGui.QTextCursor.End)
