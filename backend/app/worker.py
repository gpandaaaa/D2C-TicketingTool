import logging
import time

from app.core.database import SessionLocal
from app.services.email import deliver_pending
from app.services.tickets import sla_scan


def run():
    while True:
        try:
            with SessionLocal() as db:
                sla_scan(db)
        except Exception:
            logging.error('{"event":"sla_scan_failed"}')
        try:
            with SessionLocal() as db:
                deliver_pending(db)
        except Exception:
            logging.error('{"event":"email_worker_failed"}')
        time.sleep(30)


if __name__ == "__main__":
    run()
