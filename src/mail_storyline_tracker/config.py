from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def load_env_files(project_root: Path) -> None:
    """读取本地环境文件；进程环境变量优先，.env 优先于 common.env。"""
    for name in (".env", "common.env"):
        path = project_root / name
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def load_config(project_root: Path, config_file: str | Path = "config.yaml") -> dict[str, Any]:
    load_env_files(project_root)
    _set_cloudstation_root()
    path = Path(config_file)
    if not path.is_absolute():
        path = project_root / path
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml 顶层必须是映射结构")
    return _interpolate(data)


def _set_cloudstation_root() -> None:
    if os.environ.get("CLOUDSTATION_ROOT"):
        return
    system = platform.system().upper()
    name = {"WINDOWS": "CLOUDSTATION_ROOT_WINDOWS", "DARWIN": "CLOUDSTATION_ROOT_MACOS", "LINUX": "CLOUDSTATION_ROOT_LINUX"}.get(system)
    if name and os.environ.get(name):
        os.environ["CLOUDSTATION_ROOT"] = os.environ[name]


def _interpolate(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _interpolate(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item) for item in value]
    if not isinstance(value, str):
        return value
    replaced = ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1)) or (match.group(2) or ""), value)
    stripped = replaced.strip()
    if (stripped.startswith("[") and stripped.endswith("]")) or (stripped.startswith("{") and stripped.endswith("}")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return replaced


@dataclass(frozen=True)
class AppContext:
    project_root: Path
    config: dict[str, Any]

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.project_root / path

    @property
    def data_dir(self) -> Path:
        return self.resolve_path(self.config.get("app", {}).get("data_dir", "./data"))

    @property
    def output_dir(self) -> Path:
        return self.resolve_path(self.config.get("app", {}).get("output_dir", "./output"))


def bootstrap(project_root: Path, config_file: str | Path = "config.yaml") -> AppContext:
    return AppContext(project_root=project_root, config=load_config(project_root, config_file))
