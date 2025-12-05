import time
import struct
from typing import Callable, Optional, Tuple

from PySide6 import QtCore, QtWidgets

from binary_protocol import BinaryProtocol

try:
    import serial  # type: ignore
    from serial.tools import list_ports  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    serial = None
    list_ports = None

# STM32 VID/PID used by downloader.stm32_get_port().
STM32_VID = 1155
STM32_PID = 41879

LogFn = Callable[[str], None]
ResultFn = Callable[[bool, str], None]

# Track the most recently opened STM32 serial handle so other flows (e.g. Ctrl+D)
# can reuse an existing connection instead of reopening the port while it is busy.
_ACTIVE_STM32_HANDLE = None  # type: ignore
_ACTIVE_STM32_PORT: Optional[str] = None


def set_active_stm32_handle(handle, port: Optional[str]) -> None:
    global _ACTIVE_STM32_HANDLE, _ACTIVE_STM32_PORT
    _ACTIVE_STM32_HANDLE = handle
    _ACTIVE_STM32_PORT = port

def close_active_stm32_handle() -> None:
    """Close any active STM32 serial handle being tracked."""
    global _ACTIVE_STM32_HANDLE, _ACTIVE_STM32_PORT
    try:
        if _ACTIVE_STM32_HANDLE and getattr(_ACTIVE_STM32_HANDLE, "is_open", False):
            _ACTIVE_STM32_HANDLE.close()
    except Exception:
        pass
    _ACTIVE_STM32_HANDLE = None
    _ACTIVE_STM32_PORT = None


def get_active_stm32_handle():
    """
    Return a tuple (handle, port) if a STM32 handle is currently active/open.
    The handle is whatever object was passed to set_active_stm32_handle (usually serial.Serial).
    """
    return _ACTIVE_STM32_HANDLE, _ACTIVE_STM32_PORT


def discover_stm32_port() -> Optional[str]:
    """Mirror downloader.stm32_get_port() logic to locate the STM32 COM port."""
    if list_ports is None:
        return None
    for port in list_ports.comports():
        if port.pid == STM32_PID and port.vid == STM32_VID:
            return port.device
    return None


class Stm32BinaryClient:
    def __init__(
        self,
        port: Optional[str] = None,
        log_cb: Optional[LogFn] = None,
        baudrate: int = 115200,
        read_timeout_s: float = 0.05,
    ) -> None:
        self.port = port
        self._log_cb = log_cb
        self.baudrate = baudrate
        self.read_timeout_s = read_timeout_s
        self.ser = None

    def _log(self, message: str) -> None:
        cb = self._log_cb
        if not cb:
            return
        app = QtWidgets.QApplication.instance()
        if app:
            QtCore.QTimer.singleShot(0, app, lambda: cb(message))
        else:
            QtCore.QTimer.singleShot(0, lambda: cb(message))

    def open(self) -> str:
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        # Reuse an active STM32 handle if one is already open.
        cur_handle, cur_port = get_active_stm32_handle()
        if cur_handle and getattr(cur_handle, "is_open", False):
            self.ser = cur_handle
            self.port = cur_port
            self._log(f"[STM32] reuse {self.port}")
            return self.port
        port = self.port or discover_stm32_port()
        if not port:
            raise RuntimeError("stm32_get_port not found (VID=0x0483 PID=0xA3D7)")

        self.ser = serial.Serial(
            port=port,
            baudrate=self.baudrate,
            timeout=self.read_timeout_s,
            write_timeout=1,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
        )
        self.port = self.ser.port
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self._log(f"[STM32] open {self.port}")
        set_active_stm32_handle(self.ser, self.port)
        return self.port

    def close(self) -> None:
        if self.ser:
            current = self.ser
            try:
                if self.ser.is_open:
                    self.ser.close()
                    self._log(f"[STM32] close {self.port}")
            except Exception:
                pass
        # Only clear the active handle if it still points to us.
        cur_handle, _ = get_active_stm32_handle()
        if cur_handle is current:
            set_active_stm32_handle(None, None)
        self.ser = None

    def send_statement(self, statement: str) -> None:
        if not self.ser:
            raise RuntimeError("STM32 port not opened")
        frame = BinaryProtocol.build_exec_statement_cmd(statement)
        self.ser.write(frame)
        self.ser.flush()
        self._log(f"[STM32] TX {statement.strip()}")

    def send_get_register(self, reg_id: int) -> None:
        if not self.ser:
            raise RuntimeError("STM32 port not opened")
        frame = BinaryProtocol.build_get_reg_cmd(reg_id)
        self.ser.write(frame)
        self.ser.flush()
        self._log(f"[STM32] TX get_reg {reg_id}")

    def read_until_idle(self, idle_timeout_s: float = 0.1, max_wait_s: float = 1.2) -> bytes:
        if not self.ser:
            raise RuntimeError("STM32 port not opened")
        start = time.time()
        last_rx = start
        buf = bytearray()
        while time.time() - start < max_wait_s:
            in_waiting = self.ser.in_waiting if hasattr(self.ser, "in_waiting") else 0
            chunk = self.ser.read(in_waiting or 1)
            if chunk:
                buf.extend(chunk)
                last_rx = time.time()
            elif time.time() - last_rx >= idle_timeout_s:
                break
        return bytes(buf)


