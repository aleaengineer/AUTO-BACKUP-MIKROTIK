# Auto Backup MikroTik Tool

Tool untuk backup konfigurasi MikroTik secara otomatis berdasarkan jadwal. Mendukung multi-device, backup binary (.backup) dan export config (.rsc), upload ke Google Drive, dan berjalan cross-platform (Windows/Linux).

---

## Daftar Isi

1. [Fitur](#fitur)
2. [Arsitektur Project](#arsitektur-project)
3. [Flow Backup per Device](#flow-backup-per-device)
4. [Prasyarat](#prasyarat)
   - [MikroTik](#1-mikrotik)
   - [Python](#2-python)
   - [Google Drive (Opsional)](#3-google-drive-opsional)
5. [Instalasi](#instalasi)
6. [Konfigurasi](#konfigurasi)
   - [Penjelasan Setiap Section](#penjelasan-setiap-section)
   - [Substitusi Environment Variable](#substitusi-environment-variable)
7. [Cara Menjalankan](#cara-menjalankan)
   - [One-time Backup](#1-one-time-backup-sekali-jalan)
   - [Scheduler Otomatis](#2-scheduler-otomatis-berjalan-terus)
   - [Backup Device Tertentu](#3-backup-device-tertentu)
   - [Menjalankan tanpa --config](#4-menjalankan-tanpa---config)
8. [Contoh Konfigurasi](#contoh-konfigurasi)
9. [Format Nama File Backup](#format-nama-file-backup)
10. [Struktur Penyimpanan Backup](#struktur-penyimpanan-backup)
11. [Google Drive Setup](#google-drive-setup)
12. [Menjalankan sebagai Service](#menjalankan-sebagai-service)
13. [Troubleshooting](#troubleshooting)
14. [Dependencies](#dependencies)
15. [Catatan Keamanan](#catatan-keamanan)

---

## Fitur

- **Backup otomatis** berdasarkan jadwal (interval atau cron expression)
- **Dua tipe backup**: binary `.backup` dan export config `.rsc`
- **Multi-device**: backup banyak MikroTik sekaligus dari satu config file
- **Upload ke Google Drive**: backup tersimpan di cloud dengan retention policy
- **Local storage**: backup disimpan lokal dengan struktur `device/tanggal/file`
- **Retention policy**: hapus backup lama otomatis (lokal + Google Drive)
- **Cross-platform**: berjalan di Windows dan Linux
- **Password via env var**: support substitusi `${ENV_VAR}` untuk keamanan
- **Nama file berdasarkan identity**: otomatis ambil identity MikroTik untuk nama file backup
- **Show sensitive**: export `.rsc` menyertakan password/secret (bisa di-restore lengkap)
- **Kompatibel RouterOS v6 & v7**: menggunakan library `librouteros`

---

## Arsitektur Project

```
Auto-Backup-Mikrotik-Tool/
├── main.py                     # CLI entry point (argparse)
├── config.example.yaml          # Template config dengan komentar
├── requirements.txt             # Python dependencies
├── .gitignore
├── __init__.py
└── src/
    ├── __init__.py
    ├── logger.py                # Logger (console + rotating file)
    ├── config_loader.py         # Load & validasi config YAML + env var
    ├── mikrotik_client.py       # MikroTik API (connect, backup, identity, files)
    ├── ftp_downloader.py         # Download backup via FTP (binary mode)
    ├── google_drive_uploader.py # Upload ke Google Drive (OAuth2)
    ├── local_storage.py         # Manajemen file lokal + retention
    ├── backup_manager.py        # Orchestrator (7-step backup flow)
    └── scheduler.py             # APScheduler (interval/cron)
```

### Penjelasan Modul

| Modul | Fungsi |
|-------|--------|
| `main.py` | CLI entry point. Parsing argumen, load config, jalankan backup atau scheduler |
| `src/logger.py` | Logger singleton dengan console + rotating file handler |
| `src/config_loader.py` | Load config YAML, substitusi `${ENV_VAR}`, validasi struktur |
| `src/mikrotik_client.py` | Koneksi MikroTik via API (`librouteros`), buat backup, ambil identity, list/delete file |
| `src/ftp_downloader.py` | Download file backup dari MikroTik via FTP (binary mode) |
| `src/google_drive_uploader.py` | Upload backup ke Google Drive via API v3 (OAuth2, chunked upload) |
| `src/local_storage.py` | Simpan backup ke lokal dengan struktur folder, retention policy |
| `src/backup_manager.py` | Orchestrator: koordinasi semua modul untuk 7-step backup flow |
| `src/scheduler.py` | Scheduler otomatis dengan APScheduler (interval/cron trigger) |

---

## Flow Backup per Device

Setiap device melalui 7 langkah backup:

```
[1/7] Connect ke MikroTik via API (port 8728/8729)
[2/7] Create backup files di router (.backup + .rsc)
[3/7] Connect FTP & download file backup ke lokal
[4/7] Save ke local storage (backups/device/tanggal/file)
[5/7] Upload ke Google Drive (jika enabled)
[6/7] Cleanup file backup di router
[7/7] Apply retention policy (hapus backup lama - lokal + Google Drive)
```

---

## Prasyarat

### 1. MikroTik

Pastikan service berikut aktif di MikroTik:

```routeros
/ip service enable api
/ip service enable ftp
```

Verifikasi service sudah aktif:

```routeros
/ip service print where name=api
/ip service print where name=ftp
```

Buat user khusus untuk backup (opsional tapi disarankan):

```routeros
/user add name=backup group=full password=your_password
```

User yang dipakai untuk backup harus punya:
- Akses API (service `api` aktif)
- Akses FTP (service `ftp` aktif)
- Permission `read` + `write` (group `full` atau custom dengan permission cukup)

### 2. Python

- Python 3.10 atau newer
- pip (sudah included di Python 3.4+)

Cek versi Python:

```bash
python --version
```

### 3. Google Drive (Opsional)

Jika ingin upload backup ke Google Drive, perlu setup Google Cloud Project. Lihat section [Google Drive Setup](#google-drive-setup) untuk panduan lengkap.

---

## Instalasi

### Langkah 1: Download/Copy Project

```bash
# Jika dari git
git clone <repository-url>
cd Auto-Backup-Mikrotik-Tool
```

Atau copy folder project ke direktori yang diinginkan.

### Langkah 2: Buat Virtual Environment (Disarankan)

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Langkah 3: Install Dependencies

```bash
pip install -r requirements.txt
```

Dependencies yang akan diinstall:

| Package | Fungsi |
|---------|--------|
| librouteros | Koneksi MikroTik API (kompatibel v6 & v7) |
| APScheduler | Scheduler (interval/cron) |
| PyYAML | Parse config YAML |
| google-api-python-client | Google Drive API |
| google-auth-oauthlib | OAuth2 authentication |
| google-auth-httplib2 | HTTP transport untuk Google auth |

### Langkah 4: Copy Config

```bash
# Windows
copy config.example.yaml config.yaml

# Linux
cp config.example.yaml config.yaml
```

### Langkah 5: Edit Config

Edit `config.yaml` dengan text editor, sesuaikan:
- Daftar device MikroTik (host, username, password)
- Jadwal backup
- Lokasi penyimpanan
- Google Drive (jika dipakai)
- Logging

---

## Konfigurasi

File config menggunakan format YAML. Semua nilai sensitif (password) support substitusi environment variable dengan format `${VAR_NAME}`.

### Penjelasan Setiap Section

#### schedule — Jadwal Backup

```yaml
schedule:
  # Tipe schedule: "interval" atau "cron"
  type: interval

  # Untuk type=interval (pilih salah satu atau keduanya):
  hours: 6          # backup setiap 6 jam
  # minutes: 30     # atau setiap 30 menit

  # Untuk type=cron:
  # type: cron
  # cron_expression: "0 2 * * *"    # setiap hari jam 02:00
```

#### devices — Daftar MikroTik

```yaml
devices:
  - name: router1              # Nama device (untuk log & folder backup)
    host: 192.168.88.1         # IP atau hostname MikroTik
    username: admin             # Username API/FTP
    password: ""                # Password API/FTP (boleh kosong)
    api_port: 8728             # Port API (default 8728, SSL: 8729)
    ftp_port: 21               # Port FTP (default 21)
    use_ssl: false             # Gunakan SSL untuk API
    ssl_verify: true           # Verifikasi SSL certificate
    backup_types:              # Tipe backup yang dibuat
      - backup                  #   backup = file .backup (binary)
      - rsc                     #   rsc = file .rsc (export config)
    cleanup_router: true       # Hapus file backup dari router setelah download
```

#### storage — Penyimpanan Lokal

```yaml
storage:
  local_path: ./backups        # Path folder backup lokal
  retention_days: 30           # Hapus backup lokal lebih tua dari N hari (0 = tidak hapus)
```

#### google_drive — Upload ke Cloud

```yaml
google_drive:
  enabled: false               # Aktifkan upload ke Google Drive
  credentials_file: credentials.json  # Path ke credentials.json
  token_file: token.json       # Path untuk menyimpan token OAuth2
  folder_id: ""                # ID folder Google Drive
  retention_days: 90           # Hapus backup di Drive lebih tua dari N hari
```

#### logging — Konfigurasi Log

```yaml
logging:
  level: INFO                  # Level: DEBUG, INFO, WARNING, ERROR
  console: true                # Log ke console
  file: ./logs/backup.log      # File log (kosongkan jika tidak ingin file)
  max_size: 5                  # Ukuran max file log (MB) sebelum rotasi
  backup_count: 3              # Jumlah file rotasi yang disimpan
```

### Substitusi Environment Variable

Password dan nilai sensitif lainnya bisa menggunakan env var untuk keamanan:

```yaml
devices:
  - name: router1
    host: 192.168.88.1
    username: admin
    password: ${MIKROTIK_PASSWORD}    # Akan di-substitusi dari env var
```

**Windows (PowerShell):**
```powershell
$env:MIKROTIK_PASSWORD = "mysecret"
python main.py run --config config.yaml
```

**Windows (Command Prompt):**
```cmd
set MIKROTIK_PASSWORD=mysecret
python main.py run --config config.yaml
```

**Linux:**
```bash
export MIKROTIK_PASSWORD=mysecret
python main.py run --config config.yaml
```

---

## Cara Menjalankan

### 1. One-time Backup (Sekali Jalan)

Backup semua device di config:
```bash
python main.py run --config config.yaml
```

Output:
```
=== Auto Backup MikroTik Tool ===
Mode: RUN (one-time backup)
Backup semua device (2 device)

============================================================
Memulai backup device: router1 (192.168.99.31)
============================================================
[1/7] Connect ke MikroTik API 192.168.99.31:8728
[2/7] Membuat backup files di router
[3/7] Connect FTP & download files
[4/7] Simpan ke local storage
[5/7] Upload ke Google Drive
[6/7] Cleanup file di router
[7/7] Apply retention policy
Backup router1 (192.168.99.31) berhasil!

============================================================
Memulai backup device: router2 (192.168.99.30)
============================================================
...

============================================================
Summary: 2 berhasil, 0 gagal
  router1: BERHASIL
  router2: BERHASIL
```

### 2. Scheduler Otomatis (Berjalan Terus)

Jalankan scheduler sesuai jadwal di config:
```bash
python main.py schedule --config config.yaml
```

Jalankan backup langsung saat startup, lalu lanjut scheduler:
```bash
python main.py schedule --config config.yaml --run-now
```

Scheduler akan berjalan terus sampai dihentikan dengan `Ctrl+C`. Next backup time akan ditampilkan di log:
```
Scheduler: interval mode (hours=6)
Next backup dijadwalkan: 2026-10-31 00:35:24
Memulai scheduler (tekan Ctrl+C untuk berhenti)...
```

### 3. Backup Device Tertentu

Backup hanya satu device berdasarkan nama:
```bash
python main.py run --config config.yaml --device router1
```

### 4. Menjalankan tanpa --config

Jika `--config` tidak diberikan, tool otomatis mencari `config.yaml` di current directory:
```bash
python main.py run
python main.py schedule
```

### 5. Lihat Help

```bash
# Help utama
python main.py --help

# Help command run
python main.py run --help

# Help command schedule
python main.py schedule --help
```

---

## Contoh Konfigurasi

### Interval (setiap 6 jam)
```yaml
schedule:
  type: interval
  hours: 6
```

### Interval (setiap 30 menit)
```yaml
schedule:
  type: interval
  minutes: 30
```

### Cron (setiap hari jam 02:00)
```yaml
schedule:
  type: cron
  cron_expression: "0 2 * * *"
```

### Cron (setiap 6 jam)
```yaml
schedule:
  type: cron
  cron_expression: "0 */6 * * *"
```

### Cron (setiap Minggu jam 00:00)
```yaml
schedule:
  type: cron
  cron_expression: "0 0 * * 0"
```

### Multi-device
```yaml
devices:
  - name: router1
    host: 192.168.88.1
    username: admin
    password: ""

  - name: router2
    host: 192.168.88.2
    username: admin
    password: ${ROUTER2_PASSWORD}

  - name: router3
    host: 10.0.0.1
    username: backup
    password: ${ROUTER3_PASSWORD}
    api_port: 8728
    ftp_port: 21
    use_ssl: false
    ssl_verify: true
    backup_types:
      - backup
      - rsc
    cleanup_router: true
```

### Password via Environment Variable
```yaml
devices:
  - name: router1
    host: 192.168.88.1
    username: admin
    password: ${MIKROTIK_PASSWORD}
```

---

## Format Nama File Backup

Nama file backup otomatis dibuat dengan format:

```
<identity>_Backup_<DD-MM-YYYY>_<HH-MM-SS>
```

Contoh:
- MikroTik identity: `ALE-RND`
- Tanggal: 30 Oktober 2026, 18:35:24
- Nama file: `ALE-RND_Backup_30-10-2026_18-35-24.backup` dan `.rsc`

Identity diambil otomatis dari MikroTik (`/system/identity/print`). Jika identity mengandung spasi atau karakter khusus, akan otomatis di-sanitize (spasi → `_`, `/` → `-`).

---

## Struktur Penyimpanan Backup

### Lokal

```
backups/
├── router1/
│   ├── 2026-10-30/
│   │   ├── ALE-RND_Backup_30-10-2026_18-35-24.backup
│   │   └── ALE-RND_Backup_30-10-2026_18-35-24.rsc
│   └── 2026-10-31/
│       ├── ALE-RND_Backup_31-10-2026_02-00-00.backup
│       └── ALE-RND_Backup_31-10-2026_02-00-00.rsc
└── router2/
    └── 2026-10-30/
        ├── SW-DISTRI-NOC_Backup_30-10-2026_18-35-41.backup
        └── SW-DISTRI-NOC_Backup_30-10-2026_18-35-41.rsc
```

### Google Drive

```
<folder_id>/
├── router1/
│   └── 2026-10-30/
│       ├── ALE-RND_Backup_30-10-2026_18-35-24.backup
│       └── ALE-RND_Backup_30-10-2026_18-35-24.rsc
└── router2/
    └── 2026-10-30/
        ├── SW-DISTRI-NOC_Backup_30-10-2026_18-35-41.backup
        └── SW-DISTRI-NOC_Backup_30-10-2026_18-35-41.rsc
```

Setiap device punya subfolder sendiri, dan di dalamnya subfolder per tanggal. File backup dengan nama sama akan di-overwrite di Google Drive (update, bukan duplikat).

---

## Google Drive Setup

### Langkah 1: Buat Google Cloud Project

1. Buka [Google Cloud Console](https://console.cloud.google.com/)
2. Buat project baru atau pilih project yang ada
   - Menu dropdown di top bar → New Project
   - Beri nama project (e.g., "MikroTik Backup")

### Langkah 2: Enable Google Drive API

1. Menu → **APIs & Services** → **Library**
2. Cari "Google Drive API"
3. Klik **Enable**

### Langkah 3: Buat OAuth2 Credentials

1. Menu → **APIs & Services** → **Credentials**
2. **Create Credentials** → **OAuth client ID**
3. Application type: **Desktop app**
4. Beri nama (e.g., "MikroTik Backup Client")
5. Klik **Create**
6. Download JSON file
7. Simpan sebagai `credentials.json` di folder project

### Langkah 4: Konfigurasi OAuth Consent Screen

1. Menu → **APIs & Services** → **OAuth consent screen**
2. User type: **External** (atau Internal jika Google Workspace)
3. Isi app name, email support, dll.
4. Di bagian **Scopes**, tambahkan:
   - `https://www.googleapis.com/auth/drive.file` (hanya akses file yang dibuat app)
5. Di bagian **Test users**, tambahkan email Google Anda
   - Klik **ADD USERS**
   - Masukkan email yang akan dipakai untuk login
   - Klik **Save**

> **Penting**: Selama project masih dalam status "Testing", hanya email yang didaftarkan sebagai test user yang bisa login. Jika muncul error `403: access_denied`, tambahkan email Anda sebagai test user.

### Langkah 5: Dapatkan Folder ID

1. Buka [Google Drive](https://drive.google.com/)
2. Buat folder untuk backup (e.g., "MikroTik Backups")
3. Buka folder tersebut
4. Copy Folder ID dari URL:
   ```
   https://drive.google.com/drive/folders/XXXXXXX
                                      ↑
                                   Folder ID
   ```

### Langkah 6: Konfigurasi di config.yaml

```yaml
google_drive:
  enabled: true
  credentials_file: credentials.json
  token_file: token.json
  folder_id: "XXXXXXX"          # Folder ID dari langkah 5
  retention_days: 90
```

### Auth Pertama Kali

Saat pertama kali run dengan `google_drive.enabled: true`, tool akan:
1. Membuka browser untuk OAuth2 consent
2. Login dengan Google account (yang sudah didaftarkan sebagai test user)
3. Grant permission untuk akses Drive
4. Token disimpan ke `token.json`
5. Run berikutnya tidak perlu login lagi (token auto-refresh)

### Server Headless (Tanpa Browser)

Jika tool berjalan di server tanpa browser:
1. Run sekali di mesin dengan browser (laptop/PC) untuk generate `token.json`
2. Copy `token.json` ke server
3. Tool akan menggunakan token yang sudah ada (auto-refresh jika expired)

---

## Menjalankan sebagai Service

### Linux (systemd)

Buat file `/etc/systemd/system/mikrotik-backup.service`:

```ini
[Unit]
Description=MikroTik Auto Backup Tool
After=network.target

[Service]
Type=simple
User=backup
WorkingDirectory=/opt/mikrotik-backup
ExecStart=/opt/mikrotik-backup/venv/bin/python main.py schedule --config config.yaml
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Aktifkan dan jalankan:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start saat boot)
sudo systemctl enable mikrotik-backup

# Start service
sudo systemctl start mikrotik-backup

# Cek status
sudo systemctl status mikrotik-backup

# Lihat log
sudo journalctl -u mikrotik-backup -f

# Stop service
sudo systemctl stop mikrotik-backup

# Restart service
sudo systemctl restart mikrotik-backup
```

### Windows (Task Scheduler)

1. Buka **Task Scheduler** → **Create Task**
2. Tab **General**:
   - Name: `MikroTik Auto Backup`
   - Pilih **Run whether user is logged on or not**
   - Pilih **Run with highest privileges**
3. Tab **Trigger**:
   - New → **At startup** atau **On a schedule** (sesuai kebutuhan)
4. Tab **Actions**:
   - New → **Start a program**
   - Program/script: `C:\path\to\venv\Scripts\python.exe`
   - Arguments: `main.py schedule --config config.yaml`
   - Start in: `C:\path\to\Auto-Backup-Mikrotik-Tool`
5. Tab **Settings**:
   - Uncheck "Stop if the computer switches to battery power"
   - Check "Run task as soon as possible after a scheduled start is missed"
6. Klik **OK**, masukkan password Windows jika diminta

### Windows (Run di Background dengan Python)

Alternatif tanpa Task Scheduler, bisa pakai `pythonw`:
```bash
pythonw main.py schedule --config config.yaml
```

`pythonw` berjalan tanpa window console, cocok untuk background process.

---

## Troubleshooting

| Masalah | Solusi |
|---------|--------|
| Connection refused (API) | Pastikan `/ip service enable api` dan port benar (default 8728) |
| Connection refused (FTP) | Pastikan `/ip service enable ftp` dan port 21 aktif |
| Invalid username or password (API) | Cek username/password. Pastikan user punya akses API |
| FTP: Can not size in ASCII mode | Tool sudah handle ini dengan binary mode. Update ke versi terbaru |
| Unknown parameter dont-encrypted | RouterOS v7 tidak support parameter ini. Tool sudah handle |
| Permission denied (API) | User harus punya group `full` atau minimal permission `read` + `write` |
| Permission denied (FTP) | Pastikan user punya akses FTP service |
| Google Drive: 403 access_denied | Tambahkan email Google Anda sebagai **test user** di OAuth consent screen |
| Google Drive: auth error | Hapus `token.json` dan run lagi untuk re-authenticate |
| Google Drive: credentials not found | Pastikan `credentials.json` ada di folder project |
| Module not found | Jalankan `pip install -r requirements.txt` |
| Config tidak ditemukan | Pastikan `config.yaml` ada di folder project atau berikan path dengan `--config` |
| Backup file tidak muncul di router | Tunggu beberapa detik (tool polling sampai file ada). Jika timeout, cek space disk router |

### Mengaktifkan Debug Logging

Untuk troubleshooting lebih detail, ubah level log ke DEBUG di `config.yaml`:

```yaml
logging:
  level: DEBUG
  console: true
  file: ./logs/backup.log
```

### Reset Google Drive Token

Jika Google Drive auth bermasalah, hapus token dan authenticate ulang:

```bash
# Windows
del token.json

# Linux
rm token.json
```

Lalu run lagi — browser akan terbuka untuk re-authenticate.

---

## Dependencies

| Package | Versi | Fungsi |
|---------|-------|--------|
| librouteros | >=4.2.0 | Koneksi MikroTik API (kompatibel RouterOS v6 & v7) |
| APScheduler | >=3.10.0 | Scheduler (interval/cron trigger) |
| PyYAML | >=6.0 | Parse config YAML |
| google-api-python-client | >=2.100.0 | Google Drive API v3 |
| google-auth-oauthlib | >=1.1.0 | OAuth2 authentication |
| google-auth-httplib2 | >=0.2.0 | HTTP transport untuk Google auth |
| ftplib | built-in | Download via FTP (tidak perlu install) |

Install semua:
```bash
pip install -r requirements.txt
```

---

## Catatan Keamanan

### Isi File Backup

**File `.backup` (binary)** berisi SEMUA konfigurasi MikroTik termasuk:
- Username dan password user
- Password WiFi, PPP, PPPoE
- Certificate dan private key
- Semua konfigurasi router

**File `.rsc` (export config)** berisi text config RouterOS. Dengan parameter `show-sensitive`, file ini juga menyertakan:
- Password PPP secret
- Password interface/tunnel
- Password user
- Semua konfigurasi router dalam format text

### Rekomendasi Keamanan

1. **Simpan backup di tempat aman** — file backup berisi credentials penuh router
2. **Batasi akses folder backup** — baik lokal maupun Google Drive
3. **Jangan share file `.backup` ke publik** — siapa pun yang punya file ini bisa restore ke router
4. **Gunakan env var untuk password** — gunakan `${VAR_NAME}` di config.yaml, jangan hardcode password
5. **Buat user khusus backup** — jangan pakai user `admin` utama, buat user terpisah dengan permission minimal
6. **Folder Google Drive private** — pastikan folder backup di Drive hanya diakses oleh admin yang berwenang
7. **Pertimbangkan encrypt file backup** sebelum upload jika environment production

---

## License

MIT

---

## Credit

Dibuat oleh **Farhan Ale**
