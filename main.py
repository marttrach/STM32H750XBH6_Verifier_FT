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
import json
from pathlib import Path
import datetime as dt
import copy
from typing import Any, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6

import esp32
import stlink
import usb_firmware
from com_port import available_ports, populate_combo, run_loopback_test
from stm32_binary_tool import run_gpio_test, run_lcd_test, run_ethernet_test
from global_utility import (
    TestResult,
    StatusLabel,
    append_log,
    compute_scale,
    apply_global_font,
    resize_by_scale,
    theme_stylesheet,
)
from mis_login import EmployeeLoginDialog
from setting import AppSettings, SettingDialog, load_settings, save_settings, MesConfig, MysqlConfig
LOG_DIR = Path("LOG")

APP_VERSION = "0.6_00251204"


class SerialNumberDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, prefill: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Serial Number")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._sn_regex = QtCore.QRegularExpression("^[A-Za-z0-9]+$")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3)
        title = QtWidgets.QLabel("Please Input Serial Number")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(title)

        self.edit = QtWidgets.QLineEdit(prefill)
        self.edit.setPlaceholderText("Scan or enter S/N")
        self.edit.setMinimumHeight(32)
        self.edit.setValidator(QtGui.QRegularExpressionValidator(self._sn_regex))
        layout.addWidget(self.edit)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self.ok_btn = QtWidgets.QPushButton("Check")
        self.ok_btn.setMinimumWidth(100)
        self.abort_btn = QtWidgets.QPushButton("Abort")
        self.abort_btn.setMinimumWidth(100)
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(self.abort_btn)
        layout.addLayout(btn_row)

        self.hint_label = QtWidgets.QLabel("Press Enter or Check twice to confirm S/N.")
        self.hint_label.setAlignment(QtCore.Qt.AlignCenter)
        self.hint_label.setStyleSheet("color: #d35400; font-weight: 600; padding-top: 6px;")
        layout.addWidget(self.hint_label)
        self.ok_btn.clicked.connect(self._accept)
        self.abort_btn.clicked.connect(self._abort)
        self.edit.textChanged.connect(self._update_ok_state)
        self.edit.returnPressed.connect(self._accept)
        self._update_ok_state(self.edit.text())
        self.aborted = False
        QtCore.QTimer.singleShot(0, self.edit.setFocus)

    def _update_ok_state(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            self.ok_btn.setEnabled(False)
            self.hint_label.setText("S/N cannot be empty.")
            return
        if not self._sn_regex.match(stripped).hasMatch():
            self.ok_btn.setEnabled(False)
            self.hint_label.setText("S/N must be letters/numbers only.")
            return
        self.ok_btn.setEnabled(True)
        self.hint_label.setText("Press Enter or Check to confirm S/N.")

    def _accept(self) -> None:
        stripped = self.edit.text().strip()
        if not stripped:
            self.hint_label.setText("S/N cannot be empty.")
            return
        if not self._sn_regex.match(stripped).hasMatch():
            self.hint_label.setText("S/N must be letters/numbers only.")
            return
        self.hint_label.setText("")
        self.aborted = False
        self.accept()

    def _abort(self) -> None:
        self.aborted = True
        self.reject()

    def serial_text(self) -> str:
        return self.edit.text().strip()


class MesMysqlDialog(QtWidgets.QDialog):
    def __init__(self, settings: AppSettings, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MES / MySQL Settings")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.settings_copy = copy.deepcopy(settings)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # MES section
        mes_group = QtWidgets.QGroupBox("MES")
        mes_form = QtWidgets.QFormLayout(mes_group)
        mes_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.mes_enable = QtWidgets.QCheckBox("Enable MES")
        self.mes_enable.setChecked(bool(self.settings_copy.mes_enabled))
        mes_form.addRow("MES", self.mes_enable)

        self.mes_cc = QtWidgets.QLineEdit(self.settings_copy.mes_config.cc)
        self.mes_un = QtWidgets.QLineEdit(self.settings_copy.mes_config.un)
        self.mes_token = QtWidgets.QLineEdit(self.settings_copy.mes_config.token)
        self.mes_prcs = QtWidgets.QLineEdit(self.settings_copy.mes_config.prcs)
        self.mes_station = QtWidgets.QLineEdit(self.settings_copy.mes_config.station)
        self.mes_project = QtWidgets.QLineEdit(self.settings_copy.mes_config.project)
        self.mes_base_url = QtWidgets.QLineEdit(self.settings_copy.mes_config.base_url)
        self.mes_check_sn_key = QtWidgets.QLineEdit(self.settings_copy.mes_config.check_sn_key)
        self.mes_insert_key = QtWidgets.QLineEdit(self.settings_copy.mes_config.insert_details_key)
        self.mes_plant_code = QtWidgets.QLineEdit(self.settings_copy.mes_config.plant_code)

        mes_form.addRow("CC", self.mes_cc)
        mes_form.addRow("UN", self.mes_un)
        mes_form.addRow("Token", self.mes_token)
        mes_form.addRow("PRCS", self.mes_prcs)
        mes_form.addRow("Station", self.mes_station)
        mes_form.addRow("Project", self.mes_project)
        mes_form.addRow("BaseURL", self.mes_base_url)
        mes_form.addRow("CheckSNKey", self.mes_check_sn_key)
        mes_form.addRow("InsertDetailsKey", self.mes_insert_key)
        mes_form.addRow("PlantCode", self.mes_plant_code)

        # MySQL section
        mysql_group = QtWidgets.QGroupBox("MySQL")
        mysql_form = QtWidgets.QFormLayout(mysql_group)
        mysql_form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.mysql_enable = QtWidgets.QCheckBox("Enable MySQL")
        self.mysql_enable.setChecked(bool(self.settings_copy.mysql_config.enable))
        mysql_form.addRow("MySQL", self.mysql_enable)

        self.mysql_host = QtWidgets.QLineEdit(self.settings_copy.mysql_config.host)
        self.mysql_port = QtWidgets.QLineEdit(str(self.settings_copy.mysql_config.port))
        self.mysql_db = QtWidgets.QLineEdit(self.settings_copy.mysql_config.db_name)
        self.mysql_table = QtWidgets.QLineEdit(self.settings_copy.mysql_config.table_name)
        self.mysql_user = QtWidgets.QLineEdit(self.settings_copy.mysql_config.user)
        self.mysql_pass = QtWidgets.QLineEdit(self.settings_copy.mysql_config.password)
        self.mysql_pass.setEchoMode(QtWidgets.QLineEdit.Password)

        mysql_form.addRow("Host", self.mysql_host)
        mysql_form.addRow("Port", self.mysql_port)
        mysql_form.addRow("DB Name", self.mysql_db)
        mysql_form.addRow("Table Name", self.mysql_table)
        mysql_form.addRow("User", self.mysql_user)
        mysql_form.addRow("Password", self.mysql_pass)

        layout.addWidget(mes_group)
        layout.addWidget(mysql_group)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QtWidgets.QPushButton("Save")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        ok_btn.clicked.connect(self._accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _accept(self) -> None:
        self.settings_copy.mes_enabled = self.mes_enable.isChecked()
        mc = self.settings_copy.mes_config
        mc.cc = self.mes_cc.text().strip()
        mc.un = self.mes_un.text().strip()
        mc.token = self.mes_token.text().strip()
        mc.prcs = self.mes_prcs.text().strip()
        mc.station = self.mes_station.text().strip()
        mc.project = self.mes_project.text().strip()
        mc.base_url = self.mes_base_url.text().strip()
        mc.check_sn_key = self.mes_check_sn_key.text().strip()
        mc.insert_details_key = self.mes_insert_key.text().strip()
        mc.plant_code = self.mes_plant_code.text().strip()

        my = self.settings_copy.mysql_config
        my.enable = self.mysql_enable.isChecked()
        my.host = self.mysql_host.text().strip()
        try:
            my.port = int(self.mysql_port.text().strip() or my.port)
        except Exception:
            pass
        my.db_name = self.mysql_db.text().strip()
        my.table_name = self.mysql_table.text().strip()
        my.user = self.mysql_user.text().strip()
        my.password = self.mysql_pass.text().strip()
        self.accept()

    def updated_settings(self) -> AppSettings:
        return self.settings_copy


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
    def __init__(self, app_settings: AppSettings, employee_no: str = "") -> None:
        super().__init__()
        self.setWindowTitle("STM32 Production Test Fixture Tool")
        # Scale UI relative to screen; cap size and shrink fonts/buttons for 1024x768.
        base_scale = compute_scale() * 0.6
        self.ui_scale = min(0.75, max(0.55, base_scale))
        apply_global_font(self.ui_scale)
        resize_by_scale(self, self.ui_scale)
        self.app_settings: AppSettings = copy.deepcopy(app_settings)
        self.employee_no = employee_no.strip()
        self.results: Dict[str, TestResult] = {
            "power": TestResult("Power"),
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
        self.current_theme = (self.app_settings.theme or "light").lower()
        self.logged_in = bool(self.employee_no)
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
        self._current_test_start: Optional[dt.datetime] = None
        self.power_rows: Dict[str, Dict[str, Any]] = {}
        self.power_thresholds = copy.deepcopy(self.app_settings.power)
        self.power_data_ready = False
        self.power_inflight = False
        self.batch_inflight = False
        self._flashback_inflight = False
        self._flashback_done = False
        self._flashback_fail_reason: str = ""
        self._pending_end_outcome: Optional[str] = None
        self.current_serial: str = ""
        self._active_serial_for_run: str = ""
        self._current_batch_tests: List[str] = []
        self._tested_serial_results: Dict[str, str] = {}
        self._dut_elapsed_seconds: float = 0.0
        self._run_total: int = 0
        self._run_pass: int = 0
        self._run_fail: int = 0
        self._current_run_outcome: Optional[str] = None
        self._run_recorded: bool = False
        self._batch_start_ts: Optional[dt.datetime] = None
        self._esp32_end_confirmed: bool = False
        self._esp32_end_inflight: bool = False
        self._batch_start_ts: Optional[dt.datetime] = None
        self._esp32_end_confirmed: bool = False
        self._rework_check_done: bool = False
        self._last_rework_board_info: Optional[Dict[str, Any]] = None
        self._pending_power_log: Optional[Dict[str, object]] = None
        # Use a scroll area to keep widgets visible on small or full-screen displays.
        content = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(content)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(3)

        self._build_menubar()
        main_layout.addWidget(self._build_header())
        main_layout.addSpacing(1)

        # Top row: power, tests (ratio 2:2).
        main_row = QtWidgets.QHBoxLayout()
        main_row.setSpacing(int(3 * self.ui_scale))
        main_row.addWidget(self._build_power_panel(), stretch=2)
        main_row.addWidget(self._build_tests(), stretch=2)
        main_layout.addLayout(main_row)

        # Middle row: summary status (left) and log panel (right).
        mid_row = QtWidgets.QHBoxLayout()
        mid_row.setSpacing(int(3 * self.ui_scale))
        mid_row.addWidget(self._build_summary_status(), stretch=1)
        mid_row.addWidget(self._build_log_panel(), stretch=1)
        main_layout.addLayout(mid_row)

        # Initialize USB controls (hidden) so USB logic still works.
        self._usb_options_group = self._build_usb_options()
        if self._usb_options_group:
            self._usb_options_group.hide()
        self._sync_usb_controls_from_settings()

        self._restore_selected_tests()
        self._loading_config = False

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        self.setCentralWidget(scroll)
        self._resize_to_base(scroll)
        self._enable_tests(self.logged_in)
        self._apply_theme(self.current_theme)
        self._populate_ports()
        self._setup_usb_controller()
        self._update_summary_status()
        self._update_header_texts()
        self._update_clock()
        self._update_totals()
        self._serial_prompt_shown = False
        self._clock_timer = QtCore.QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self.serial_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F10"), self)
        self.serial_shortcut.activated.connect(lambda: self._show_serial_dialog(force=True))
        self._refresh_shortcuts_and_toolbar()
        if self.logged_in:
            self._handle_login_success(self.employee_no)

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

        setting_act = QtGui.QAction("Setting", self)
        setting_act.triggered.connect(self._open_settings)
        bar.addAction(setting_act)
        mes_setting_act = QtGui.QAction("MES", self)
        mes_setting_act.triggered.connect(self._open_mes_settings)
        bar.addAction(mes_setting_act)

        license_menu = bar.addMenu("License")
        license_act = QtGui.QAction("PySide6 LGPL", self)
        license_act.triggered.connect(self._show_license)
        license_menu.addAction(license_act)

        about_menu = bar.addMenu("About")
        about_act = QtGui.QAction("About / Changelog", self)
        about_act.triggered.connect(self._show_about)
        about_menu.addAction(about_act)
        self._toolbar_actions = {
            "import": import_act,
            "export": export_act,
            "setting": setting_act,
            "mes": mes_setting_act,
            "license": license_act,
            "about": about_act,
        }

    def _build_header(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(3 * self.ui_scale))

        # Top row: version | program | clock
        top_row = QtWidgets.QHBoxLayout()
        self.version_label = QtWidgets.QLabel(APP_VERSION)
        self.version_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #1f3b80;")
        top_row.addWidget(self.version_label, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        self.program_label = QtWidgets.QLabel(self.app_settings.program_name)
        self.program_label.setAlignment(QtCore.Qt.AlignCenter)
        self.program_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #1f3b80;")
        top_row.addWidget(self.program_label, stretch=1, alignment=QtCore.Qt.AlignCenter)

        self.clock_label = QtWidgets.QLabel("")
        self.clock_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.clock_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #1f3b80;")
        top_row.addWidget(self.clock_label, alignment=QtCore.Qt.AlignRight)
        layout.addLayout(top_row)

        # Middle row with station/emp/totals and SN/TestTime/MES
        mid_row = QtWidgets.QHBoxLayout()
        mid_row.setSpacing(int(10 * self.ui_scale))

        left_box = QtWidgets.QGroupBox()
        left_grid = QtWidgets.QGridLayout(left_box)
        left_grid.setContentsMargins(2, 2, 2, 2)
        left_grid.setHorizontalSpacing(int(10 * self.ui_scale))
        left_grid.setVerticalSpacing(int(6 * self.ui_scale))

        station_label = QtWidgets.QLabel("Station")
        station_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.station_value_label = QtWidgets.QLabel(self.app_settings.station or "N/A")
        self.station_value_label.setStyleSheet("color: #1f3b80; font-weight: 700;")
        left_grid.addWidget(station_label, 0, 0)
        left_grid.addWidget(self.station_value_label, 0, 1)

        emp_label = QtWidgets.QLabel("Emp")
        emp_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.emp_value_label = QtWidgets.QLabel("N/A")
        self.emp_value_label.setStyleSheet("color: #1f3b80; font-weight: 700;")
        left_grid.addWidget(emp_label, 1, 0)
        left_grid.addWidget(self.emp_value_label, 1, 1)

        self.user_btn = QtWidgets.QPushButton("Login" if not self.logged_in else "Logout")
        self.user_btn.setMinimumHeight(max(int(26 * self.ui_scale), 30))
        self.user_btn.setMinimumWidth(max(int(90 * self.ui_scale), 110))
        self.user_btn.setStyleSheet("font-size: 14px;")
        self.user_btn.clicked.connect(self._toggle_login)
        self._register_button_cursor(self.user_btn)
        left_grid.addWidget(self.user_btn, 1, 2)

        total_label = QtWidgets.QLabel("Total:")
        total_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.total_count_label = QtWidgets.QLabel("0")
        self.pass_count_label = QtWidgets.QLabel("Pass: 0")
        self.pass_count_label.setStyleSheet("color: #16a34a; font-weight: 700;")
        self.fail_count_label = QtWidgets.QLabel("Fail: 0")
        self.fail_count_label.setStyleSheet("color: #dc2626; font-weight: 700;")
        total_row = QtWidgets.QHBoxLayout()
        total_row.setSpacing(int(3 * self.ui_scale))
        total_row.addWidget(total_label)
        total_row.addWidget(self.total_count_label)
        total_row.addSpacing(int(25 * self.ui_scale))
        total_row.addWidget(self.pass_count_label)
        total_row.addSpacing(int(25 * self.ui_scale))
        total_row.addWidget(self.fail_count_label)
        total_row.addStretch()
        left_grid.addLayout(total_row, 2, 0, 1, 3)

        right_box = QtWidgets.QGroupBox()
        right_grid = QtWidgets.QGridLayout(right_box)
        right_grid.setContentsMargins(2, 2, 2, 2)
        right_grid.setHorizontalSpacing(int(8 * self.ui_scale))
        right_grid.setVerticalSpacing(int(6 * self.ui_scale))

        sn_label = QtWidgets.QLabel("S/N")
        sn_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.serial_edit = QtWidgets.QLabel("N/A")
        self.serial_edit.setMinimumHeight(max(int(26 * self.ui_scale), 30))
        self.serial_edit.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self.serial_edit.setStyleSheet(
            "padding: 4px 8px; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 6px; color: #1f2937;"
        )
        self.check_sn_btn = QtWidgets.QPushButton("Enter")
        self.check_sn_btn.setMinimumHeight(max(int(26 * self.ui_scale), 30))
        self.check_sn_btn.clicked.connect(lambda: self._show_serial_dialog(force=True))
        self._register_button_cursor(self.check_sn_btn)
        sn_row = QtWidgets.QHBoxLayout()
        sn_row.setSpacing(int(3 * self.ui_scale))
        sn_row.addWidget(self.serial_edit, stretch=1)
        sn_row.addWidget(self.check_sn_btn)
        right_grid.addWidget(sn_label, 0, 0)
        right_grid.addLayout(sn_row, 0, 1)

        test_time_label = QtWidgets.QLabel("Test Time")
        test_time_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.test_time_value = QtWidgets.QLabel("-")
        self.test_time_value.setStyleSheet("color: #1f3b80; font-weight: 700;")
        right_grid.addWidget(test_time_label, 1, 0)
        right_grid.addWidget(self.test_time_value, 1, 1)

        mes_label = QtWidgets.QLabel("MES")
        mes_label.setStyleSheet("color: #d35400; font-weight: 700;")
        self.mes_status_label = QtWidgets.QLabel("Disabled" if not self.app_settings.mes_enabled else "Enabled")
        self.mes_status_label.setStyleSheet("color: #1f3b80; font-weight: 700;")
        right_grid.addWidget(mes_label, 2, 0)
        right_grid.addWidget(self.mes_status_label, 2, 1)

        mid_row.addWidget(left_box, stretch=1)
        mid_row.addWidget(right_box, stretch=1)
        layout.addLayout(mid_row)

        return widget

    def _build_summary_status(self) -> QtWidgets.QWidget:
        box = QtWidgets.QFrame()
        box.setFrameShape(QtWidgets.QFrame.StyledPanel)
        box.setStyleSheet("padding: 8px;")
        layout = QtWidgets.QHBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2)
        self.summary_font_size = 66
        self.summary_label = QtWidgets.QLabel("IDLE")
        self.summary_label.setAlignment(QtCore.Qt.AlignCenter)
        self.summary_label.setMinimumHeight(int(52 * self.ui_scale * 3))
        self.summary_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.summary_label.setStyleSheet(
            f"background: #e5e7eb; color: #111827; border-radius: 8px; font-size: {self.summary_font_size}px; font-weight: 700;"
        )
        layout.addWidget(self.summary_label)
        return box

    def _set_summary_status(self, status: str) -> None:
        palette = {
            "PASS": "background: #0f9d58; color: white;",
            "FAIL": "background: #d93025; color: white;",
            "RUNNING": "background: #1a73e8; color: white;",
            "IDLE": "background: #9ca3af; color: #111827;",
            "FLASH BACK": "background: #a855f7; color: white;",
            "ERROR": "background: #fbbf24; color: #111827;",
        }
        style = palette.get(status.upper(), palette["IDLE"])
        self.summary_label.setText(status.upper())
        self.summary_label.setStyleSheet(
            f"{style} border-radius: 8px; font-size: {self.summary_font_size}px; font-weight: 700;"
        )

    def _update_summary_status(self) -> None:
        if self._flashback_inflight:
            self._set_summary_status("FLASH BACK")
            return
        if self.active_test or self.batch_inflight:
            self._set_summary_status("RUNNING")
            return
        statuses = [
            res.status
            for res in self.results.values()
            if res and res.status and res.status.upper() != "IDLE"
        ]
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
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(int(3 * self.ui_scale))

        # ESP32 port selection
        port_row = QtWidgets.QHBoxLayout()
        port_row.setSpacing(int(3 * self.ui_scale))
        port_row.addWidget(QtWidgets.QLabel("ESP32 COM"))
        self.power_port_combo = RefreshingCombo(self._refresh_power_combo)
        self.power_port_combo.setMinimumHeight(int(24 * self.ui_scale))
        populate_combo(self.power_port_combo, available_ports())
        self._restore_power_port()
        self.power_port_combo.currentIndexChanged.connect(self._on_power_port_changed)
        port_row.addWidget(self.power_port_combo, stretch=1)
        layout.addLayout(port_row)

        # Excel-like table
        self.power_table = QtWidgets.QTableWidget(parent=group)
        headers = ["No", "Item", "Expected", "Up limit", "Low limit", "Unit", "Measurement", "Result"]
        self.power_table.setColumnCount(len(headers))
        self.power_table.setHorizontalHeaderLabels(headers)
        self.power_table.setRowCount(len(self.power_thresholds))
        header = self.power_table.horizontalHeader()
        header.setStretchLastSection(True)
        widths = [40, 120, 90, 90, 90, 70, 120, 80]
        for idx, w in enumerate(widths):
            header.resizeSection(idx, int(w * self.ui_scale))
        self.power_table.verticalHeader().setVisible(False)
        self.power_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.power_table.setAlternatingRowColors(True)
        self.power_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.power_rows = {}
        styles = self._power_styles()

        def _fmt_int(val: Any) -> str:
            try:
                return str(int(float(val)))
            except Exception:
                try:
                    return str(int(val))
                except Exception:
                    return str(val)

        for row_idx, (key, meta) in enumerate(self.power_thresholds.items()):
            no_item = QtWidgets.QTableWidgetItem(str(row_idx + 1))
            no_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.power_table.setItem(row_idx, 0, no_item)

            item_item = QtWidgets.QTableWidgetItem(meta.get("label", key))
            item_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.power_table.setItem(row_idx, 1, item_item)

            expected_edit = QtWidgets.QLineEdit(_fmt_int(meta.get("expected", "")))
            upper_edit = QtWidgets.QLineEdit(_fmt_int(meta.get("upper", meta.get("max", ""))))
            lower_edit = QtWidgets.QLineEdit(_fmt_int(meta.get("lower", meta.get("min", ""))))
            for edit in (expected_edit, upper_edit, lower_edit):
                edit.setReadOnly(True)
                edit.setFixedHeight(max(int(26 * self.ui_scale), 30))
                edit.setStyleSheet(styles["cell"])
                edit.setAlignment(QtCore.Qt.AlignCenter)
            self.power_table.setCellWidget(row_idx, 2, expected_edit)
            self.power_table.setCellWidget(row_idx, 3, upper_edit)
            self.power_table.setCellWidget(row_idx, 4, lower_edit)

            unit_item = QtWidgets.QTableWidgetItem(meta.get("unit", ""))
            unit_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.power_table.setItem(row_idx, 5, unit_item)

            meas_edit = QtWidgets.QLineEdit("")
            meas_edit.setReadOnly(True)
            meas_edit.setFixedHeight(max(int(26 * self.ui_scale), 30))
            meas_edit.setAlignment(QtCore.Qt.AlignCenter)
            meas_edit.setStyleSheet(styles["measurement"])
            self.power_table.setCellWidget(row_idx, 6, meas_edit)

            result_label = QtWidgets.QLabel("-")
            result_label.setAlignment(QtCore.Qt.AlignCenter)
            result_label.setStyleSheet(styles["result_idle"])
            self.power_table.setCellWidget(row_idx, 7, result_label)

            self.power_rows[key] = {
                "row": row_idx,
                "expected": expected_edit,
                "upper": upper_edit,
                "lower": lower_edit,
                "measurement": meas_edit,
                "result": result_label,
            }
            self.power_table.setRowHeight(row_idx, max(int(28 * self.ui_scale), 32))

        self.power_table.setStyleSheet(styles["table"])
        layout.addWidget(self.power_table)
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
        self.test_checks["stlink"].setChecked("stlink" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["stlink"], 1, 0)
        grid.addWidget(QtWidgets.QLabel("STLink (Bootloader)"), 1, 1)
        grid.addWidget(self.stlink_btn, 1, 2, 1, 2)
        grid.addWidget(self.stlink_status, 1, 4)

        self.test_checks["usb"] = QtWidgets.QCheckBox()
        self.test_checks["usb"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["usb"].setChecked("usb" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["usb"], 2, 0)
        grid.addWidget(QtWidgets.QLabel("USB (Firmware)"), 2, 1)
        grid.addWidget(self.usb_btn, 2, 2, 1, 2)
        grid.addWidget(self.usb_status, 2, 4)

        self.test_checks["gpio"] = QtWidgets.QCheckBox()
        self.test_checks["gpio"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["gpio"].setChecked("gpio" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["gpio"], 3, 0)
        grid.addWidget(QtWidgets.QLabel("GPIO"), 3, 1)
        grid.addWidget(self.gpio_btn, 3, 2, 1, 2)
        grid.addWidget(self.gpio_status, 3, 4)

        self.test_checks["rs485"] = QtWidgets.QCheckBox()
        self.test_checks["rs485"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs485"].setChecked("rs485" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["rs485"], 4, 0)
        grid.addWidget(QtWidgets.QLabel("RS485 COM"), 4, 1)
        grid.addWidget(self.rs485_port, 4, 2)
        grid.addWidget(self.rs485_btn, 4, 3)
        grid.addWidget(self.rs485_status, 4, 4)

        self.test_checks["rs232"] = QtWidgets.QCheckBox()
        self.test_checks["rs232"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs232"].setChecked("rs232" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["rs232"], 5, 0)
        grid.addWidget(QtWidgets.QLabel("RS232 COM"), 5, 1)
        grid.addWidget(self.rs232_port, 5, 2)
        grid.addWidget(self.rs232_btn, 5, 3)
        grid.addWidget(self.rs232_status, 5, 4)

        self.test_checks["rs422"] = QtWidgets.QCheckBox()
        self.test_checks["rs422"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["rs422"].setChecked("rs422" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["rs422"], 6, 0)
        grid.addWidget(QtWidgets.QLabel("RS422 COM"), 6, 1)
        grid.addWidget(self.rs422_port, 6, 2)
        grid.addWidget(self.rs422_btn, 6, 3)
        grid.addWidget(self.rs422_status, 6, 4)

        self.test_checks["lcd"] = QtWidgets.QCheckBox()
        self.test_checks["lcd"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["lcd"].setChecked("lcd" in self.app_settings.selected_tests)
        grid.addWidget(self.test_checks["lcd"], 7, 0)
        grid.addWidget(QtWidgets.QLabel("LCD/Backlight"), 7, 1)
        grid.addWidget(self.lcd_btn, 7, 2, 1, 2)
        grid.addWidget(self.lcd_status, 7, 4)

        self.test_checks["ethernet"] = QtWidgets.QCheckBox()
        self.test_checks["ethernet"].stateChanged.connect(self._persist_selected_tests)
        self.test_checks["ethernet"].setChecked("ethernet" in self.app_settings.selected_tests)
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
        variant_layout.setSpacing(int(3 * self.ui_scale))
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
        # Return the log widget directly so it fills the available space without borders.
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFrameStyle(QtWidgets.QFrame.NoFrame)
        self.log_box.setStyleSheet("background: #0f1115; color: #d1d5db; border: none;")
        self.log_box.setMinimumHeight(int(140 * self.ui_scale))
        self.log_box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        return self.log_box

    def _append_downloader_message(self, message: str) -> None:
        append_log(self.log_box, message)

    def _on_usb_save_log(self, action: str) -> None:
        append_log(self.log_box, f"USB action saved: {action}")

    def _check_serial_input(self) -> None:
        self._show_serial_dialog(force=True)

    def _handle_serial_accept(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            append_log(self.log_box, "S/N cannot be empty.")
            return
        if not text.isalnum():
            append_log(self.log_box, "S/N must contain letters/numbers only.")
            return
        try:
            sn_limit = int(getattr(self.app_settings, "sn_len", 10) or 10)
        except Exception:
            sn_limit = 10
        if len(text) > sn_limit:
            append_log(self.log_box, f"S/N length exceeds limit ({sn_limit}); please re-enter.")
            return
        if text != self.current_serial:
            if self.active_test or self.batch_inflight:
                append_log(self.log_box, "A test is running; please finish before switching S/N.")
                return
            self._prepare_new_serial_session(text)
        self.current_serial = text
        self.serial_checked = True
        self.serial_edit.setText(text)
        append_log(self.log_box, f"S/N check passed: {text}")
        if not self.active_test and self.tests_enabled:
            self._set_interactive_enabled(True)

    def _handle_serial_abort(self) -> None:
        self.serial_checked = False
        self.current_serial = ""
        self.serial_edit.setText("N/A")
        self._set_interactive_enabled(False)
        append_log(self.log_box, "S/N cleared; tests are locked until a new S/N is entered.")

    def _show_serial_dialog(self, force: bool = False) -> None:
        if not self.logged_in:
            append_log(self.log_box, "Please login first.")
            return
        if self.active_test or self.batch_inflight:
            if force:
                append_log(self.log_box, "A test is running; wait until it finishes to change S/N.")
            return
        dlg = SerialNumberDialog(self, prefill=self.current_serial)
        if dlg.exec() == QtWidgets.QDialog.Accepted and not dlg.aborted:
            self._handle_serial_accept(dlg.serial_text())
        elif dlg.aborted:
            self._handle_serial_abort()

    def _refresh_shortcuts_and_toolbar(self) -> None:
        allow = self.logged_in
        if hasattr(self, "serial_shortcut"):
            self.serial_shortcut.setEnabled(allow)
        # Lock toolbar/menus except login/logout when not logged in.
        locked = not allow
        for act in getattr(self, "_toolbar_actions", {}).values():
            try:
                act.setEnabled(not locked)
            except Exception:
                pass
        # Keep logout/login button available.
        if hasattr(self, "user_btn"):
            self.user_btn.setEnabled(True)

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

    def _format_board_info_text(self, board_info: dict) -> str:
        resv = board_info.get("version_reserved", "")
        res_a = resv[0:1] if len(resv) > 0 else ""
        res_b = resv[1:2] if len(resv) > 1 else ""
        res_c = resv[2:3] if len(resv) > 2 else ""
        return (
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

    def handle_board_info(self, board_info: dict) -> None:
        try:
            text = self._format_board_info_text(board_info)
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

    # Settings and header helpers
    def _open_settings(self) -> None:
        dialog = SettingDialog(self.app_settings, self, reboot_handler=self._handle_dut_reboot)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.app_settings = dialog.get_settings()
            self.power_thresholds = copy.deepcopy(self.app_settings.power)
            self._sync_power_table_from_settings()
            self._apply_theme(self.app_settings.theme)
            self._persist_settings()
            self._update_header_texts()
            self._refresh_power_styles()
            self._sync_usb_controls_from_settings()

    def _handle_dut_reboot(self) -> None:
        ctrl = getattr(self, "usb_controller", None)
        if not ctrl:
            append_log(self.log_box, "USB controller not ready; cannot reboot DUT.")
            return
        if ctrl.d.isRunning():
            append_log(self.log_box, "USB downloader is busy; cannot reboot DUT.")
            return
        try:
            ok = ctrl.send_ctrl_d()
            if ok:
                append_log(self.log_box, "DUT Ctrl+D reboot issued (MP mode).")
            else:
                append_log(self.log_box, "DUT Ctrl+D reboot skipped (not MP mode or send failed).")
        except Exception as exc:
            append_log(self.log_box, f"DUT reboot failed: {exc}")

    def _open_mes_settings(self) -> None:
        dialog = MesMysqlDialog(self.app_settings, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.app_settings = dialog.updated_settings()
            self.power_thresholds = copy.deepcopy(self.app_settings.power)
            self._persist_settings()
            self._update_header_texts()
            self._refresh_power_styles()

    def _persist_settings(self) -> None:
        if getattr(self, "_loading_config", False):
            return
        save_settings(self.app_settings)

    def _sync_usb_controls_from_settings(self) -> None:
        """Sync hidden USB controls from app settings."""
        try:
            self.usb_custom_action_box.setChecked(bool(self.app_settings.usb_custom))
            # action combo
            idx = self.usb_action_combo.findData(self.app_settings.usb_action or "mpfw")
            if idx >= 0:
                self.usb_action_combo.setCurrentIndex(idx)
            # fw path
            self.usb_fw_path.setText(self.app_settings.usb_fw_path or str(Path("bin/firmware_ctp.orig")))
            # variant
            variant = (self.app_settings.usb_variant or "ctp").lower()
            if variant == "rtp":
                self.usb_variant_ctp.setChecked(False)
                self.usb_variant_rtp.setChecked(True)
            else:
                self.usb_variant_ctp.setChecked(True)
                self.usb_variant_rtp.setChecked(False)
            # verify
            self.usb_verify_box.setChecked(bool(self.app_settings.usb_verify))
            self._apply_usb_custom_state()
        except Exception:
            pass

    def _toggle_login(self) -> None:
        if self.logged_in:
            self._handle_logout()
        else:
            self._prompt_employee_login()

    def _prompt_employee_login(self) -> None:
        dialog = EmployeeLoginDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self._handle_login_success(dialog.employee_no)

    def _update_header_texts(self) -> None:
        self.program_label.setText(self.app_settings.program_name or "")
        self.station_value_label.setText(self.app_settings.station or "N/A")
        self.mes_status_label.setText("Enabled" if self.app_settings.mes_enabled else "Disabled")
        self.mes_status_label.setStyleSheet(
            "color: #1f3b80; font-weight: 700;" if self.app_settings.mes_enabled else "color: #6b7280; font-weight: 700;"
        )
        self._update_emp_label()
        self._update_totals()

    def _update_emp_label(self) -> None:
        self.emp_value_label.setText(self.employee_no if self.logged_in else "N/A")
        self.user_btn.setText("Logout" if self.logged_in else "Login")

    def _update_totals(self) -> None:
        total = self._run_total
        passed = self._run_pass
        failed = self._run_fail
        self.total_count_label.setText(str(total))
        self.pass_count_label.setText(f"Pass: {passed}")
        self.fail_count_label.setText(f"Fail: {failed}")

    def _log_root_dir(self) -> Path:
        return Path("LOG") if getattr(self.app_settings, "mes_enabled", False) else Path("DEBUG_LOG")

    def _today_log_dir(self) -> Path:
        return self._log_root_dir() / dt.datetime.now().strftime("%Y%m%d")

    def _ensure_log_dir(self) -> None:
        try:
            root = self._log_root_dir()
            root.mkdir(exist_ok=True)
            self._today_log_dir().mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _check_max_fail_limit(self, serial: str) -> bool:
        limit = getattr(self.app_settings, "max_fail", 0) or 0
        if limit <= 0:
            return True
        today_dir = self._today_log_dir()
        if not today_dir.exists():
            return True
        pattern = f"{serial}_*_FAIL.txt"
        current_fail = len(list(today_dir.glob(pattern)))
        if current_fail >= limit:
            append_log(
                self.log_box,
                f"S/N {serial} reached MaxFail limit ({limit}); cannot start tests.",
            )
            self._set_interactive_enabled(False)
            return False
        return True

    def _save_run_log(self, outcome: str) -> None:
        text = self.log_box.toPlainText().strip()
        if not text:
            return
        self._ensure_log_dir()
        now = dt.datetime.now()
        date_dir = self._today_log_dir()
        serial = self.current_serial or "UNKNOWN"
        fname = f"{serial}_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}_{outcome.upper()}.txt"
        path = date_dir / fname
        try:
            path.write_text(text, encoding="utf-8")
        except Exception:
            pass

    def _prepare_new_serial_session(self, serial: str) -> None:
        if serial == self.current_serial:
            return
        self.current_serial = serial
        self._dut_elapsed_seconds = 0.0
        self._current_batch_tests = []
        self._active_serial_for_run = ""
        self._current_run_outcome = None
        self._run_recorded = False
        self._flashback_inflight = False
        self._flashback_done = False
        self._pending_end_outcome = None
        self.batch_inflight = False
        self.batch_uses_esp32 = False
        self.test_queue = []
        self.power_data_ready = False
        self._current_test_start = None
        if getattr(self, "log_box", None) and shiboken6.isValid(self.log_box):
            self.log_box.clear()
        try:
            self._reset_power_readings()
        except Exception:
            pass
        self._reset_results()
        self._set_summary_status("IDLE")
        if hasattr(self, "test_time_value"):
            self.test_time_value.setText("-")

    def _compute_batch_outcome(self) -> Optional[str]:
        keys = list(self._current_batch_tests or [])
        if self.batch_uses_esp32 and "power" not in keys:
            keys = ["power"] + keys
        if not keys:
            return None
        seen_any = False
        all_pass = True
        for key in keys:
            result = self.results.get(key)
            if result is None:
                continue
            status = (result.status or "").upper()
            seen_any = True
            if status == "RUNNING":
                return None
            if status != "PASS":
                all_pass = False
        if not seen_any:
            return None
        if all_pass:
            return "PASS"
        return "FAIL"

    def _record_current_dut_result(self) -> None:
        serial = self._active_serial_for_run or self.current_serial
        if not serial:
            return
        outcome = self._current_run_outcome or self._compute_batch_outcome()
        if outcome is None:
            return
        self._tested_serial_results[serial] = outcome
        # Recompute totals from recorded serial outcomes to ensure final (including flashback) status is reflected.
        total = len(self._tested_serial_results)
        passed = sum(1 for v in self._tested_serial_results.values() if v == "PASS")
        failed = total - passed
        self._run_total = total
        self._run_pass = passed
        self._run_fail = failed
        self._run_recorded = True
        self._current_run_outcome = outcome
        self._update_totals()

    def _update_clock(self) -> None:
        now = dt.datetime.now()
        self.clock_label.setText(now.strftime("%Y/%m/%d %H:%M:%S"))

    def _append_end_summary(self, outcome: str) -> None:
        lines = [
            "-----------------------------------------------------",
            f"[END] Test = {outcome}",
        ]
        if outcome == "FAIL":
            for reason in self._gather_failure_reasons():
                lines.append(f"[Reason] {reason}")
        lines.extend([
            "-----------------------------------------------------",
            "---------------------TEST DONE-----------------------",
        ])
        for line in lines:
            append_log(self.log_box, line)

    def _gather_failure_reasons(self) -> List[str]:
        """Collect detailed failure reasons for summary footer."""
        reasons: List[str] = []
        if getattr(self, "_flashback_fail_reason", ""):
            reasons.append(self._flashback_fail_reason)
        selected_keys = list(self._current_batch_tests) if getattr(self, "_current_batch_tests", None) else list(self.results.keys())
        # Preserve the order defined in self.results.
        for key, res in self.results.items():
            if key not in selected_keys:
                continue
            status = (res.status or "").upper()
            if status == "PASS" or status == "":
                continue
            detail = res.detail or ""
            name = res.name or key
            reason_text = f"{name}: {detail}" if detail else f"{name}: no detail"
            reasons.append(reason_text)
        if not reasons:
            reasons.append("Unknown failure")
        return reasons

    def _update_power_log_test_time(self, seconds: float, final_outcome: Optional[str] = None) -> None:
        """Update the latest power log entry with final test time and final outcome."""
        path = self._today_log_dir() / "power_log.csv"
        if not path.exists():
            return
        try:
            import csv

            with path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                fieldnames = reader.fieldnames
            if not rows or not fieldnames:
                return
            # Find last data row (skip Up/Low limits).
            for row in reversed(rows):
                if row.get("Emp") not in ("Up Limit", "Low Limit"):
                    row["TestTime"] = str(int(round(seconds)))
                    if final_outcome:
                        row["Final"] = final_outcome
                    break
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except Exception:
            pass

    def _sync_power_table_from_settings(self) -> None:
        if not getattr(self, "power_rows", None):
            return
        for key, row in self.power_rows.items():
            meta = self.power_thresholds.get(key, {})
            if "expected" in row:
                try:
                    row["expected"].setText(str(int(float(meta.get("expected", "")))))
                except Exception:
                    row["expected"].setText(str(meta.get("expected", "")))
            if "upper" in row:
                try:
                    row["upper"].setText(str(int(float(meta.get("upper", "")))))
                except Exception:
                    row["upper"].setText(str(meta.get("upper", "")))
            if "lower" in row:
                try:
                    row["lower"].setText(str(int(float(meta.get("lower", "")))))
                except Exception:
                    row["lower"].setText(str(meta.get("lower", "")))
            item_item = self.power_table.item(row["row"], 1) if hasattr(self, "power_table") else None
            if item_item:
                item_item.setText(meta.get("label", key))
            unit_item = self.power_table.item(row["row"], 5) if hasattr(self, "power_table") else None
            if unit_item:
                unit_item.setText(meta.get("unit", ""))
        self._reset_power_readings()

    # Logic handlers
    def _handle_login_success(self, user: str) -> None:
        user = (user or "").strip()
        self.employee_no = user
        self.logged_in = bool(user)
        self._enable_tests(self.logged_in)
        self._update_emp_label()
        self._refresh_shortcuts_and_toolbar()
        display_user = user or "Unknown"
        append_log(self.log_box, f"Login success ({display_user}), tests are now enabled.")
        if not self._serial_prompt_shown:
            self._serial_prompt_shown = True
            QtCore.QTimer.singleShot(0, lambda: self._show_serial_dialog(force=True))

    def _handle_logout(self) -> None:
        self.logged_in = False
        self.employee_no = ""
        self._enable_tests(False)
        self._reset_results()
        self.serial_checked = False
        self._update_emp_label()
        self._refresh_shortcuts_and_toolbar()
        append_log(self.log_box, "Logged out. Please login again to continue.")

    def _enable_tests(self, enable: bool) -> None:
        self.tests_enabled = enable
        if self.active_test:
            self._set_interactive_enabled(False)
        else:
            self._set_interactive_enabled(enable and self.serial_checked)

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
        self.results["power"].status = "IDLE"
        self.results["power"].detail = ""
        try:
            self._reset_power_readings()
        except Exception:
            pass
        self._dut_elapsed_seconds = 0.0
        self._current_test_start = None
        self._update_summary_status()
        self._update_totals()
        if hasattr(self, "test_time_value"):
            self.test_time_value.setText("-")

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
        self._restore_saved_port(self.rs485_port, self.app_settings.rs485_port)
        self._restore_saved_port(self.rs232_port, self.app_settings.rs232_port)
        self._restore_saved_port(self.rs422_port, self.app_settings.rs422_port)
        self._refresh_power_combo()

    def _refresh_single_combo(self, combo: QtWidgets.QComboBox) -> None:
        ports = available_ports()
        populate_combo(combo, ports)
        if combo is self.rs485_port:
            self._restore_saved_port(combo, self.app_settings.rs485_port)
        elif combo is self.rs232_port:
            self._restore_saved_port(combo, self.app_settings.rs232_port)
        elif combo is self.rs422_port:
            self._restore_saved_port(combo, self.app_settings.rs422_port)

    def _refresh_power_combo(self, combo: Optional[QtWidgets.QComboBox] = None) -> None:
        combo = combo or getattr(self, "power_port_combo", None)
        if combo is None:
            return
        ports = available_ports()
        populate_combo(combo, ports)
        self._restore_saved_port(combo, self.app_settings.esp32_port)

    def _restore_saved_port(self, combo: QtWidgets.QComboBox, saved_port: str) -> None:
        if not saved_port:
            return
        idx = combo.findData(saved_port)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _restore_power_port(self) -> None:
        if hasattr(self, "power_port_combo"):
            self._restore_saved_port(self.power_port_combo, self.app_settings.esp32_port)

    def _persist_port_selection(self, key: str) -> None:
        if getattr(self, "_loading_config", False):
            return
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
            self.app_settings.rs485_port = val or ""
        elif key == "rs232":
            self.app_settings.rs232_port = val or ""
        elif key == "rs422":
            self.app_settings.rs422_port = val or ""
        self._persist_settings()

    def _restore_selected_tests(self) -> None:
        """Re-apply saved test selections without firing change handlers."""
        if not self.test_checks:
            return
        saved = self.app_settings.selected_tests or []
        if not isinstance(saved, (list, tuple, set)):
            saved = [saved]
        saved_set = {str(item) for item in saved}
        normalized = [key for key in self.test_checks if key in saved_set]
        for key, box in self.test_checks.items():
            prev = box.blockSignals(True)
            box.setChecked(key in saved_set)
            box.blockSignals(prev)
        if normalized != list(self.app_settings.selected_tests):
            self.app_settings.selected_tests = normalized
            if not getattr(self, "_loading_config", False):
                self._persist_settings()

    def _persist_selected_tests(self) -> None:
        if getattr(self, "_loading_config", False):
            return
        if not self.test_checks:
            return
        selected = [key for key, box in self.test_checks.items() if box.isChecked()]
        self.app_settings.selected_tests = selected
        self._persist_settings()

    def _validate_selected_ports_for_batch(self, selected: List[str]) -> bool:
        """Ensure every selected serial test has a COM port chosen."""
        mapping = {
            "rs485": self.rs485_port,
            "rs232": self.rs232_port,
            "rs422": self.rs422_port,
        }
        missing_labels = []
        for key in selected:
            combo = mapping.get(key)
            if combo is not None and not combo.currentData():
                label = self.results.get(key).name if key in self.results else key
                missing_labels.append(label or key)
        if missing_labels:
            msg = f"Please select COM port for: {', '.join(missing_labels)} before starting tests."
            append_log(self.log_box, msg)
            QtWidgets.QMessageBox.warning(self, "Missing COM Port", msg)
            self._set_summary_status("IDLE")
            return False
        return True

    def _validate_power_thresholds_ready(self) -> bool:
        """Confirm power limit settings are present and numeric before starting batch."""
        for key, meta in self.power_thresholds.items():
            label = meta.get("label", key)
            for field in ("expected", "upper", "lower"):
                val = meta.get(field, "")
                text = str(val).strip() if val is not None else ""
                if text == "":
                    msg = f"Power limit '{label}' field '{field}' is empty; please correct in Settings."
                    append_log(self.log_box, msg)
                    QtWidgets.QMessageBox.warning(self, "Power Limits", msg)
                    self._set_summary_status("IDLE")
                    return False
                try:
                    float(text)
                except Exception:
                    msg = f"Power limit '{label}' field '{field}' must be numeric; please correct in Settings."
                    append_log(self.log_box, msg)
                    QtWidgets.QMessageBox.warning(self, "Power Limits", msg)
                    self._set_summary_status("IDLE")
                    return False
        return True

    def _on_power_port_changed(self) -> None:
        if not hasattr(self, "power_port_combo"):
            return
        if getattr(self, "_loading_config", False):
            return
        val = self.power_port_combo.currentData()
        self.app_settings.esp32_port = val or ""
        self._persist_settings()

    def _setup_usb_controller(self) -> None:
        self.usb_controller = usb_firmware.UsbFirmwareController(
            message_handler=self._append_downloader_message,
            enable_handler=self._set_usb_controls_enabled,
            board_info_handler=self.handle_board_info,
            save_log_handler=self._on_usb_save_log,
        )
        # Restore saved variant selection
        variant = getattr(self.app_settings, "usb_variant", "ctp")
        self._set_usb_variant(variant)

    def _set_usb_variant(self, variant: str) -> None:
        variant = (variant or "ctp").lower()
        if variant == "rtp":
            self.usb_variant_ctp.setChecked(False)
            self.usb_variant_rtp.setChecked(True)
            self.usb_fw_path.setText(str(Path("bin/firmware_rtp.orig")))
            self.app_settings.usb_variant = "rtp"
        else:
            self.usb_variant_ctp.setChecked(True)
            self.usb_variant_rtp.setChecked(False)
            self.usb_fw_path.setText(str(Path("bin/firmware_ctp.orig")))
            self.app_settings.usb_variant = "ctp"
        self._persist_settings()

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
        self._current_test_start = dt.datetime.now()
        self.test_time_value.setText("-")
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
            esp32_port = (
                self.power_port_combo.currentData()
                if hasattr(self, "power_port_combo")
                else None
            ) or self.app_settings.esp32_port
            if not esp32_port:
                detail = "Please select ESP32 COM port before GPIO test."
                append_log(self.log_box, detail)
                QtCore.QTimer.singleShot(0, lambda: self._finish_test(key, False, detail))
                return True
            self.app_settings.esp32_port = esp32_port or ""
            self._persist_settings()
            run_gpio_test(
                stm32_port=None,
                esp32_port=esp32_port,
                log_cb=lambda msg: append_log(self.log_box, msg),
                callback=lambda passed, detail: self._finish_test(key, passed, detail),
            )
        elif key == "lcd":
            run_lcd_test(
                stm32_port=None,
                log_cb=lambda msg: append_log(self.log_box, msg),
                callback=lambda passed, detail: self._finish_test(key, passed, detail),
                timeout_s=10.0,
            )
        elif key in ("rs485", "rs232", "rs422"):
            run_loopback_test(
                port=selected_port,
                label=self.results[key].name,
                callback=lambda passed, detail: self._finish_test(key, passed, detail),
            )
        else:
            if key == "ethernet":
                run_ethernet_test(
                    stm32_port=None,
                    log_cb=lambda msg: append_log(self.log_box, msg),
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
            append_log(self.log_box, "MP flash completed; waiting 9s then re-enumerate USB...")
            QtCore.QTimer.singleShot(9000, finalize_reenum)

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
            meas = row.get("measurement")
            if meas and shiboken6.isValid(meas):
                meas.setText("")
                meas.setStyleSheet(styles["measurement"])
            result = row.get("result")
            if result and shiboken6.isValid(result):
                result.setText("-")
                result.setStyleSheet(styles["result_idle"])

    def _update_power_readings(self, metrics: Dict[str, float]) -> None:
        styles = self._power_styles()
        for key, row in self.power_rows.items():
            cur_val = metrics.get(key)
            meas_widget = row["measurement"]
            result_widget = row["result"]
            if cur_val is None:
                meas_widget.setText("")
                meas_widget.setStyleSheet(styles["measurement"])
                result_widget.setText("-")
                result_widget.setStyleSheet(styles["result_idle"])
                continue
            try:
                meas_widget.setText(str(int(float(cur_val))))
            except Exception:
                meas_widget.setText(str(cur_val))
            try:
                min_v = float(row["lower"].text() or 0)
                max_v = float(row["upper"].text() or 0)
            except ValueError:
                min_v, max_v = 0, 0
            except Exception as exc:
                print(f"[DEBUG] power reading parse error for {key}: {exc}")
                min_v, max_v = 0, 0
            within = not ((min_v and cur_val < min_v) or (max_v and cur_val > max_v))
            if within:
                result_widget.setText("PASS")
                result_widget.setStyleSheet(styles["result_pass"])
                meas_widget.setStyleSheet(styles["measurement"])
            else:
                result_widget.setText("FAIL")
                result_widget.setStyleSheet(styles["result_fail"])
                meas_widget.setStyleSheet(styles["measurement"])

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
                min_v = float(row["lower"].text() or 0)
                max_v = float(row["upper"].text() or 0)
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

    def _current_power_signature(self) -> List[str]:
        """Return a stable signature list representing current power limits."""
        keys = ["vin_mv", "iin_ma", "v3v3_mv", "v5v_mv"]
        sig: List[str] = []
        for key in keys:
            row = self.power_rows.get(key) if hasattr(self, "power_rows") else None
            lower = row.get("lower").text().strip() if row and row.get("lower") else ""
            upper = row.get("upper").text().strip() if row and row.get("upper") else ""
            sig.append(f"{key}:{lower}:{upper}")
        return sig

    def _pick_power_log_path(self, log_dir: Path) -> Path:
        """Choose a power log file path based on current limit signature to avoid mixing limits."""
        sig = self._current_power_signature()
        meta_path = log_dir / "power_log_meta.json"
        meta: Dict[str, List[str]] = {}
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}

        # Reuse existing file if signature matches.
        for fname, stored_sig in meta.items():
            if stored_sig == sig:
                return log_dir / fname

        # Need a new file; decide suffix.
        existing_names = set(meta.keys())
        base_name = "power_log.csv"
        if base_name not in existing_names and not (log_dir / base_name).exists():
            chosen = base_name
        else:
            # find next available index
            idx = 1
            while True:
                candidate = f"power_log_{idx}.csv"
                if candidate not in existing_names and not (log_dir / candidate).exists():
                    chosen = candidate
                    break
                idx += 1

        meta[chosen] = sig
        try:
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass
        return log_dir / chosen

    def _flush_pending_power_log(self, outcome: Optional[str] = None) -> None:
        """Write deferred power log (if any) using the latest outcome/statuses."""
        if not self._pending_power_log:
            return
        try:
            data = self._pending_power_log
            self._save_power_results(
                data.get("metrics", {}) or {},
                data.get("raw_text", "") or "",
                str(data.get("port", "") or ""),
                outcome_override=outcome,
            )
        finally:
            self._pending_power_log = None

    def _save_power_results(
        self, metrics: Dict[str, float], raw_text: str, port: str, outcome_override: Optional[str] = None
    ) -> None:
        """Persist power readings in a structured CSV similar to the reference layout."""
        self._ensure_log_dir()
        log_dir = self._today_log_dir()
        log_path = self._pick_power_log_path(log_dir)
        now = dt.datetime.now()
        ts = self._batch_start_ts or now
        date_str = ts.strftime("%Y/%m/%d %H:%M:%S")

        # Column order based on sample layout
        columns = [
            "Emp",
            "Station",
            "SW_Version",
            "SN",
            "DUT_Pos",
            "FirstFail",
            "TestResult",
            "FW Ver",
            "Input_V",
            "Input_I",
            "VDD3v3",
            "VDD5V",
            "Final",
            "TestTime",
            "TestDate",
            "Port",
            "Raw",
        ]

        # Map columns to metric keys (best-effort; missing metrics stay blank).
        metric_key_map = {
            "Input_V": "vin_mv",
            "Input_I": "iin_ma",
            "VDD3v3": "v3v3_mv",
            "VDD5V": "v5v_mv",
        }

        def _metric_value(col: str) -> str:
            key = metric_key_map.get(col)
            if not key:
                return ""
            val = metrics.get(key)
            if val is None:
                return ""
            try:
                # Cast to int for cleaner CSV like the sample screenshot
                return str(int(round(float(val))))
            except Exception:
                return str(val)

        def _limit_value(col: str, which: str) -> str:
            key = metric_key_map.get(col)
            if not key:
                return ""
            row = self.power_rows.get(key) if hasattr(self, "power_rows") else None
            if not row:
                return ""
            widget = row.get("upper" if which == "upper" else "lower")
            if not widget:
                return ""
            txt = widget.text()
            return txt.strip()

        # Determine first failing item for "FirstFail" column.
        first_fail = ""
        # 1) Prefer the first non-PASS status from the recorded test results.
        for key in ["power", "stlink", "usb", "gpio", "lcd", "rs485", "rs232", "rs422", "ethernet"]:
            res = self.results.get(key)
            status = (res.status or "").upper() if res else "IDLE"
            if status and status not in ("PASS", "IDLE", "RUNNING"):
                first_fail = res.name if res and res.name else key
                break
        # 2) If no test status shows a failure, fall back to power metrics out of range.
        if not first_fail:
            for col, key in metric_key_map.items():
                val = metrics.get(key)
                if val is None:
                    continue
                row = self.power_rows.get(key) if hasattr(self, "power_rows") else None
                if not row:
                    continue
                try:
                    low = float(row.get("lower").text() or 0) if row.get("lower") else 0
                    high = float(row.get("upper").text() or 0) if row.get("upper") else 0
                except Exception:
                    low = high = 0
                if (low and val < low) or (high and val > high):
                    first_fail = self.power_thresholds.get(key, {}).get("label", key)
                    break

        within_limits = self._power_within_limits(metrics)
        computed_outcome = outcome_override or self._current_run_outcome or self._compute_batch_outcome()
        test_result = computed_outcome or ("PASS" if within_limits else "FAIL")

        # Main data row
        row = {
            "Emp": self.employee_no or "",
            "Station": self.app_settings.station if hasattr(self, "app_settings") else "",
            "SW_Version": APP_VERSION,
            "SN": self.current_serial or "",
            "DUT_Pos": 1,
            "FirstFail": first_fail,
            "TestResult": test_result,
            "FW Ver": "V1.0_251027",
            "Input_V": _metric_value("Input_V"),
            "Input_I": _metric_value("Input_I"),
            "VDD3v3": _metric_value("VDD3v3"),
            "VDD5V": _metric_value("VDD5V"),
            "Final": "",
            "TestTime": str(int(round(self._dut_elapsed_seconds))) if getattr(self, "_dut_elapsed_seconds", 0) else "",
            "TestDate": date_str,
            "Port": port,
            "Raw": raw_text.replace("\n", " | "),
        }

        write_header = not log_path.exists()
        try:
            import csv

            with log_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                if write_header:
                    writer.writeheader()
                    # Insert Up/Low limit rows to mirror the example sheet.
                    up_row = {col: "" for col in columns}
                    up_row["Emp"] = "Up Limit"
                    low_row = {col: "" for col in columns}
                    low_row["Emp"] = "Low Limit"
                    for col in columns:
                        if col in metric_key_map:
                            up_row[col] = _limit_value(col, "upper")
                            low_row[col] = _limit_value(col, "lower")
                    writer.writerow(up_row)
                    writer.writerow(low_row)
                writer.writerow(row)
        except Exception:
            pass

    def _start_power_sequence_then_tests(self, port: str) -> None:
        append_log(self.log_box, f"ESP32 power check on {port} (T then S)...")
        print(f"[DEBUG][ESP32] start power sequence on {port}")
        self._reset_power_readings()
        self.power_inflight = True
        if "power" in self.results:
            self.results["power"].status = "RUNNING"
            self.results["power"].detail = "Measuring..."

        def on_timeout() -> None:
            if not self.power_inflight:
                return
            self.results["power"].status = "FAIL"
            self.results["power"].detail = "Timeout"
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
                    if "power" in self.results:
                        self.results["power"].status = "FAIL"
                        self.results["power"].detail = detail
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
                print("[DEBUG] power readings updated, caching power log pending...")
                self._pending_power_log = {"metrics": metrics, "raw_text": text, "port": port}
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
                        "Power readings out of range.",
                    )
                    print("[DEBUG] power readings out of range")
                    if "power" in self.results:
                        self.results["power"].status = "FAIL"
                        self.results["power"].detail = "Out of range"
                    if getattr(self.app_settings, "stop_fail", False):
                        self._abort_batch("Stop on fail: power out of range")
                        return
                else:
                    if "power" in self.results:
                        self.results["power"].status = "PASS"
                        self.results["power"].detail = "Within limits"
                    print("[DEBUG] power readings within limits, scheduling tests...")
                self._update_totals()
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
        if "power" in self.results and self.results["power"].status == "RUNNING":
            self.results["power"].status = "FAIL"
            self.results["power"].detail = reason
        if self._current_run_outcome is None:
            self._current_run_outcome = "FAIL"
            self._run_fail += 1
            self._run_recorded = True
            self._update_totals()
        self._flush_pending_power_log(self._current_run_outcome)
        if self.batch_uses_esp32:
            self._send_esp32_end_signal()
        else:
            self._complete_batch_cleanup()

    def _send_esp32_end_signal(self) -> None:
        port = self.app_settings.esp32_port
        if not port:
            self._complete_batch_cleanup()
            return
        if self._esp32_end_inflight or self._esp32_end_confirmed:
            return
        self._esp32_end_inflight = True
        append_log(self.log_box, f"ESP32 end signal on {port}...")
        print(f"[DEBUG][ESP32] TX end on {port}")

        def on_done(ok: bool, detail: str) -> None:
            append_log(self.log_box, f"ESP32 end result: {detail}")
            if ok and "test end" in (detail or "").lower():
                self._esp32_end_confirmed = True
            else:
                self._esp32_end_confirmed = False
                append_log(self.log_box, "ESP32 end confirmation missing; assuming power may still be on.")
                self._set_summary_status("ERROR")
                self._current_run_outcome = "FAIL"
                self._flashback_fail_reason = self._flashback_fail_reason or "ESP32 power-off confirmation missing."
                self._record_current_dut_result()
            self._esp32_end_inflight = False
            self._complete_batch_cleanup()

        esp32.send_end_signal(port, lambda msg: append_log(self.log_box, msg), on_done)

    def _run_rework_board_info_check(self) -> None:
        # Rework board info check removed per requirement; rely on STLink result only.
        self._rework_check_done = True

    def _reboot_before_stlink_connect(self) -> None:
        ctrl = getattr(self, "usb_controller", None)
        if not ctrl:
            append_log(self.log_box, "[Main] USB controller unavailable; skip Ctrl+D reboot before STLink.")
            return
        try:
            ok = ctrl.send_ctrl_d()
            if ok:
                append_log(self.log_box, "[Main] Issued Ctrl+D reboot before STLink connect (MP mode).")
            else:
                append_log(self.log_box, "[Main] Skip Ctrl+D reboot before STLink (not MP mode or send failed).")
        except Exception as exc:
            append_log(self.log_box, f"[Main] Failed to issue Ctrl+D reboot before STLink: {exc}")

    def _complete_batch_cleanup(self) -> None:
        outcome = self._current_run_outcome or self._compute_batch_outcome()
        log_outcome = (outcome or self.summary_label.text().strip() or "UNKNOWN").upper()
        is_batch = bool(self.batch_inflight or self.batch_uses_esp32 or self._current_batch_tests)
        self._run_rework_board_info_check()
        self._flush_pending_power_log(log_outcome)
        if is_batch and getattr(self.app_settings, "stop_fail", False) and log_outcome == "FAIL" and not self._flashback_done:
            append_log(self.log_box, "[Main] Stop-on-fail enabled; skip flashback sequence.")
            self._flashback_done = True
            self._current_run_outcome = "FAIL"
            self._flashback_fail_reason = self._flashback_fail_reason or "Skipped flashback due to earlier failure (Stop on Fail)."
            # Ensure ESP32 power-off signal sent once; if already confirmed, finalize immediately.
            if not self._esp32_end_confirmed:
                self._send_esp32_end_signal()
                if self._esp32_end_inflight:
                    return
            self._finalize_batch("FAIL", is_batch=is_batch)
            return
        if is_batch and not self._flashback_inflight and not self._flashback_done:
            self._flashback_inflight = True
            self._start_flashback_sequence(log_outcome, is_batch=True)
            return
        self._finalize_batch(log_outcome, is_batch=is_batch)

    def _finalize_batch(self, outcome: str, *, is_batch: bool) -> None:
        outcome = (outcome or "UNKNOWN").upper()
        self._current_run_outcome = outcome
        if is_batch:
            self._record_current_dut_result()
            self._append_end_summary(outcome)
            self._update_power_log_test_time(self._dut_elapsed_seconds, outcome)
        self._save_run_log(outcome)
        self._set_summary_status(outcome)
        self.batch_uses_esp32 = False
        self.power_data_ready = False
        self.test_queue = []
        self.active_test = None
        self.last_finished_test = None
        self.batch_inflight = False
        self._current_batch_tests = []
        self._active_serial_for_run = ""
        self._current_run_outcome = None
        self._run_recorded = False
        self._flashback_inflight = False
        self._flashback_done = False
        self._flashback_fail_reason = ""
        self._pending_end_outcome = None
        self._rework_check_done = False
        self._last_rework_board_info = None
        self._esp32_end_confirmed = False
        self._esp32_end_inflight = False
        can_enable = self.tests_enabled and self.serial_checked
        self._set_interactive_enabled(can_enable)

    def _start_flashback_sequence(self, base_outcome: str, *, is_batch: bool) -> None:
        """After batch tests, flash legacy bootloader via STLink and verify board info."""
        try:
            from stm32_binary_tool import close_active_stm32_handle, get_active_stm32_handle
            handle, port = get_active_stm32_handle()
            if handle and getattr(handle, "is_open", False) and port:
                append_log(self.log_box, f"[STM32] close {port}")
            close_active_stm32_handle()
        except Exception:
            pass
        append_log(self.log_box, "[Main] Starting STLink bootloader flash back sequence...")
        self._flashback_fail_reason = ""
        self._set_summary_status("FLASH BACK")
        self._set_interactive_enabled(False)
        self._reboot_before_stlink_connect()
        elf_path = Path("bin/bootloader_old.elf")

        def launch_stlink() -> None:
            if not elf_path.exists():
                append_log(self.log_box, "[Main] Missing bootloader file: bin/bootloader_old.elf")
                self._finalize_batch("FAIL", is_batch=is_batch)
                return
            try:
                stlink.run_stlink(
                    lambda passed, detail: QtCore.QTimer.singleShot(
                        0, lambda: self._flashback_verify_step(base_outcome, passed, detail, is_batch=is_batch)
                    ),
                    elf_path=elf_path,
                )
            except Exception as exc:  # pragma: no cover - runtime protection
                append_log(self.log_box, f"[Main] STLink flash back launch failed: {exc}")
                self._finalize_batch("FAIL", is_batch=is_batch)

        append_log(self.log_box, "[Main] Delay 100ms then connecting STLink...")
        QtCore.QTimer.singleShot(100, launch_stlink)

    def _flashback_verify_step(self, base_outcome: str, stlink_passed: bool, detail: str, *, is_batch: bool) -> None:
        if detail:
            append_log(self.log_box, detail)
        success = bool(stlink_passed)
        result_text = "[Main] STLink bootloader flash back Successed." if success else "[Main] STLink bootloader flash back Fail."
        append_log(self.log_box, result_text)
        if not success:
            self._flashback_fail_reason = "STLink flash back failed; please rerun the test."
            append_log(self.log_box, f"[Main] TEST FAIL due to STLink flash back error. Please rerun the test.")
        final_outcome = base_outcome if success else "FAIL"
        self._flashback_done = True
        self._flashback_inflight = False
        self._current_run_outcome = final_outcome
        self._send_esp32_end_signal()

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

        if getattr(self.app_settings, "skip_tests", False):
            append_log(self.log_box, "[Main] Skip Test enabled; skipping all tests and calling MES connect stub.")
            try:
                print("MES connect")
            except Exception:
                pass
            self._reset_results()
            try:
                self._reset_power_readings()
            except Exception:
                pass
            self._flashback_inflight = False
            self._flashback_done = False
            self._pending_end_outcome = None
            self._current_run_outcome = None
            self._current_batch_tests = []
            self.test_queue = []
            self._set_summary_status("IDLE")
            return

        order = ["stlink", "usb", "gpio", "rs485", "rs232", "rs422", "lcd", "ethernet"]
        selected = [key for key in order if key in self.test_checks and self.test_checks[key].isChecked()]
        if not selected:
            append_log(self.log_box, "No tests selected.")
            return
        if not self._validate_selected_ports_for_batch(selected):
            return
        esp32_port = getattr(self, "power_port_combo", None).currentData() if hasattr(self, "power_port_combo") else None
        if not esp32_port:
            append_log(self.log_box, "Please select ESP32 COM port before starting tests.")
            self._set_summary_status("IDLE")
            return
        if not self._validate_power_thresholds_ready():
            return
        # Clear log panel before starting a new batch.
        if self.log_box.toPlainText().strip():
            self.log_box.clear()
        # Reset all status labels each time a new batch starts.
        self._current_batch_tests = selected
        self._active_serial_for_run = self.current_serial
        self._current_run_outcome = None
        self._run_recorded = False
        self._flashback_inflight = False
        self._flashback_done = False
        self._pending_end_outcome = None
        self._rework_check_done = False
        self._last_rework_board_info = None
        self._batch_start_ts = dt.datetime.now()
        self._esp32_end_confirmed = False
        self._esp32_end_inflight = False
        self._dut_elapsed_seconds = 0.0
        self.test_time_value.setText("-")
        self._reset_results()
        if len(self.current_serial) > int(getattr(self.app_settings, "sn_len", 10) or 10):
            append_log(
                self.log_box,
                f"S/N length exceeds limit ({self.app_settings.sn_len}); please re-enter.",
            )
            self.serial_checked = False
            self._set_interactive_enabled(False)
            return
        if not self._check_max_fail_limit(self.current_serial):
            return
        # Pre-book this serial as a running entry for totals.
        if self._tested_serial_results.get(self.current_serial) is None:
            self._tested_serial_results[self.current_serial] = "RUNNING"
            self._update_totals()
        self._persist_selected_tests()
        self.app_settings.esp32_port = esp32_port or ""
        self._persist_settings()
        self._run_total += 1
        self._update_totals()
        if "power" not in self.results:
            self.results["power"] = TestResult("Power")
        self.results["power"].status = "RUNNING"
        self.results["power"].detail = "Measuring..."
        self._current_batch_tests = ["power"] + selected
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
        elapsed_seconds = 0.0
        if self._current_test_start:
            elapsed_seconds = (dt.datetime.now() - self._current_test_start).total_seconds()
        self._dut_elapsed_seconds += elapsed_seconds
        if self._dut_elapsed_seconds > 0:
            self.test_time_value.setText(f"{self._dut_elapsed_seconds:.1f}s")
        else:
            self.test_time_value.setText("-")
        self._current_test_start = None
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
        self._update_totals()
        if not self.test_queue and (self.batch_inflight or self.batch_uses_esp32):
            self._record_current_dut_result()

        if not passed and getattr(self.app_settings, "stop_fail", False):
            self.test_queue = []
            if self.batch_uses_esp32 or self.batch_inflight:
                self._abort_batch("Stop on fail (setting enabled)")
            else:
                self._complete_batch_cleanup()
            return

        if self.test_queue:
            QtCore.QTimer.singleShot(0, self._run_next_test_from_queue)
            return
        if self.batch_uses_esp32 or self.batch_inflight:
            if not self._flashback_done and not self._flashback_inflight:
                base_outcome = self._compute_batch_outcome() or self._current_run_outcome or "UNKNOWN"
                self._flashback_inflight = True
                self._start_flashback_sequence(base_outcome, is_batch=True)
                return
            self._send_esp32_end_signal()
            return

        self._complete_batch_cleanup()

    def _apply_theme(self, mode: str) -> None:
        normalized = (mode or "light").lower()
        self.current_theme = normalized
        app = QtWidgets.QApplication.instance()
        if app:
            app.setStyleSheet(theme_stylesheet(normalized))
        apply_global_font(self.ui_scale)
        self._refresh_power_styles()
        if hasattr(self, "app_settings") and self.app_settings.theme != normalized:
            self.app_settings.theme = normalized
            self._persist_settings()

    def _power_styles(self) -> Dict[str, str]:
        """Theme-aware styles for the Excel-like power table."""
        if self.current_theme == "dark":
            return {
                "table": (
                    "QTableWidget {gridline-color: #3c4043;} "
                    "QHeaderView::section {background: #2f333a; color: #e8eaed; padding: 4px; font-weight: 600;} "
                    "QTableWidget {background: #1f232a; alternate-background-color: #242830; color: #e8eaed;}"
                ),
                "cell": "background: #1f232a; color: #e8eaed; border: 1px solid #3c4043;",
                "measurement": "background: #1b1f26; color: #e8eaed; border: 1px solid #3c4043;",
                "result_pass": "background: #1b5e20; color: #d1fae5; font-weight: 700; border-radius: 4px; padding: 2px;",
                "result_fail": "background: #8b1e1e; color: #fee2e2; font-weight: 700; border-radius: 4px; padding: 2px;",
                "result_idle": "background: #2f333a; color: #e5e7eb; border-radius: 4px; padding: 2px;",
            }
        return {
            "table": (
                "QTableWidget {gridline-color: #cfd5e4;} "
                "QHeaderView::section {background: #e7ebf3; color: #1f2937; padding: 4px; font-weight: 600;} "
                "QTableWidget {background: #f7f9fc; alternate-background-color: #eef2fb; color: #1f2937;}"
            ),
            "cell": "background: #ffffff; color: #1f2937; border: 1px solid #cfd5e4;",
            "measurement": "background: #f2f4f8; color: #1f2937; border: 1px solid #cfd5e4;",
            "result_pass": "background: #16a34a; color: white; font-weight: 700; border-radius: 4px; padding: 2px;",
            "result_fail": "background: #dc2626; color: white; font-weight: 700; border-radius: 4px; padding: 2px;",
            "result_idle": "background: #e5e7eb; color: #1f2937; border-radius: 4px; padding: 2px;",
        }

    def _refresh_power_styles(self) -> None:
        """Update power table colors for current theme."""
        if not getattr(self, "power_rows", None):
            return
        styles = self._power_styles()
        if hasattr(self, "power_table"):
            self.power_table.setStyleSheet(styles["table"])
        for row in self.power_rows.values():
            for key in ("expected", "upper", "lower"):
                widget = row.get(key)
                if widget and shiboken6.isValid(widget):
                    widget.setStyleSheet(styles["cell"])
            meas = row.get("measurement")
            if meas and shiboken6.isValid(meas):
                meas.setStyleSheet(styles["measurement"])
            result = row.get("result")
            if result and shiboken6.isValid(result):
                text = result.text().strip().upper()
                if text == "PASS":
                    result.setStyleSheet(styles["result_pass"])
                elif text == "FAIL":
                    result.setStyleSheet(styles["result_fail"])
                else:
                    result.setStyleSheet(styles["result_idle"])

    def _resize_to_base(self, scroll: QtWidgets.QScrollArea) -> None:
        """Set initial window size; cap at 1024x768 and keep window within that bound."""
        base_w, base_h = 1024, 768
        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.availableGeometry() if screen else QtCore.QRect(0, 0, base_w, base_h)
        width = min(base_w, rect.width(), 1024)
        height = min(base_h, rect.height(), 768)
        self.resize(width, height)
        self.setMaximumSize(1024, 768)
        # Allow smaller windows; scroll area will handle overflow.
        self.setMinimumSize(int(base_w * 0.7), int(base_h * 0.7))

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
            self, "Import Settings", "", "Settings Files (*.json);;All Files (*.*)"
        )
        if not path:
            return
        try:
            raw_data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(raw_data, dict):
                raise ValueError("Settings file must be a JSON object.")
            new_settings = load_settings(Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Import Settings", f"Failed to import settings:\n{exc}")
            return

        self._loading_config = True
        try:
            self.app_settings = copy.deepcopy(new_settings)
            self.power_thresholds = copy.deepcopy(self.app_settings.power)
            self._sync_power_table_from_settings()
            self._restore_selected_tests()
            self._populate_ports()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Import Settings", f"Failed to apply settings:\n{exc}")
            return
        finally:
            self._loading_config = False
        self.current_theme = (self.app_settings.theme or "light").lower()
        self._sync_usb_controls_from_settings()
        self._apply_theme(self.app_settings.theme)
        self._update_header_texts()
        self._refresh_power_styles()
        self._persist_settings()
        append_log(self.log_box, f"Imported settings from {path}")

    def _handle_export(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Settings", "settings_export.json", "Settings Files (*.json);;All Files (*.*)"
        )
        if not path:
            return
        try:
            save_settings(self.app_settings, Path(path))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export Settings", f"Failed to export settings:\n{exc}")
            return
        append_log(self.log_box, f"Exported settings to {path}")

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
    app_settings = load_settings()
    initial_theme = (app_settings.theme or "light").lower()
    app.setStyleSheet(theme_stylesheet(initial_theme))
    apply_global_font(max(0.6, compute_scale() * 0.7))
    login_dialog = EmployeeLoginDialog()
    if login_dialog.exec() != QtWidgets.QDialog.Accepted:
        sys.exit(0)
    window = TestFixtureWindow(app_settings, login_dialog.employee_no)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
