"""Background SQS worker. Run with: python worker.py"""
import json
import logging
import time

from dotenv import load_dotenv

load_dotenv()

from aws_services.notifications import notify_incident_submitted
from aws_services.queue import delete_message, receive_incidents
from aws_services.monitoring import configure_logging

configure_logging()
logger = logging.getLogger("incident-worker")

if __name__ == "__main__":
    logger.info("Incident queue worker started")
    while True:
        try:
            for message in receive_incidents():
                try:
                    incident = json.loads(message["Body"])
                    notify_incident_submitted(incident)
                    delete_message(message["ReceiptHandle"])
                    logger.info("Processed incident %s", incident["id"])
                except Exception:
                    logger.exception("Could not process queue message; it will be retried")
        except Exception:
            logger.exception("Queue poll failed; retrying shortly")
            time.sleep(5)
