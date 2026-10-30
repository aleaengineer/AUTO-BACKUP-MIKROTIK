"""
Auto Backup MikroTik Tool
=========================
Tool untuk backup konfigurasi MikroTik secara otomatis berdasarkan jadwal.

Fitur:
- Koneksi ke MikroTik via API (port 8728/8729)
- Backup binary (.backup) dan export config (.rsc)
- Download file backup via FTP
- Upload ke Google Drive
- Scheduler builtin (interval/cron)
- Multi-device support
- Cross-platform (Windows/Linux)
"""

__version__ = "1.0.0"
__author__ = "Auto Backup MikroTik Tool"
