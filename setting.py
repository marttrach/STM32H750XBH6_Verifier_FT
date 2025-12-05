import json
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtWidgets, QtGui

SETTINGS_FILE = Path("settings.json")
LEGACY_USER_CONFIG_FILE = Path("user_config.json")

DEFAULT_POWER = {
    "vin_mv": {"label": "VIN_mV", "unit": "mV", "expected": 12000, "upper": 13000, "lower": 11000},
    "iin_ma": {"label": "VIN_mA", "unit": "mA", "expected": 100, "upper": 200, "lower": 30},
    "v3v3_mv": {"label": "3V3_mV", "unit": "mV", "expected": 3300, "upper": 3500, "lower": 3100},
    "v5v_mv": {"label": "5V_mV", "unit": "mV", "expected": 5000, "upper": 5300, "lower": 4700},
}


@dataclass
class MesConfig:
    cc: str = ""
    un: str = ""
    token: str = ""
    prcs: str = ""
    station: str = ""
    project: str = ""
    base_url: str = ""
    check_sn_key: str = ""
    insert_details_key: str = ""
    plant_code: str = ""


@dataclass
class MysqlConfig:
    enable: bool = False
    host: str = ""
    port: int = 3306
    db_name: str = ""
    table_name: str = ""
    user: str = ""
    password: str = ""


@dataclass
class AppSettings:
    station: str = "TEST_7M89"
    fixture_id: str = "TEST_FT_7M89"
    program_name: str = "Toppan 7M89"
    mes_enabled: bool = False
    theme: str = "light"
    stop_fail: bool = False
    skip_tests: bool = False
    sn_len: int = 10
    max_fail: int = 3
    usb_custom: bool = False
    usb_action: str = "mpfw"
    usb_fw_path: str = ""
    usb_variant: str = "ctp"
    usb_verify: bool = False
    selected_tests: List[str] = field(default_factory=list)
    rs485_port: str = ""
    rs232_port: str = ""
    rs422_port: str = ""
    esp32_port: str = ""
    power: Dict[str, Dict[str, Any]] = field(default_factory=lambda: deepcopy(DEFAULT_POWER))
    mes_config: MesConfig = field(default_factory=MesConfig)
    mysql_config: MysqlConfig = field(default_factory=MysqlConfig)


