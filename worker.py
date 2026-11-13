
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
            messages = receive_incidents()

            for message in messages:
                receipt_handle = message["ReceiptHandle"]
                message_id = message.get("MessageId", "unknown")

                try:
                    # Decode the SQS message
                    incident = json.loads(message["Body"])

                    # Validate the message structure
                    if not isinstance(incident, dict) or "id" not in incident:
                        logger.error(
                            "Invalid incident format. Discarding message: %s",
                            message_id
                        )
                        delete_message(receipt_handle)
                        continue

                except (json.JSONDecodeError, TypeError):
                    # Permanently malformed messages should not be retried
                    logger.error(
                        "Invalid JSON in SQS message. Discarding message: %s",
                        message_id
                    )
                    delete_message(receipt_handle)
                    continue

                try:
                    # Process valid incident
                    notify_incident_submitted(incident)

                    # Delete only after successful processing
                    delete_message(receipt_handle)

                    logger.info(
                        "Successfully processed incident %s",
                        incident["id"]
                    )

                except Exception:
                    # Leave valid messages in SQS for retry
                    logger.exception(
                        "Failed to process incident %s; message will be retried",
                        incident["id"]
                    )

        except KeyboardInterrupt:
            logger.info("Incident worker stopped by user")
            break

        except Exception:
            logger.exception("Queue polling failed; retrying in 5 seconds")
            time.sleep(5)