class GpioTestJob(QtCore.QRunnable):
    def __init__(
        self,
        *,
        stm32_port: Optional[str],
        esp32_port: Optional[str],
        log_cb: Optional[LogFn],
        callback: ResultFn,
    ) -> None:
        super().__init__()
        self.stm32_port = stm32_port
        self.esp32_port = esp32_port
        self.log_cb = log_cb
        self.callback = callback

    def _log(self, message: str) -> None:
        cb = self.log_cb
        if not cb:
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

    def _read_until_idle(self, ser, idle_timeout_s: float, max_wait_s: float) -> bytes:
        start = time.time()
        last_rx = start
        buf = bytearray()
        while time.time() - start < max_wait_s:
            in_waiting = ser.in_waiting if hasattr(ser, "in_waiting") else 0
            chunk = ser.read(in_waiting or 1)
            if chunk:
                buf.extend(chunk)
                last_rx = time.time()
            elif time.time() - last_rx >= idle_timeout_s:
                break
        return bytes(buf)

    def _ping_esp32(self) -> Tuple[bool, str]:
        if not self.esp32_port:
            return True, "ESP32 port not provided; skipping ping."
        if serial is None:
            return False, "pyserial is not installed"
        try:
            ser = serial.Serial(
                port=self.esp32_port,
                baudrate=115200,
                timeout=0.05,
                write_timeout=1,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"open ESP32 port failed: {exc}"

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"A")
            ser.flush()
            self._log(f"[GPIO] ESP32 TX 'A' on {self.esp32_port}")
            rx = self._read_until_idle(ser, idle_timeout_s=0.05, max_wait_s=0.4)
            text = rx.decode(errors="ignore").strip()
            if text:
                self._log(f"[GPIO] ESP32 RX: {text}")
            else:
                self._log("[GPIO] ESP32 RX: (no response)")
            return True, text
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _send_esp32_finish(self) -> None:
        """Send ESP32 end marker 'F' after GPIO test completes."""
        if not self.esp32_port or serial is None:
            return
        try:
            ser = serial.Serial(
                port=self.esp32_port,
                baudrate=115200,
                timeout=0.05,
                write_timeout=1,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
        except Exception as exc:
            self._log(f"[GPIO] ESP32 end TX failed (open): {exc}")
            return
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            ser.write(b"F")
            ser.flush()
            self._log(f"[GPIO] ESP32 TX 'F' on {self.esp32_port}")
            rx = self._read_until_idle(ser, idle_timeout_s=0.05, max_wait_s=0.3)
            text = rx.decode(errors="ignore").strip()
            if text:
                self._log(f"[GPIO] ESP32 RX after F: {text}")
        except Exception as exc:
            self._log(f"[GPIO] ESP32 end TX error: {exc}")
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _run_gpio_sequence(self) -> Tuple[bool, str]:
        client = Stm32BinaryClient(port=self.stm32_port, log_cb=self.log_cb)
        port_name = client.open()
        try:
            # Clear any residual RX before issuing commands.
            try:
                if client.ser:
                    client.ser.reset_input_buffer()
                    client.ser.reset_output_buffer()
                    client.read_until_idle(idle_timeout_s=0.05, max_wait_s=0.2)
            except Exception:
                pass
            # Sequence described in the spec.
            time.sleep(0.05)
            client.send_statement("gpio0123out()\n")
            time.sleep(0.5)
            client.send_statement("gpio4567read()\n")
            time.sleep(0.05)
            client.send_statement("gpio4567out()\n")
            time.sleep(0.5)
            client.send_statement("gpio0123read()\n")
            time.sleep(0.05)
            rx = client.read_until_idle(idle_timeout_s=0.1, max_wait_s=1.5)
            text = rx.decode(errors="ignore")
            if text:
                self._log(f"[GPIO] STM32 RX ({port_name}): {text.strip()}")
            else:
                self._log(f"[GPIO] STM32 RX ({port_name}): (empty)")
            raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
            lines = [ln.lower() for ln in raw_lines if not ln.lower().startswith("bin_cmd:")]
            expected = ["y", "y", "y", "y"]
            ok = lines[:4] == expected and all(line == "y" for line in lines) if lines else False
            if not ok and lines:
                first_non_y = next((ln for ln in lines if ln != "y"), "")
                detail = (
                    f"GPIO mismatch: expected {expected}, got head={lines[:4]} (first non-y: {first_non_y})"
                )
            else:
                detail = "\n".join(raw_lines).strip() or "STM32 GPIO did not return data"
            return ok, detail
        finally:
            client.close()
            try:
                # Ensure any tracked active handle is cleared/closed.
                from stm32_binary_tool import close_active_stm32_handle  # safe local import
                close_active_stm32_handle()
            except Exception:
                pass

    def run(self) -> None:
        if serial is None:
            self._emit(False, "pyserial is not installed")
            return
        esp_ok, esp_detail = self._ping_esp32()
        if not esp_ok:
            self._emit(False, esp_detail or "ESP32 ping failed")
            return
        ok = False
        detail = ""
        try:
            ok, detail = self._run_gpio_sequence()
        except Exception as exc:  # pragma: no cover - defensive
            detail = f"GPIO test exception: {exc}"
        finally:
            self._send_esp32_finish()
        status = "PASS" if ok else "FAIL"
        self._emit(ok, f"GPIO {status}: {detail}")


def run_gpio_test(
    *,
    stm32_port: Optional[str],
    esp32_port: Optional[str],
    log_cb: Optional[LogFn],
    callback: ResultFn,
) -> None:
    job = GpioTestJob(
        stm32_port=stm32_port,
        esp32_port=esp32_port,
        log_cb=log_cb,
        callback=callback,
    )
    QtCore.QThreadPool.globalInstance().start(job)


def _decode_value(dtype: int, data: bytes):
    try:
        if dtype == 0x0:  # bool
            return bool(data[0]) if data else False
        if dtype == 0x1:  # string
            return data.decode(errors="ignore")
        if dtype == 0x2:  # int
            fmt = {1: "<b", 2: "<h", 4: "<i", 8: "<q"}.get(len(data))
            return struct.unpack(fmt, data)[0] if fmt else None
        if dtype == 0x3:  # unsigned int
            fmt = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}.get(len(data))
            return struct.unpack(fmt, data)[0] if fmt else None
        if dtype == 0x4:  # float
            fmt = {4: "<f", 8: "<d"}.get(len(data))
            return struct.unpack(fmt, data)[0] if fmt else None
    except Exception:
        return None
    return None


