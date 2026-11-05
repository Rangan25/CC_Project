import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


def _sns_client():
    return boto3.client("sns", region_name=os.getenv("AWS_REGION", "us-east-1"),
                        config=Config(connect_timeout=2, read_timeout=4, retries={"max_attempts": 1}))


def _send(subject, message):
    topic_arn = os.getenv("SNS_TOPIC_ARN")
    if not topic_arn:
        logger.info("Notification (local mode): %s — %s", subject, message)
        return False
    try:
        _sns_client().publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)
        logger.info("SNS notification sent: %s", subject)
        return True
    except (BotoCoreError, ClientError, NoCredentialsError) as exc:
        logger.warning("SNS notification failed: %s", exc)
        return False


def notify_incident_submitted(incident):
    return _send(f"New incident #{incident['id']}: {incident['title']}",
                 f"A new {incident['priority'].lower()} priority incident was submitted.\n\n"
                 f"Title: {incident['title']}\nCategory: {incident['category']}\n"
                 f"Location: {incident['location']}\nReporter: {incident['reporter_name']} ({incident['reporter_email']})")


def notify_incident_resolved(incident):
    return _send(f"Incident #{incident['id']} resolved", f"Incident '{incident['title']}' has been marked as resolved.")
