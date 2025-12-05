import time
from typing import Callable, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets

try:
    from serial.tools import list_ports
    import serial
except ImportError:  # pragma: no cover - optional dependency
    list_ports = None
    serial = None

PAYLOAD = bytes(range(128))  # fixed binary payload for loopback verification


def available_ports() -> List[str]:
    if list_ports is None:
        print("[COM-DEBUG] pyserial not installed; available_ports empty.")
        return []
    ports = [p.device for p in list_ports.comports()]
    # print(f"[COM-DEBUG] Detected ports: {ports}")
    return ports


def populate_combo(combo: QtWidgets.QComboBox, ports: List[str]) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("None", None)
    for dev in ports:
        combo.addItem(dev, dev)
    combo.setCurrentIndex(0)
    combo.blockSignals(False)


def _perform_loopback(
    port: str,
    baudrate: int = 115200,
    timeout_s: float = 1.0,
    poll_timeout_s: float = 0.002,
    wait_after_write_s: float = 0.5,
) -> Tuple[bool, str]:
    if serial is None:
        print("[COM-DEBUG] Loopback aborted: pyserial not installed.")
        return False, "pyserial not installed"
    try:
        print(f"[COM-DEBUG] Opening port {port} @ {baudrate} baud")
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=poll_timeout_s,
            write_timeout=timeout_s,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
        )
    except Exception as exc:  # pragma: no cover
        print(f"[COM-DEBUG] Open port failed: {exc}")
        return False, f"Open port failed: {exc}"

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"[COM-DEBUG] Writing {len(PAYLOAD)} bytes to {port}")
        try:
            ser.write(PAYLOAD)
            ser.flush()
        except Exception as exc:
            detail = f"Loopback write error: {exc}"
            print(f"[COM-DEBUG] {detail}")
            return False, detail

        receive_deadline = time.monotonic() + wait_after_write_s
        received = bytearray()
        while time.monotonic() < receive_deadline and len(received) < len(PAYLOAD):
            try:
                chunk = ser.read(len(PAYLOAD) - len(received))
            except Exception as exc:
                detail = f"Loopback read error: {exc}"
                print(f"[COM-DEBUG] {detail}")
                return False, detail
            if chunk:
                received.extend(chunk)
                print(f"[COM-DEBUG] Read {len(chunk)} bytes (total {len(received)})")
                if len(received) >= len(PAYLOAD):
                    break
            else:
                time.sleep(0.01)

        if len(received) < len(PAYLOAD):
            print(
                f"[COM-DEBUG] Loopback timeout: expected {len(PAYLOAD)} bytes, got {len(received)}"
            )
            return False, f"Loopback timeout after {wait_after_write_s}s (got {len(received)} bytes)"
        if received[: len(PAYLOAD)] == PAYLOAD:
            print("[COM-DEBUG] Loopback OK")
            return True, f"Loopback OK ({len(received)} bytes)"
        print(
            f"[COM-DEBUG] Loopback mismatch: expected {len(PAYLOAD)} bytes, got {len(received)}"
        )
        return False, f"Loopback mismatch: got {len(received)} bytes"
    except Exception as exc:  # pragma: no cover
        print(f"[COM-DEBUG] Loopback error: {exc}")
        return False, f"Loopback error: {exc}"
    finally:
        try:
            ser.close()
            print(f"[COM-DEBUG] Closed port {port}")
        except Exception:
            print(f"[COM-DEBUG] Error closing port {port}")
            pass


class _LoopbackJob(QtCore.QRunnable):
    def __init__(
        self,
        port: str,
        callback: Callable[[bool, str], None],
        label: str,
    ) -> None:
        super().__init__()
        self.port = port
        self.callback = callback
        self.label = label

    def _dispatch_result(self, passed: bool, message: str) -> None:
        """Post result back to the main thread (or call directly)."""
        print(f"[COM-DEBUG] Dispatching result for {self.port}: {message}")
        cb = self.callback
        if cb is None:
            print("[COM-DEBUG] No callback set; skipping dispatch.")
            return
        app = QtWidgets.QApplication.instance()
        if app:
            # Ensure callback runs in the GUI thread to update status labels.
            QtCore.QTimer.singleShot(0, app, lambda: cb(passed, message))
        else:
            cb(passed, message)

    def run(self) -> None:
        print(f"[COM-DEBUG] Starting loopback job for {self.port} ({self.label})")
        try:
            passed, detail = _perform_loopback(self.port)
        except Exception as exc:  # pragma: no cover - defensive
            passed, detail = False, f"Loopback exception: {exc}"
            print(f"[COM-DEBUG] Loopback job exception: {exc}")
        message = f"{self.label}: {detail}"
        self._dispatch_result(passed, message)


def run_loopback_test(
    port: str,
    label: str,
    callback: Callable[[bool, str], None],
) -> None:
    """Launch serial loopback test in background; callback(passed, detail)."""
    print(f"[COM-DEBUG] Queue loopback test on {port} ({label})")
    job = _LoopbackJob(port, callback, label)
    QtCore.QThreadPool.globalInstance().start(job)
