"""
Modul scheduler untuk Auto Backup MikroTik Tool.
Menjalankan backup secara otomatis berdasarkan jadwal.
Mendukung 2 mode:
- interval: Setiap N menit/jam (e.g., setiap 6 jam)
- cron: Ekspresi cron (e.g., "0 2 * * *" = setiap hari jam 02:00)

Menggunakan APScheduler (Advanced Python Scheduler).
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from src.logger import get_logger

logger = get_logger("scheduler")


class SchedulerError(Exception):
    """Error saat setup scheduler."""


class BackupScheduler:
    """
    Scheduler untuk menjalankan backup otomatis.

    Usage:
        scheduler = BackupScheduler(config)
        scheduler.setup_job(backup_callable)
        scheduler.start()  # Blocking - berjalan sampai Ctrl+C
    """

    def __init__(self, config):
        """
        Inisialisasi scheduler.

        Args:
            config: Instance Config dari config_loader.
        """
        self.config = config
        self.scheduler = BlockingScheduler()
        self._backup_func = None

    def _create_trigger(self):
        """
        Buat trigger berdasarkan config schedule.

        Returns:
            IntervalTrigger atau CronTrigger.
        """
        sched_config = self.config.schedule
        sched_type = sched_config.get("type")

        if sched_type == "interval":
            minutes = sched_config.get("minutes")
            hours = sched_config.get("hours")

            kwargs = {}
            if hours is not None:
                kwargs["hours"] = int(hours)
            if minutes is not None:
                kwargs["minutes"] = int(minutes)

            logger.info(f"Scheduler: interval mode (hours={hours}, minutes={minutes})")
            return IntervalTrigger(**kwargs)

        elif sched_type == "cron":
            cron_expr = sched_config.get("cron_expression")
            if not cron_expr:
                raise SchedulerError("cron_expression wajib diisi untuk type=cron")

            # Parse cron expression: "minute hour day month day_of_week"
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                raise SchedulerError(
                    f"cron_expression harus 5 field (minute hour day month day_of_week), "
                    f"dapat: {cron_expr}"
                )

            cron_kwargs = {
                "minute": parts[0],
                "hour": parts[1],
                "day": parts[2],
                "month": parts[3],
                "day_of_week": parts[4],
            }

            logger.info(f"Scheduler: cron mode ({cron_expr})")
            return CronTrigger(**cron_kwargs)

        else:
            raise SchedulerError(f"Tipe schedule tidak dikenal: {sched_type}")

    def setup_job(self, backup_func):
        """
        Setup job backup ke scheduler.

        Args:
            backup_func: Callable yang akan dijalankan oleh scheduler.
                         Idealnya: BackupManager.backup_all_devices
        """
        self._backup_func = backup_func
        trigger = self._create_trigger()

        # Tambah job ke scheduler
        self.scheduler.add_job(
            func=self._run_backup,
            trigger=trigger,
            id="mikrotik_backup_job",
            name="MikroTik Auto Backup",
            misfire_grace_time=300,  # 5 menit grace time
            max_instances=1,  # Jangan overlap jika backup sebelumnya belum selesai
            coalesce=True,  # Gabungkan misfire jadi 1 run
        )

        # Log next run time
        jobs = self.scheduler.get_jobs()
        if jobs:
            next_run = jobs[0].next_run_time
            logger.info(f"Next backup dijadwalkan: {next_run}")

    def _run_backup(self):
        """
        Wrapper untuk menjalankan backup dengan error handling.
        Dipanggil oleh scheduler.
        """
        logger.info("Scheduler triggered: menjalankan backup...")
        try:
            self._backup_func()
            logger.info("Backup terjadwal selesai")
        except Exception as e:
            logger.error(f"Error saat backup terjadwal: {e}", exc_info=True)

    def start(self):
        """
        Mulai scheduler (blocking).
        Akan berjalan terus sampai di-stop (Ctrl+C / SIGTERM).
        """
        logger.info("Memulai scheduler (tekan Ctrl+C untuk berhenti)...")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler dihentikan")
            self.scheduler.shutdown(wait=False)

    def shutdown(self):
        """Hentikan scheduler."""
        logger.info("Mematikan scheduler...")
        self.scheduler.shutdown(wait=True)
