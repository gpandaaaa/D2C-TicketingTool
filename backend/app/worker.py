import logging
import time

from app.core.database import SessionLocal
from app.services.tickets import sla_scan


def run():
    while True:
        try:
            with SessionLocal() as db:
                sla_scan(db)
        except Exception:
            logging.error('{"event":"sla_scan_failed"}')
        time.sleep(30)


if __name__ == "__main__":
    run()
