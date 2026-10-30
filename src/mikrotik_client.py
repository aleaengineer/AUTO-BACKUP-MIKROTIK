"""
Modul mikrotik_client untuk Auto Backup MikroTik Tool.
Handle koneksi ke MikroTik via RouterOS API, create backup (.backup + .rsc),
dan file operations (list, delete, find).

Menggunakan library librouteros (kompatibel dengan RouterOS v6 & v7).
"""

import time
from dataclasses import dataclass

from src.logger import get_logger

logger = get_logger("mikrotik_client")

# Import librouteros
try:
    import librouteros
    from librouteros import exceptions as ros_exceptions
except ImportError:
    librouteros = None
    ros_exceptions = None
    logger.warning(
        "Library librouteros belum terinstall. "
        "Install dengan: pip install librouteros"
    )


class MikrotikConnectionError(Exception):
    """Error koneksi ke MikroTik."""


class MikrotikAPIError(Exception):
    """Error saat eksekusi API command."""


@dataclass
class MikrotikFile:
    """Representasi file di MikroTik."""

    name: str
    size: int
    file_id: str = ""
    creation_time: str = ""


class MikrotikClient:
    """
    Client untuk koneksi dan operasi backup di MikroTik via RouterOS API.

    Menggunakan librouteros (kompatibel RouterOS v6 & v7).

    Usage:
        client = MikrotikClient(host, username, password)
        client.connect()
        client.create_binary_backup("my_backup")
        files = client.list_files()
        client.disconnect()
    """

    # Polling config untuk menunggu file backup tersedia
    FILE_POLL_INTERVAL = 1  # detik
    FILE_POLL_TIMEOUT = 30  # detik

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 8728,
        use_ssl: bool = False,
        ssl_verify: bool = True,
        timeout: int = 15,
    ):
        """
        Inisialisasi MikroTik client.

        Args:
            host: IP atau hostname MikroTik
            username: Username API
            password: Password API
            port: Port API (default 8728, 8729 untuk SSL)
            use_ssl: Gunakan SSL connection
            ssl_verify: Verifikasi SSL certificate
            timeout: Connection timeout dalam detik
        """
        if librouteros is None:
            raise ImportError(
                "librouteros belum terinstall. "
                "Install dengan: pip install librouteros"
            )

        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.use_ssl = use_ssl
        self.ssl_verify = ssl_verify
        self.timeout = timeout
        self._api = None

    def connect(self):
        """Connect ke MikroTik via API."""
        logger.info(f"Connecting ke MikroTik {self.host}:{self.port}...")

        try:
            self._api = librouteros.connect(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
            )
            logger.info(f"Berhasil connect ke MikroTik {self.host}")
        except ros_exceptions.ConnectionError if ros_exceptions else Exception as e:
            raise MikrotikConnectionError(
                f"Gagal connect ke MikroTik {self.host}:{self.port}: {e}"
            )
        except Exception as e:
            raise MikrotikConnectionError(
                f"Gagal connect ke MikroTik {self.host}:{self.port}: {e}"
            )

    def disconnect(self):
        """Disconnect dari MikroTik."""
        if self._api:
            try:
                self._api.close()
                logger.debug(f"Disconnected dari {self.host}")
            except Exception as e:
                logger.warning(f"Error saat disconnect: {e}")
            finally:
                self._api = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def _ensure_connected(self):
        """Pastikan koneksi aktif sebelum eksekusi command."""
        if self._api is None:
            raise MikrotikConnectionError(
                "Belum connect ke MikroTik. Panggil connect() dulu."
            )

    def get_identity(self) -> str:
        """
        Ambil identity (nama) dari MikroTik.

        Returns:
            String identity MikroTik (e.g., "MikroTik").
            Jika gagal, kembalikan "MikroTik".
        """
        self._ensure_connected()
        try:
            result = list(self._api("/system/identity/print"))
            if result:
                return result[0].get("name", "MikroTik")
            return "MikroTik"
        except Exception as e:
            logger.warning(f"Gagal ambil identity: {e}")
            return "MikroTik"

    def create_binary_backup(self, name: str, dont_encrypt: bool = True) -> str:
        """
        Create binary backup file di MikroTik.

        Command: /system backup save name=<name>

        Catatan: Parameter dont-encrypted tidak kompatibel dengan RouterOS v7.
        Backup dibuat tanpa encryption secara default di v7.

        Args:
            name: Nama file backup (tanpa extension)
            dont_encrypt: Parameter kompatibilitas (diabaikan di RouterOS v7)

        Returns:
            Nama file backup yang dibuat (dengan .backup extension)
        """
        self._ensure_connected()

        logger.info(f"Membuat binary backup: {name}.backup")

        try:
            # RouterOS v6: bisa pakai dont-encrypted=True
            # RouterOS v7: parameter dont-encrypted tidak dikenal, backup default tanpa encryption
            # Gunakan hanya name untuk kompatibilitas
            kwargs = {"name": name}

            result = self._api("/system/backup/save", **kwargs)
            # Consume generator
            list(result)
        except Exception as e:
            raise MikrotikAPIError(f"Gagal create binary backup: {e}")

        # Tunggu file muncul di /file
        backup_filename = f"{name}.backup"
        self._wait_for_file(backup_filename)

        logger.info(f"Binary backup berhasil dibuat: {backup_filename}")
        return backup_filename

    def create_export_rsc(self, name: str, compact: bool = True, show_sensitive: bool = True) -> str:
        """
        Create export config (.rsc) di MikroTik.

        Command: /export file=<name> [compact] [show-sensitive]

        Args:
            name: Nama file export (tanpa extension)
            compact: Jika True, export dengan format compact
            show_sensitive: Jika True, tampilkan password/secret di export

        Returns:
            Nama file export yang dibuat (dengan .rsc extension)
        """
        self._ensure_connected()

        logger.info(f"Membuat export config: {name}.rsc")

        try:
            kwargs = {"file": name}
            if compact:
                kwargs["compact"] = True
            if show_sensitive:
                kwargs["show-sensitive"] = True

            # librouteros: /export file=name compact show-sensitive
            result = self._api("/export", **kwargs)
            # Consume generator
            list(result)
        except Exception as e:
            raise MikrotikAPIError(f"Gagal create export rsc: {e}")

        # Tunggu file muncul di /file
        rsc_filename = f"{name}.rsc"
        self._wait_for_file(rsc_filename)

        logger.info(f"Export config berhasil dibuat: {rsc_filename}")
        return rsc_filename

    def list_files(self) -> list[MikrotikFile]:
        """
        List semua file di MikroTik.

        Returns:
            List of MikrotikFile objects.
        """
        self._ensure_connected()

        try:
            result = self._api("/file/print")
            items = list(result)
        except Exception as e:
            raise MikrotikAPIError(f"Gagal list files: {e}")

        files = []
        for item in items:
            name = item.get("name", "")
            size_str = item.get("size", "0")
            # Size bisa dalam format "1.2KiB" - parse ke bytes approximate
            size = self._parse_size(size_str)
            creation_time = item.get("creation-time", "")
            file_id = item.get(".id", item.get("id", ""))

            files.append(
                MikrotikFile(
                    name=name,
                    size=size,
                    file_id=file_id,
                    creation_time=creation_time,
                )
            )

        return files

    def find_file(self, filename: str) -> MikrotikFile | None:
        """
        Cari file berdasarkan nama di MikroTik.

        Args:
            filename: Nama file yang dicari.

        Returns:
            MikrotikFile jika ditemukan, None jika tidak.
        """
        files = self.list_files()
        for f in files:
            if f.name == filename:
                return f
        return None

    def delete_file(self, filename: str):
        """
        Hapus file dari MikroTik.

        Args:
            filename: Nama file yang akan dihapus.
        """
        self._ensure_connected()

        logger.debug(f"Menghapus file dari MikroTik: {filename}")

        try:
            # Cari file ID
            file_obj = self.find_file(filename)
            if file_obj is None:
                logger.warning(f"File tidak ditemukan untuk dihapus: {filename}")
                return

            if not file_obj.file_id:
                # Fallback: list ulang untuk cari ID
                files = self.list_files()
                for f in files:
                    if f.name == filename:
                        file_obj = f
                        break

            if file_obj.file_id:
                self._api("/file/remove", **{".id": file_obj.file_id})
                logger.info(f"File dihapus dari MikroTik: {filename}")
            else:
                logger.warning(f"Tidak bisa menemukan ID file: {filename}")
        except Exception as e:
            raise MikrotikAPIError(f"Gagal hapus file {filename}: {e}")

    def _wait_for_file(self, filename: str, timeout: int = None):
        """
        Tunggu sampai file muncul di /file list.

        Args:
            filename: Nama file yang ditunggu.
            timeout: Timeout dalam detik (default: FILE_POLL_TIMEOUT)
        """
        if timeout is None:
            timeout = self.FILE_POLL_TIMEOUT

        logger.debug(f"Menunggu file {filename} muncul (timeout={timeout}s)...")

        elapsed = 0
        while elapsed < timeout:
            file_obj = self.find_file(filename)
            if file_obj is not None:
                logger.debug(f"File ditemukan: {filename} (size={file_obj.size} bytes)")
                return
            time.sleep(self.FILE_POLL_INTERVAL)
            elapsed += self.FILE_POLL_INTERVAL

        raise MikrotikAPIError(
            f"Timeout menunggu file {filename} muncul di MikroTik "
            f"setelah {timeout} detik"
        )

    @staticmethod
    def _parse_size(size_str) -> int:
        """
        Parse size string dari MikroTik ke bytes.

        MikroTik format: "1.2KiB", "500B", "3.4MiB"
        """
        if not size_str or size_str == "0":
            return 0

        size_str = str(size_str).strip()
        multipliers = {
            "B": 1,
            "KiB": 1024,
            "MiB": 1024**2,
            "GiB": 1024**3,
            "KB": 1000,
            "MB": 1000**2,
            "GB": 1000**3,
            "K": 1024,
            "M": 1024**2,
            "G": 1024**3,
        }

        # Coba parse dengan suffix
        for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
            if size_str.endswith(suffix):
                try:
                    num = float(size_str[: -len(suffix)])
                    return int(num * mult)
                except ValueError:
                    continue

        # Fallback: coba parse sebagai int langsung
        try:
            return int(size_str)
        except ValueError:
            return 0
