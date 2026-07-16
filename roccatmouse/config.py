"""Local RoccatMouse configuration with atomic replacement."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AppConfig:
    retention_days: int = 30
    queue_size: int = 10_000
    marker_context_seconds: int = 30
    automatic_startup: bool = False

    def __post_init__(self) -> None:
        if self.retention_days < 1:
            raise ValueError("retention_days must be positive")
        if self.queue_size < 100:
            raise ValueError("queue_size must be at least 100")
        if self.marker_context_seconds < 1:
            raise ValueError("marker_context_seconds must be positive")
        if self.automatic_startup:
            raise ValueError("automatic startup is not supported in this milestone")


def config_path(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    root = values.get("APPDATA")
    if not root:
        raise RuntimeError("APPDATA is unavailable")
    return Path(root) / "RoccatMouse" / "config.json"


def telemetry_path(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    root = values.get("LOCALAPPDATA")
    if not root:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    return Path(root) / "RoccatMouse" / "telemetry.sqlite3"


def load_config(path: Path | None = None) -> AppConfig:
    target = path or config_path()
    if not target.exists():
        return AppConfig()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        allowed = {field for field in AppConfig.__dataclass_fields__}
        return AppConfig(**{key: value for key, value in data.items() if key in allowed})
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        corrupt = target.with_name(f"{target.name}.corrupt-{stamp}")
        try:
            os.replace(target, corrupt)
        except OSError:
            pass
        return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(asdict(config), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target
