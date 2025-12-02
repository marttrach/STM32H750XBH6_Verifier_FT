import time
from typing import Callable, Dict, Tuple

from PySide6 import QtCore, QtWidgets

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    serial = None


Esp32Callback = Callable[[bool, str, Dict[str, float]], None]


def _parse_metrics(text: str) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        if "input_v" in line and "mv" in line:
            try:
                val = float(line.split("=")[1].split("mv")[0])
                metrics["vin_mv"] = val
            except Exception:
                pass
        if "input_i" in line and "ma" in line:
            try:
                val = float(line.split("=")[1].split("ma")[0])
                metrics["iin_ma"] = val
            except Exception:
                pass
        if "3v3" in line and "mv" in line:
            try:
                val = float(line.split("=")[1].split("mv")[0])
                metrics["v3v3_mv"] = val
            except Exception:
                pass
        if "5v" in line and "mv" in line:
            try:
                val = float(line.split("=")[1].split("mv")[0])
                metrics["v5v_mv"] = val
            except Exception:
                pass
    return metrics


class Esp32PowerJob(QtCore.QRunnable):
    def __init__(
        self,
        port: str,
        callback: Esp32Callback,
        log_cb: Callable[[str], None],
        read_timeout_s: float = 3.0,
    ) -> None:
        super().__init__()
        self.port = port
        self.callback = callback
        self.log_cb = log_cb
        self.read_timeout_s = read_timeout_s
        self.idle_timeout_s = 1.0
        self.max_wait_s = 10.0

    def _log(self, message: str) -> None:
        """Ensure ESP32 logs are emitted on the GUI thread."""
        cb = self.log_cb
        if cb is None:
            return
        app = QtWidgets.QApplication.instance()
        if app:
            QtCore.QTimer.singleShot(0, app, lambda: cb(message))
        else:
            QtCore.QTimer.singleShot(0, lambda: cb(message))

    def _read_until_idle(self, ser) -> list[str]:
        """Read lines until idle_timeout_s of silence or max_wait_s reached."""
        start = time.time()
        last_rx = start
        lines: list[str] = []
        while True:
            line = ser.readline()
            now = time.time()
            if line:
                decoded = line.decode(errors="ignore").strip()
                last_rx = now
                if decoded:
                    lines.append(decoded)
                    self._log(f"[ESP32] RX: {decoded}")
                    print(f"[DEBUG][ESP32] RX: {decoded}")
            if (now - last_rx) >= self.idle_timeout_s:
                break
            if (now - start) >= self.max_wait_s:
                print("[DEBUG][ESP32] max_wait reached, stopping RX")
                break
        return lines

    def _emit(self, ok: bool, text: str, metrics: Dict[str, float]) -> None:
        cb = self.callback

        def wrapper() -> None:
            try:
                cb(ok, text, metrics)
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[DEBUG][ESP32] callback exception: {exc}")

        app = QtWidgets.QApplication.instance()
        if app:
            # Attach to QApplication so the callback always runs on the GUI thread.
            QtCore.QTimer.singleShot(0, app, wrapper)
        else:
            QtCore.QTimer.singleShot(0, wrapper)

    def run(self) -> None:
        if serial is None:
            self._emit(False, "pyserial is not installed", {})
            return
        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=115200,
                timeout=0.1,
                write_timeout=1,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[DEBUG][ESP32] open port failed: {exc}")
            self._emit(False, f"open ESP32 port failed: {exc}", {})
            return

        text_lines = []
        try:
            self._log(f"[ESP32] open {self.port}")
            print(f"[DEBUG][ESP32] open {self.port}")
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            # Sequence: E -> wait for RX idle -> T -> wait for RX idle -> S -> wait for RX idle
            try:
                ser.write(b"E")
                ser.flush()
                self._log("[ESP32] TX: E")
                print("[DEBUG][ESP32] TX: E")
            except Exception as exc:
                print(f"[DEBUG][ESP32] TX E failed: {exc}")
                self._emit(False, f"ESP32 TX E failed: {exc}", {})
                return
            text_lines.extend(self._read_until_idle(ser))
            try:
                ser.write(b"T")
                ser.flush()
                self._log("[ESP32] TX: T")
                print("[DEBUG][ESP32] TX: T")
            except Exception as exc:
                print(f"[DEBUG][ESP32] TX T failed: {exc}")
                self._emit(False, f"ESP32 TX T failed: {exc}", {})
                return
            text_lines.extend(self._read_until_idle(ser))
            try:
                ser.write(b"S")
                ser.flush()
                self._log("[ESP32] TX: S")
                print("[DEBUG][ESP32] TX: S")
            except Exception as exc:
                print(f"[DEBUG][ESP32] TX S failed: {exc}")
                self._emit(False, f"ESP32 TX S failed: {exc}", {})
                return
            text_lines.extend(self._read_until_idle(ser))

            full_text = "\n".join(text_lines)
            metrics = _parse_metrics(full_text)
            if not text_lines:
                print("[DEBUG][ESP32] no response")
                self._emit(False, "ESP32 no response (timeout)", {})
            elif not metrics:
                print(f"[DEBUG][ESP32] no metrics parsed from: {full_text}")
                self._emit(False, "ESP32 returned no metrics", {})
            else:
                print(f"[DEBUG][ESP32] metrics parsed: {metrics}")
                self._emit(True, full_text, metrics)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[DEBUG][ESP32] read error: {exc}")
            self._emit(False, f"ESP32 read error: {exc}", {})
        finally:
            try:
                ser.close()
                self._log("[ESP32] close")
                print("[DEBUG][ESP32] close")
            except Exception:
                pass


