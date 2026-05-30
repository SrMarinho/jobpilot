import os
from pathlib import Path

from src.utils.logger import CustomLogger

_log_settings = {
    "app_name": os.getenv("APP_NAME", "APP"),
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "log_dir": Path("logs"),
}

logger = CustomLogger(_log_settings).get_logger()

base_dir = Path("").resolve()
files_dir = base_dir / ".local" / "files"
files_dir.mkdir(exist_ok=True)

screenshots_path = files_dir / "screenshots"
