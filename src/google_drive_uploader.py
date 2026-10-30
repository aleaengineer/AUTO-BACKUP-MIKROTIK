"""
Modul google_drive_uploader untuk Auto Backup MikroTik Tool.
Upload file backup ke Google Drive via Google Drive API v3.
Menggunakan OAuth2 untuk autentikasi.

Setup:
1. Buat project di Google Cloud Console
2. Enable Google Drive API
3. Buat OAuth2 credentials (Desktop app)
4. Download credentials.json
5. Letakkan di folder project
6. Run tool pertama kali untuk authorize (browser akan terbuka)
7. Token akan disimpan di token.json untuk run berikutnya
"""

import os
from datetime import datetime
from pathlib import Path

from src.logger import get_logger

logger = get_logger("google_drive")


class GoogleDriveError(Exception):
    """Error saat upload ke Google Drive."""


class GoogleDriveUploader:
    """
    Upload file backup ke Google Drive via API v3.

    Features:
    - OAuth2 authentication (first run: browser, subsequent: token cache)
    - Upload ke folder tertentu (folder_id)
    - Organize backup by device name (subfolder per device)
    - Cleanup old files berdasarkan retention policy
    - Upload dengan resume support (chunked)

    Usage:
        uploader = GoogleDriveUploader(
            credentials_file="credentials.json",
            token_file="token.json",
            folder_id="parent_folder_id",
        )
        uploader.authenticate()
        uploader.upload_file("local_backup.backup", "device1")
        uploader.cleanup_old_files("device1", retention_days=30)
    """

    # Chunk size untuk upload (5MB)
    CHUNK_SIZE = 5 * 1024 * 1024

    def __init__(
        self,
        credentials_file: str,
        token_file: str = "token.json",
        folder_id: str = "",
        base_dir: Path | None = None,
    ):
        """
        Inisialisasi Google Drive uploader.

        Args:
            credentials_file: Path ke credentials.json dari Google Cloud Console.
            token_file: Path untuk menyimpan token OAuth2 (auto-generated).
            folder_id: ID folder Google Drive tempat backup disimpan.
            base_dir: Base directory untuk resolve relative path.
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.folder_id = folder_id
        self.base_dir = base_dir or Path.cwd()
        self._service = None

        # Resolve path
        cred_path = Path(self.credentials_file)
        if not cred_path.is_absolute():
            cred_path = self.base_dir / cred_path
        self._credentials_path = cred_path

        token_path = Path(self.token_file)
        if not token_path.is_absolute():
            token_path = self.base_dir / token_path
        self._token_path = token_path

    def authenticate(self):
        """
        Autentikasi ke Google Drive API via OAuth2.

        First run: Browser akan terbuka untuk consent.
        Subsequent: Token dari token.json digunakan.

        Raises:
            GoogleDriveError: Jika autentikasi gagal.
        """
        logger.info("Autentikasi Google Drive API...")

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            raise GoogleDriveError(
                "Google Drive dependencies belum terinstall. "
                "Install dengan: pip install google-api-python-client "
                "google-auth-oauthlib google-auth-httplib2"
            )

        # Scope: upload files ke Drive, akses file yang dibuat oleh app ini
        SCOPES = ["https://www.googleapis.com/auth/drive.file"]

        creds = None

        # Load token yang sudah ada
        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), SCOPES
                )
            except Exception as e:
                logger.warning(f"Gagal load token, akan re-auth: {e}")

        # Refresh atau buat credential baru
        if creds and creds.expired and creds.refresh_token:
            logger.debug("Token expired, refreshing...")
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Gagal refresh token, akan re-auth: {e}")
                creds = None

        if not creds or not creds.valid:
            if not self._credentials_path.exists():
                raise GoogleDriveError(
                    f"File credentials tidak ditemukan: {self._credentials_path}. "
                    "Download dari Google Cloud Console > APIs & Services > "
                    "Credentials > Create OAuth2 Client ID (Desktop app) > "
                    "Download JSON."
                )

            logger.info("Menjalankan OAuth2 flow (browser akan terbuka)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self._credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token untuk run berikutnya
        with open(self._token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        logger.debug(f"Token disimpan ke {self._token_path}")

        # Build service
        try:
            self._service = build("drive", "v3", credentials=creds)
            logger.info("Google Drive API siap digunakan")
        except Exception as e:
            raise GoogleDriveError(f"Gagal build Google Drive service: {e}")

    def _ensure_authenticated(self):
        """Pastikan sudah authenticate sebelum operasi."""
        if self._service is None:
            raise GoogleDriveError(
                "Google Drive belum authenticate. Panggil authenticate() dulu."
            )

    def _get_or_create_folder(self, folder_name: str, parent_id: str = None) -> str:
        """
        Cari atau buat folder di Google Drive.

        Args:
            folder_name: Nama folder yang dicari/dibuat.
            parent_id: ID parent folder (default: self.folder_id).

        Returns:
            ID folder.
        """
        self._ensure_authenticated()
        parent_id = parent_id or self.folder_id

        # Cari folder dengan nama ini di parent folder
        query = (
            f"name='{folder_name}' and "
            f"mimeType='application/vnd.google-apps.folder' and "
            f"'{parent_id}' in parents and trashed=false"
        )

        try:
            results = (
                self._service.files()
                .list(q=query, spaces="drive", fields="files(id, name)")
                .execute()
            )
            folders = results.get("files", [])
        except Exception as e:
            raise GoogleDriveError(f"Gagal cari folder {folder_name}: {e}")

        if folders:
            # Folder ditemukan
            folder_id = folders[0]["id"]
            logger.debug(f"Folder ditemukan: {folder_name} ({folder_id})")
            return folder_id

        # Buat folder baru
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }

        try:
            folder = self._service.files().create(
                body=file_metadata, fields="id"
            ).execute()
            folder_id = folder.get("id")
            logger.info(f"Folder baru dibuat: {folder_name} ({folder_id})")
            return folder_id
        except Exception as e:
            raise GoogleDriveError(f"Gagal buat folder {folder_name}: {e}")

    def upload_file(
        self, local_path: str | Path, device_name: str, subfolder: str = None
    ) -> str:
        """
        Upload file ke Google Drive.

        File akan disimpan di struktur:
            <root_folder>/<device_name>/[<subfolder>/]<filename>

        Args:
            local_path: Path file lokal yang akan diupload.
            device_name: Nama device (akan dibuat subfolder per device).
            subfolder: Subfolder tambahan (optional, e.g., tanggal backup).

        Returns:
            File ID di Google Drive.

        Raises:
            GoogleDriveError: Jika upload gagal.
        """
        self._ensure_authenticated()

        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError:
            raise GoogleDriveError("googleapiclient belum terinstall")

        local_path = Path(local_path)
        if not local_path.exists():
            raise GoogleDriveError(f"File lokal tidak ditemukan: {local_path}")

        # Tentukan parent folder
        parent_id = self._get_or_create_folder(device_name, self.folder_id)

        if subfolder:
            parent_id = self._get_or_create_folder(subfolder, parent_id)

        filename = local_path.name
        file_size = local_path.stat().st_size

        logger.info(
            f"Uploading {filename} ({file_size} bytes) ke Google Drive "
            f"[{device_name}/{subfolder or ''}]"
        )

        # Cek apakah file dengan nama sama sudah ada (overwrite)
        query = (
            f"name='{filename}' and "
            f"'{parent_id}' in parents and trashed=false"
        )
        try:
            results = (
                self._service.files()
                .list(q=query, fields="files(id, name)")
                .execute()
            )
            existing = results.get("files", [])
        except Exception:
            existing = []

        file_metadata = {"name": filename, "parents": [parent_id]}
        media = MediaFileUpload(
            str(local_path),
            mimetype="application/octet-stream",
            resumable=True,
            chunksize=self.CHUNK_SIZE,
        )

        try:
            if existing:
                # Update file yang sudah ada
                file_id = existing[0]["id"]
                logger.debug(f"Overwrite existing file: {filename} ({file_id})")
                request = self._service.files().update(
                    fileId=file_id,
                    body=file_metadata,
                    media_body=media,
                    fields="id",
                )
            else:
                # Create file baru
                request = self._service.files().create(
                    body=file_metadata, media_body=media, fields="id"
                )
        except Exception as e:
            raise GoogleDriveError(f"Gagal mulai upload {filename}: {e}")

        # Upload dengan progress tracking
        response = None
        previous_progress = 0
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                if progress >= previous_progress + 20 or progress == 100:
                    logger.debug(f"Upload {filename}: {progress}%")
                    previous_progress = progress

        file_id = response.get("id")
        logger.info(f"Upload berhasil: {filename} -> Google Drive ID: {file_id}")
        return file_id

    def cleanup_old_files(self, device_name: str, retention_days: int):
        """
        Hapus file backup lama di Google Drive berdasarkan retention policy.

        Args:
            device_name: Nama device untuk cleanup.
            retention_days: File lebih tua dari ini akan dihapus (0 = tidak hapus).
        """
        self._ensure_authenticated()

        if retention_days <= 0:
            logger.debug("Retention=0, skip cleanup Google Drive")
            return

        # Dapatkan folder device
        device_folder_id = self._get_or_create_folder(device_name, self.folder_id)

        # Cari semua file di folder device
        query = (
            f"'{device_folder_id}' in parents and trashed=false"
        )
        try:
            results = (
                self._service.files()
                .list(
                    q=query,
                    fields="files(id, name, modifiedTime)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            files = results.get("files", [])
        except Exception as e:
            raise GoogleDriveError(f"Gagal list files untuk cleanup: {e}")

        if not files:
            logger.debug(f"Tidak ada file untuk cleanup di {device_name}")
            return

        # Hitung cutoff date
        cutoff = datetime.utcnow().timestamp() - (retention_days * 86400)

        deleted_count = 0
        for f in files:
            try:
                modified_str = f.get("modifiedTime", "")
                if not modified_str:
                    continue

                # Parse ISO 8601 datetime
                from datetime import datetime as dt

                modified_dt = dt.fromisoformat(
                    modified_str.replace("Z", "+00:00")
                )
                modified_ts = modified_dt.timestamp()

                if modified_ts < cutoff:
                    logger.info(
                        f"Hapus file lama di Google Drive: {f['name']} "
                        f"(modified: {modified_str})"
                    )
                    self._service.files().delete(fileId=f["id"]).execute()
                    deleted_count += 1
            except Exception as e:
                logger.warning(f"Gagal hapus file {f.get('name')}: {e}")

        if deleted_count > 0:
            logger.info(
                f"Cleanup Google Drive: {deleted_count} file dihapus dari "
                f"{device_name} (retention={retention_days} hari)"
            )
