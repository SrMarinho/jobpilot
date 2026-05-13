from pathlib import Path
from src.utils.logger import CustomLogger
import src.config.logging as logging

logger = CustomLogger(logging.settings).get_logger()

base_dir = Path("").resolve().resolve()
files_dir = base_dir / ".local" / "files"
files_dir.mkdir(exist_ok=True)

screenshots_path = files_dir / "screenshots"
