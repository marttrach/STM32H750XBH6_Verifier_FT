from dataclasses import dataclass, field

from setting import SETTINGS_FILE, AppSettings, load_settings, save_settings

CONFIG_FILE = SETTINGS_FILE


@dataclass
class UserConfig:
    theme: str = "light"
    usb_variant: str = "ctp"
    selected_tests: list = field(default_factory=list)
    rs485_port: str = ""
    rs232_port: str = ""
    rs422_port: str = ""
    esp32_port: str = ""


def load_user_config() -> UserConfig:
    settings: AppSettings = load_settings(CONFIG_FILE)
    return UserConfig(
        theme=settings.theme,
        usb_variant=settings.usb_variant,
        selected_tests=getattr(settings, "selected_tests", []),
        rs485_port=getattr(settings, "rs485_port", ""),
        rs232_port=getattr(settings, "rs232_port", ""),
        rs422_port=getattr(settings, "rs422_port", ""),
        esp32_port=getattr(settings, "esp32_port", ""),
    )


def save_user_config(config: UserConfig) -> None:
    settings: AppSettings = load_settings(CONFIG_FILE)
    settings.theme = config.theme or settings.theme
    settings.usb_variant = config.usb_variant or settings.usb_variant
    settings.selected_tests = list(config.selected_tests or [])
    settings.rs485_port = config.rs485_port or ""
    settings.rs232_port = config.rs232_port or ""
    settings.rs422_port = config.rs422_port or ""
    settings.esp32_port = config.esp32_port or ""
    save_settings(settings, CONFIG_FILE)
