from typing import Callable

from PySide6 import QtWidgets

from global_utility import DEFAULT_PASSWORD, DEFAULT_USERNAME


class LoginPanel(QtWidgets.QGroupBox):
    """Login/logout UI and state holder."""

    def __init__(
        self,
        scale: float,
        on_login: Callable[[str, str], None],
        on_logout: Callable[[], None],
    ) -> None:
        super().__init__("")
        self.on_login = on_login
        self.on_logout = on_logout
        self.logged_in = False

        form = QtWidgets.QGridLayout(self)
        self.username_edit = QtWidgets.QLineEdit(DEFAULT_USERNAME)
        self.password_edit = QtWidgets.QLineEdit(DEFAULT_PASSWORD)
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.action_btn = QtWidgets.QPushButton("Login")
        self.action_btn.clicked.connect(self._handle_action)
        self.password_edit.returnPressed.connect(self._handle_action)
        self.login_status = QtWidgets.QLabel("Not logged in")
        self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")

        for w in [
            self.username_edit,
            self.password_edit,
            self.action_btn,
        ]:
            w.setMinimumHeight(int(28 * scale))

        form.addWidget(QtWidgets.QLabel("Username"), 0, 0)
        form.addWidget(self.username_edit, 0, 1)
        form.addWidget(QtWidgets.QLabel("Password"), 1, 0)
        form.addWidget(self.password_edit, 1, 1)
        form.addWidget(self.action_btn, 0, 2, 2, 1)
        form.addWidget(self.login_status, 0, 3, 2, 1)

    def _handle_action(self) -> None:
        if self.logged_in:
            self._handle_logout()
        else:
            self._handle_login()

    def _handle_login(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()
        if username == DEFAULT_USERNAME and password == DEFAULT_PASSWORD:
            self.logged_in = True
            self.login_status.setText("Logged in")
            self.login_status.setStyleSheet("color: #1a7f37; font-weight: bold;")
            self.username_edit.setEnabled(False)
            self.password_edit.setEnabled(False)
            self.action_btn.setText("Logout")
            if self.on_login:
                self.on_login(username, password)
        else:
            self.login_status.setText("Not logged in")
            self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")

    def _handle_logout(self) -> None:
        self.logged_in = False
        self.login_status.setText("Not logged in")
        self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")
        self.username_edit.setEnabled(True)
        self.password_edit.setEnabled(True)
        self.action_btn.setText("Login")
        if self.on_logout:
            self.on_logout()

    def is_logged_in(self) -> bool:
        return self.logged_in

    def current_user(self) -> str:
        return self.username_edit.text().strip()

    def current_password(self) -> str:
        return self.password_edit.text().strip()

    def prefill_credentials(self, username: setattr) -> None:
        if username:
            self.username_edit.setText(username)
