import os
from pathlib import Path

from dotenv import load_dotenv

from src.utils.logger import CustomLogger

# Carrega .env aqui (não só no main): settings é lido no import, antes do
# load_dotenv() do main — sem isto, DATABASE_URL viria vazio. interpolate=False
# preserva senhas com '$' (senão o dotenv expande '$VAR' e corrompe a senha).
load_dotenv(interpolate=False)

_log_settings = {
    "app_name": os.getenv("APP_NAME", "APP"),
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    # LOG_DIR existe pros testes: sem ele a suite grava em logs/YYYY/MM junto
    # com os runs de verdade, e erros de fixture (breaker fake, resume
    # inexistente) viram falso incidente na analise dos logs.
    "log_dir": Path(os.getenv("LOG_DIR", "logs")),
}

logger = CustomLogger(_log_settings).get_logger()

# Persistência: vazio => modo JSON local (.local/files). Setado => Postgres.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

base_dir = Path("").resolve()
files_dir = base_dir / ".local" / "files"
files_dir.mkdir(exist_ok=True)

screenshots_path = files_dir / "screenshots"
