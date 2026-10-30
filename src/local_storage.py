"""
Modul local_storage untuk Auto Backup MikroTik Tool.
Mengelola penyimpanan file backup di lokal dengan struktur direktori
dan retention policy (hapus backup lama berdasarkan jumlah hari).
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from src.logger import get_logger

logger = get_logger("local_storage")


class LocalStorageError(Exception):
    """Error saat operasi local storage."""


class LocalStorage:
    """
    Mengelola file backup di lokal.

    Struktur direktori:
        <local_path>/<device_name>/<YYYY-MM-DD>/<filename>

    Features:
    - Buat direktori per device + per tanggal
    - List file backup
    - Cleanup berdasarkan retention_days
    - Hitung total ukuran backup per device
    """

    def __init__(self, base_path: str, retention_days: int = 30, base_dir: Path = None):
        """
        Inisialisasi local storage.

        Args:
            base_path: Path dasar untuk menyimpan backup (relative ke base_dir atau absolute).
            retention_days: Backup lebih tua dari ini akan dihapus (0 = tidak hapus).
            base_dir: Base directory untuk resolve relative path.
        """
        path = Path(base_path)
        if not path.is_absolute():
            path = (base_dir or Path.cwd()) / path
        self.base_path = path
        self.retention_days = retention_days

        # Pastikan direktori ada
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Local storage initialized: {self.base_path}")

    def get_device_dir(self, device_name: str) -> Path:
        """
        Dapatkan path direktori untuk device tertentu.

        Args:
            device_name: Nama device.

        Returns:
            Path ke direktori device.
        """
        return self.base_path / device_name

    def get_backup_dir(self, device_name: str, date_str: str = None) -> Path:
        """
        Dapatkan path direktori backup untuk device + tanggal.

        Args:
            device_name: Nama device.
            date_str: String tanggal (YYYY-MM-DD). Default: hari ini.

        Returns:
            Path ke direktori backup.
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        device_dir = self.get_device_dir(device_name)
        backup_dir = device_dir / date_str
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def save_file(self, source_path: str | Path, device_name: str, date_str: str = None) -> Path:
        """
        Simpan (copy/move) file backup ke struktur direktori lokal.

        Args:
            source_path: Path file sumber (temporary atau hasil download).
            device_name: Nama device.
            date_str: String tanggal (YYYY-MM-DD). Default: hari ini.

        Returns:
            Path ke file yang sudah disimpan.
        """
        source_path = Path(source_path)
        if not source_path.exists():
            raise LocalStorageError(f"File sumber tidak ditemukan: {source_path}")

        backup_dir = self.get_backup_dir(device_name, date_str)
        dest_path = backup_dir / source_path.name

        # Jika source dan dest sama, skip
        if source_path.resolve() == dest_path.resolve():
            return dest_path

        # Copy file
        shutil.copy2(str(source_path), str(dest_path))
        logger.debug(f"File disimpan: {source_path} -> {dest_path}")
        return dest_path

    def list_backups(self, device_name: str = None) -> list[dict]:
        """
        List semua file backup di local storage.

        Args:
            device_name: Filter per device (optional). Jika None, list semua.

        Returns:
            List dict dengan keys: device, date, filename, path, size, modified
        """
        backups = []

        if device_name:
            device_dirs = [self.get_device_dir(device_name)]
        else:
            device_dirs = [
                d for d in self.base_path.iterdir() if d.is_dir()
            ]

        for device_dir in device_dirs:
            if not device_dir.exists():
                continue

            for date_dir in sorted(device_dir.iterdir()):
                if not date_dir.is_dir():
                    continue

                for file_path in sorted(date_dir.iterdir()):
                    if file_path.is_file():
                        stat = file_path.stat()
                        backups.append({
                            "device": device_dir.name,
                            "date": date_dir.name,
                            "filename": file_path.name,
                            "path": str(file_path),
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime),
                        })

        return backups

    def cleanup_old_backups(self, device_name: str = None) -> int:
        """
        Hapus backup lama berdasarkan retention_days.

        Args:
            device_name: Cleanup untuk device tertentu (optional). Jika None, semua device.

        Returns:
            Jumlah file yang dihapus.
        """
        if self.retention_days <= 0:
            logger.debug("retention_days=0, skip cleanup")
            return 0

        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        deleted_count = 0

        backups = self.list_backups(device_name)
        for backup in backups:
            if backup["modified"] < cutoff_date:
                try:
                    Path(backup["path"]).unlink()
                    deleted_count += 1
                    logger.debug(
                        f"Backup lama dihapus: {backup['path']} "
                        f"(modified: {backup['modified'].strftime('%Y-%m-%d')})"
                    )
                except Exception as e:
                    logger.warning(f"Gagal hapus {backup['path']}: {e}")

        # Bersihkan direktori tanggal yang kosong
        self._cleanup_empty_dirs(device_name)

        if deleted_count > 0:
            logger.info(
                f"Cleanup local: {deleted_count} file dihapus "
                f"(retention={self.retention_days} hari)"
            )

        return deleted_count

    def _cleanup_empty_dirs(self, device_name: str = None):
        """Hapus direktori tanggal yang kosong."""
        if device_name:
            device_dirs = [self.get_device_dir(device_name)]
        else:
            device_dirs = [
                d for d in self.base_path.iterdir() if d.is_dir()
            ]

        for device_dir in device_dirs:
            if not device_dir.exists():
                continue

            for date_dir in list(device_dir.iterdir()):
                if date_dir.is_dir() and not any(date_dir.iterdir()):
                    date_dir.rmdir()
                    logger.debug(f"Direktori kosong dihapus: {date_dir}")

    def get_total_size(self, device_name: str = None) -> int:
        """
        Hitung total ukuran backup di local storage.

        Args:
            device_name: Hitung untuk device tertentu (optional).

        Returns:
            Total ukuran dalam bytes.
        """
        total = 0
        backups = self.list_backups(device_name)
        for backup in backups:
            total += backup["size"]
        return total
