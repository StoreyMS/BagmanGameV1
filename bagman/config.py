"""Settings, read from environment variables with safe defaults.

Personal details (name, address, phone) live in profile.json, which is git-ignored.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BAGMAN_DATA_DIR", "data")))
    profile_path: Path = field(default_factory=lambda: Path(os.environ.get("BAGMAN_PROFILE", "profile.json")))
    google_credentials: Path = field(
        default_factory=lambda: Path(os.environ.get("BAGMAN_GOOGLE_CREDENTIALS", "credentials.json"))
    )
    google_token: Path = field(default_factory=lambda: Path(os.environ.get("BAGMAN_GOOGLE_TOKEN", "token.json")))
    # Minimum match score (0-100) before a settlement becomes a claim for you to review.
    match_threshold: int = field(default_factory=lambda: int(os.environ.get("BAGMAN_MATCH_THRESHOLD", "50")))
    # When true, the filer fills forms but never presses submit. Leave on until a form has been checked.
    filer_dry_run: bool = field(default_factory=lambda: _bool("BAGMAN_FILER_DRY_RUN", True))
    browser_path: str | None = field(default_factory=lambda: os.environ.get("BAGMAN_BROWSER_PATH"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bagman.db"

    def load_profile(self) -> dict:
        if not self.profile_path.exists():
            return {}
        return json.loads(self.profile_path.read_text())


def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
