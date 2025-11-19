from typing import List

from PySide6 import QtWidgets

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - optional dependency
    list_ports = None


def available_ports() -> List[str]:
    if list_ports is None:
        return []
    return [p.device for p in list_ports.comports()]


def populate_combo(combo: QtWidgets.QComboBox, ports: List[str]) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("None", None)
    for dev in ports:
        combo.addItem(dev, dev)
    combo.setCurrentIndex(0)
    combo.blockSignals(False)
