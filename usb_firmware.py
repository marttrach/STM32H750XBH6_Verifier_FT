from PySide6 import QtCore


def run_usb_flash(callback, duration_ms: int = 800) -> None:
    """Simulate USB firmware flash. Replace with actual dfu-util/cli hook."""
    QtCore.QTimer.singleShot(duration_ms, lambda: callback(True, "USB Firmware 完成"))
