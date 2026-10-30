"""
Modul ftp_downloader untuk Auto Backup MikroTik Tool.
Download file backup dari MikroTik via FTP (port 21).
MikroTik memiliki FTP server built-in yang bisa dipakai untuk transfer file.
"""

import os
from pathlib import Path

from src.logger import get_logger

logger = get_logger("ftp_downloader")

# ftplib adalah library built-in Python (tidak perlu install)
from ftplib import FTP, error_perm, error_temp, error_reply


class FTPDownloaderError(Exception):
    """Error saat download via FTP."""


class FTPDownloader:
    """
    Download file dari MikroTik via FTP.

    MikroTik memiliki FTP server built-in yang bisa di-enable
    di /ip service. Pastikan ftp service aktif.

    Usage:
        downloader = FTPDownloader(host, username, password)
        downloader.connect()
        downloader.download_file("backup.backup", "/local/path/backup.backup")
        downloader.disconnect()
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 21,
        timeout: int = 30,
    ):
        """
        Inisialisasi FTP downloader.

        Args:
            host: IP atau hostname MikroTik
            username: Username FTP (sama dengan username API)
            password: Password FTP (sama dengan password API)
            port: Port FTP (default 21)
            timeout: Connection timeout dalam detik
        """
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self._ftp = None

    def connect(self):
        """Connect ke MikroTik FTP server."""
        logger.info(f"Connecting FTP ke {self.host}:{self.port}...")

        try:
            self._ftp = FTP()
            self._ftp.connect(self.host, self.port, timeout=self.timeout)
            self._ftp.login(self.username, self.password)
            # Set binary mode (TYPE I) — penting untuk transfer file backup
            # MikroTik FTP server memerlukan binary mode untuk command SIZE
            self._ftp.sendcmd("TYPE I")
            logger.info(f"FTP connected ke {self.host}")
        except error_reply as e:
            raise FTPDownloaderError(f"FTP reply error: {e}")
        except error_temp as e:
            raise FTPDownloaderError(f"FTP temporary error: {e}")
        except error_perm as e:
            raise FTPDownloaderError(f"FTP permission denied: {e}")
        except Exception as e:
            raise FTPDownloaderError(f"Gagal connect FTP ke {self.host}:{self.port}: {e}")

    def disconnect(self):
        """Disconnect dari FTP server."""
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                try:
                    self._ftp.close()
                except Exception:
                    pass
            self._ftp = None
            logger.debug(f"FTP disconnected dari {self.host}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def download_file(self, remote_filename: str, local_path: str) -> Path:
        """
        Download file dari MikroTik ke local.

        Args:
            remote_filename: Nama file di MikroTik (di root /file)
            local_path: Path lokal tujuan (file path, bukan direktori)

        Returns:
            Path ke file lokal yang sudah didownload.

        Raises:
            FTPDownloaderError: Jika download gagal.
        """
        if self._ftp is None:
            raise FTPDownloaderError("FTP belum connect. Panggil connect() dulu.")

        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading {remote_filename} -> {local_path}")

        try:
            # Cek ukuran file remote (optional, MikroTik mungkin tidak support SIZE)
            remote_size = None
            try:
                remote_size = self._ftp.size(remote_filename)
                logger.debug(f"Remote file size: {remote_size} bytes")
            except Exception as size_err:
                logger.debug(f"SIZE command tidak didukung: {size_err}")

            # Download ke temporary file dulu, lalu rename
            temp_path = local_path.with_suffix(local_path.suffix + ".tmp")

            with open(temp_path, "wb") as f:
                # callback untuk write data
                def callback(data):
                    f.write(data)

                self._ftp.retrbinary(f"RETR {remote_filename}", callback)

            # Rename temp file ke final name
            temp_path.rename(local_path)

            # Verifikasi ukuran jika SIZE command didukung
            local_size = local_path.stat().st_size
            if remote_size is not None and local_size != remote_size:
                logger.warning(
                    f"Ukuran file tidak match! Remote={remote_size}, Local={local_size}"
                )
            else:
                logger.info(
                    f"Download berhasil: {remote_filename} -> {local_path} "
                    f"({local_size} bytes)"
                )

            return local_path

        except error_perm as e:
            raise FTPDownloaderError(
                f"Permission denied saat download {remote_filename}: {e}"
            )
        except FileNotFoundError as e:
            raise FTPDownloaderError(f"File remote tidak ditemukan: {remote_filename}")
        except Exception as e:
            # Cleanup temp file jika ada
            temp_path = Path(str(local_path) + ".tmp")
            if temp_path.exists():
                temp_path.unlink()
            raise FTPDownloaderError(f"Gagal download {remote_filename}: {e}")

    def download_files(self, file_list: list[tuple[str, str]]) -> list[Path]:
        """
        Download multiple files sekaligus.

        Args:
            file_list: List tuple (remote_filename, local_path)

        Returns:
            List path file lokal yang berhasil didownload.
        """
        downloaded = []
        for remote_filename, local_path in file_list:
            try:
                path = self.download_file(remote_filename, local_path)
                downloaded.append(path)
            except FTPDownloaderError as e:
                logger.error(f"Gagal download {remote_filename}: {e}")
                # Continue ke file berikutnya
        return downloaded

    def list_remote_files(self) -> list[str]:
        """
        List file di FTP server (root directory).

        Returns:
            List nama file di MikroTik.
        """
        if self._ftp is None:
            raise FTPDownloaderError("FTP belum connect. Panggil connect() dulu.")

        try:
            files = self._ftp.nlst()
            return files
        except Exception as e:
            raise FTPDownloaderError(f"Gagal list files: {e}")

    def delete_remote_file(self, filename: str):
        """
        Hapus file di FTP server.

        Args:
            filename: Nama file yang akan dihapus.
        """
        if self._ftp is None:
            raise FTPDownloaderError("FTP belum connect. Panggil connect() dulu.")

        try:
            self._ftp.delete(filename)
            logger.info(f"File dihapus dari FTP: {filename}")
        except error_perm as e:
            logger.warning(f"Tidak bisa hapus {filename} via FTP: {e}")
        except Exception as e:
            logger.warning(f"Error hapus {filename} via FTP: {e}")
