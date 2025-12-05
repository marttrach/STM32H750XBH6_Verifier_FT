from typing import Callable, Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QRegularExpressionValidator


class EmployeeLoginDialog(QtWidgets.QDialog):
    """Small modal dialog for entering an employee number."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
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
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #233873;")

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
