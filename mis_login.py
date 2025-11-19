from typing import Callable

from PySide6 import QtWidgets

from global_utility import DEFAULT_PASSWORD, DEFAULT_USERNAME


class LoginPanel(QtWidgets.QGroupBox):
    """Login/logout UI and state holder."""

    def __init__(
        self,
        scale: float,
        on_login: Callable[[str], None],
        on_logout: Callable[[], None],
    ) -> None:
        super().__init__("登入")
        self.on_login = on_login
        self.on_logout = on_logout
        self.logged_in = False

        form = QtWidgets.QGridLayout(self)
        self.username_edit = QtWidgets.QLineEdit(DEFAULT_USERNAME)
        self.password_edit = QtWidgets.QLineEdit(DEFAULT_PASSWORD)
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.login_btn = QtWidgets.QPushButton("Login")
        self.login_btn.clicked.connect(self._handle_login)
        self.logout_btn = QtWidgets.QPushButton("Logout")
        self.logout_btn.clicked.connect(self._handle_logout)
        self.logout_btn.setEnabled(False)
        self.login_status = QtWidgets.QLabel("未登入")
        self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")

        for w in [
            self.username_edit,
            self.password_edit,
            self.login_btn,
            self.logout_btn,
        ]:
            w.setMinimumHeight(int(28 * scale))

        form.addWidget(QtWidgets.QLabel("使用者"), 0, 0)
        form.addWidget(self.username_edit, 0, 1)
        form.addWidget(QtWidgets.QLabel("密碼"), 1, 0)
        form.addWidget(self.password_edit, 1, 1)
        form.addWidget(self.login_btn, 0, 2, 2, 1)
        form.addWidget(self.logout_btn, 0, 3, 2, 1)
        form.addWidget(self.login_status, 0, 4, 2, 1)

    def _handle_login(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text().strip()
        if username == DEFAULT_USERNAME and password == DEFAULT_PASSWORD:
            self.logged_in = True
            self.login_status.setText("已登入")
            self.login_status.setStyleSheet("color: #1a7f37; font-weight: bold;")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
            self.username_edit.setEnabled(False)
            self.password_edit.setEnabled(False)
            if self.on_login:
                self.on_login(username)
        else:
            self.login_status.setText("未登入")
            self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")

    def _handle_logout(self) -> None:
        self.logged_in = False
        self.login_status.setText("未登入")
        self.login_status.setStyleSheet("color: #c93c37; font-weight: bold;")
        self.login_btn.setEnabled(True)
        self.logout_btn.setEnabled(False)
        self.username_edit.setEnabled(True)
        self.password_edit.setEnabled(True)
        if self.on_logout:
            self.on_logout()

    def is_logged_in(self) -> bool:
        return self.logged_in

    def current_user(self) -> str:
        return self.username_edit.text().strip()
