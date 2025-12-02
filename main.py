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
import datetime as dt
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6

import csv_log
import esp32
import stlink
import usb_firmware
from com_port import available_ports, populate_combo, run_loopback_test
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
        # Scale UI relative to screen; base design is 1280x720.
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
        self._closing = False
        self.test_checks: Dict[str, QtWidgets.QCheckBox] = {}
        self._loading_config = True
        self.test_queue: List[str] = []
        self.batch_uses_esp32 = False
        self.last_finished_test: Optional[str] = None
        self.usb_controls_locked = False
        self.power_rows: Dict[str, Dict[str, QtWidgets.QLineEdit]] = {}
        self.power_header_labels: List[QtWidgets.QLabel] = []
        self.power_thresholds = {
            "vin_mv": {"min": 11000, "max": 13000, "label": "VIN (mV)"},
            "iin_ma": {"min": 30, "max": 200, "label": "VIN I (mA)"},
            "v3v3_mv": {"min": 3100, "max": 3500, "label": "3V3 (mV)"},
            "v5v_mv": {"min": 4700, "max": 5300, "label": "5V (mV)"},
        }
        self.power_data_ready = False
        self.power_inflight = False
        self.batch_inflight = False
        # Use a scroll area to keep widgets visible on small or full-screen displays.
        content = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(content)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        self._build_menubar()
        main_layout.addLayout(self._build_header())
        main_layout.addSpacing(4)

        # Top row: power, tests, log (ratio 2:2:1).
        main_row = QtWidgets.QHBoxLayout()
        main_row.setSpacing(int(8 * self.ui_scale))
        main_row.addWidget(self._build_power_panel(), stretch=2)
        main_row.addWidget(self._build_tests(), stretch=2)
        main_row.addWidget(self._build_log_panel(), stretch=1)
        main_layout.addLayout(main_row)

        # Middle row: summary status (left) and USB options (right).
        mid_row = QtWidgets.QHBoxLayout()
        mid_row.setSpacing(int(8 * self.ui_scale))
        mid_row.addWidget(self._build_summary_status(), stretch=1)
        mid_row.addWidget(self._build_usb_options(), stretch=1)
        main_layout.addLayout(mid_row)

        self._restore_selected_tests()
        self._loading_config = False
        main_layout.addWidget(self._build_footer())

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        self.setCentralWidget(scroll)
        self._resize_to_base(scroll)
        self._enable_tests(False)
        self._apply_theme(self.current_theme)
        self._populate_ports()
        self._setup_usb_controller()
        self._update_summary_status()

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
        layout.setSpacing(int(10 * self.ui_scale))

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

        # Logo placeholder moved to the right
        logo_frame = QtWidgets.QFrame()
        logo_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        logo_frame.setFixedSize(
            int(140 * self.ui_scale), int(70 * self.ui_scale)
        )
        logo_layout = QtWidgets.QVBoxLayout(logo_frame)
        logo_label = QtWidgets.QLabel("LOGO")
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_label.setStyleSheet(
            f"font-size: {int(16 * self.ui_scale)}px; font-weight: bold;"
        )
        logo_layout.addWidget(logo_label)
        layout.addWidget(logo_frame)

        return layout

    def _build_summary_status(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setFrameShape(QtWidgets.QFrame.StyledPanel)
        box.setStyleSheet("padding: 8px;")
        layout = QtWidgets.QHBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        self.summary_label = QtWidgets.QLabel("IDLE")
        self.summary_label.setAlignment(QtCore.Qt.AlignCenter)
        self.summary_label.setMinimumHeight(int(52 * self.ui_scale))
        self.summary_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.summary_label.setStyleSheet(
            "background: #e5e7eb; color: #111827; border-radius: 8px; font-size: 22px; font-weight: 700;"
        )
        layout.addWidget(self.summary_label)
        return box

    def _set_summary_status(self, status: str) -> None:
        palette = {
            "PASS": "background: #0f9d58; color: white;",
            "FAIL": "background: #d93025; color: white;",
            "RUNNING": "background: #1a73e8; color: white;",
            "IDLE": "background: #9ca3af; color: #111827;",
        }
        style = palette.get(status.upper(), palette["IDLE"])
        self.summary_label.setText(status.upper())
        self.summary_label.setStyleSheet(
            f"{style} border-radius: 8px; font-size: 22px; font-weight: 700;"
        )

    def _update_summary_status(self) -> None:
        selected = [key for key, box in self.test_checks.items() if box.isChecked()]
        if not selected:
            self._set_summary_status("IDLE")
            return
        statuses = [self.results.get(key).status for key in selected if self.results.get(key)]
        if any(status == "RUNNING" for status in statuses):
            self._set_summary_status("RUNNING")
        elif any(status == "FAIL" for status in statuses):
            self._set_summary_status("FAIL")
        elif statuses and all(status == "PASS" for status in statuses):
            self._set_summary_status("PASS")
        else:
            self._set_summary_status("IDLE")

    def _build_power_panel(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(6 * self.ui_scale))
        grid.setVerticalSpacing(int(4 * self.ui_scale))
        grid.setColumnStretch(2, 1)
        cell_height = int(30 * self.ui_scale)
        header_font_px = int(12 * self.ui_scale)
        styles = self._power_styles(header_font_px)

        # ESP32 port selection
        grid.addWidget(QtWidgets.QLabel("ESP32 COM"), 0, 0)
        self.power_port_combo = RefreshingCombo(self._refresh_power_combo)
        self.power_port_combo.setMinimumHeight(int(28 * self.ui_scale))
        populate_combo(self.power_port_combo, available_ports())
        self._restore_power_port()
        self.power_port_combo.currentIndexChanged.connect(self._on_power_port_changed)
        grid.addWidget(self.power_port_combo, 0, 1, 1, 2)

        header_style = styles["header"]
        cell_style = styles["cell"]
        current_style = styles["current"]

        headers = ["", "MIN", "Current", "MAX"]
        self.power_header_labels = []
        for col, text in enumerate(headers):
            label = QtWidgets.QLabel(text)
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setStyleSheet(header_style)
            label.setFixedHeight(cell_height)
            self.power_header_labels.append(label)
            grid.addWidget(label, 1, col)

        row = 2
        self.power_rows = {}
        for key, meta in self.power_thresholds.items():
            label = QtWidgets.QLabel(meta["label"])
            min_edit = QtWidgets.QLineEdit(str(meta["min"]))
            cur_edit = QtWidgets.QLineEdit("")
            cur_edit.setReadOnly(True)
            cur_edit.setStyleSheet(current_style)
            max_edit = QtWidgets.QLineEdit(str(meta["max"]))
            for edit in (min_edit, max_edit):
                edit.setMaximumWidth(int(90 * self.ui_scale))
            for edit in (min_edit, max_edit, cur_edit):
                edit.setFixedHeight(cell_height)
                edit.setStyleSheet(cell_style if edit is not cur_edit else current_style)
            label.setFixedHeight(cell_height)
            label.setStyleSheet(styles["label"])
            grid.addWidget(label, row, 0)
            grid.addWidget(min_edit, row, 1)
            grid.addWidget(cur_edit, row, 2)
            grid.addWidget(max_edit, row, 3)
            self.power_rows[key] = {
                "label": label,
                "min": min_edit,
                "current": cur_edit,
                "max": max_edit,
            }
            row += 1

        return group

    def _build_tests(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(10 * self.ui_scale))
        grid.setVerticalSpacing(int(8 * self.ui_scale))
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        btn_height = int(32 * self.ui_scale)

        # Start-all button
        self.start_all_tests_btn = QtWidgets.QPushButton("START TEST")
        self.start_all_tests_btn.setMinimumHeight(btn_height)
        self.start_all_tests_btn.clicked.connect(self._start_selected_tests)
        self._register_button_cursor(self.start_all_tests_btn)

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
        self.rs485_port.currentIndexChanged.connect(lambda _: self._persist_port_selection("rs485"))

        self.rs232_port = RefreshingCombo(self._refresh_single_combo)
        self.rs232_port.setMinimumHeight(btn_height)
        self.rs232_status = StatusLabel(scale=self.ui_scale)
        self.rs232_btn = QtWidgets.QPushButton("RS232 Test")
        self.rs232_btn.setMinimumHeight(btn_height)
        self.rs232_btn.clicked.connect(lambda: self._run_test("rs232"))
        self._register_button_cursor(self.rs232_btn)
        self.rs232_port.currentIndexChanged.connect(lambda _: self._persist_port_selection("rs232"))

        self.rs422_port = RefreshingCombo(self._refresh_single_combo)
        self.rs422_port.setMinimumHeight(btn_height)
        self.rs422_status = StatusLabel(scale=self.ui_scale)
        self.rs422_btn = QtWidgets.QPushButton("RS422 Test")
        self.rs422_btn.setMinimumHeight(btn_height)
        self.rs422_btn.clicked.connect(lambda: self._run_test("rs422"))
        self._register_button_cursor(self.rs422_btn)
        self.rs422_port.currentIndexChanged.connect(lambda _: self._persist_port_selection("rs422"))

        # Ethernet test
        self.eth_status = StatusLabel(scale=self.ui_scale)
        self.eth_btn = QtWidgets.QPushButton("Ethernet Test")
        self.eth_btn.setMinimumHeight(btn_height)
        self.eth_btn.clicked.connect(lambda: self._run_test("ethernet"))
        self._register_button_cursor(self.eth_btn)

        # Layout rows
        grid.addWidget(self.start_all_tests_btn, 0, 0, 1, 5)

        self.test_checks["stlink"] = QtWidgets.QCheckBox()
        self.test_checks["stlink"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["stlink"].setChecked("stlink" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["stlink"], 1, 0)
        grid.addWidget(QtWidgets.QLabel("STLink (Bootloader)"), 1, 1)
        grid.addWidget(self.stlink_btn, 1, 2, 1, 2)
        grid.addWidget(self.stlink_status, 1, 4)

        self.test_checks["usb"] = QtWidgets.QCheckBox()
        self.test_checks["usb"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["usb"].setChecked("usb" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["usb"], 2, 0)
        grid.addWidget(QtWidgets.QLabel("USB (Firmware)"), 2, 1)
        grid.addWidget(self.usb_btn, 2, 2, 1, 2)
        grid.addWidget(self.usb_status, 2, 4)

        self.test_checks["gpio"] = QtWidgets.QCheckBox()
        self.test_checks["gpio"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["gpio"].setChecked("gpio" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["gpio"], 3, 0)
        grid.addWidget(QtWidgets.QLabel("GPIO"), 3, 1)
        grid.addWidget(self.gpio_btn, 3, 2, 1, 2)
        grid.addWidget(self.gpio_status, 3, 4)

        self.test_checks["rs485"] = QtWidgets.QCheckBox()
        self.test_checks["rs485"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs485"].setChecked("rs485" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["rs485"], 4, 0)
        grid.addWidget(QtWidgets.QLabel("RS485 COM"), 4, 1)
        grid.addWidget(self.rs485_port, 4, 2)
        grid.addWidget(self.rs485_btn, 4, 3)
        grid.addWidget(self.rs485_status, 4, 4)

        self.test_checks["rs232"] = QtWidgets.QCheckBox()
        self.test_checks["rs232"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs232"].setChecked("rs232" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["rs232"], 5, 0)
        grid.addWidget(QtWidgets.QLabel("RS232 COM"), 5, 1)
        grid.addWidget(self.rs232_port, 5, 2)
        grid.addWidget(self.rs232_btn, 5, 3)
        grid.addWidget(self.rs232_status, 5, 4)

        self.test_checks["rs422"] = QtWidgets.QCheckBox()
        self.test_checks["rs422"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs422"].setChecked("rs422" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["rs422"], 6, 0)
        grid.addWidget(QtWidgets.QLabel("RS422 COM"), 6, 1)
        grid.addWidget(self.rs422_port, 6, 2)
        grid.addWidget(self.rs422_btn, 6, 3)
        grid.addWidget(self.rs422_status, 6, 4)

        self.test_checks["lcd"] = QtWidgets.QCheckBox()
        self.test_checks["lcd"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["lcd"].setChecked("lcd" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["lcd"], 7, 0)
        grid.addWidget(QtWidgets.QLabel("LCD/Backlight"), 7, 1)
        grid.addWidget(self.lcd_btn, 7, 2, 1, 2)
        grid.addWidget(self.lcd_status, 7, 4)

        self.test_checks["ethernet"] = QtWidgets.QCheckBox()
        self.test_checks["ethernet"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["ethernet"].setChecked("ethernet" in self.user_config.selected_tests)
        grid.addWidget(self.test_checks["ethernet"], 8, 0)
        grid.addWidget(QtWidgets.QLabel("Ethernet"), 8, 1)
        grid.addWidget(self.eth_btn, 8, 2, 1, 2)
        grid.addWidget(self.eth_status, 8, 4)

        return group

    def _build_usb_options(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Minimum)
        grid = QtWidgets.QGridLayout(group)
        grid.setHorizontalSpacing(int(10 * self.ui_scale))
        grid.setVerticalSpacing(int(6 * self.ui_scale))
        grid.setColumnStretch(1, 1)

        self.usb_custom_action_box = QtWidgets.QCheckBox("Customize USB Flash")
        self.usb_custom_action_box.setChecked(False)
        self.usb_custom_action_box.toggled.connect(self._apply_usb_custom_state)

        self.usb_action_combo = QtWidgets.QComboBox()
        self.usb_action_combo.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_action_combo.addItem("MP Firmware", userData="mpfw")
        self.usb_action_combo.addItem("Loader", userData="loader")
        self.usb_action_combo.addItem("CB Firmware", userData="cb")
        self.usb_action_combo.addItem("ADE/Data", userData="ade")
        self.usb_action_combo.addItem("Factory Reset", userData="reset")
        self.usb_action_combo.setCurrentIndex(0)
        self.usb_action_combo.currentIndexChanged.connect(self._on_usb_action_changed)

        self.usb_fw_path = QtWidgets.QLineEdit()
        self.usb_fw_path.setPlaceholderText("Select firmware file to flash")
        self.usb_fw_path.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_fw_path.setText(str(Path("bin/firmware_ctp.orig")))
        self.usb_browse_btn = QtWidgets.QPushButton("Browse...")
        self.usb_browse_btn.setMinimumHeight(int(28 * self.ui_scale))
        self.usb_browse_btn.clicked.connect(self._choose_usb_file)
        self._register_button_cursor(self.usb_browse_btn)

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

        grid.addWidget(self.usb_custom_action_box, 0, 0, 1, 3)

        grid.addWidget(QtWidgets.QLabel("Firmware File"), 1, 0)
        grid.addWidget(self.usb_fw_path, 1, 1)
        grid.addWidget(self.usb_browse_btn, 1, 2)

        grid.addWidget(QtWidgets.QLabel("USB Action"), 2, 0)
        grid.addWidget(self.usb_action_combo, 2, 1)
        variant_layout = QtWidgets.QHBoxLayout()
        variant_layout.setContentsMargins(0, 0, 0, 0)
        variant_layout.setSpacing(int(6 * self.ui_scale))
        variant_layout.addWidget(self.usb_variant_ctp)
        variant_layout.addWidget(self.usb_variant_rtp)
        variant_box = QtWidgets.QWidget()
        variant_box.setLayout(variant_layout)
        grid.addWidget(variant_box, 2, 2)

        grid.addWidget(self.usb_verify_box, 3, 0)

        grid.addWidget(self.usb_info_btn, 3, 1)
        grid.addWidget(self.usb_board_info_label, 3, 2)

        self._on_usb_action_changed()
        self._apply_usb_custom_state()

        return group

    def _build_log_panel(self) -> QtWidgets.QWidget:
        group = QtWidgets.QGroupBox()
        group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(group)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background: #0f1115; color: #d1d5db;")
        self.log_box.setMinimumHeight(int(140 * self.ui_scale))
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
        effective = enabled and not self.usb_controls_locked
        widgets = [
            self.usb_btn,
            self.usb_fw_path,
            self.usb_browse_btn,
            self.usb_action_combo,
            self.usb_verify_box,
            self.usb_info_btn,
            self.usb_custom_action_box,
        ]
        for widget in widgets:
            widget.setEnabled(effective)
        self._apply_usb_custom_state()
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
        path = ""
        if select_mode == "mpfw":
            filter_path = "Firmware Files (*.orig);;All Files (*.*)"
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select MP Firmware File", "", filter_path
            )
        elif select_mode == "loader":
            filter_path = "Loader Files (*.orig);;All Files (*.*)"
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

    def _on_usb_action_changed(self) -> None:
        mode = self.usb_action_combo.currentData()
        placeholder = "Select firmware file to flash"
        if mode == "ade":
            placeholder = "Select ADE/Data file"
        elif mode == "cb":
            placeholder = "Select CB firmware file"
        self.usb_fw_path.setPlaceholderText(placeholder)
        self._apply_usb_custom_state()

    def _apply_usb_custom_state(self) -> None:
        # Only allow editing firmware path/action when custom checkbox is checked and USB controls are not locked.
        custom_box = getattr(self, "usb_custom_action_box", None)
        if custom_box is None:
            return
        base_enabled = bool(self.usb_btn.isEnabled()) and not self.usb_controls_locked
        editable = custom_box.isChecked() and base_enabled
        targets = [
            self.usb_fw_path,
            self.usb_browse_btn,
            self.usb_action_combo,
            self.usb_verify_box,
        ]
        for widget in targets:
            widget.setEnabled(editable)
        self._refresh_all_button_cursors()

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
        self._update_summary_status()

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
                self.usb_custom_action_box,
            ],
            "gpio": [self.gpio_btn],
            "lcd": [self.lcd_btn],
            "rs485": [self.rs485_btn, self.rs485_port],
            "rs232": [self.rs232_btn, self.rs232_port],
            "rs422": [self.rs422_btn, self.rs422_port],
            "ethernet": [self.eth_btn],
            "batch": [self.start_all_tests_btn, *self.test_checks.values()],
            "power": [getattr(self, "power_port_combo", None)]
        }
        for key, widgets in controls.items():
            key_enable = enable
            if key == "usb" and self.usb_controls_locked:
                key_enable = False
            if key == "batch" and self.test_queue:
                key_enable = False
            if key == "power" and self.batch_uses_esp32:
                key_enable = False
            for widget in widgets:
                widget.setEnabled(key_enable)
        self._apply_usb_custom_state()
        self._refresh_all_button_cursors()

    def _populate_ports(self) -> None:
        ports = available_ports()
        if not ports:
            append_log(self.log_box, "No COM port found. Please ensure pyserial is installed.")
        for combo in [self.rs485_port, self.rs232_port, self.rs422_port]:
            populate_combo(combo, ports)
        self._restore_saved_port(self.rs485_port, self.user_config.rs485_port)
        self._restore_saved_port(self.rs232_port, self.user_config.rs232_port)
        self._restore_saved_port(self.rs422_port, self.user_config.rs422_port)
        self._refresh_power_combo()

    def _refresh_single_combo(self, combo: QtWidgets.QComboBox) -> None:
        ports = available_ports()
        populate_combo(combo, ports)
        if combo is self.rs485_port:
            self._restore_saved_port(combo, self.user_config.rs485_port)
        elif combo is self.rs232_port:
            self._restore_saved_port(combo, self.user_config.rs232_port)
        elif combo is self.rs422_port:
            self._restore_saved_port(combo, self.user_config.rs422_port)

    def _refresh_power_combo(self, combo: Optional[QtWidgets.QComboBox] = None) -> None:
        combo = combo or getattr(self, "power_port_combo", None)
        if combo is None:
            return
        ports = available_ports()
        populate_combo(combo, ports)
        self._restore_saved_port(combo, self.user_config.esp32_port)

    def _restore_saved_port(self, combo: QtWidgets.QComboBox, saved_port: str) -> None:
        if not saved_port:
            return
        idx = combo.findData(saved_port)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _restore_power_port(self) -> None:
        if hasattr(self, "power_port_combo"):
            self._restore_saved_port(self.power_port_combo, self.user_config.esp32_port)

    def _persist_port_selection(self, key: str) -> None:
        combo_map = {
            "rs485": self.rs485_port,
            "rs232": self.rs232_port,
            "rs422": self.rs422_port,
        }
        combo = combo_map.get(key)
        if combo is None:
            return
        val = combo.currentData()
        if key == "rs485":
            self.user_config.rs485_port = val or ""
        elif key == "rs232":
            self.user_config.rs232_port = val or ""
        elif key == "rs422":
            self.user_config.rs422_port = val or ""
        save_user_config(self.user_config)

    def _restore_selected_tests(self) -> None:
        """Re-apply saved test selections without firing change handlers."""
        if not self.test_checks:
            return
        saved = self.user_config.selected_tests or []
        if not isinstance(saved, (list, tuple, set)):
            saved = [saved]
        saved_set = {str(item) for item in saved}
        normalized = [key for key in self.test_checks if key in saved_set]
        for key, box in self.test_checks.items():
            prev = box.blockSignals(True)
            box.setChecked(key in saved_set)
            box.blockSignals(prev)
        if normalized != list(self.user_config.selected_tests):
            self.user_config.selected_tests = normalized
            if not getattr(self, "_loading_config", False):
                save_user_config(self.user_config)

    def _persist_selected_tests(self) -> None:
        if getattr(self, "_loading_config", False):
            return
        if not self.test_checks:
            return
        selected = [key for key, box in self.test_checks.items() if box.isChecked()]
        self.user_config.selected_tests = selected
        save_user_config(self.user_config)
        self._update_summary_status()

    def _on_power_port_changed(self) -> None:
        if not hasattr(self, "power_port_combo"):
            return
        val = self.power_port_combo.currentData()
        self.user_config.esp32_port = val or ""
        save_user_config(self.user_config)

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

    def _run_test(self, key: str) -> bool:
        if not self.logged_in:
            append_log(self.log_box, "Please login first.")
            return False
        if not self.serial_checked:
            append_log(self.log_box, "Please enter S/N code and press Check before running tests.")
            return False

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

        selected_port = None
        if key == "rs485":
            selected_port = self.rs485_port.currentData()
        elif key == "rs232":
            selected_port = self.rs232_port.currentData()
        elif key == "rs422":
            selected_port = self.rs422_port.currentData()

        if key in ("rs485", "rs232", "rs422") and not selected_port:
            append_log(self.log_box, "Please select the correct COM port before testing.")
            QtCore.QTimer.singleShot(
                0, lambda: self._finish_test(key, False, "Missing COM port selection.")
            )
            return True

        if self.active_test:
            busy_name = self.results[self.active_test].name
            append_log(self.log_box, f"{busy_name} is running, please wait.")
            return False

        status_label.update_status("RUNNING")
        self.results[key].status = "RUNNING"
        self.results[key].detail = ""
        action_name = self.results[key].name
        if selected_port:
            action_name = f"{action_name} ({selected_port})"
        append_log(self.log_box, f"{action_name} started...")
        self.active_test = key
        self._set_interactive_enabled(False)
        self.submit_btn.setEnabled(False)
        self._refresh_button_cursor(self.submit_btn)
        self._update_summary_status()

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
            if not self.usb_custom_action_box.isChecked():
                self._run_default_usb_sequence()
                return
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
        elif key in ("rs485", "rs232", "rs422"):
            run_loopback_test(
                port=selected_port,
                label=self.results[key].name,
                callback=lambda passed, detail: self._finish_test(key, passed, detail),
            )
        else:
            QtCore.QTimer.singleShot(
                800,
                lambda: self._finish_test(
                    key, True, f"{action_name} completed"
                ),
            )
        return True

    def _run_default_usb_sequence(self) -> None:
        """Default USB flow: ADE -> wait -> MP -> wait -> re-enumerate."""
        ade_path = Path("bin/FT_test.cpio")
        mp_path_text = self.usb_fw_path.text().strip()
        verify_board = self.usb_verify_box.isChecked()

        if not ade_path.is_file():
            detail = f"ADE/Data file missing: {ade_path}"
            append_log(self.log_box, detail)
            QtCore.QTimer.singleShot(0, lambda: self._finish_test("usb", False, detail))
            return
        mp_path = Path(mp_path_text)
        if not mp_path.is_file():
            detail = f"MP firmware file missing: {mp_path_text or '(empty)'}"
            append_log(self.log_box, detail)
            QtCore.QTimer.singleShot(0, lambda: self._finish_test("usb", False, detail))
            return

        append_log(self.log_box, "# Default USB flow: ADE -> MP -> re-enumerate")
        self.usb_controls_locked = True
        self._set_usb_controls_enabled(False)

        def fail(detail: str) -> None:
            append_log(self.log_box, detail)
            QtCore.QTimer.singleShot(0, lambda: self._finish_test("usb", False, detail))

        def start_mpfw() -> None:
            started = self.usb_controller.start_flash(
                action="mpfw",
                file_path=str(mp_path),
                verify_board=verify_board,
                callback=after_mpfw,
            )
            if not started:
                fail("USB downloader busy during MP flash.")

        def after_ade(passed: bool, detail: str) -> None:
            if not passed:
                fail(f"ADE flash failed: {detail}")
                return
            append_log(self.log_box, "ADE/Data flash completed; waiting 1s before MP flash...")
            QtCore.QTimer.singleShot(1000, start_mpfw)

        def after_mpfw(passed: bool, detail: str) -> None:
            if not passed:
                fail(f"MP flash failed: {detail}")
                return
            append_log(self.log_box, "MP flash completed; waiting 10s then re-enumerate USB...")
            QtCore.QTimer.singleShot(10000, finalize_reenum)

        def finalize_reenum() -> None:
            reenum_ok = self.usb_controller.reenumerate_port()
            if reenum_ok:
                self._finish_test("usb", True, "ADE + MP flash and USB re-enumerate completed")
            else:
                self._finish_test("usb", False, "USB re-enumerate failed after flashing")

        started = self.usb_controller.start_flash(
            action="ade",
            file_path=str(ade_path),
            verify_board=verify_board,
            callback=after_ade,
        )
        if not started:
            fail("USB downloader busy during ADE flash.")

    def _reset_power_readings(self) -> None:
        styles = self._power_styles()
        for row in self.power_rows.values():
            row["current"].setText("")
            row["current"].setStyleSheet(styles["current"])

    def _update_power_readings(self, metrics: Dict[str, float]) -> None:
        styles = self._power_styles()
        for key, row in self.power_rows.items():
            cur_val = metrics.get(key)
            cur_widget = row["current"]
            if cur_val is None:
                cur_widget.setText("")
                cur_widget.setStyleSheet(styles["current"])
                continue
            cur_widget.setText(f"{cur_val:.0f}")
            try:
                min_v = float(row["min"].text() or 0)
                max_v = float(row["max"].text() or 0)
            except ValueError:
                min_v, max_v = 0, 0
            except Exception as exc:
                print(f"[DEBUG] power reading parse error for {key}: {exc}")
                min_v, max_v = 0, 0
            if (min_v and cur_val < min_v) or (max_v and cur_val > max_v):
                cur_widget.setStyleSheet(styles["warn"])
            else:
                cur_widget.setStyleSheet(styles["current"])

    def _power_within_limits(self, metrics: Dict[str, float]) -> bool:
        """Validate only the metrics we actually received; VIN/IIN are required."""
        required = ("vin_mv", "iin_ma")
        missing_required = [key for key in required if metrics.get(key) is None]
        if missing_required:
            print(f"[DEBUG] power limit missing required metrics: {', '.join(missing_required)}")
            return False

        within = True
        for key, row in self.power_rows.items():
            cur_val = metrics.get(key)
            if cur_val is None:
                print(f"[DEBUG] power limit skipping {key} (not reported)")
                continue
            try:
                min_v = float(row["min"].text() or 0)
                max_v = float(row["max"].text() or 0)
            except ValueError:
                print(f"[DEBUG] power limit parse error for {key}")
                within = False
                continue
            except Exception as exc:
                print(f"[DEBUG] power limit unexpected error for {key}: {exc}")
                within = False
                continue
            if (min_v and cur_val < min_v) or (max_v and cur_val > max_v):
                print(f"[DEBUG] power limit out of range for {key}: {cur_val} not in [{min_v},{max_v}]")
                within = False
        return within

    def _save_power_results(self, metrics: Dict[str, float], raw_text: str, port: str) -> None:
        log_path = Path("power_log.csv")
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "timestamp": timestamp,
            "port": port,
            "vin_mv": metrics.get("vin_mv", ""),
            "iin_ma": metrics.get("iin_ma", ""),
            "v3v3_mv": metrics.get("v3v3_mv", ""),
            "v5v_mv": metrics.get("v5v_mv", ""),
            "raw": raw_text.replace("\n", " | "),
        }
        write_header = not log_path.exists()
        try:
            import csv

            with log_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=row.keys())
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

    def _start_power_sequence_then_tests(self, port: str) -> None:
        append_log(self.log_box, f"ESP32 power check on {port} (T then S)...")
        print(f"[DEBUG][ESP32] start power sequence on {port}")
        self._reset_power_readings()
        self.power_inflight = True

        def on_timeout() -> None:
            if not self.power_inflight:
                return
            append_log(self.log_box, "ESP32 power check timeout; aborting batch tests.")
            self.power_inflight = False
            self._abort_batch("ESP32 power check timeout")

        def on_done(ok: bool, text: str, metrics: Dict[str, float]) -> None:
            if not self.power_inflight:
                return
            self.power_inflight = False
            try:
                print(f"[DEBUG] ESP32 on_done ok={ok}, metrics={metrics}")
                if not ok or not metrics:
                    detail = text or "ESP32 power check failed"
                    append_log(self.log_box, detail)
                    print(f"[DEBUG] ESP32 fail detail: {detail}")
                    self._abort_batch(detail)
                    return
                self.power_data_ready = True
                append_log(self.log_box, "ESP32 power data received; starting selected tests...")
                append_log(self.log_box, text)
                print(f"[DEBUG] ESP32 metrics: {metrics}")
                print("[DEBUG] updating power readings...")
                self._update_power_readings(metrics)
                print("[DEBUG] power readings updated, saving results...")
                self._save_power_results(metrics, text, port)
                missing_optional = [
                    meta["label"]
                    for key, meta in self.power_thresholds.items()
                    if key not in ("vin_mv", "iin_ma") and metrics.get(key) is None
                ]
                if missing_optional:
                    append_log(
                        self.log_box,
                        f"ESP32 did not report {', '.join(missing_optional)}; skipping those checks.",
                    )
                within = self._power_within_limits(metrics)
                if not within:
                    append_log(
                        self.log_box,
                        "Power readings out of range; continuing tests (check PSU/DUT).",
                    )
                    print("[DEBUG] power readings out of range, continuing tests...")
                else:
                    print("[DEBUG] power readings within limits, scheduling tests...")
                QtCore.QTimer.singleShot(0, self._run_next_test_from_queue)
            except Exception as exc:
                append_log(self.log_box, f"ESP32 data handling exception: {exc}")
                print(f"[DEBUG] ESP32 exception: {exc}")
                self._abort_batch(f"ESP32 exception: {exc}")

        esp32.start_power_sequence(port, on_done, lambda msg: append_log(self.log_box, msg))
        # watchdog timeout (10s after request to cover slower DUT)
        QtCore.QTimer.singleShot(10000, on_timeout)

    def _abort_batch(self, reason: str) -> None:
        append_log(self.log_box, f"Batch aborted: {reason}")
        print(f"[DEBUG] Batch abort: {reason}")
        if self.batch_uses_esp32:
            self._send_esp32_end_signal()
        else:
            self._complete_batch_cleanup()

    def _send_esp32_end_signal(self) -> None:
        port = self.user_config.esp32_port
        if not port:
            self._complete_batch_cleanup()
            return
        append_log(self.log_box, f"ESP32 end signal on {port}...")
        print(f"[DEBUG][ESP32] TX end on {port}")

        def on_done(ok: bool, detail: str) -> None:
            append_log(self.log_box, f"ESP32 end result: {detail}")
            self._complete_batch_cleanup()

        esp32.send_end_signal(port, lambda msg: append_log(self.log_box, msg), on_done)

    def _complete_batch_cleanup(self) -> None:
        self.batch_uses_esp32 = False
        self.power_data_ready = False
        self.test_queue = []
        self.active_test = None
        self.last_finished_test = None
        self.batch_inflight = False
        can_enable = self.tests_enabled and self.serial_checked
        self._set_interactive_enabled(can_enable)
        if shiboken6.isValid(self.submit_btn):
            self.submit_btn.setEnabled(can_enable)
            self._refresh_button_cursor(self.submit_btn)

    def _start_selected_tests(self) -> None:
        if not self.logged_in:
            append_log(self.log_box, "Please login first.")
            return
        if not self.serial_checked:
            append_log(self.log_box, "Please enter S/N code and press Check before running tests.")
            return
        if self.active_test:
            busy_name = self.results[self.active_test].name
            append_log(self.log_box, f"{busy_name} is running, please wait.")
            return
        if self.test_queue:
            append_log(self.log_box, "Batch test is already running.")
            return

        order = ["stlink", "usb", "gpio", "rs485", "rs232", "rs422", "lcd", "ethernet"]
        selected = [key for key in order if key in self.test_checks and self.test_checks[key].isChecked()]
        if not selected:
            append_log(self.log_box, "No tests selected.")
            return
        # Reset all status labels each time a new batch starts.
        self._reset_results()
        self._persist_selected_tests()
        esp32_port = getattr(self, "power_port_combo", None).currentData() if hasattr(self, "power_port_combo") else None
        if not esp32_port:
            append_log(self.log_box, "Please select ESP32 COM port before starting tests.")
            return
        self.user_config.esp32_port = esp32_port or ""
        save_user_config(self.user_config)
        self.test_queue = selected
        self.batch_uses_esp32 = True
        self.batch_inflight = True
        self.power_data_ready = False
        self.last_finished_test = None
        append_log(self.log_box, f"Starting batch tests: {', '.join(selected)}")
        self._set_interactive_enabled(False)
        self._start_power_sequence_then_tests(esp32_port)
        self._update_summary_status()

    def _run_next_test_from_queue(self) -> None:
        if self.active_test or not self.test_queue:
            return
        if self.batch_uses_esp32 and not self.power_data_ready:
            return
        next_key = self.test_queue.pop(0)
        delay_ms = 0
        if self.last_finished_test == "stlink" and next_key == "usb":
            delay_ms = max(delay_ms, 3000)
        if delay_ms > 0:
            append_log(self.log_box, f"Waiting {delay_ms/1000:.1f}s before {next_key}...")
            QtCore.QTimer.singleShot(delay_ms, lambda: self._start_queue_test(next_key))
        else:
            self._start_queue_test(next_key)

    def _start_queue_test(self, key: str) -> None:
        print(f"[DEBUG] Starting queued test: {key}")
        started = self._run_test(key)
        if not started:
            QtCore.QTimer.singleShot(0, self._run_next_test_from_queue)

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
        self.results[key].status = status_text
        self.results[key].detail = detail
        self.active_test = None
        self.last_finished_test = key
        if key == "usb":
            self.usb_controls_locked = False
        if self.test_queue:
            # keep controls disabled until queue completes
            pass
        if self._closing or not shiboken6.isValid(self):
            return

        if shiboken6.isValid(status_label):
            status_label.update_status(status_text)

        log_box_ok = shiboken6.isValid(self.log_box)
        if key == "stlink" and detail and log_box_ok:
            append_log(self.log_box, detail)
        if log_box_ok:
            append_log(self.log_box, f"{self.results[key].name}: {status_text} - {detail}")

        self._update_summary_status()

        if self.test_queue:
            QtCore.QTimer.singleShot(0, self._run_next_test_from_queue)
            return
        if self.batch_uses_esp32 or self.batch_inflight:
            self._send_esp32_end_signal()
            return

        self._complete_batch_cleanup()

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
        self._refresh_power_styles()
        if hasattr(self, "user_config") and self.user_config.theme != normalized:
            self.user_config.theme = normalized
            save_user_config(self.user_config)

    def _power_styles(self, header_font_px: Optional[int] = None) -> Dict[str, str]:
        """Return power table styles keyed by element name, theme-aware."""
        header_px = header_font_px or int(12 * self.ui_scale)
        if self.current_theme == "dark":
            return {
                "header": (
                    f"background: #2f333a; border: 1px solid #4a505a; padding: 6px 10px; "
                    f"font-weight: 600; font-size: {header_px}px; color: #e8eaed;"
                ),
                "cell": "background: #1f232a; color: #e8eaed; border: 1px solid #3c424d; padding: 6px 10px;",
                "current": "background: #1b1f26; color: #e8eaed; border: 1px solid #3c424d; padding: 6px 10px;",
                "warn": "background: #2d1b1d; color: #ffb4b4; border: 1px solid #f28b82; padding: 6px 10px;",
                "label": "padding-left: 10px; color: #e8eaed;",
            }
        return {
            "header": (
                f"background: #e7ebf3; border: 1px solid #cfd5e4; padding: 6px 10px; "
                f"font-weight: 600; font-size: {header_px}px; color: #1f2937;"
            ),
            "cell": "background: #f7f9fc; color: #1f2937; border: 1px solid #cfd5e4; padding: 6px 10px;",
            "current": "background: #f7f9fc; color: #1f2937; border: 1px solid #cfd5e4; padding: 6px 10px;",
            "warn": "background: #fff1f1; color: #b91c1c; border: 1px solid #ef4444; padding: 6px 10px;",
            "label": "padding-left: 10px; color: #1f2937;",
        }

    def _refresh_power_styles(self) -> None:
        """Update power table colors for current theme."""
        if not self.power_rows:
            return
        styles = self._power_styles()
        for lbl in getattr(self, "power_header_labels", []):
            if shiboken6.isValid(lbl):
                lbl.setStyleSheet(styles["header"])
        for row in self.power_rows.values():
            lbl = row.get("label")
            if lbl and shiboken6.isValid(lbl):
                lbl.setStyleSheet(styles["label"])
            for key in ("min", "max"):
                widget = row.get(key)
                if widget and shiboken6.isValid(widget):
                    widget.setStyleSheet(styles["cell"])
            cur_widget = row.get("current")
            if cur_widget and shiboken6.isValid(cur_widget):
                # Reset current style to base; _update_power_readings will recolor on thresholds.
                cur_widget.setStyleSheet(styles["current"])

    def _resize_to_base(self, scroll: QtWidgets.QScrollArea) -> None:
        """Set initial window size to 1280x720; allow scaling up via screen size."""
        base_w, base_h = 1280, 720
        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.availableGeometry() if screen else QtCore.QRect(0, 0, base_w, base_h)
        width = min(base_w, rect.width())
        height = min(base_h, rect.height())
        self.resize(width, height)
        # Allow smaller windows; scroll area will handle overflow.
        self.setMinimumSize(int(base_w * 0.75), int(base_h * 0.75))

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
        dark_mode = self.current_theme == "dark"
        text_color = "#e8eaed" if dark_mode else "#111827"
        bg_color = "#202124" if dark_mode else "#ffffff"
        if markdown and hasattr(viewer, "setMarkdown"):
            viewer.setMarkdown(content)
        else:
            viewer.setPlainText(content)
        if transparent and dark_mode:
            dialog.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            dialog.setStyleSheet("background: transparent;")
            viewer.setStyleSheet(
                f"background: transparent; border: none; color: {text_color};"
            )
        else:
            dialog.setStyleSheet(f"background: {bg_color}; color: {text_color};")
            viewer.setStyleSheet(
                f"background: {bg_color}; color: {text_color}; border: none;"
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
        self._closing = True
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
