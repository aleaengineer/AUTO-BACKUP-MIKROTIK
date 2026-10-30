"""
Modul backup_manager untuk Auto Backup MikroTik Tool.
Orchestrator yang mengkoordinasi seluruh proses backup per device:
1. Connect ke MikroTik via API
2. Buat backup (.backup) dan export (.rsc)
3. Download file via FTP
4. Simpan ke local storage
5. Upload ke Google Drive (jika enabled)
6. Cleanup file di router + local + Google Drive (retention policy)
"""

from datetime import datetime
from pathlib import Path

from src.logger import get_logger
from src.mikrotik_client import MikrotikClient, MikrotikConnectionError, MikrotikAPIError
from src.ftp_downloader import FTPDownloader, FTPDownloaderError
from src.local_storage import LocalStorage, LocalStorageError

logger = get_logger("backup_manager")


class BackupManagerError(Exception):
    """Error saat proses backup."""


class BackupManager:
    """
    Orchestrator untuk proses backup MikroTik.

    Mengkoordinasi: MikrotikClient (API), FTPDownloader (FTP),
    LocalStorage (local), GoogleDriveUploader (cloud).
    """

    def __init__(self, config):
        """
        Inisialisasi BackupManager.

        Args:
            config: Instance Config dari config_loader.
        """
        self.config = config
        self.local_storage = LocalStorage(
            base_path=config.storage.get("local_path", "./backups"),
            retention_days=config.storage.get("retention_days", 30),
            base_dir=config.base_dir,
        )
        self.gdrive_uploader = None
        if config.google_drive.get("enabled", False):
            try:
                from src.google_drive_uploader import GoogleDriveUploader
                self.gdrive_uploader = GoogleDriveUploader(
                    credentials_file=config.google_drive.get("credentials_file"),
                    token_file=config.google_drive.get("token_file", "token.json"),
                    folder_id=config.google_drive.get("folder_id", ""),
                    base_dir=config.base_dir,
                )
            except ImportError:
                logger.warning(
                    "Google Drive dependencies belum terinstall. "
                    "Upload ke Google Drive akan di-skip."
                )
                self.gdrive_uploader = None

    def backup_device(self, device_config: dict) -> bool:
        """
        Jalankan proses backup lengkap untuk satu device.

        Flow:
        1. Connect MikroTik API
        2. Buat backup files di router
        3. Connect FTP
        4. Download backup files
        5. Simpan ke local storage
        6. Upload ke Google Drive (jika enabled)
        7. Cleanup file di router
        8. Apply retention policy (local + Google Drive)

        Args:
            device_config: Dict konfigurasi device (dari config.yaml).

        Returns:
            True jika backup berhasil, False jika ada error.
        """
        name = device_config.get("name", "unknown")
        host = device_config.get("host")
        username = device_config.get("username")
        password = device_config.get("password", "")
        api_port = device_config.get("api_port", 8728)
        ftp_port = device_config.get("ftp_port", 21)
        use_ssl = device_config.get("use_ssl", False)
        ssl_verify = device_config.get("ssl_verify", True)
        backup_types = device_config.get("backup_types", ["backup", "rsc"])
        cleanup_router = device_config.get("cleanup_router", True)
        retention_days = self.config.storage.get("retention_days", 30)
        gdrive_retention = self.config.google_drive.get("retention_days", retention_days)

        # Timestamp untuk nama backup
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        logger.info(f"{'='*60}")
        logger.info(f"Memulai backup device: {name} ({host})")
        logger.info(f"{'='*60}")

        # Objects untuk cleanup
        mikrotik = None
        ftp = None
        router_files_created = []
        downloaded_files = []
        success = False

        try:
            # Step 1: Connect ke MikroTik API
            logger.info(f"[1/7] Connect ke MikroTik API {host}:{api_port}")
            mikrotik = MikrotikClient(
                host=host,
                username=username,
                password=password,
                port=api_port,
                use_ssl=use_ssl,
                ssl_verify=ssl_verify,
            )
            mikrotik.connect()

            # Ambil identity MikroTik untuk nama file backup
            identity = mikrotik.get_identity()
            # Sanitize identity: ganti karakter yang tidak valid untuk filename
            safe_identity = identity.replace(" ", "_").replace("/", "-").replace("\\", "-")
            timestamp = now.strftime("%d-%m-%Y_%H-%M-%S")
            backup_name = f"{safe_identity}_Backup_{timestamp}"

            logger.info(f"Router identity: {identity}")
            logger.info(f"Backup name: {backup_name}")

            # Step 2: Buat backup files di router
            logger.info(f"[2/7] Membuat backup files di router")
            if "backup" in backup_types:
                backup_filename = mikrotik.create_binary_backup(backup_name)
                router_files_created.append(backup_filename)

            if "rsc" in backup_types:
                rsc_filename = mikrotik.create_export_rsc(backup_name)
                router_files_created.append(rsc_filename)

            logger.info(f"Backup files dibuat di router: {router_files_created}")

            # Step 3: Connect FTP & download
            logger.info(f"[3/7] Connect FTP & download files")
            ftp = FTPDownloader(
                host=host,
                username=username,
                password=password,
                port=ftp_port,
            )
            ftp.connect()

            # Download ke temp dir dulu
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "mikrotik_backup_tmp"
            temp_dir.mkdir(parents=True, exist_ok=True)

            downloaded_paths = []
            for filename in router_files_created:
                local_temp = temp_dir / filename
                try:
                    path = ftp.download_file(filename, str(local_temp))
                    downloaded_paths.append(path)
                except FTPDownloaderError as e:
                    logger.error(f"Gagal download {filename}: {e}")

            if not downloaded_paths:
                raise BackupManagerError("Tidak ada file yang berhasil didownload")

            # Step 4: Simpan ke local storage
            logger.info(f"[4/7] Simpan ke local storage")
            for path in downloaded_paths:
                try:
                    saved = self.local_storage.save_file(
                        source_path=path,
                        device_name=name,
                        date_str=date_str,
                    )
                    downloaded_files.append(saved)
                    logger.info(f"Saved locally: {saved}")
                except LocalStorageError as e:
                    logger.error(f"Gagal simpan {path}: {e}")

            # Step 5: Upload ke Google Drive (jika enabled)
            if self.gdrive_uploader is not None:
                logger.info(f"[5/7] Upload ke Google Drive")
                try:
                    # Authenticate jika belum
                    self.gdrive_uploader.authenticate()

                    for path in downloaded_files:
                        try:
                            self.gdrive_uploader.upload_file(
                                local_path=path,
                                device_name=name,
                                subfolder=date_str,
                            )
                        except Exception as e:
                            logger.error(f"Gagal upload {path.name} ke Google Drive: {e}")
                except Exception as e:
                    logger.error(f"Google Drive authentication gagal: {e}")
            else:
                logger.info(f"[5/7] Google Drive tidak dienabled, skip upload")

            # Step 6: Cleanup file di router
            if cleanup_router:
                logger.info(f"[6/7] Cleanup file di router")
                for filename in router_files_created:
                    try:
                        mikrotik.delete_file(filename)
                    except MikrotikAPIError as e:
                        logger.warning(f"Gagal hapus {filename} dari router: {e}")

            # Step 7: Apply retention policy
            logger.info(f"[7/7] Apply retention policy")
            try:
                self.local_storage.cleanup_old_backups(name)
            except Exception as e:
                logger.warning(f"Cleanup local storage gagal: {e}")

            if self.gdrive_uploader is not None:
                try:
                    self.gdrive_uploader.cleanup_old_files(name, gdrive_retention)
                except Exception as e:
                    logger.warning(f"Cleanup Google Drive gagal: {e}")

            success = True
            logger.info(f"Backup {name} ({host}) berhasil!")

        except MikrotikConnectionError as e:
            logger.error(f"Gagal connect ke MikroTik: {e}")
        except MikrotikAPIError as e:
            logger.error(f"Error MikroTik API: {e}")
        except FTPDownloaderError as e:
            logger.error(f"Error FTP: {e}")
        except BackupManagerError as e:
            logger.error(f"Error backup: {e}")
        except Exception as e:
            logger.error(f"Error tidak terduga: {e}", exc_info=True)
        finally:
            # Cleanup: disconnect
            if mikrotik:
                mikrotik.disconnect()
            if ftp:
                ftp.disconnect()

            # Cleanup temp files
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "mikrotik_backup_tmp"
            if temp_dir.exists():
                for f in temp_dir.iterdir():
                    try:
                        f.unlink()
                    except Exception:
                        pass

        return success

    def backup_all_devices(self) -> dict[str, bool]:
        """
        Jalankan backup untuk semua device di config.

        Returns:
            Dict mapping device name -> success status.
        """
        results = {}
        for device in self.config.devices:
            name = device.get("name", "unknown")
            results[name] = self.backup_device(device)
        return results

    def backup_device_by_name(self, device_name: str) -> bool | None:
        """
        Backup device tertentu berdasarkan nama.

        Args:
            device_name: Nama device yang akan di-backup.

        Returns:
            True jika berhasil, False jika gagal, None jika device tidak ditemukan.
        """
        device = self.config.get_device(device_name)
        if device is None:
            logger.error(f"Device tidak ditemukan: {device_name}")
            return None
        return self.backup_device(device)
