"""
Modul config_loader untuk Auto Backup MikroTik Tool.
Load config dari file YAML, substitusi env var, validasi struktur.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml

from src.logger import get_logger

logger = get_logger("config_loader")


class ConfigError(Exception):
    """Error saat load atau validasi config."""


def _resolve_env_vars(value: Any) -> Any:
    """
    Substitusi ${ENV_VAR} dengan nilai dari environment.
    Jika env var tidak ada, gunakan string kosong.

    Args:
        value: Value dari config (bisa str, dict, list, dll.)

    Returns:
        Value dengan env var sudah di-substitusi.
    """
    pattern = re.compile(r"\$\{([^}]+)\}")

    if isinstance(value, str):
        def replacer(match):
            env_name = match.group(1)
            return os.environ.get(env_name, "")

        return pattern.sub(replacer, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


class Config:
    """
    Representasi config yang sudah di-load dan divalidasi.

    Attributes:
        schedule: Dict konfigurasi scheduler.
        devices: List konfigurasi per device MikroTik.
        storage: Dict konfigurasi local storage.
        google_drive: Dict konfigurasi Google Drive.
        logging: Dict konfigurasi logging.
    """

    def __init__(self, raw: dict, base_dir: Path):
        self.base_dir = base_dir
        self.schedule = raw.get("schedule", {})
        self.devices = raw.get("devices", [])
        self.storage = raw.get("storage", {})
        self.google_drive = raw.get("google_drive", {})
        self.logging = raw.get("logging", {})

    def validate(self):
        """Validasi struktur config. Raise ConfigError jika ada masalah."""
        errors = []

        # Validasi schedule
        sched_type = self.schedule.get("type")
        if not sched_type:
            errors.append("'schedule.type' wajib diisi (interval/cron)")
        elif sched_type not in ("interval", "cron"):
            errors.append(
                f"'schedule.type' harus 'interval' atau 'cron', dapat: {sched_type}"
            )

        if sched_type == "interval":
            if not self.schedule.get("minutes") and not self.schedule.get("hours"):
                errors.append(
                    "'schedule.minutes' atau 'schedule.hours' wajib diisi "
                    "untuk type=interval"
                )
        elif sched_type == "cron":
            if not self.schedule.get("cron_expression"):
                errors.append(
                    "'schedule.cron_expression' wajib diisi untuk type=cron"
                )

        # Validasi devices
        if not self.devices:
            errors.append("'devices' wajib diisi minimal 1 device")

        for i, dev in enumerate(self.devices):
            prefix = f"devices[{i}]"
            if not dev.get("name"):
                errors.append(f"{prefix}.name wajib diisi")
            if not dev.get("host"):
                errors.append(f"{prefix}.host wajib diisi")
            if not dev.get("username"):
                errors.append(f"{prefix}.username wajib diisi")
            # Password bisa kosish tapi wajib ada key
            if "password" not in dev:
                errors.append(f"{prefix}.password wajib diisi (boleh kosong)")
            # Validasi backup_types
            backup_types = dev.get("backup_types", ["backup", "rsc"])
            valid_types = {"backup", "rsc"}
            if not set(backup_types).issubset(valid_types):
                errors.append(
                    f"{prefix}.backup_types hanya boleh berisi: {valid_types}"
                )

        # Validasi storage
        local_path = self.storage.get("local_path")
        if not local_path:
            errors.append("'storage.local_path' wajib diisi")

        # Validasi retention
        retention = self.storage.get("retention_days")
        if retention is not None:
            if not isinstance(retention, int) or retention < 0:
                errors.append(
                    "'storage.retention_days' harus integer >= 0"
                )

        # Validasi google_drive
        if self.google_drive.get("enabled", False):
            creds_file = self.google_drive.get("credentials_file")
            if not creds_file:
                errors.append(
                    "'google_drive.credentials_file' wajib diisi jika enabled=true"
                )
            folder_id = self.google_drive.get("folder_id")
            if not folder_id:
                errors.append(
                    "'google_drive.folder_id' wajib diisi jika enabled=true"
                )

        if errors:
            raise ConfigError("Config validation errors:\n  - " + "\n  - ".join(errors))

    def get_device(self, name: str) -> dict | None:
        """Cari device berdasarkan nama."""
        for dev in self.devices:
            if dev["name"] == name:
                return dev
        return None


def load_config(config_path: str) -> Config:
    """
    Load config dari file YAML.

    Args:
        config_path: Path ke config file (relative atau absolute).

    Returns:
        Instance Config yang sudah divalidasi.

    Raises:
        ConfigError: Jika file tidak ada, format salah, atau validasi gagal.
        FileNotFoundError: Jika file config tidak ditemukan.
    """
    path = Path(config_path)
    if not path.is_absolute():
        # Cari relative ke cwd
        path = Path.cwd() / path

    if not path.exists():
        raise FileNotFoundError(f"File config tidak ditemukan: {path}")

    logger.info(f"Loading config dari: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Error parsing YAML: {e}")

    if not isinstance(raw, dict):
        raise ConfigError("Config file harus berisi dictionary di top-level")

    # Substitusi env vars
    raw = _resolve_env_vars(raw)

    base_dir = path.parent
    config = Config(raw, base_dir)
    config.validate()

    logger.info("Config loaded dan divalidasi berhasil")
    return config
