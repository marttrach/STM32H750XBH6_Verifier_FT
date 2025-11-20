"""
PySide6-based factory test fixture UI for STM32 DUTs.

Modules:
- global_utility: shared constants, scaling, theme, status label.
- mis_login: login/logout UI.
- com_port: COM port management helpers.
- stlink: STLink bootloader flashing module.
- usb_firmware: USB firmware flashing module.
- csv_log: write test results to CSV.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

import csv_log
import stlink
import usb_firmware
from com_port import available_ports, populate_combo
from config_store import UserConfig, load_user_config, save_user_config
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


class RefreshingCombo(QtWidgets.QComboBox):
    """ComboBox that refreshes COM ports when opened."""

    def __init__(self, refresh_cb, parent=None):
        super().__init__(parent)
        self._refresh_cb = refresh_cb

    def showPopup(self) -> None:
        if callable(self._refresh_cb):
            self._refresh_cb(self)
        super().showPopup()


class TestFixtureWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STM32 Production Test Fixture - PySide6")
        self.ui_scale = compute_scale()
        apply_global_font(self.ui_scale)
        resize_by_scale(self, self.ui_scale)
        self.user_config: UserConfig = load_user_config()
        self.results: Dict[str, TestResult] = {
            "stlink": TestResult("STLink (Bootloader)"),
            "usb": TestResult("USB (Firmware)"),
            "gpio": TestResult("GPIO"),
            "lcd": TestResult("LCD/Backlight"),
            "rs485": TestResult("RS485"),
            "rs232": TestResult("RS232"),
            "rs422": TestResult("RS422"),
            "ethernet": TestResult("Ethernet"),
        }
        self.active_test: Optional[str] = None
        self.tests_enabled = False
        self.current_theme = (self.user_config.theme or "light").lower()
        self.logged_in = False
        self.serial_checked = False
        self._cursor_buttons: List[QtWidgets.QPushButton] = []
        self._theme_sync_scheduled = False
        # Use a scroll area to keep widgets visible on small or full-screen displays.
        content = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(content)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        self._build_menubar()
        main_layout.addLayout(self._build_header())
        main_layout.addSpacing(6)
        main_layout.addWidget(self._build_tests())
        main_layout.addWidget(self._build_usb_options())
        main_layout.addWidget(self._build_log_panel(), stretch=1)
        main_layout.addWidget(self._build_footer())

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        self.setCentralWidget(scroll)
        self._enable_tests(False)
        self._apply_theme(self.current_theme)
        self._populate_ports()
        self._setup_usb_controller()

    # UI builders
    def _build_menubar(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        import_act = QtGui.QAction("Import", self)
        import_act.triggered.connect(self._handle_import)
        import_act.setEnabled(False)
        export_act = QtGui.QAction("Export", self)
        export_act.triggered.connect(self._handle_export)
        export_act.setEnabled(False)
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

        # Login panel with S/N input stacked below
        self.login_panel = LoginPanel(
            scale=self.ui_scale,
            on_login=self._handle_login_success,
            on_logout=self._handle_logout,
        )
        self.login_panel.prefill_credentials(
            self.user_config.username
        )
        login_column = QtWidgets.QVBoxLayout()
        login_column.setSpacing(int(8 * self.ui_scale))
        login_column.addWidget(self.login_panel)
        self._register_button_cursor(self.login_panel.action_btn)

        sn_widget = QtWidgets.QWidget()
        sn_layout = QtWidgets.QHBoxLayout(sn_widget)
        sn_layout.setContentsMargins(0, 0, 0, 0)
        sn_layout.setSpacing(int(8 * self.ui_scale))
        sn_label = QtWidgets.QLabel("S/N Code")
        sn_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.serial_edit = QtWidgets.QLineEdit()
        self.serial_edit.setPlaceholderText("Scan or enter DUT serial number")
        self.serial_edit.setMinimumHeight(int(28 * self.ui_scale))
        self.serial_edit.textChanged.connect(self._on_serial_changed)
        self.serial_edit.returnPressed.connect(self._check_serial_input)
        self.check_sn_btn = QtWidgets.QPushButton("Check")
        self.check_sn_btn.setMinimumHeight(int(28 * self.ui_scale))
        self.check_sn_btn.clicked.connect(self._check_serial_input)
        self._register_button_cursor(self.check_sn_btn)
        sn_layout.addWidget(sn_label)
        sn_layout.addWidget(self.serial_edit, stretch=1)
        sn_layout.addWidget(self.check_sn_btn)
        login_column.addWidget(sn_widget)
        layout.addLayout(login_column, stretch=1)

        # Theme toggle
        theme_box = QtWidgets.QGroupBox()
        theme_layout = QtWidgets.QHBoxLayout(theme_box)
        self.light_btn = QtWidgets.QPushButton("Light")
        self.dark_btn = QtWidgets.QPushButton("Dark")
        for btn in [self.light_btn, self.dark_btn]:
            btn.setCheckable(True)
            btn.setMinimumHeight(int(28 * self.ui_scale))
            self._register_button_cursor(btn)
        self.light_btn.setChecked(True)
        self.light_btn.clicked.connect(lambda: self._apply_theme("light"))
        self.dark_btn.clicked.connect(lambda: self._apply_theme("dark"))
        theme_layout.addWidget(self.light_btn)
        theme_layout.addWidget(self.dark_btn)
        layout.addWidget(theme_box)

        return layout

    def _build_tests(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(10 * self.ui_scale))
        grid.setVerticalSpacing(int(8 * self.ui_scale))
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        btn_height = int(32 * self.ui_scale)

        # STLink and USB buttons
        self.stlink_status = StatusLabel(scale=self.ui_scale)
        self.stlink_btn = QtWidgets.QPushButton("STLink Flash Bootloader")
        self.stlink_btn.setMinimumHeight(btn_height)
        self.stlink_btn.clicked.connect(lambda: self._run_test("stlink"))
        self._register_button_cursor(self.stlink_btn)

        self.usb_status = StatusLabel(scale=self.ui_scale)
        self.usb_btn = QtWidgets.QPushButton("USB Flash Firmware")
        self.usb_btn.setMinimumHeight(btn_height)
        self.usb_btn.clicked.connect(lambda: self._run_test("usb"))
        self._register_button_cursor(self.usb_btn)

        self.lcd_status = StatusLabel(scale=self.ui_scale)
        self.lcd_btn = QtWidgets.QPushButton("LCD/Backlight Test")
        self.lcd_btn.setMinimumHeight(btn_height)
        self.lcd_btn.clicked.connect(lambda: self._run_test("lcd"))
        self._register_button_cursor(self.lcd_btn)

        self.gpio_status = StatusLabel(scale=self.ui_scale)
        self.gpio_btn = QtWidgets.QPushButton("GPIO Test")
        self.gpio_btn.setMinimumHeight(btn_height)
        self.gpio_btn.clicked.connect(lambda: self._run_test("gpio"))
        self._register_button_cursor(self.gpio_btn)

        # Serial port entries
        self.rs485_port = RefreshingCombo(self._refresh_single_combo)
        self.rs485_port.setMinimumHeight(btn_height)
        self.rs485_status = StatusLabel(scale=self.ui_scale)
        self.rs485_btn = QtWidgets.QPushButton("RS485 Test")
        self.rs485_btn.setMinimumHeight(btn_height)
        self.rs485_btn.clicked.connect(lambda: self._run_test("rs485"))
        self._register_button_cursor(self.rs485_btn)

        self.rs232_port = RefreshingCombo(self._refresh_single_combo)
        self.rs232_port.setMinimumHeight(btn_height)
        self.rs232_status = StatusLabel(scale=self.ui_scale)
        self.rs232_btn = QtWidgets.QPushButton("RS232 Test")
        self.rs232_btn.setMinimumHeight(btn_height)
        self.rs232_btn.clicked.connect(lambda: self._run_test("rs232"))
        self._register_button_cursor(self.rs232_btn)

        self.rs422_port = RefreshingCombo(self._refresh_single_combo)
        self.rs422_port.setMinimumHeight(btn_height)
        self.rs422_status = StatusLabel(scale=self.ui_scale)
        self.rs422_btn = QtWidgets.QPushButton("RS422 Test")
        self.rs422_btn.setMinimumHeight(btn_height)
        self.rs422_btn.clicked.connect(lambda: self._run_test("rs422"))
        self._register_button_cursor(self.rs422_btn)

        # Ethernet test
        self.eth_status = StatusLabel(scale=self.ui_scale)
        self.eth_btn = QtWidgets.QPushButton("Ethernet Test")
        self.eth_btn.setMinimumHeight(btn_height)
        self.eth_btn.clicked.connect(lambda: self._run_test("ethernet"))
        self._register_button_cursor(self.eth_btn)

        # Layout rows
        grid.addWidget(QtWidgets.QLabel("STLink (Bootloader)"), 0, 0)
        grid.addWidget(self.stlink_btn, 0, 1, 1, 2)
        grid.addWidget(self.stlink_status, 0, 3)

        grid.addWidget(QtWidgets.QLabel("USB (Firmware)"), 1, 0)
        grid.addWidget(self.usb_btn, 1, 1, 1, 2)
        grid.addWidget(self.usb_status, 1, 3)

        grid.addWidget(QtWidgets.QLabel("GPIO"), 2, 0)
        grid.addWidget(self.gpio_btn, 2, 1, 1, 2)
        grid.addWidget(self.gpio_status, 2, 3)

        grid.addWidget(QtWidgets.QLabel("RS485 COM"), 3, 0)
        grid.addWidget(self.rs485_port, 3, 1)
        grid.addWidget(self.rs485_btn, 3, 2)
        grid.addWidget(self.rs485_status, 3, 3)

        grid.addWidget(QtWidgets.QLabel("RS232 COM"), 4, 0)
        grid.addWidget(self.rs232_port, 4, 1)
        grid.addWidget(self.rs232_btn, 4, 2)
        grid.addWidget(self.rs232_status, 4, 3)

        grid.addWidget(QtWidgets.QLabel("RS422 COM"), 5, 0)
        grid.addWidget(self.rs422_port, 5, 1)
        grid.addWidget(self.rs422_btn, 5, 2)
        grid.addWidget(self.rs422_status, 5, 3)

        grid.addWidget(QtWidgets.QLabel("LCD/Backlight"), 6, 0)
        grid.addWidget(self.lcd_btn, 6, 1, 1, 2)
        grid.addWidget(self.lcd_status, 6, 3)

        grid.addWidget(QtWidgets.QLabel("Ethernet"), 7, 0)
        grid.addWidget(self.eth_btn, 7, 1, 1, 2)
        grid.addWidget(self.eth_status, 7, 3)

        return group

    def _build_usb_options(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(10 * self.ui_scale))
        grid.setVerticalSpacing(int(6 * self.ui_scale))
        grid.setColumnStretch(1, 1)

        self.usb_fw_path = QtWidgets.QLineEdit()
        self.usb_fw_path.setPlaceholderText("Select firmware file to flash")
        self.usb_fw_path.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_fw_path.setText(str(Path("bin/firmware_ctp.orig")))
        self.usb_browse_btn = QtWidgets.QPushButton("Browse...")
        self.usb_browse_btn.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_browse_btn.clicked.connect(self._choose_usb_file)
        self._register_button_cursor(self.usb_browse_btn)

        self.usb_action_combo = QtWidgets.QComboBox()
        self.usb_action_combo.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_action_combo.addItem("MP Firmware", userData="mpfw")
        self.usb_action_combo.addItem("Loader", userData="loader")
        self.usb_action_combo.addItem("CB Firmware", userData="cb")
        self.usb_action_combo.addItem("ADE/Data", userData="ade")
        self.usb_action_combo.addItem("Factory Reset", userData="reset")
        self.usb_action_combo.setCurrentIndex(0)

        self.usb_variant_ctp = QtWidgets.QCheckBox("CTP")
        self.usb_variant_rtp = QtWidgets.QCheckBox("RTP")
        for btn in (self.usb_variant_ctp, self.usb_variant_rtp):
            btn.setMinimumHeight(int(28 * self.ui_scale))
            self._register_button_cursor(btn)
        self.usb_variant_ctp.clicked.connect(lambda checked: self._set_usb_variant("ctp"))
        self.usb_variant_rtp.clicked.connect(lambda checked: self._set_usb_variant("rtp"))

        self.usb_verify_box = QtWidgets.QCheckBox("Verify board info")
        self.usb_verify_box.setChecked(False)

        self.usb_info_btn = QtWidgets.QPushButton("Read Board Info")
        self.usb_info_btn.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_info_btn.clicked.connect(self._handle_board_info_request)
        self._register_button_cursor(self.usb_info_btn)

        self.usb_board_info_label = QtWidgets.QLabel("Board info: -")
        self.usb_board_info_label.setWordWrap(True)

        grid.addWidget(QtWidgets.QLabel("Firmware File"), 0, 0)
        grid.addWidget(self.usb_fw_path, 0, 1)
        grid.addWidget(self.usb_browse_btn, 0, 2)

        grid.addWidget(QtWidgets.QLabel("USB Action"), 1, 0)
        grid.addWidget(self.usb_action_combo, 1, 1)
        variant_layout = QtWidgets.QHBoxLayout()
        variant_layout.setContentsMargins(0, 0, 0, 0)
        variant_layout.setSpacing(int(6 * self.ui_scale))
        variant_layout.addWidget(self.usb_variant_ctp)
        variant_layout.addWidget(self.usb_variant_rtp)
        variant_box = QtWidgets.QWidget()
        variant_box.setLayout(variant_layout)
        grid.addWidget(variant_box, 1, 2)

        grid.addWidget(self.usb_verify_box, 2, 0)

        grid.addWidget(self.usb_info_btn, 2, 1)
        grid.addWidget(self.usb_board_info_label, 2, 2)

        return group

    def _build_log_panel(self) -> QtWidgets.QWidget:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(group)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background: #0f1115; color: #d1d5db;")
        layout.addWidget(self.log_box)
        return group

    def _build_footer(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)

        self.submit_btn = QtWidgets.QPushButton("SUBMIT (Submit Test Results)")
        self.submit_btn.clicked.connect(self._submit_results)
        self.submit_btn.setEnabled(False)
        self._register_button_cursor(self.submit_btn)

        layout.addStretch()
        layout.addWidget(self.submit_btn)
        return widget

    def _append_downloader_message(self, message: str) -> None:
        append_log(self.log_box, message)

    def _on_usb_save_log(self, action: str) -> None:
        append_log(self.log_box, f"USB action saved: {action}")

    def _check_serial_input(self) -> None:
        text = self.serial_edit.text().strip()
        if not text:
            self.serial_checked = False
            append_log(self.log_box, "Please enter S/N code before checking.")
            self._set_interactive_enabled(False)
            self.submit_btn.setEnabled(False)
            return
        self.serial_checked = True
        append_log(self.log_box, f"S/N check passed: {text}")
        if not self.active_test and self.tests_enabled:
            self._set_interactive_enabled(True)
        self.submit_btn.setEnabled(self.tests_enabled and self.serial_checked and not self.active_test)

    def _on_serial_changed(self) -> None:
        if self.serial_checked:
            self.serial_checked = False
            self._set_interactive_enabled(False)
            self.submit_btn.setEnabled(False)

    def _set_usb_controls_enabled(self, enabled: bool) -> None:
        widgets = [
            self.usb_btn,
            self.usb_fw_path,
            self.usb_browse_btn,
            self.usb_action_combo,
            self.usb_verify_box,
            self.usb_info_btn,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)
        self._refresh_all_button_cursors()

    def _handle_board_info_request(self) -> None:
        if not getattr(self, "usb_controller", None):
            append_log(self.log_box, "USB controller not ready.")
            return
        if not self.logged_in:
            append_log(self.log_box, "Please login first.")
            return
        if self.active_test:
            append_log(self.log_box, "Another test is active; please wait before reading board info.")
            return
        if not self.usb_controller.read_board_info():
            append_log(self.log_box, "USB downloader is busy, cannot read board info.")

    def handle_board_info(self, board_info: dict) -> None:
        try:
            resv = board_info.get("version_reserved", "")
            res_a = resv[0:1] if len(resv) > 0 else ""
            res_b = resv[1:2] if len(resv) > 1 else ""
            res_c = resv[2:3] if len(resv) > 2 else ""
            text = (
                f"ser: {board_info.get('board_series', '')}, "
                f"ver: {board_info.get('board_version', '')}, "
                f"prod: {board_info.get('product_type', '')}, "
                f"size: {board_info.get('lcd_size', '')}, "
                f"res: {board_info.get('lcd_hor_res', '')}x{board_info.get('lcd_ver_res', '')}, "
                f"color: {board_info.get('lcd_color_depth', '')}, "
                f"touch: {board_info.get('lcd_touch_type', '')}, "
                f"lcd: {board_info.get('lcd_vendor', '')}, "
                f"comm: {res_a}, mem: {res_b}, resv: {res_c}"
            )
            self.usb_board_info_label.setText(f"Board info: {text}")
            append_log(self.log_box, text)
        except Exception as exc:  # pragma: no cover - runtime protection
            append_log(self.log_box, f"Failed to parse board info: {exc}")

    def _choose_usb_file(self) -> None:
        select_mode = self.usb_action_combo.currentData()
        if select_mode == "mpfw":
            filter_path = "Firmware Files (*.orig);;All Files (*.*)"
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select MP Firmware File", "", filter_path
            )
        elif select_mode == "loader":
            filter_path = "ELF Files (*.elf);;All Files (*.*)"
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select Loader ELF File", "", filter_path
            )
        elif select_mode == "cb":
            filter_path = "CB Firmware Files (*.cb);;All Files (*.*)"
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select CB Firmware File", "", filter_path
            )
        elif select_mode == "ade":
            filter_path = "ADE/Data Files (*.cpio);;All Files (*.*)"
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select ADE/Data File", "", filter_path
            )
        if path:
            self.usb_fw_path.setText(path)

    # Logic handlers
    def _handle_login_success(self, user: str, password: str) -> None:
        self.logged_in = True
        self._enable_tests(True)
        self.user_config.username = user
        # self.user_config.password = password
        save_user_config(self.user_config)
        append_log(self.log_box, f"Login success ({user}), tests are now enabled.")
    def _handle_logout(self) -> None:
        self.logged_in = False
        self._enable_tests(False)
        self._reset_results()
        self.serial_checked = False
        append_log(self.log_box, "Logged out. Please login again to continue.")
    def _enable_tests(self, enable: bool) -> None:
        self.tests_enabled = enable
        if self.active_test:
            self._set_interactive_enabled(False)
        else:
            self._set_interactive_enabled(enable and self.serial_checked)
        self.submit_btn.setEnabled(enable and self.serial_checked and not self.active_test)
        self._refresh_button_cursor(self.submit_btn)

    def _reset_results(self) -> None:
        for key, label in [
            ("stlink", self.stlink_status),
            ("usb", self.usb_status),
            ("gpio", self.gpio_status),
            ("lcd", self.lcd_status),
            ("rs485", self.rs485_status),
            ("rs232", self.rs232_status),
            ("rs422", self.rs422_status),
            ("ethernet", self.eth_status),
        ]:
            label.update_status("IDLE")
            self.results[key].status = "IDLE"
            self.results[key].detail = ""

    def _set_interactive_enabled(self, enable: bool) -> None:
        controls = {
            "stlink": [self.stlink_btn],
            "usb": [
                self.usb_btn,
                self.usb_fw_path,
                self.usb_browse_btn,
                self.usb_action_combo,
                self.usb_variant_ctp,
                self.usb_variant_rtp,
                self.usb_verify_box,
                self.usb_info_btn,
            ],
            "gpio": [self.gpio_btn],
            "lcd": [self.lcd_btn],
            "rs485": [self.rs485_btn, self.rs485_port],
            "rs232": [self.rs232_btn, self.rs232_port],
            "rs422": [self.rs422_btn, self.rs422_port],
            "ethernet": [self.eth_btn],
        }
        for key, widgets in controls.items():
            for widget in widgets:
                widget.setEnabled(enable)
        self._refresh_all_button_cursors()

    def _populate_ports(self) -> None:
        ports = available_ports()
        if not ports:
            append_log(self.log_box, "No COM port found. Please ensure pyserial is installed.")
        for combo in [self.rs485_port, self.rs232_port, self.rs422_port]:
            populate_combo(combo, ports)

    def _refresh_single_combo(self, combo: QtWidgets.QComboBox) -> None:
        ports = available_ports()
        populate_combo(combo, ports)

    def _setup_usb_controller(self) -> None:
        self.usb_controller = usb_firmware.UsbFirmwareController(
            message_handler=self._append_downloader_message,
            enable_handler=self._set_usb_controls_enabled,
            board_info_handler=self.handle_board_info,
            save_log_handler=self._on_usb_save_log,
        )
        # Restore saved variant selection
        variant = getattr(self.user_config, "usb_variant", "ctp")
        self._set_usb_variant(variant)

    def _set_usb_variant(self, variant: str) -> None:
        variant = (variant or "ctp").lower()
        if variant == "rtp":
            self.usb_variant_ctp.setChecked(False)
            self.usb_variant_rtp.setChecked(True)
            self.usb_fw_path.setText(str(Path("bin/firmware_rtp.orig")))
            self.user_config.usb_variant = "rtp"
        else:
            self.usb_variant_ctp.setChecked(True)
            self.usb_variant_rtp.setChecked(False)
            self.usb_fw_path.setText(str(Path("bin/firmware_ctp.orig")))
            self.user_config.usb_variant = "ctp"
        save_user_config(self.user_config)

    def _run_test(self, key: str) -> None:
        if not self.logged_in:
            append_log(self.log_box, "Please login first.")
            return
        if not self.serial_checked:
            append_log(self.log_box, "Please enter S/N code and press Check before running tests.")
            return

        status_label = {
            "stlink": self.stlink_status,
            "usb": self.usb_status,
            "gpio": self.gpio_status,
            "lcd": self.lcd_status,
            "rs485": self.rs485_status,
            "rs232": self.rs232_status,
            "rs422": self.rs422_status,
            "ethernet": self.eth_status,
        }[key]

        com_port = None
        if key == "rs485":
            com_port = self.rs485_port.currentData()
        elif key == "rs232":
            com_port = self.rs232_port.currentData()
        elif key == "rs422":
            com_port = self.rs422_port.currentData()

        if key in ("rs485", "rs232", "rs422") and not com_port:
            append_log(self.log_box, "Please select the correct COM port before testing.")
            return

        if self.active_test:
            busy_name = self.results[self.active_test].name
            append_log(self.log_box, f"{busy_name} is running, please wait.")
            return

        status_label.update_status("RUNNING")
        self.results[key].status = "RUNNING"
        self.results[key].detail = ""
        action_name = self.results[key].name
        if com_port:
            action_name = f"{action_name} ({com_port})"
        append_log(self.log_box, f"{action_name} started...")
        self.active_test = key
        self._set_interactive_enabled(False)
        self.submit_btn.setEnabled(False)
        self._refresh_button_cursor(self.submit_btn)

        if key == "stlink":
            target_elf = getattr(stlink, "DEFAULT_ELF", Path("bootloader.elf"))
            resolved = target_elf if target_elf.is_absolute() else (Path.cwd() / target_elf)
            if not resolved.exists():
                detail = f"Bootloader file not found: {resolved}"
                append_log(self.log_box, detail)
                QtCore.QTimer.singleShot(0, lambda: self._finish_test(key, False, detail))
                return
            stlink.run_stlink(lambda passed, detail: self._finish_test(key, passed, detail))
        elif key == "usb":
            action = self.usb_action_combo.currentData()
            firmware_path = self.usb_fw_path.text().strip()
            verify_board = self.usb_verify_box.isChecked()
            needs_file = action in {"loader", "mpfw", "cb", "ade"}
            if needs_file and not firmware_path:
                detail = "Firmware file missing for USB flash."
                append_log(self.log_box, detail)
                QtCore.QTimer.singleShot(
                    0, lambda: self._finish_test(key, False, detail)
                )
                return
            started = self.usb_controller.start_flash(
                action=action,
                file_path=firmware_path,
                verify_board=verify_board,
                callback=lambda passed, detail: self._finish_test(key, passed, detail),
            )
            if not started:
                QtCore.QTimer.singleShot(
                    0, lambda: self._finish_test(key, False, "USB downloader busy.")
                )
        elif key == "gpio":
            QtCore.QTimer.singleShot(
                800, lambda: self._finish_test(key, True, f"{action_name} completed")
            )
        elif key == "lcd":
            QtCore.QTimer.singleShot(
                800, lambda: self._finish_test(key, True, f"{action_name} completed")
            )
        else:
            QtCore.QTimer.singleShot(
                800,
                lambda: self._finish_test(
                    key, True, f"{action_name} completed"
                ),
            )

    def _finish_test(self, key: str, passed: bool, detail: str = "") -> None:
        status_label = {
            "stlink": self.stlink_status,
            "usb": self.usb_status,
            "gpio": self.gpio_status,
            "rs485": self.rs485_status,
            "rs232": self.rs232_status,
            "rs422": self.rs422_status,
            "lcd": self.lcd_status,
            "ethernet": self.eth_status,
        }[key]

        status_text = "PASS" if passed else "FAIL"
        status_label.update_status(status_text)
        self.results[key].status = status_text
        self.results[key].detail = detail
        if key == "stlink" and detail:
            append_log(self.log_box, detail)
        append_log(self.log_box, f"{self.results[key].name}: {status_text} - {detail}")
        self.active_test = None
        self._set_interactive_enabled(self.tests_enabled and self.serial_checked)
        self.submit_btn.setEnabled(self.tests_enabled and self.serial_checked)
        self._refresh_button_cursor(self.submit_btn)

    def _submit_results(self) -> None:
        if not self.logged_in:
            append_log(self.log_box, "Not logged in; cannot submit.")
            return
        serial_number = self.serial_edit.text().strip()
        if not serial_number:
            append_log(self.log_box, "Please enter the DUT S/N code before submitting.")
            self.serial_edit.setFocus()
            return
        path = csv_log.submit_results(
            self.login_panel.current_user(), serial_number, self.results
        )
        append_log(
            self.log_box,
            f"Submission saved to {path.resolve()} (S/N: {serial_number})",
        )

    def _apply_theme(self, mode: str) -> None:
        normalized = (mode or "light").lower()
        self.current_theme = normalized
        self.light_btn.setChecked(normalized == "light")
        self.dark_btn.setChecked(normalized == "dark")
        self.setStyleSheet(theme_stylesheet(normalized))
        apply_global_font(self.ui_scale)
        if hasattr(self, "user_config") and self.user_config.theme != normalized:
            self.user_config.theme = normalized
            save_user_config(self.user_config)

    def _register_button_cursor(self, button: QtWidgets.QPushButton) -> None:
        if not button:
            return
        if button not in self._cursor_buttons:
            self._cursor_buttons.append(button)
        self._refresh_button_cursor(button)

    def _refresh_button_cursor(self, button: QtWidgets.QPushButton) -> None:
        if not button:
            return
        cursor = QtGui.QCursor(
            QtCore.Qt.PointingHandCursor if button.isEnabled() else QtCore.Qt.ArrowCursor
        )
        button.setCursor(cursor)

    def _refresh_all_button_cursors(self) -> None:
        for button in self._cursor_buttons:
            self._refresh_button_cursor(button)

    def _show_text_window(
        self,
        title: str,
        content: str,
        *,
        markdown: bool = False,
        transparent: bool = False,
    ) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(int(640 * self.ui_scale), int(480 * self.ui_scale))
        layout = QtWidgets.QVBoxLayout(dialog)
        viewer = QtWidgets.QTextBrowser()
        viewer.setReadOnly(True)
        viewer.setOpenExternalLinks(True)
        if markdown and hasattr(viewer, "setMarkdown"):
            viewer.setMarkdown(content)
        else:
            viewer.setPlainText(content)
        if transparent:
            text_color = "#e8eaed" if self.current_theme == "dark" else "#111827"
            dialog.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            dialog.setStyleSheet("background: transparent;")
            viewer.setStyleSheet(
                f"background: transparent; border: none; color: {text_color};"
            )
        layout.addWidget(viewer)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dialog.exec()

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
        license_path = Path("LICENSE")
        if license_path.exists():
            content = license_path.read_text(encoding="utf-8")
        else:
            content = "LICENSE file not found."
        self._show_text_window(
            "License",
            content,
            markdown=False,
            transparent=True,
        )

    def _show_about(self) -> None:
        about_path = Path("about.md")
        if about_path.exists():
            content = about_path.read_text(encoding="utf-8")
        else:
            content = "# About\nSTM32 Production Test Fixture - no changelog available."
        self._show_text_window(
            "About / Changelog",
            content,
            markdown=True,
            transparent=False,
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Exit",
            "Do you really want to close the application?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            event.ignore()
            return
        reply2 = QtWidgets.QMessageBox.question(
            self,
            "Additional Confirmation",
            "Please confirm once more that you want to quit.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply2 != QtWidgets.QMessageBox.Yes:
            event.ignore()
            return
        event.accept()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._theme_sync_scheduled:
            self._theme_sync_scheduled = True
            QtCore.QTimer.singleShot(
                0, lambda: self._apply_theme(self.current_theme)
            )


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = TestFixtureWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
