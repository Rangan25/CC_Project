import json
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


def _sqs_client():
    return boto3.client(
        "sqs",
        region_name=os.getenv("AWS_REGION", "ap-southeast-2"),
        config=Config(
            connect_timeout=5,
            read_timeout=25,
            retries={
                "max_attempts": 3,
                "mode": "standard"
            }
        )
    )


def enqueue_incident(incident):
    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        return False
    try:
        _sqs_client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(incident))
        logger.info("Queued incident %s for background processing", incident["id"])
        return True
    except (BotoCoreError, ClientError, NoCredentialsError) as exc:
        logger.warning("SQS unavailable; processing notification locally: %s", exc)
        return False


def receive_incidents(wait_seconds=10):
    queue_url = os.getenv("SQS_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("SQS_QUEUE_URL is required to run the worker")
    return _sqs_client().receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10,
                                        WaitTimeSeconds=wait_seconds, VisibilityTimeout=30,
                                        AttributeNames=["All"]).get("Messages", [])


def delete_message(receipt_handle):
    return _sqs_client().delete_message(QueueUrl=os.environ["SQS_QUEUE_URL"], ReceiptHandle=receipt_handle)