class Esp32EndJob(QtCore.QRunnable):
    def __init__(
        self,
        port: str,
        log_cb: Callable[[str], None],
        callback: Callable[[bool, str], None],
        read_timeout_s: float = 1.5,
    ) -> None:
        super().__init__()
        self.port = port
        self.log_cb = log_cb
        self.callback = callback
        self.read_timeout_s = read_timeout_s

    def _log(self, message: str) -> None:
        """Ensure ESP32 logs are emitted on the GUI thread."""
        cb = self.log_cb
        if cb is None:
            return
        app = QtWidgets.QApplication.instance()
        if app:
            QtCore.QTimer.singleShot(0, app, lambda: cb(message))
        else:
            QtCore.QTimer.singleShot(0, lambda: cb(message))

    def _emit(self, ok: bool, detail: str) -> None:
        app = QtWidgets.QApplication.instance()
        if app:
            QtCore.QTimer.singleShot(0, app, lambda: self.callback(ok, detail))
        else:
            QtCore.QTimer.singleShot(0, lambda: self.callback(ok, detail))

    def run(self) -> None:
        if serial is None:
            self._emit(False, "pyserial not installed")
            return
        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=115200,
                timeout=0.2,
                write_timeout=1,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
        except Exception as exc:
            self._emit(False, f"open ESP32 port failed: {exc}")
            return
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"E")
            ser.flush()
            self._log("[ESP32] TX: E")
            start = time.time()
            text = ""
            while time.time() - start < self.read_timeout_s:
                line = ser.readline()
                if line:
                    decoded = line.decode(errors="ignore").strip()
                    if decoded:
                        text += decoded + "\n"
                        self._log(f"[ESP32] RX: {decoded}")
                    if "test end" in decoded.lower():
                        self._emit(True, "Test End")
                        return
            self._emit(False, text.strip() or "No response")
        except Exception as exc:  # pragma: no cover
            self._emit(False, f"ESP32 end error: {exc}")
        finally:
            try:
                ser.close()
                self._log("[ESP32] close")
            except Exception:
                pass


def start_power_sequence(port: str, callback: Esp32Callback, log_cb: Callable[[str], None]) -> None:
    job = Esp32PowerJob(port=port, callback=callback, log_cb=log_cb)
    QtCore.QThreadPool.globalInstance().start(job)


def send_end_signal(port: str, log_cb: Callable[[str], None], callback: Callable[[bool, str], None]) -> None:
    job = Esp32EndJob(port=port, log_cb=log_cb, callback=callback)
    QtCore.QThreadPool.globalInstance().start(job)