def _parse_set_reg_frames(buf: bytes) -> dict[int, object]:
    """
    Parse one or more SET_REG responses (0x11 0x00 ...) from the STM32.
    Returns a mapping reg_id -> decoded value.
    """
    res: dict[int, object] = {}
    idx = 0
    length = len(buf)
    while idx + 7 <= length:
        if buf[idx] != 0x11 or buf[idx + 1] != 0x00:
            idx += 1
            continue
        reg_id = struct.unpack("<H", buf[idx + 2 : idx + 4])[0]
        dtype = buf[idx + 4]
        data_len = struct.unpack("<H", buf[idx + 5 : idx + 7])[0]
        end = idx + 7 + data_len
        if end > length:
            break
        data = buf[idx + 7 : end]
        val = _decode_value(dtype, data)
        res[reg_id] = val
        idx = end
    return res


class _Reg:
    def __init__(self) -> None:
        self.val = None


class _RegBank:
    def __init__(self, reg_ids: set[int]) -> None:
        self.regs = {rid: _Reg() for rid in reg_ids}

    def get_register(self, reg_id: int):
        return self.regs.get(reg_id)


def _decode_regs_via_protocol(buf: bytes, reg_ids: set[int]) -> dict[int, object]:
    """
    Use BinaryProtocol.handle_input_buf to decode SET_REG frames into a reg map.
    """
    bank = _RegBank(reg_ids)
    try:
        BinaryProtocol.handle_input_buf(buf, lambda _: None, bank)
    except Exception:
        return {}
    return {rid: bank.regs[rid].val for rid in reg_ids if bank.regs[rid].val is not None}


