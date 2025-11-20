from __future__ import annotations
from pathlib import Path
from typing import Callable, Optional
from PySide6 import QtCore
from iot_downloader_ft import downloader

UsbCallback = Callable[[bool, str], None]


class UsbFirmwareController(QtCore.QObject):
    """
    Thin wrapper around iot_downloader_ft.downloader for PySide6.

    Responsibilities:
    - Fan out downloader signals to UI-friendly handlers.
    - Provide a mutex so only one flash/read job runs at a time.
    - Surface a simple callback interface back to the caller.
    """

    def __init__(
        self,
        *,
        message_handler: Callable[[str], None],
        enable_handler: Optional[Callable[[bool], None]] = None,
        board_info_handler: Optional[Callable[[dict], None]] = None,
        save_log_handler: Optional[Callable[[str], None]] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._message_handler = message_handler
        self._enable_handler = enable_handler
        self._board_info_handler = board_info_handler
        self._save_log_handler = save_log_handler
        self._callback: Optional[UsbCallback] = None
        self._current_action: str = ""
        self._last_detail: str = ""
        self._saw_error = False
        self._pending_enable = False
        self._mp_transfer_done = False
        self._mp_flash_ok = False
        self._cb_flash_ok = False
        self._ade_flash_ok = False

        self.d = downloader()
        self.d.message_cb.connect(self._handle_message)
        self.d.save_log_cb.connect(self._handle_save_log)
        self.d.btns_enable_cb.connect(self._handle_btns_enabled)
        self.d.board_info_cb.connect(self._handle_board_info)
        self.d.finished.connect(self._on_finished)

    # Public API ---------------------------------------------------------
    def start_flash(
        self,
        *,
        action: str,
        file_path: Optional[str],
        verify_board: bool = False,
        need_log: bool = True,
        callback: Optional[UsbCallback] = None,
    ) -> bool:
        """
        Kick off a flash-related action.
        Returns False if the downloader is busy or inputs are invalid.
        """
        if self.d.isRunning():
            self._handle_message("USB downloader is busy, please wait...")
            return False

        requires_file = action in {"loader", "mpfw", "cb", "ade"}
        if requires_file:
            path = Path(file_path or "")
            if not path.is_file():
                self._handle_message("Firmware file missing; please select a valid path.")
                return False

        self._callback = callback
        self._current_action = action
        self._last_detail = ""
        self._saw_error = False
        self._pending_enable = False
        self._mp_transfer_done = False
        self._mp_flash_ok = False
        self._cb_flash_ok = False
        self._ade_flash_ok = False
        self.d.stm32_port = ""
        if self._enable_handler:
            self._enable_handler(False)

        try:
            self.d.set_action(
                action,
                need_log=need_log,
                file_path=file_path,
                varify_board=verify_board,
            )
            self.d.start()
        except Exception as exc:  # pragma: no cover - runtime protection
            self._handle_message(f"error: failed to start downloader ({exc})")
            if self._enable_handler:
                self._enable_handler(True)
            return False
        return True

    def read_board_info(self) -> bool:
        """Request board info; returns False if busy."""
        if self.d.isRunning():
            self._handle_message("USB downloader is busy, please wait...")
            return False
        self._callback = None
        self._current_action = "board_info"
        self._last_detail = ""
        self._saw_error = False
        self._pending_enable = False
        self._mp_transfer_done = False
        self._mp_flash_ok = False
        self._cb_flash_ok = False
        self._ade_flash_ok = False
        if self._enable_handler:
            self._enable_handler(False)
        self.d.set_action("board_info")
        self.d.start()
        return True

    # Internal signal handlers ------------------------------------------
    def _handle_message(self, text: str) -> None:
        lowered = text.lower()
        if (
            "error" in lowered
            or lowered.startswith("!!!")
            or "fail" in lowered
            or "no suitable port found" in lowered
        ):
            self._saw_error = True
        if "# transfer completely" in lowered:
            self._mp_transfer_done = True
        if "[mp_firmware] flash ok" in lowered:
            self._mp_flash_ok = True
        if "[cb_firmware] flash ok" in lowered:
            self._cb_flash_ok = True
        if "[flash ade] flash project done" in lowered:
            self._ade_flash_ok = True
        self._last_detail = text
        self._message_handler(text)

    def _handle_save_log(self, action: str) -> None:
        if self._save_log_handler:
            self._save_log_handler(action)

    def _handle_btns_enabled(self, enabled: bool) -> None:
        if not enabled and self._enable_handler:
            self._enable_handler(False)
        # Defer re-enable until the finished signal arrives to keep mutex intact.
        if enabled:
            self._pending_enable = True

    def _handle_board_info(self, board_info: dict) -> None:
        if self._board_info_handler:
            self._board_info_handler(board_info)

    def _on_finished(self) -> None:
        if self._enable_handler and self._pending_enable:
            self._enable_handler(True)
        detail = self._last_detail or f"{self._current_action} completed"
        result = not self._saw_error
        if self._current_action == "mpfw":
            result = self._mp_transfer_done and self._mp_flash_ok and not self._saw_error
            detail = "MP firmware flash completed" if result else "MP firmware flash incomplete"
        if self._current_action == "cb":
            result = self._cb_flash_ok and not self._saw_error
            detail = "CB firmware flash completed" if result else "CB firmware flash incomplete"
        if self._current_action == "ade":
            result = self._ade_flash_ok and not self._saw_error
            detail = "ADE flash completed" if result else "ADE flash incomplete"
        cb = self._callback
        if cb:
            QtCore.QTimer.singleShot(0, lambda cb=cb, res=result, det=detail: cb(res, det))
        self._callback = None
        self._current_action = ""
        self._pending_enable = False
