
import logging
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-2")

AWS_CONFIG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "standard"}
)


def _logs_client():
    return boto3.client(
        "logs",
        region_name=AWS_REGION,
        config=AWS_CONFIG
    )


def configure_logging():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout
    )

    group = os.getenv("CLOUDWATCH_LOG_GROUP")

    if group:
        try:
            handler = CloudWatchLogHandler(
                group,
                os.getenv("CLOUDWATCH_LOG_STREAM", "cloud-incident-reporter")
            )

            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            ))

            logging.getLogger().addHandler(handler)
            logging.getLogger(__name__).info(
                "CloudWatch logging enabled: %s", group
            )

        except (BotoCoreError, ClientError, NoCredentialsError) as exc:
            logging.getLogger(__name__).warning(
                "CloudWatch unavailable; using local logs: %s", exc
            )


class CloudWatchLogHandler(logging.Handler):

    def __init__(self, group, stream):
        super().__init__()

        self.client = _logs_client()
        self.group = group
        self.stream = stream

        try:
            self.client.create_log_group(logGroupName=group)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceAlreadyExistsException":
                raise

        try:
            self.client.create_log_stream(
                logGroupName=group,
                logStreamName=stream
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceAlreadyExistsException":
                raise

    def emit(self, record):
        try:
            self.client.put_log_events(
                logGroupName=self.group,
                logStreamName=self.stream,
                logEvents=[{
                    "timestamp": int(record.created * 1000),
                    "message": self.format(record)
                }]
            )
        except (BotoCoreError, ClientError, NoCredentialsError):
            self.handleError(record)


def _check(label, configured, check):
    if not configured:
        return {
            "name": label,
            "state": "Local",
            "detail": "Not configured — local mode is active"
        }

    try:
        check()
        return {
            "name": label,
            "state": "Connected",
            "detail": "AWS API responded successfully"
        }

    except (BotoCoreError, ClientError, NoCredentialsError, KeyError) as exc:
        code = getattr(exc, "response", {}).get(
            "Error", {}
        ).get("Code", type(exc).__name__)

        return {
            "name": label,
            "state": "Issue",
            "detail": str(code)
        }


def get_aws_status():
    region = AWS_REGION
    config = Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 2, "mode": "standard"}
    )

    aws_configured = any(os.getenv(key) for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_PROFILE",
        "S3_BUCKET",
        "SQS_QUEUE_URL",
        "SNS_TOPIC_ARN",
        "CLOUDWATCH_LOG_GROUP",
    ))

    return [
        _check(
            "EC2",
            aws_configured,
            lambda: boto3.client(
                "ec2", region_name=region, config=config
            ).describe_regions(RegionNames=[region])
        ),

        _check(
            "S3",
            bool(os.getenv("S3_BUCKET")),
            lambda: boto3.client(
                "s3", region_name=region, config=config
            ).head_bucket(Bucket=os.environ["S3_BUCKET"])
        ),

        _check(
            "SQS",
            bool(os.getenv("SQS_QUEUE_URL")),
            lambda: boto3.client(
                "sqs", region_name=region, config=config
            ).get_queue_attributes(
                QueueUrl=os.environ["SQS_QUEUE_URL"],
                AttributeNames=["QueueArn"]
            )
        ),

        _check(
            "SNS",
            bool(os.getenv("SNS_TOPIC_ARN")),
            lambda: boto3.client(
                "sns", region_name=region, config=config
            ).get_topic_attributes(
                TopicArn=os.environ["SNS_TOPIC_ARN"]
            )
        ),

        _check(
            "CloudWatch",
            bool(os.getenv("CLOUDWATCH_LOG_GROUP")),
            lambda: _logs_client().describe_log_groups(
                logGroupNamePrefix=os.environ["CLOUDWATCH_LOG_GROUP"],
                limit=1
            )
        )
    ]
