import json
from dataclasses import asdict, dataclass
from pathlib import Path

from global_utility import DEFAULT_PASSWORD, DEFAULT_USERNAME


CONFIG_FILE = Path("user_config.json")


@dataclass
class UserConfig:
    username: str = DEFAULT_USERNAME
    password: str = DEFAULT_PASSWORD
    theme: str = "light"
    usb_variant: str = "ctp"


def load_user_config() -> UserConfig:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return UserConfig(
                    username=data.get("username", DEFAULT_USERNAME),
                    password=data.get("password", DEFAULT_PASSWORD),
                    theme=data.get("theme", "light"),
                    usb_variant=data.get("usb_variant", "ctp"),
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return UserConfig()


def save_user_config(config: UserConfig) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    except OSError:
        # Non-fatal; configuration persistence is best-effort.
        pass
