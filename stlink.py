"""
STLink integration based on pystlink (https://github.com/pavelrevak/pystlink).

Defaults:
- port: SWD
- freq: 4000 kHz
- mode: normal
- reset: software
- address: 0x0800_0000
- file: ./bootloader.elf

This module launches the pystlink CLI in a worker thread to avoid blocking the UI.
If pystlink is not installed or fails, the callback receives (False, message).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore


DEFAULT_ELF = Path("./bootloader.elf")
DEFAULT_PORT = "swd"
DEFAULT_FREQ_KHZ = 4000
DEFAULT_MODE = "normal"
DEFAULT_RESET = "software"
DEFAULT_ADDRESS = "0x08000000"


class _StlinkJob(QtCore.QRunnable):
    def __init__(
        self,
        callback: Callable[[bool, str], None],
        elf_path: Path,
        port: str,
        freq_khz: int,
        mode: str,
        reset: str,
        address: str,
    ) -> None:
        super().__init__()
        self.callback = callback
        self.elf_path = elf_path
        self.port = port
        self.freq_khz = freq_khz
        self.mode = mode
        self.reset = reset
        self.address = address

    def run(self) -> None:
        passed, detail = self._flash()
        # Return to main thread
        QtCore.QTimer.singleShot(0, lambda: self.callback(passed, detail))

    def _flash(self) -> tuple[bool, str]:
        if not self.elf_path.exists():
            return False, f"Bootloader 檔案不存在: {self.elf_path}"

        cmd = [
            "python",
            "-m",
            "pystlink",
            "-P",
            self.port,
            "-c",
            str(self.freq_khz),
            "-m",
            self.mode,
            "-r",
            self.reset,
            "-a",
            self.address,
            "-w",
            str(self.elf_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except FileNotFoundError:
            return False, "找不到 pystlink，請先安裝：pip install pystlink"
        except subprocess.TimeoutExpired:
            return False, "pystlink 執行逾時"

        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            return False, f"pystlink 失敗: {msg}"

        return True, "STLink 燒錄完成"


def run_stlink(
    callback: Callable[[bool, str], None],
    elf_path: Optional[Path] = None,
    port: str = DEFAULT_PORT,
    freq_khz: int = DEFAULT_FREQ_KHZ,
    mode: str = DEFAULT_MODE,
    reset: str = DEFAULT_RESET,
    address: str = DEFAULT_ADDRESS,
) -> None:
    """
    Launch STLink flash in background.
    callback: function(passed: bool, detail: str)
    """
    job = _StlinkJob(
        callback=callback,
        elf_path=elf_path or DEFAULT_ELF,
        port=port,
        freq_khz=freq_khz,
        mode=mode,
        reset=reset,
        address=address,
    )
    QtCore.QThreadPool.globalInstance().start(job)