def _load_json(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return {}


def load_settings(path: Path = SETTINGS_FILE) -> AppSettings:
    data = _load_json(path)
    legacy_user = _load_json(LEGACY_USER_CONFIG_FILE) if path == SETTINGS_FILE else {}
    migrated_from_legacy = False

    power = deepcopy(DEFAULT_POWER)
    for key, meta in data.get("power", {}).items():
        if not isinstance(meta, dict):
            continue
        base = power.get(key, {"label": key, "unit": "", "expected": "", "upper": "", "lower": ""})
        for field_name in ("label", "unit", "expected", "upper", "lower"):
            if field_name in meta:
                base[field_name] = meta[field_name]
        power[key] = base

    mes_data = data.get("mes_config", {}) or {}
    mes_config = MesConfig(
        cc=mes_data.get("cc", ""),
        un=mes_data.get("un", ""),
        token=mes_data.get("token", ""),
        prcs=mes_data.get("prcs", ""),
        station=mes_data.get("station", ""),
        project=mes_data.get("project", ""),
        base_url=mes_data.get("base_url", ""),
        check_sn_key=mes_data.get("check_sn_key", ""),
        insert_details_key=mes_data.get("insert_details_key", ""),
        plant_code=mes_data.get("plant_code", ""),
    )

    selected_tests = data.get("selected_tests", [])
    if not selected_tests and legacy_user.get("selected_tests"):
        selected_tests = legacy_user.get("selected_tests", [])
        migrated_from_legacy = True
    if not isinstance(selected_tests, (list, tuple, set)):
        selected_tests = [selected_tests]

    def _pick_port(key: str) -> str:
        val = data.get(key, "") or legacy_user.get(key, "")
        if val:
            nonlocal migrated_from_legacy
            if key not in data and legacy_user.get(key):
                migrated_from_legacy = True
        return str(val or "")

    mysql_data = data.get("mysql_config", {}) or {}
    mysql_config = MysqlConfig(
        enable=bool(mysql_data.get("enable", False)),
        host=str(mysql_data.get("host", "") or ""),
        port=int(mysql_data.get("port", 3306) or 3306),
        db_name=str(mysql_data.get("db_name", "") or ""),
        table_name=str(mysql_data.get("table_name", "") or ""),
        user=str(mysql_data.get("user", "") or ""),
        password=str(mysql_data.get("password", "") or ""),
    )

    settings = AppSettings(
        station=data.get("station", "TEST_7M89"),
        fixture_id=data.get("fixture_id", "TEST_FT_7M89"),
        program_name=data.get("program_name", "Toppan 7M89"),
        mes_enabled=bool(data.get("mes_enabled", False)),
        theme=(data.get("theme", legacy_user.get("theme", "light")) or "light"),
        power=power,
        stop_fail=bool(data.get("stop_fail", False)),
        skip_tests=bool(data.get("skip_tests", False)),
        sn_len=int(data.get("sn_len", 10) or 10),
        max_fail=int(data.get("max_fail", 3) or 3),
        usb_custom=bool(data.get("usb_custom", False)),
        usb_action=str(data.get("usb_action", "mpfw") or "mpfw"),
        usb_fw_path=str(data.get("usb_fw_path", "") or ""),
        usb_variant=str(data.get("usb_variant", legacy_user.get("usb_variant", "ctp")) or "ctp"),
        usb_verify=bool(data.get("usb_verify", False)),
        selected_tests=list(selected_tests),
        rs485_port=_pick_port("rs485_port"),
        rs232_port=_pick_port("rs232_port"),
        rs422_port=_pick_port("rs422_port"),
        esp32_port=_pick_port("esp32_port"),
        mes_config=mes_config,
        mysql_config=mysql_config,
    )

    if path == SETTINGS_FILE and migrated_from_legacy:
        try:
            save_settings(settings, path)
        except Exception:
            # Best-effort; if persisting fails we still return the merged settings.
            pass

    return settings


def save_settings(settings: AppSettings, path: Path = SETTINGS_FILE) -> None:
    payload = {
        "station": settings.station,
        "fixture_id": settings.fixture_id,
        "program_name": settings.program_name,
        "mes_enabled": settings.mes_enabled,
        "theme": settings.theme,
        "stop_fail": settings.stop_fail,
        "skip_tests": settings.skip_tests,
        "sn_len": settings.sn_len,
        "max_fail": settings.max_fail,
        "usb_custom": settings.usb_custom,
        "usb_action": settings.usb_action,
        "usb_fw_path": settings.usb_fw_path,
        "usb_variant": settings.usb_variant,
        "usb_verify": settings.usb_verify,
        "selected_tests": settings.selected_tests,
        "rs485_port": settings.rs485_port,
        "rs232_port": settings.rs232_port,
        "rs422_port": settings.rs422_port,
        "esp32_port": settings.esp32_port,
        "power": settings.power,
        "mes_config": asdict(settings.mes_config),
        "mysql_config": asdict(settings.mysql_config),
    }
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


class SettingDialog(QtWidgets.QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent: Optional[QtWidgets.QWidget] = None,
        reboot_handler: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Setting")
        self.settings = deepcopy(settings)
        self._reboot_handler = reboot_handler
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.station_edit = QtWidgets.QLineEdit(self.settings.station)
        self.fixture_edit = QtWidgets.QLineEdit(self.settings.fixture_id or "TEST_FT_7M89")
        self.skip_test_checkbox = QtWidgets.QCheckBox("Skip all tests (MES/DB connectivity only)")
        self.skip_test_checkbox.setChecked(bool(self.settings.skip_tests))
        self.program_edit = QtWidgets.QLineEdit(self.settings.program_name)
        self.stop_fail_checkbox = QtWidgets.QCheckBox("Stop on Fail")
        self.stop_fail_checkbox.setChecked(bool(self.settings.stop_fail))
        self.sn_len_edit = QtWidgets.QLineEdit(str(self.settings.sn_len))
        self.sn_len_edit.setValidator(QtGui.QIntValidator(1, 99, self))
        self.sn_len_edit.setMaximumWidth(80)
        self.max_fail_edit = QtWidgets.QLineEdit(str(self.settings.max_fail))
        self.max_fail_edit.setValidator(QtGui.QIntValidator(1, 999, self))
        self.max_fail_edit.setMaximumWidth(80)
        # USB options moved here
        self.usb_custom_box = QtWidgets.QCheckBox("Customize USB Flash")
        self.usb_custom_box.setChecked(bool(self.settings.usb_custom))
        self.usb_action_combo = QtWidgets.QComboBox()
        self.usb_action_combo.addItem("MP Firmware", userData="mpfw")
        self.usb_action_combo.addItem("Loader", userData="loader")
        self.usb_action_combo.addItem("CB Firmware", userData="cb")
        self.usb_action_combo.addItem("ADE/Data", userData="ade")
        self.usb_action_combo.addItem("Factory Reset", userData="reset")
        idx = self.usb_action_combo.findData(self.settings.usb_action or "mpfw")
        if idx >= 0:
            self.usb_action_combo.setCurrentIndex(idx)
        self.usb_fw_path_edit = QtWidgets.QLineEdit(self.settings.usb_fw_path or "")
        self.usb_fw_path_edit.setPlaceholderText("Firmware path")
        self.usb_variant_combo = QtWidgets.QComboBox()
        self.usb_variant_combo.addItem("CTP", userData="ctp")
        self.usb_variant_combo.addItem("RTP", userData="rtp")
        idxv = self.usb_variant_combo.findData((self.settings.usb_variant or "ctp").lower())
        if idxv >= 0:
            self.usb_variant_combo.setCurrentIndex(idxv)
        self.usb_verify_box = QtWidgets.QCheckBox("Verify board info")
        self.usb_verify_box.setChecked(bool(self.settings.usb_verify))
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("Light", userData="light")
        self.theme_combo.addItem("Dark", userData="dark")
        idx = self.theme_combo.findData((self.settings.theme or "light").lower())
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        form.addRow("Station", self.station_edit)
        form.addRow("Fixture ID", self.fixture_edit)
        form.addRow("Skip Test", self.skip_test_checkbox)
        form.addRow("Program Name", self.program_edit)
        form.addRow("Stop on Fail", self.stop_fail_checkbox)
        form.addRow("S/N Length Limit", self.sn_len_edit)
        form.addRow("Max Fail per S/N", self.max_fail_edit)
        form.addRow("USB: Customize", self.usb_custom_box)
        form.addRow("USB: Action", self.usb_action_combo)
        form.addRow("USB: Firmware Path", self.usb_fw_path_edit)
        form.addRow("USB: Variant", self.usb_variant_combo)
        form.addRow("USB: Verify", self.usb_verify_box)
        form.addRow("Theme", self.theme_combo)
        layout.addLayout(form)

        self.dut_reboot_btn = QtWidgets.QPushButton("DUT REBOOT")
        self.dut_reboot_btn.clicked.connect(self._handle_dut_reboot)
        layout.addWidget(self.dut_reboot_btn)

        layout.addWidget(QtWidgets.QLabel("Power Limits"))
        self.power_table = QtWidgets.QTableWidget(parent=self)
        headers = ["Item", "Expected", "Up limit", "Low limit", "Unit"]
        self.power_table.setColumnCount(len(headers))
        self.power_table.setHorizontalHeaderLabels(headers)
        self.power_keys: List[str] = list(self.settings.power.keys())
        self.power_table.setRowCount(len(self.power_keys))
        self.power_widgets: Dict[str, Dict[str, QtWidgets.QLineEdit]] = {}
        header = self.power_table.horizontalHeader()
        header.setStretchLastSection(True)
        widths = [120, 90, 90, 90, 70]
        for idx, w in enumerate(widths):
            header.resizeSection(idx, w)
        self.power_table.verticalHeader().setVisible(False)
        self.power_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.power_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)

        for row_idx, key in enumerate(self.power_keys):
            meta = self.settings.power.get(key, {})
            item_item = QtWidgets.QTableWidgetItem(meta.get("label", key))
            self.power_table.setItem(row_idx, 0, item_item)

            validator = QtGui.QDoubleValidator(bottom=-1e9, top=1e9, decimals=3, parent=self)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            exp_edit = QtWidgets.QLineEdit(str(meta.get("expected", "")))
            up_edit = QtWidgets.QLineEdit(str(meta.get("upper", "")))
            low_edit = QtWidgets.QLineEdit(str(meta.get("lower", "")))
            for edit in (exp_edit, up_edit, low_edit):
                edit.setAlignment(QtCore.Qt.AlignCenter)
                edit.setValidator(validator)
            self.power_table.setCellWidget(row_idx, 1, exp_edit)
            self.power_table.setCellWidget(row_idx, 2, up_edit)
            self.power_table.setCellWidget(row_idx, 3, low_edit)

            unit_item = QtWidgets.QTableWidgetItem(meta.get("unit", ""))
            unit_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.power_table.setItem(row_idx, 4, unit_item)

            self.power_widgets[key] = {"expected": exp_edit, "upper": up_edit, "lower": low_edit}

        layout.addWidget(self.power_table)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _float_or_default(self, text: str, default: Any) -> Any:
        try:
            return float(text)
        except (TypeError, ValueError):
            return default

    def _handle_dut_reboot(self) -> None:
        if self._reboot_handler:
            try:
                self._reboot_handler()
            except Exception as exc:  # pragma: no cover - defensive
                QtWidgets.QMessageBox.warning(self, "DUT REBOOT", f"Reboot failed: {exc}")
        else:
            QtWidgets.QMessageBox.information(self, "DUT REBOOT", "Reboot handler unavailable.")

    def _validate_power_entries(self) -> Optional[str]:
        for row_idx, key in enumerate(self.power_keys):
            widgets = self.power_widgets.get(key, {})
            for field in ("expected", "upper", "lower"):
                widget = widgets.get(field, QtWidgets.QLineEdit())
                text = widget.text().strip()
                if text == "":
                    return f"Power item '{key}' field '{field}' cannot be empty."
                try:
                    float(text)
                except Exception:
                    return f"Power item '{key}' field '{field}' must be numeric."
        return None

    def accept(self) -> None:
        error = self._validate_power_entries()
        if error:
            QtWidgets.QMessageBox.warning(self, "Power Limits", error)
            return
        fixture_text = self.fixture_edit.text().strip()
        if not fixture_text:
            QtWidgets.QMessageBox.warning(self, "Fixture ID", "Fixture ID is required.")
            return
        new_power: Dict[str, Dict[str, Any]] = deepcopy(DEFAULT_POWER)
        for row_idx, key in enumerate(self.power_keys):
            widgets = self.power_widgets.get(key, {})
            exp = self._float_or_default(widgets.get("expected", QtWidgets.QLineEdit()).text(), new_power.get(key, {}).get("expected", ""))
            upper = self._float_or_default(widgets.get("upper", QtWidgets.QLineEdit()).text(), new_power.get(key, {}).get("upper", ""))
            lower = self._float_or_default(widgets.get("lower", QtWidgets.QLineEdit()).text(), new_power.get(key, {}).get("lower", ""))
            item_item = self.power_table.item(row_idx, 0)
            unit_item = self.power_table.item(row_idx, 4)
            new_power[key] = {
                "label": item_item.text() if item_item else key,
                "unit": unit_item.text() if unit_item else "",
                "expected": exp,
                "upper": upper,
                "lower": lower,
            }

        self.settings.station = self.station_edit.text().strip() or "N/A"
        self.settings.fixture_id = fixture_text or "TEST_FT_7M89"
        self.settings.program_name = self.program_edit.text().strip() or "N/A"
        self.settings.theme = self.theme_combo.currentData()
        try:
            self.settings.sn_len = int(self.sn_len_edit.text() or 10)
        except ValueError:
            self.settings.sn_len = 10
        try:
            self.settings.max_fail = int(self.max_fail_edit.text() or 3)
        except ValueError:
            self.settings.max_fail = 3
        self.settings.stop_fail = self.stop_fail_checkbox.isChecked()
        self.settings.skip_tests = self.skip_test_checkbox.isChecked()
        self.settings.usb_custom = self.usb_custom_box.isChecked()
        self.settings.usb_action = self.usb_action_combo.currentData()
        self.settings.usb_fw_path = self.usb_fw_path_edit.text().strip()
        self.settings.usb_variant = self.usb_variant_combo.currentData()
        self.settings.usb_verify = self.usb_verify_box.isChecked()
        self.settings.power = new_power
        save_settings(self.settings)
        super().accept()

    def get_settings(self) -> AppSettings:
        return deepcopy(self.settings)
