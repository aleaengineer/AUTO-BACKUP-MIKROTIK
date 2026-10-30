"""
Modul logger untuk Auto Backup MikroTik Tool.
Mendukung logging ke file (dengan rotasi) dan console.
Cross-platform Windows/Linux.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


class Logger:
    """Logger terpusat untuk seluruh modul aplikasi."""

    _instance = None
    _configured = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._configured:
            self._configure_default()

    def _configure_default(self):
        """Konfigurasi default logger sebelum config_loader di-load."""
        self.logger = logging.getLogger("mikrotik_backup")
        self.logger.setLevel(logging.DEBUG)
        # Clear existing handlers
        self.logger.handlers.clear()
        # Console handler only
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console.setFormatter(formatter)
        self.logger.addHandler(console)
        Logger._configured = True

    def configure(self, log_config: dict, base_dir: Path):
        """
        Konfigurasi ulang logger berdasarkan config file.

        Args:
            log_config: Dictionary dengan keys:
                level: "DEBUG"|"INFO"|"WARNING"|"ERROR" (default: INFO)
                file: path ke file log (optional, relative ke base_dir)
                max_size: ukuran max file log dalam MB (default: 5)
                backup_count: jumlah file rotasi (default: 3)
                console: bool, log ke console (default: True)
            base_dir: Path dasar untuk resolve relative path
        """
        self.logger.handlers.clear()

        level_str = log_config.get("level", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)
        self.logger.setLevel(level)

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler
        if log_config.get("console", True):
            console = logging.StreamHandler()
            console.setLevel(level)
            console.setFormatter(formatter)
            self.logger.addHandler(console)

        # File handler dengan rotasi
        log_file = log_config.get("file")
        if log_file:
            log_path = Path(log_file)
            if not log_path.is_absolute():
                log_path = base_dir / log_path
            # Pastikan direktori ada
            log_path.parent.mkdir(parents=True, exist_ok=True)

            max_bytes = int(log_config.get("max_size", 5)) * 1024 * 1024
            backup_count = int(log_config.get("backup_count", 3))

            file_handler = RotatingFileHandler(
                str(log_path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        Logger._configured = True

    def get_logger(self, name: str = None) -> logging.Logger:
        """Ambil logger child dengan nama modul."""
        if name:
            return self.logger.getChild(name)
        return self.logger


# Singleton instance
logger_instance = Logger()


def get_logger(name: str = None) -> logging.Logger:
    """Fungsi utilitas untuk ambil logger."""
    return logger_instance.get_logger(name)
