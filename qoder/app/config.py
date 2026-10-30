from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    powercontext_url: str
    host: str
    port: int
    max_upload_bytes: int = 2 * 1024 * 1024
    max_documents_per_project: int = 200
    sample_dir: Path = BASE_DIR / "samples"
    static_dir: Path = BASE_DIR / "app" / "static"

    @classmethod
    def from_env(cls) -> "Settings":
        default_data = BASE_DIR / "data"
        data_dir = _env_path("RT_DATA_DIR", default_data)
        return cls(
            data_dir=data_dir,
            database_path=_env_path("RT_DATABASE_PATH", data_dir / "researchtrail.sqlite3"),
            powercontext_url=os.environ.get("RT_POWERCONTEXT_URL", "http://127.0.0.1:8765").rstrip("/"),
            host=os.environ.get("RT_HOST", "127.0.0.1"),
            port=int(os.environ.get("RT_PORT", "8000")),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
