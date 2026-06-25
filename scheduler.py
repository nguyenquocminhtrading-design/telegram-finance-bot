import os
import shutil
import logging
from datetime import datetime, date
from apscheduler.schedulers.background import BackgroundScheduler

from config import DATABASE_PATH
from asset_manager import run_monthly_depreciation

logger = logging.getLogger(__name__)


def backup_database():
    db_dir = os.path.dirname(DATABASE_PATH)
    backup_dir = os.path.join(db_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    today_str = date.today().isoformat()
    backup_path = os.path.join(backup_dir, f"finance_{today_str}.db")
    try:
        shutil.copy2(DATABASE_PATH, backup_path)
        logger.info(f"Database backed up to {backup_path}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")


def monthly_depreciation_job():
    logger.info("Running monthly depreciation...")
    try:
        results = run_monthly_depreciation()
        logger.info(f"Depreciation applied to {len(results)} assets.")
    except Exception as e:
        logger.error(f"Depreciation job failed: {e}")


def create_scheduler():
    scheduler = BackgroundScheduler(daemon=True)

    scheduler.add_job(
        backup_database,
        "cron",
        hour=2,
        minute=0,
        id="backup_db",
        replace_existing=True,
    )

    scheduler.add_job(
        monthly_depreciation_job,
        "cron",
        day=1,
        hour=0,
        minute=5,
        id="monthly_depreciation",
        replace_existing=True,
    )

    return scheduler
