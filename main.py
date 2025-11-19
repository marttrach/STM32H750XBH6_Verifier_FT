"""
PySide6-based factory test fixture UI for STM32 DUTs.

Modularized into:
- global_utility: shared constants, scaling, theme, status label.
- mis_login: login/logout UI.
- com_port: COM 列表管理。
- stlink: STLink Bootloader 燒錄模組。
- usb_firmware: USB Firmware 燒錄模組。
- csv_log: 測試結果寫入 CSV。
"""

import sys
from pathlib import Path
from typing import Dict

from PySide6 import QtCore, QtGui, QtWidgets

import csv_log
import stlink
import usb_firmware
from com_port import available_ports, populate_combo
from global_utility import (
    TestResult,
    StatusLabel,
    append_log,
    compute_scale,
    apply_global_font,
    resize_by_scale,
    theme_stylesheet,
)
from mis_login import LoginPanel


class TestFixtureWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STM32 生產測試治具 - PySide6")
        self.ui_scale = compute_scale()
        apply_global_font(self.ui_scale)
        resize_by_scale(self, self.ui_scale)
        self.results: Dict[str, TestResult] = {
            "stlink": TestResult("STLink (Bootloader)"),
            "usb": TestResult("USB (Firmware)"),
            "rs485": TestResult("RS485"),
            "rs232": TestResult("RS232"),
            "rs422": TestResult("RS422"),
        }
        self.current_theme = "light"
        self.logged_in = False

        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        self._build_menubar()
        main_layout.addLayout(self._build_header())
        main_layout.addSpacing(6)
        main_layout.addWidget(self._build_tests())
        main_layout.addWidget(self._build_log_panel(), stretch=1)
        main_layout.addWidget(self._build_footer())

        self.setCentralWidget(central)
        self._enable_tests(False)
        self._apply_theme(self.current_theme)
        self._populate_ports()

    # UI builders
    def _build_menubar(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        import_act = QtGui.QAction("Import", self)
        import_act.triggered.connect(self._handle_import)
        export_act = QtGui.QAction("Export", self)
        export_act.triggered.connect(self._handle_export)
        exit_act = QtGui.QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addActions([import_act, export_act, exit_act])

        license_menu = bar.addMenu("License")
        license_act = QtGui.QAction("PySide6 LGPL", self)
        license_act.triggered.connect(self._show_license)
        license_menu.addAction(license_act)

        about_menu = bar.addMenu("About")
        about_act = QtGui.QAction("About / Changelog", self)
        about_act.triggered.connect(self._show_about)
        about_menu.addAction(about_act)

    def _build_header(self) -> QtWidgets.QLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(int(12 * self.ui_scale))

        # Logo placeholder
        logo_frame = QtWidgets.QFrame()
        logo_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        logo_frame.setFixedSize(
            int(180 * self.ui_scale), int(90 * self.ui_scale)
        )
        logo_layout = QtWidgets.QVBoxLayout(logo_frame)
        logo_label = QtWidgets.QLabel("LOGO")
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_label.setStyleSheet(
            f"font-size: {int(18 * self.ui_scale)}px; font-weight: bold;"
        )
        logo_layout.addWidget(logo_label)
        layout.addWidget(logo_frame)

        # Login panel
        self.login_panel = LoginPanel(
            scale=self.ui_scale,
            on_login=self._handle_login_success,
            on_logout=self._handle_logout,
        )
        layout.addWidget(self.login_panel, stretch=1)

        # Theme toggle
        theme_box = QtWidgets.QGroupBox("Theme")
        theme_layout = QtWidgets.QHBoxLayout(theme_box)
        self.light_btn = QtWidgets.QPushButton("Light")
        self.dark_btn = QtWidgets.QPushButton("Dark")
        for btn in [self.light_btn, self.dark_btn]:
            btn.setCheckable(True)
            btn.setMinimumHeight(int(28 * self.ui_scale))
        self.light_btn.setChecked(True)
        self.light_btn.clicked.connect(lambda: self._apply_theme("light"))
        self.dark_btn.clicked.connect(lambda: self._apply_theme("dark"))
        theme_layout.addWidget(self.light_btn)
        theme_layout.addWidget(self.dark_btn)
        layout.addWidget(theme_box)

        return layout

    def _build_tests(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("測試項目")
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(10 * self.ui_scale))
        grid.setVerticalSpacing(int(8 * self.ui_scale))

        btn_height = int(32 * self.ui_scale)

        # STLink and USB buttons
        self.stlink_status = StatusLabel(scale=self.ui_scale)
        self.stlink_btn = QtWidgets.QPushButton("STLink 燒錄 Bootloader")
        self.stlink_btn.setMinimumHeight(btn_height)
        self.stlink_btn.clicked.connect(lambda: self._run_test("stlink"))

        self.usb_status = StatusLabel(scale=self.ui_scale)
        self.usb_btn = QtWidgets.QPushButton("USB 燒錄 Firmware")
        self.usb_btn.setMinimumHeight(btn_height)
        self.usb_btn.clicked.connect(lambda: self._run_test("usb"))

        # Serial port entries
        self.rs485_port = QtWidgets.QComboBox()
        self.rs485_port.setMinimumHeight(btn_height)
        self.rs485_status = StatusLabel(scale=self.ui_scale)
        self.rs485_btn = QtWidgets.QPushButton("RS485 測試")
        self.rs485_btn.setMinimumHeight(btn_height)
        self.rs485_btn.clicked.connect(lambda: self._run_test("rs485"))

        self.rs232_port = QtWidgets.QComboBox()
        self.rs232_port.setMinimumHeight(btn_height)
        self.rs232_status = StatusLabel(scale=self.ui_scale)
        self.rs232_btn = QtWidgets.QPushButton("RS232 測試")
        self.rs232_btn.setMinimumHeight(btn_height)
        self.rs232_btn.clicked.connect(lambda: self._run_test("rs232"))

        self.rs422_port = QtWidgets.QComboBox()
        self.rs422_port.setMinimumHeight(btn_height)
        self.rs422_status = StatusLabel(scale=self.ui_scale)
        self.rs422_btn = QtWidgets.QPushButton("RS422 測試")
        self.rs422_btn.setMinimumHeight(btn_height)
        self.rs422_btn.clicked.connect(lambda: self._run_test("rs422"))

        # Layout rows
        grid.addWidget(QtWidgets.QLabel("STLink (Bootloader)"), 0, 0)
        grid.addWidget(self.stlink_status, 0, 1)
        grid.addWidget(self.stlink_btn, 0, 2)

        grid.addWidget(QtWidgets.QLabel("USB (Firmware)"), 1, 0)
        grid.addWidget(self.usb_status, 1, 1)
        grid.addWidget(self.usb_btn, 1, 2)

        grid.addWidget(QtWidgets.QLabel("RS485 COM"), 2, 0)
        grid.addWidget(self.rs485_port, 2, 1)
        grid.addWidget(self.rs485_btn, 2, 2)
        grid.addWidget(self.rs485_status, 2, 3)

        grid.addWidget(QtWidgets.QLabel("RS232 COM"), 3, 0)
        grid.addWidget(self.rs232_port, 3, 1)
        grid.addWidget(self.rs232_btn, 3, 2)
        grid.addWidget(self.rs232_status, 3, 3)

        grid.addWidget(QtWidgets.QLabel("RS422 COM"), 4, 0)
        grid.addWidget(self.rs422_port, 4, 1)
        grid.addWidget(self.rs422_btn, 4, 2)
        grid.addWidget(self.rs422_status, 4, 3)

        return group

    def _build_log_panel(self) -> QtWidgets.QWidget:
        group = QtWidgets.QGroupBox("LOG")
        layout = QtWidgets.QVBoxLayout(group)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background: #0f1115; color: #d1d5db;")
        layout.addWidget(self.log_box)
        return group

    def _build_footer(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        self.submit_btn = QtWidgets.QPushButton("SUBMIT (儲存測試結果)")
        self.submit_btn.clicked.connect(self._submit_results)
        self.submit_btn.setEnabled(False)

        layout.addStretch()
        layout.addWidget(self.submit_btn)
        return widget

    # Logic handlers
    def _handle_login_success(self, user: str) -> None:
        self.logged_in = True
        self._enable_tests(True)
        append_log(self.log_box, f"登入成功 ({user})，請開始測試流程。")

    def _handle_logout(self) -> None:
        self.logged_in = False
        self._enable_tests(False)
        self._reset_results()
        append_log(self.log_box, "已登出，請重新登入。")

    def _enable_tests(self, enable: bool) -> None:
        for btn in [
            self.stlink_btn,
            self.usb_btn,
            self.rs485_btn,
            self.rs232_btn,
            self.rs422_btn,
            self.submit_btn,
        ]:
            btn.setEnabled(enable)

    def _reset_results(self) -> None:
        for key, label in [
            ("stlink", self.stlink_status),
            ("usb", self.usb_status),
            ("rs485", self.rs485_status),
            ("rs232", self.rs232_status),
            ("rs422", self.rs422_status),
        ]:
            label.update_status("待測")
            self.results[key].status = "待測"
            self.results[key].detail = ""

    def _populate_ports(self) -> None:
        ports = available_ports()
        if not ports:
            append_log(self.log_box, "未找到可用 COM 埠或未安裝 pyserial。")
        for combo in [self.rs485_port, self.rs232_port, self.rs422_port]:
            populate_combo(combo, ports)

    def _run_test(self, key: str) -> None:
        if not self.logged_in:
            append_log(self.log_box, "請先登入。")
            return

        status_label = {
            "stlink": self.stlink_status,
            "usb": self.usb_status,
            "rs485": self.rs485_status,
            "rs232": self.rs232_status,
            "rs422": self.rs422_status,
        }[key]

        # Inputs for RS tests
        com_port = None
        if key == "rs485":
            com_port = self.rs485_port.currentData()
        elif key == "rs232":
            com_port = self.rs232_port.currentData()
        elif key == "rs422":
            com_port = self.rs422_port.currentData()

        if key in ("rs485", "rs232", "rs422") and not com_port:
            append_log(self.log_box, "請先選擇有效的 COM 埠再開始測試。")
            return

        status_label.update_status("進行中")
        self.results[key].status = "進行中"
        self.results[key].detail = ""
        action_name = self.results[key].name
        if com_port:
            action_name = f"{action_name} ({com_port})"
        append_log(self.log_box, f"{action_name} 開始...")

        if key == "stlink":
            stlink.run_stlink(lambda passed, detail: self._finish_test(key, passed, detail))
        elif key == "usb":
            usb_firmware.run_usb_flash(lambda passed, detail: self._finish_test(key, passed, detail))
        else:
            QtCore.QTimer.singleShot(
                800,
                lambda: self._finish_test(
                    key, True, f"{action_name} 完成"
                ),
            )

    def _finish_test(self, key: str, passed: bool, detail: str = "") -> None:
        status_label = {
            "stlink": self.stlink_status,
            "usb": self.usb_status,
            "rs485": self.rs485_status,
            "rs232": self.rs232_status,
            "rs422": self.rs422_status,
        }[key]

        status_text = "PASS" if passed else "FAIL"
        status_label.update_status(status_text)
        self.results[key].status = status_text
        self.results[key].detail = detail
        append_log(self.log_box, f"{self.results[key].name}: {status_text} - {detail}")

    def _submit_results(self) -> None:
        if not self.logged_in:
            append_log(self.log_box, "未登入，無法提交。")
            return
        path = csv_log.submit_results(self.login_panel.current_user(), self.results)
        append_log(self.log_box, f"提交完成，儲存於 {path.resolve()}")

    def _apply_theme(self, mode: str) -> None:
        self.current_theme = mode
        self.light_btn.setChecked(mode == "light")
        self.dark_btn.setChecked(mode == "dark")
        self.setStyleSheet(theme_stylesheet(mode))

    # Menu and helper handlers
    def _handle_import(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import file", "", "All Files (*.*)"
        )
        if path:
            append_log(self.log_box, f"Import: {path}")

    def _handle_export(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export log", "export_log.txt", "Text Files (*.txt);;All Files (*.*)"
        )
        if path:
            Path(path).write_text(self.log_box.toPlainText(), encoding="utf-8")
            append_log(self.log_box, f"Export log to {path}")

    def _show_license(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "License",
            "本程式 UI 使用 PySide6 (LGPL)。請依 LGPL v3 條款進行分發與連結。",
        )

    def _show_about(self) -> None:
        about_path = Path("about.md")
        if about_path.exists():
            content = about_path.read_text(encoding="utf-8")
        else:
            content = "STM32 生產測試治具 - 開發記錄未找到。"
        QtWidgets.QMessageBox.information(self, "About", content)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "離開確認",
            "確定要關閉程式嗎？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            event.ignore()
            return
        reply2 = QtWidgets.QMessageBox.question(
            self,
            "再次確認",
            "請再次確認關閉程式。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply2 != QtWidgets.QMessageBox.Yes:
            event.ignore()
            return
        event.accept()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = TestFixtureWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
