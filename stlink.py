"""
STLink flashing helper built on local stm32cubeprog (CubeProgrammer API).

Key behaviors:
- Checks STM32CubeProgrammer installation path before connecting.
- Logs connected STLink board info and target info (device id/name/revision).
- Runs in a worker thread; callback always receives (passed, detail).
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6 import QtCore, QtWidgets

LOCAL_CUBEPROG = Path(__file__).resolve().parent / "stm32cubeprog" / "api.py"
_CUBEPROG_IMPORT_ERROR: Optional[str] = None

if LOCAL_CUBEPROG.exists():
    spec = importlib.util.spec_from_file_location(
        "stm32cubeprog.api_local", str(LOCAL_CUBEPROG)
    )
    cubeprog_module = importlib.util.module_from_spec(spec) if spec else None
    try:
        if spec and spec.loader and cubeprog_module:
            spec.loader.exec_module(cubeprog_module)
            CubeProgrammerApi = cubeprog_module.CubeProgrammerApi  # type: ignore[attr-defined]
            CubeProgrammerError = cubeprog_module.CubeProgrammerError  # type: ignore[attr-defined]
            CubeProgrammerResetMode = cubeprog_module.CubeProgrammerResetMode  # type: ignore[attr-defined]
        else:  # pragma: no cover
            raise ImportError("Cannot load stm32cubeprog.api spec")
    except Exception as exc:  # pragma: no cover
        CubeProgrammerApi = None
        CubeProgrammerError = None
        CubeProgrammerResetMode = None
        _CUBEPROG_IMPORT_ERROR = f"Failed to import {LOCAL_CUBEPROG}: {exc}"
else:
    CubeProgrammerApi = None  # type: ignore
    CubeProgrammerError = None  # type: ignore
    CubeProgrammerResetMode = None  # type: ignore
    _CUBEPROG_IMPORT_ERROR = f"Local CubeProgrammer API not found at {LOCAL_CUBEPROG}"


DEFAULT_ELF = Path("bootloader.elf")
DEFAULT_FREQ_KHZ = 4000
DEFAULT_RESET = "software"
DEFAULT_ADDRESS = "0x08000000"
DEFAULT_TIMEOUT_S = 15
class _StlinkJob(QtCore.QRunnable):
    def __init__(
        self,
        callback: Callable[[bool, str], None],
        elf_path: Path,
        freq_khz: int,
        reset: str,
        address: str,
        timeout_s: int,
    ) -> None:
        super().__init__()
        self.callback = callback
        self.elf_path = elf_path
        self.freq_khz = freq_khz
        self.reset = reset
        self.address = address
        self.timeout_s = timeout_s

    def run(self) -> None:
        passed, detail = self._flash()
        app = QtWidgets.QApplication.instance()
        if app:
            QtCore.QTimer.singleShot(0, app, lambda: self.callback(passed, detail))
        else:
            self.callback(passed, detail)

    def _flash(self) -> tuple[bool, str]:
        _log("Starting STLink flash worker...")
        if CubeProgrammerApi is None:
            msg = _CUBEPROG_IMPORT_ERROR or "CubeProgrammer API module unavailable."
            _log(f"ERROR: {msg}")
            return False, msg

        cube_root = _find_cubeprog_root()
        if not cube_root:
            msg = "STM32CubeProgrammer not found; install it and set STM32CUBEPROG_PATH"
            _log(f"ERROR: {msg}")
            return False, msg
        _log(f"Resolved CubeProgrammer root: {cube_root}")

        resolved_elf = (
            self.elf_path if self.elf_path.is_absolute() else (Path.cwd() / self.elf_path)
        ).resolve()
        if not resolved_elf.exists():
            msg = f"Bootloader file not found: {resolved_elf}"
            _log(f"ERROR: {msg}")
            return False, msg
        _log(f"Using firmware: {resolved_elf}")

        dll_path = _cubeprog_dll_path(cube_root)
        if dll_path and not dll_path.exists():
            msg = f"CubeProgrammer API not found at {dll_path}"
            _log(f"ERROR: {msg}")
            return False, msg

        _prepare_cubeprog_env(cube_root)

        start = time.monotonic()
        deadline = start + self.timeout_s
        try:
            _log("Loading CubeProgrammer API...")
            api = CubeProgrammerApi(str(cube_root))
            _log("CubeProgrammer API loaded.")
        except Exception as exc:  # CubeProgrammerError or OSError
            msg = f"Failed to load CubeProgrammer API: {exc}"
            _log(f"ERROR: {msg}")
            return False, msg

        try:
            ok, stlinks = _run_with_timeout(api.stlink.find, _step_timeout(deadline), "detect STLink")
            if not ok:
                _log(f"ERROR: {stlinks}")
                return False, stlinks  # error message
            if len(stlinks) == 0:
                msg = "No STLink detected; check USB connection"
                _log(f"ERROR: {msg}")
                return False, msg
            if len(stlinks) > 1:
                msg = f"Multiple STLinks found ({len(stlinks)}); leave only one connected"
                _log(f"ERROR: {msg}")
                return False, msg
            _log("STLink device detected.")

            stlink = stlinks[0]
            stlink.frequency = self.freq_khz * 1000  # Hz expected
            stlink.reset_mode = _reset_mode_from_text(self.reset)
            _log(
                f"Preparing STLink board={stlink.board} FW={stlink.firmware_version} "
                f"SN={stlink.serial_number} freq={stlink.frequency}"
            )

            ok, err = _run_with_timeout(
                lambda: api.stlink.connect(stlink), _step_timeout(deadline), "connect STLink"
            )
            if not ok:
                _log(f"ERROR: {err}")
                return False, err
            _log("STLink connected.")

            ok, target = _run_with_timeout(api.info, _step_timeout(deadline), "read target info")
            if not ok:
                _log(f"ERROR: {target}")
                return False, target
            _log(
                f"Target info: name={getattr(target, 'name', '?')} "
                f"ID={getattr(target, 'device_id', '?')} rev={getattr(target, 'revision_id', '?')}"
            )

            if hasattr(api, "write_option_bytes"):
                try:
                    _log("Setting RDP level to 0xAA (unlocked)")
                    api.write_option_bytes("-ob rdp=0xAA BOR_LEV=0")
                except Exception as exc:
                    _log(f"ERROR: Failed to update RDP level: {exc}")
                    return False, f"Failed to set RDP level: {exc}"

            if time.monotonic() > deadline:
                msg = f"Operation timed out after {self.timeout_s}s; check STLink connection"
                _log(f"ERROR: {msg}")
                return False, msg

            ok, err = _run_with_timeout(
                lambda: api.download(
                    str(resolved_elf),
                    int(self.address, 0),
                    skip_erase=False,
                    verify=True,
                ),
                _step_timeout(deadline),
                "flash bootloader",
            )
            if not ok:
                _log(f"ERROR: {err}")
                return False, err
            _log("Bootloader flashed.")

            ok, err = _run_with_timeout(
                lambda: api.reset(stlink.reset_mode),
                _step_timeout(deadline),
                "reset target",
            )
            if not ok:
                _log(f"ERROR: {err}")
                return False, err
            _log("Target reset.")

            detail = (
                f"Board: {stlink.board}, FW: {stlink.firmware_version}, SN: {stlink.serial_number}; "
                f"Device: {getattr(target, 'name', '?')} (ID: {getattr(target, 'device_id', '?')}, "
                f"Rev: {getattr(target, 'revision_id', '?')})"
            )
            success_msg = f"Flashed successfully in {time.monotonic() - start:.1f}s. {detail}"
            _log(f"PASS: {success_msg}")
            return True, success_msg
        except CubeProgrammerError as exc:
            msg = f"CubeProgrammer error: {exc}"
            _log(f"ERROR: {msg}")
            return False, msg
        except Exception as exc:
            msg = f"Flash failed: {exc}"
            _log(f"ERROR: {msg}")
            return False, msg
        finally:
            try:
                api.disconnect()
            except Exception as exc:
                _log(f"Warning: disconnect raised an exception: {exc}")
            else:
                _log("CubeProgrammer API disconnected.")


def run_stlink(
    callback: Callable[[bool, str], None],
    elf_path: Optional[Path] = None,
    freq_khz: int = DEFAULT_FREQ_KHZ,
    reset: str = DEFAULT_RESET,
    address: str = DEFAULT_ADDRESS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> None:
    """
    Launch STLink flash in background.
    callback: function(passed: bool, detail: str)
    """
    job = _StlinkJob(
        callback=callback,
        elf_path=elf_path or DEFAULT_ELF,
        freq_khz=freq_khz,
        reset=reset,
        address=address,
        timeout_s=timeout_s,
    )
    _log(
        f"Queue STLink job (file={elf_path or DEFAULT_ELF}, address={address}, freq={freq_khz}kHz, timeout={timeout_s}s)"
    )
    QtCore.QThreadPool.globalInstance().start(job)


def _find_cubeprog_root() -> Optional[Path]:
    """Return CubeProgrammer install root if found."""
    for path in _cubeprog_candidates():
        if _has_cubeprog_binaries(path):
            return path
    return None


def _cubeprog_candidates() -> Iterable[Path]:
    # C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\api\lib
    env_path = os.environ.get("STM32CUBEPROG_PATH")
    if env_path:
        yield Path(env_path)

    system = platform.system()
    if system == "Windows":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)")
        for base in filter(None, [program_files, program_files_x86]):
            yield Path(base) / "STMicroelectronics" / "STM32Cube" / "STM32CubeProgrammer"
    elif system == "Darwin":
        yield Path.home() / "Applications" / "STMicroelectronics" / "STM32Cube" / "STM32CubeProgrammer"
        yield Path("/Applications/STMicroelectronics/STM32Cube/STM32CubeProgrammer")
    else:
        yield Path("/opt/STMicroelectronics/STM32Cube/STM32CubeProgrammer")
        yield Path.home() / "STM32CubeProgrammer"


def _has_cubeprog_binaries(root: Path) -> bool:
    if not root.exists():
        return False
    path = _cubeprog_dll_path(root)
    return bool(path and path.exists())


def _reset_mode_from_text(text: str) -> CubeProgrammerResetMode:
    text = (text or "").lower()
    if "hard" in text:
        return CubeProgrammerResetMode.HARDWARE_RESET
    if "core" in text:
        return CubeProgrammerResetMode.CORE_RESET
    return CubeProgrammerResetMode.SOFTWARE_RESET


def _run_with_timeout(func: Callable[[], object], timeout_s: float, label: str) -> tuple[bool, object]:
    """
    Execute a function with a watchdog timeout. If the function does not return within
    timeout_s seconds, we report a timeout. The worker thread is left to finish in background,
    but the caller can proceed and update UI.
    """
    result_holder: dict[str, object] = {}
    exc_holder: dict[str, Exception] = {}

    def wrapper() -> None:
        try:
            result_holder["value"] = func()
        except Exception as exc:  # pragma: no cover - runtime protection
            exc_holder["error"] = exc

    thread = threading.Thread(target=wrapper, daemon=True)
    _log(f"{label}: start with timeout={timeout_s:.1f}s")
    thread.start()
    thread.join(timeout_s)

    if thread.is_alive():
        _log(f"ERROR: {label} exceeded timeout ({timeout_s:.1f}s)")
        return False, f"{label} timed out after {timeout_s:.1f}s"
    if "error" in exc_holder:
        _log(f"ERROR: {label} raised {exc_holder['error']}")
        raise exc_holder["error"]
    _log(f"{label}: completed")
    return True, result_holder.get("value")


def _step_timeout(deadline: float, minimum: float = 1.0) -> float:
    """Compute remaining time budget for a step."""
    remaining = deadline - time.monotonic()
    return max(minimum, remaining)


def _cubeprog_dll_path(root: Path) -> Optional[Path]:
    if sys.platform.startswith("win"):
        candidates = [
            root / "api" / "lib" / "CubeProgrammer_API.dll",
            root / "bin" / "CubeProgrammer_API.dll",
        ]
    elif sys.platform.startswith("linux"):
        candidates = [root / "lib" / "libCubeProgrammer_API.so"]
    elif sys.platform == "darwin":
        candidates = [root / "lib" / "libCubeProgrammer_API.dylib"]
    else:
        return None

    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if candidates else None


def _prepare_cubeprog_env(root: Path) -> None:
    """Ensure DLL search paths include STM32CubeProgrammer directories."""
    if sys.platform.startswith("win"):
        dirs = [root / "bin", root / "api" / "lib"]
        for directory in dirs:
            if directory.exists():
                _log(f"Adding DLL directory: {directory}")
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(directory))
                else:
                    os.environ["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"
    elif sys.platform.startswith("linux"):
        lib_dir = root / "lib"
        bin_dir = root / "bin"
        pieces = [str(p) for p in (lib_dir, bin_dir) if p.exists()]
        if pieces:
            current = os.environ.get("LD_LIBRARY_PATH", "")
            new_path = os.pathsep.join(pieces + ([current] if current else []))
            os.environ["LD_LIBRARY_PATH"] = new_path
            _log(f"Updated LD_LIBRARY_PATH for CubeProgrammer: {new_path}")
    elif sys.platform == "darwin":
        lib_dir = root / "lib"
        if lib_dir.exists():
            current = os.environ.get("DYLD_LIBRARY_PATH", "")
            new_path = os.pathsep.join([str(lib_dir)] + ([current] if current else []))
            os.environ["DYLD_LIBRARY_PATH"] = new_path
            _log(f"Updated DYLD_LIBRARY_PATH for CubeProgrammer: {new_path}")


def _log(message: str) -> None:
    """Simple stdout logger for easier debugging."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [stlink] {message}")