def _decode_ascii_value(buf: bytes) -> Optional[float]:
    try:
        text = buf.decode(errors="ignore").strip()
    except Exception:
        return None
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_last_number(buf: bytes) -> Optional[float]:
    """Try to pull the last numeric token from ASCII RX."""
    try:
        text = buf.decode(errors="ignore")
    except Exception:
        return None
    candidates = []
    for line in text.splitlines():
        token = line.strip()
        if not token:
            continue
        try:
            candidates.append(float(token))
        except ValueError:
            continue
    return candidates[-1] if candidates else None


class LcdTestJob(QtCore.QRunnable):
    def __init__(
        self,
        *,
        stm32_port: Optional[str],
        log_cb: Optional[LogFn],
        callback: ResultFn,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__()
        self.stm32_port = stm32_port
        self.log_cb = log_cb
        self.callback = callback
        self.timeout_s = timeout_s

    def _log(self, message: str) -> None:
        cb = self.log_cb
        if not cb:
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
            self._emit(False, "pyserial is not installed")
            return
        client = Stm32BinaryClient(port=self.stm32_port, log_cb=self.log_cb)
        result: Optional[Tuple[bool, str]] = None
        try:
            try:
                port_name = client.open()
            except Exception as exc:
                result = (False, f"open STM32 port failed: {exc}")
            else:
                last_v17 = None
                last_v46 = None
                start = time.monotonic()
                try:
                    if client.ser:
                        client.ser.reset_input_buffer()
                        client.ser.reset_output_buffer()
                        client.read_until_idle(idle_timeout_s=0.05, max_wait_s=0.2)
                except Exception:
                    pass

                while True:
                    elapsed = time.monotonic() - start
                    if elapsed > self.timeout_s:
                        break
                    try:
                        if client.ser:
                            client.ser.reset_input_buffer()
                            client.ser.reset_output_buffer()
                        client.send_get_register(17)
                        time.sleep(0.2)  # give device time to respond
                        rx1 = client.read_until_idle(idle_timeout_s=0.1, max_wait_s=0.5)
                        if rx1:
                            self._log(f"[LCD] STM32 RX reg17 ({port_name}): {rx1.hex(' ')}")
                        parsed = _decode_regs_via_protocol(rx1, {17})
                        cur_v17 = parsed.get(17)
                        if cur_v17 is None:
                            cur_v17 = _extract_last_number(rx1)
                        if cur_v17 is not None:
                            last_v17 = cur_v17

                        if client.ser:
                            client.ser.reset_input_buffer()
                            client.ser.reset_output_buffer()
                        client.send_get_register(46)
                        time.sleep(0.2)  # allow RX settle between TX/RX
                        rx2 = client.read_until_idle(idle_timeout_s=0.1, max_wait_s=0.5)
                        if rx2:
                            self._log(f"[LCD] STM32 RX reg46 ({port_name}): {rx2.hex(' ')}")
                        parsed2 = _decode_regs_via_protocol(rx2, {17, 46})
                        cur_v46 = parsed2.get(46)
                        cur_v17_b = parsed2.get(17)
                        if cur_v46 is None:
                            cur_v46 = _extract_last_number(rx2)
                        if cur_v46 is not None:
                            last_v46 = cur_v46
                        if cur_v17_b is not None:
                            last_v17 = cur_v17_b
                    except Exception as exc:
                        result = (False, f"STM32 get register send/recv error: {exc}")
                        break

                    if last_v17 is not None and last_v46 is not None:
                        self._log(f"[LCD] reg17={last_v17}, reg46={last_v46}")
                        if isinstance(last_v17, (int, float)) and last_v17 <= 50 and last_v46 == 1:
                            detail = f"LCD/Backlight OK (reg17={last_v17}, reg46={last_v46})"
                            result = (True, detail)
                            break

                    # wait until next second tick if time remains
                    time.sleep(1.0)

                if result is None:
                    detail = (
                        f"Timeout waiting for reg17<=50 and reg46==1 (last reg17={last_v17}, reg46={last_v46})"
                    )
                    result = (False, detail)
        finally:
            client.close()
            if result is None:
                result = (False, "LCD test ended without result")
        self._emit(*result)


def run_lcd_test(
    *,
    stm32_port: Optional[str],
    log_cb: Optional[LogFn],
    callback: ResultFn,
    timeout_s: float = 10.0,
) -> None:
    job = LcdTestJob(
        stm32_port=stm32_port,
        log_cb=log_cb,
        callback=callback,
        timeout_s=timeout_s,
    )
    QtCore.QThreadPool.globalInstance().start(job)


class EthernetTestJob(QtCore.QRunnable):
    def __init__(
        self,
        *,
        stm32_port: Optional[str],
        log_cb: Optional[LogFn],
        callback: ResultFn,
    ) -> None:
        super().__init__()
        self.stm32_port = stm32_port
        self.log_cb = log_cb
        self.callback = callback

    def _log(self, message: str) -> None:
        cb = self.log_cb
        if not cb:
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
            self._emit(False, "pyserial is not installed")
            return
        client = Stm32BinaryClient(port=self.stm32_port, log_cb=self.log_cb)
        result: Optional[Tuple[bool, str]] = None
        try:
            try:
                port_name = client.open()
            except Exception as exc:
                result = (False, f"open STM32 port failed: {exc}")
            else:
                # Clean buffers before starting.
                try:
                    if client.ser:
                        client.ser.reset_input_buffer()
                        client.ser.reset_output_buffer()
                        client.read_until_idle(idle_timeout_s=0.05, max_wait_s=0.2)
                except Exception:
                    pass

                def _send_ping_and_wait() -> bool:
                    """Send pings() and wait briefly for 'y'."""
                    nonlocal result
                    try:
                        client.send_statement("pings()\n")
                    except Exception as exc_inner:
                        result = (False, f"STM32 ethernet ping send error: {exc_inner}")
                        return False
                    deadline = time.monotonic() + 1.0
                    rx_all = bytearray()
                    while time.monotonic() < deadline:
                        rx = client.read_until_idle(idle_timeout_s=0.1, max_wait_s=0.3)
                        if rx:
                            rx_all.extend(rx)
                            self._log(f"[ETH] STM32 RX ({port_name}): {rx.decode(errors='ignore').strip()}")
                            if b"y\n" in rx_all or b"y\r\n" in rx_all or rx_all.strip() == b"y":
                                return True
                        time.sleep(0.05)
                    if rx_all:
                        self._log(f"[ETH] STM32 RX aggregate ({port_name}): {rx_all.decode(errors='ignore').strip()}")
                    return False

                attempts = 0
                found = False
                # First attempt: direct pings() without restarting ethernet.
                attempts += 1
                found = _send_ping_and_wait()

                while not found and attempts < 3 and result is None:
                    try:
                        client.send_statement("eths()\n")
                    except Exception as exc:
                        result = (False, f"STM32 ethernet start error: {exc}")
                        break
                    time.sleep(4.0)
                    attempts += 1
                    found = _send_ping_and_wait()

                if result is None:
                    if found:
                        result = (True, "Ethernet ping OK (received y)")
                    else:
                        result = (False, "No 'y' received after 3 ping attempts")
        finally:
            client.close()
            if result is None:
                result = (False, "Ethernet test ended without result")
        self._emit(*result)


def run_ethernet_test(
    *,
    stm32_port: Optional[str],
    log_cb: Optional[LogFn],
    callback: ResultFn,
) -> None:
    job = EthernetTestJob(
        stm32_port=stm32_port,
        log_cb=log_cb,
        callback=callback,
    )
    QtCore.QThreadPool.globalInstance().start(job)
