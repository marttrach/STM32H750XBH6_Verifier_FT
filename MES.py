"""
MES (MIS) module
----------------
- Keeps the existing employee login UI (used by main.py).
- Adds MES API scaffolding (check SN status / upload result) aligned with factory docs.
- Includes lightweight test plans and smoke-test helpers to run during "START TEST"
  (especially when Skip Test is enabled to exercise MES/MySQL connectivity only).
"""

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QRegularExpressionValidator

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    requests = None

LOG_DIR = Path("LOG")
LOG_DIR.mkdir(exist_ok=True)


def _build_logger(name: str, filename: str, tag: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_DIR / filename, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] [" + tag + "] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


MIS_LOGGER = _build_logger("MIS", "MES.log", "MIS")


@dataclass
class MesTestResult:
    """Container for MES upload payload."""

    sn: str
    eqp_id: str
    employee_no: str
    start_time: dt.datetime
    end_time: dt.datetime
    duration_s: int
    status: str  # "0" pass, other = fail
    cell: str = "1"
    total_step: str = "1"
    error_code: str = "N/A"
    steps: str = "N/A"
    test_file: Optional[str] = None


class MesClient:
    """HTTP client for MES APIs (GetLMSNStatus / SetIRDetails)."""

    def __init__(
        self,
        base_url: str,
        check_sn_key: str,
        insert_key: str,
        plant_code: str,
        station_id: str,
        timeout_check: float = 5.0,
        timeout_upload: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.check_sn_key = check_sn_key
        self.insert_key = insert_key
        self.plant_code = plant_code
        self.station_id = station_id
        self.timeout_check = timeout_check
        self.timeout_upload = timeout_upload

    def _post_json(self, url: str, payload: Dict[str, Any], timeout: float) -> Tuple[bool, Dict[str, Any], str]:
        if not requests:
            return False, {}, "Python 'requests' not installed"
        try:
            MIS_LOGGER.info("POST %s payload=%s", url, json.dumps(payload))
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            MIS_LOGGER.info("Response %s: %s", response.status_code, data)
            return True, data, ""
        except Exception as exc:  # pragma: no cover - defensive
            MIS_LOGGER.error("MES POST failed: %s", exc)
            return False, {}, str(exc)

    def check_sn_status(self, sn: str) -> Tuple[bool, Dict[str, Any], str]:
        """Call GetLMSNStatus; returns (ok, data, error)."""
        url = f"{self.base_url}/PIEAPI/GetLMSNStatus/"
        payload = {"Key": self.check_sn_key, "PLANT_CODE": self.plant_code, "LOT_NO": sn}
        ok, data, err = self._post_json(url, payload, self.timeout_check)
        if not ok:
            return False, data, err
        status_code = str(data.get("status_code", ""))
        if status_code != "200":
            msg = data.get("message", f"status_code={status_code}")
            MIS_LOGGER.warning("MES check failed: %s", msg)
            return False, data, msg
        sn_status = data.get("SNStatus", [])
        if sn_status:
            ws_code = sn_status[0].get("WS_CODE")
            if ws_code and ws_code != self.station_id:
                msg = f"Station mismatch (expected {self.station_id}, got {ws_code})"
                MIS_LOGGER.warning(msg)
                return False, data, msg
        return True, data, ""

    def upload_result(self, result: MesTestResult) -> Tuple[bool, Dict[str, Any], str]:
        """Call SetIRDetails; returns (ok, data, error)."""
        url = f"{self.base_url}/PIEAPI/SetIRDetails"
        payload = {
            "Key": self.insert_key,
            "TEST_FILE": result.test_file or f"{result.sn}_{result.start_time:%Y%m%d%H%M%S}",
            "SN_NO": result.sn.upper(),
            "EQP_ID": result.eqp_id,
            "START_TIME": result.start_time.strftime("%Y%m%d%H%M%S"),
            "END_TIME": result.end_time.strftime("%Y%m%d%H%M%S"),
            "TEST_TIME": result.duration_s,
            "STATUS": result.status,
            "CELL": result.cell,
            "TOTAL_STEP": result.total_step,
            "ERROR_CODE": result.error_code,
            "TEST_EMP_NO": result.employee_no,
            "STEPS": result.steps,
        }
        ok, data, err = self._post_json(url, payload, self.timeout_upload)
        if not ok:
            return False, data, err
        status_code = str(data.get("status_code", ""))
        if status_code != "200":
            msg = data.get("message", f"status_code={status_code}")
            MIS_LOGGER.warning("MES upload failed: %s", msg)
            return False, data, msg
        return True, data, ""

    @staticmethod
    def test_plan() -> List[str]:
        """High-level MES checklist to run around START TEST."""
        return [
            "Connectivity smoke: POST GetLMSNStatus with known SN; expect status_code=200 and WS_CODE matches station.",
            "Negative key check: use wrong Key -> expect status_code=100.",
            "Upload happy path: SetIRDetails with PASS payload; expect status_code=200.",
            "Upload failure path: SetIRDetails with FAIL status; ensure MES accepts and records failure.",
            "Timeout handling: set low timeout and ensure UI reports [MIS] error when MES unreachable.",
        ]

    def smoke_tests(self, sample_sn: str) -> Dict[str, bool]:
        """Execute basic online checks; safe to call when Skip Test is enabled."""
        results = {}
        ok_check, _, _ = self.check_sn_status(sample_sn)
        results["check_sn_status"] = ok_check
        fake_end = dt.datetime.now()
        fake_start = fake_end - dt.timedelta(seconds=5)
        ok_upload, _, _ = self.upload_result(
            MesTestResult(
                sn=sample_sn,
                eqp_id=self.station_id,
                employee_no="MES_SMOKE",
                start_time=fake_start,
                end_time=fake_end,
                duration_s=5,
                status="0",
                steps="MES_SMOKE",
            )
        )
        results["upload_result"] = ok_upload
        return results


class EmployeeLoginDialog(QtWidgets.QDialog):
    """Small modal dialog for entering an employee number."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, theme: str = "light") -> None:
        super().__init__(parent)
        self.employee_no: str = ""
        self.setWindowTitle("Employee Login")
        self.setModal(True)
        self.setFixedSize(360, 200)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Please Input Employee No")
        title.setAlignment(QtCore.Qt.AlignCenter)
        dark = (theme or "light").lower() == "dark"
        title_color = "#e8eaed" if dark else "#233873"
        title.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {title_color};")

        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("Employee No")
        self.input.setMinimumHeight(34)
        self.input.setClearButtonEnabled(True)
        self.input.setValidator(QRegularExpressionValidator(QtCore.QRegularExpression("[A-Za-z0-9]+")))

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #c93c37; font-weight: 600;")
        self.error_label.setVisible(False)

        confirm_btn = QtWidgets.QPushButton("Confirm")
        confirm_btn.setMinimumHeight(32)
        confirm_btn.clicked.connect(self._accept_if_valid)
        self.input.returnPressed.connect(self._accept_if_valid)

        layout.addWidget(title)
        layout.addSpacing(4)
        layout.addWidget(self.input)
        layout.addWidget(self.error_label)
        layout.addStretch()
        layout.addWidget(confirm_btn, alignment=QtCore.Qt.AlignCenter)

        QtCore.QTimer.singleShot(0, self.input.setFocus)

    def _accept_if_valid(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.error_label.setText("Employee number is required.")
            self.error_label.setVisible(True)
            self.input.setFocus()
            return
        if not QtCore.QRegularExpression("^[A-Za-z0-9]+$").match(text).hasMatch():
            self.error_label.setText("Employee number must be letters/numbers only.")
            self.error_label.setVisible(True)
            self.input.setFocus()
            return
        self.employee_no = text
        self.accept()


class LoginPanel(QtWidgets.QGroupBox):
    """Login/logout UI and state holder (no password required)."""

    def __init__(
        self,
        scale: float,
        on_login: Callable[[str], None],
        on_logout: Callable[[], None],
        initial_user: str = "",
    ) -> None:
        super().__init__("")
        self.on_login = on_login
        self.on_logout = on_logout
        self.logged_in = bool(initial_user)
        self.employee_no = initial_user

        form = QtWidgets.QHBoxLayout(self)
        form.setContentsMargins(10, 8, 10, 8)
        form.setSpacing(int(12 * scale))

        form.addWidget(QtWidgets.QLabel("Employee"))

        self.user_label = QtWidgets.QLabel(self._user_display())
        self.user_label.setStyleSheet("font-weight: 600;")
        form.addWidget(self.user_label)

        self.login_status = QtWidgets.QLabel(self._status_text())
        self.login_status.setStyleSheet(self._status_style())
        form.addWidget(self.login_status)

        form.addStretch()

        self.action_btn = QtWidgets.QPushButton(
            "Logout" if self.logged_in else "Login"
        )
        self.action_btn.setMinimumHeight(int(28 * scale))
        self.action_btn.clicked.connect(self._handle_action)
        form.addWidget(self.action_btn)

    def _status_text(self) -> str:
        return "Logged in" if self.logged_in else "Not logged in"

    def _status_style(self) -> str:
        return (
            "color: #1a7f37; font-weight: bold;"
            if self.logged_in
            else "color: #c93c37; font-weight: bold;"
        )

    def _user_display(self) -> str:
        return self.employee_no or "-"

    def _handle_action(self) -> None:
        if self.logged_in:
            self._handle_logout()
        else:
            self._handle_login()

    def _handle_login(self) -> None:
        dialog = EmployeeLoginDialog(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.employee_no = dialog.employee_no
            self.logged_in = True
            self._update_labels()
            if self.on_login:
                self.on_login(self.employee_no)

    def _handle_logout(self) -> None:
        self.logged_in = False
        self.employee_no = ""
        self._update_labels()
        if self.on_logout:
            self.on_logout()

    def _update_labels(self) -> None:
        self.user_label.setText(self._user_display())
        self.login_status.setText(self._status_text())
        self.login_status.setStyleSheet(self._status_style())
        self.action_btn.setText("Logout" if self.logged_in else "Login")

    def is_logged_in(self) -> bool:
        return self.logged_in

    def current_user(self) -> str:
        return self.employee_no

    def prefill_credentials(self, username: Optional[str]) -> None:
        self.employee_no = username or ""
        self.logged_in = bool(self.employee_no)
        self._update_labels()
