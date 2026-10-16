"""Background jobs.

Run automatically by a daemon thread started with the API (SCHEDULER_ENABLED=true,
every SCHEDULER_INTERVAL_SECONDS), or on demand / from cron:

    cd backend
    python -m app.scheduler.jobs            # run all due jobs once
    python -m app.scheduler.jobs --loop     # standalone worker process

Every job is idempotent, so running the API worker and a cron worker together
cannot double-send reminders (rows are claimed atomically).
"""

from __future__ import annotations

import logging
import threading
import time

from ..database import SessionLocal
from ..services import config

logger = logging.getLogger("hirelune.scheduler")


def run_due_jobs() -> dict:
    from ..services import assessment_service, email_service, interview_service, offer_service
    results = {}
    for name, job in (
        ("interview_reminders", interview_service.process_due_reminders),
        ("expired_assessments", assessment_service.finalize_expired_assessments),
        ("expired_offers", offer_service.expire_offers),
        ("email_retries", email_service.retry_failed_emails),
    ):
        db = SessionLocal()
        try:
            results[name] = job(db)
        except Exception:  # noqa: BLE001 - one failing job must not stop the others
            logger.exception("Scheduled job %s failed", name)
            db.rollback()
            results[name] = "error"
        finally:
            db.close()
    return results


class SchedulerThread:
    def __init__(self, interval: int):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hirelune-scheduler", daemon=True)
        self.last_run: float | None = None
        self.last_result: dict | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        logger.info("Scheduler started (every %ss)", self.interval)
        while not self._stop.wait(self.interval if self.last_run else 5):
            try:
                self.last_result = run_due_jobs()
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler tick failed")
            self.last_run = time.time()


_scheduler: SchedulerThread | None = None


def start_background_scheduler() -> SchedulerThread | None:
    global _scheduler
    if not config.scheduler_enabled() or _scheduler is not None:
        return _scheduler
    _scheduler = SchedulerThread(config.scheduler_interval_seconds())
    _scheduler.start()
    return _scheduler


def stop_background_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.stop()
        _scheduler = None


def scheduler_status() -> dict:
    return {"enabled": config.scheduler_enabled(), "running": _scheduler is not None,
            "interval_seconds": config.scheduler_interval_seconds(),
            "last_run": _scheduler.last_run if _scheduler else None,
            "last_result": _scheduler.last_result if _scheduler else None}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--loop" in sys.argv:
        while True:
            logger.info("run: %s", run_due_jobs())
            time.sleep(config.scheduler_interval_seconds())
    else:
        print(run_due_jobs())
