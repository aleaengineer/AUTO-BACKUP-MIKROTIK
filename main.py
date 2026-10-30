#!/usr/bin/env python3
"""
Auto Backup MikroTik Tool - Main Entry Point
============================================
Tool untuk backup konfigurasi MikroTik secara otomatis.

Usage:
    # Run backup sekali untuk semua device
    python main.py run --config config.yaml

    # Run backup untuk device tertentu
    python main.py run --config config.yaml --device router1

    # Jalankan scheduler (blocking, berjalan terus)
    python main.py schedule --config config.yaml

    # Run backup langsung (pakai config default)
    python main.py run
"""

import argparse
import sys
from pathlib import Path

# Tambah parent directory ke sys.path agar bisa import src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.logger import get_logger, logger_instance
from src.config_loader import load_config, ConfigError
from src.backup_manager import BackupManager
from src.scheduler import BackupScheduler

logger = get_logger("main")


def cmd_run(args):
    """Command: run backup sekali."""
    config_path = args.config
    device_name = args.device

    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        logger.error(f"File config tidak ditemukan: {e}")
        return 1
    except ConfigError as e:
        logger.error(f"Config error: {e}")
        return 1

    # Configure logger dengan setting dari config
    logger_instance.configure(config.logging, config.base_dir)

    logger.info("=== Auto Backup MikroTik Tool ===")
    logger.info(f"Mode: RUN (one-time backup)")

    manager = BackupManager(config)

    if device_name:
        # Backup device tertentu
        logger.info(f"Backup device: {device_name}")
        result = manager.backup_device_by_name(device_name)
        if result is None:
            logger.error(f"Device tidak ditemukan: {device_name}")
            return 1
        return 0 if result else 1
    else:
        # Backup semua device
        logger.info(f"Backup semua device ({len(config.devices)} device)")
        results = manager.backup_all_devices()

        # Summary
        success_count = sum(1 for v in results.values() if v)
        fail_count = len(results) - success_count
        logger.info(f"{'='*60}")
        logger.info(f"Summary: {success_count} berhasil, {fail_count} gagal")
        for name, success in results.items():
            status = "BERHASIL" if success else "GAGAL"
            logger.info(f"  {name}: {status}")

        return 0 if fail_count == 0 else 1


def cmd_schedule(args):
    """Command: jalankan scheduler."""
    config_path = args.config

    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        logger.error(f"File config tidak ditemukan: {e}")
        return 1
    except ConfigError as e:
        logger.error(f"Config error: {e}")
        return 1

    # Configure logger dengan setting dari config
    logger_instance.configure(config.logging, config.base_dir)

    logger.info("=== Auto Backup MikroTik Tool ===")
    logger.info(f"Mode: SCHEDULE (otomatis berdasarkan jadwal)")
    logger.info(f"Schedule type: {config.schedule.get('type')}")
    logger.info(f"Devices: {len(config.devices)}")

    manager = BackupManager(config)

    # Run backup sekali saat startup jika --run-now
    if args.run_now:
        logger.info("Menjalankan backup pertama kali...")
        manager.backup_all_devices()

    # Setup scheduler
    scheduler = BackupScheduler(config)
    scheduler.setup_job(manager.backup_all_devices)

    # Start (blocking)
    scheduler.start()
    return 0


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Auto Backup MikroTik Tool - Backup otomatis konfigurasi MikroTik",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  python main.py run --config config.yaml
  python main.py run --config config.yaml --device router1
  python main.py schedule --config config.yaml
  python main.py schedule --config config.yaml --run-now
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Mode operasi")

    # Command: run
    run_parser = subparsers.add_parser(
        "run", help="Jalankan backup sekali langsung"
    )
    run_parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path ke file config YAML (default: config.yaml)",
    )
    run_parser.add_argument(
        "--device", "-d",
        default=None,
        help="Backup device tertentu (default: semua device di config)",
    )

    # Command: schedule
    sched_parser = subparsers.add_parser(
        "schedule", help="Jalankan scheduler otomatis (blocking)"
    )
    sched_parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path ke file config YAML (default: config.yaml)",
    )
    sched_parser.add_argument(
        "--run-now",
        action="store_true",
        default=False,
        help="Jalankan backup sekali saat startup sebelum scheduler mulai",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "run":
        return cmd_run(args)
    elif args.command == "schedule":
        return cmd_schedule(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
