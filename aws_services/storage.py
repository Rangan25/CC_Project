import logging
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


def _s3_client():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"),
                        config=Config(connect_timeout=2, read_timeout=4, retries={"max_attempts": 1}))


def upload_image(stream, filename, upload_folder):
    bucket = os.getenv("S3_BUCKET")
    if bucket:
        try:
            _s3_client().upload_fileobj(stream, bucket, filename, ExtraArgs={"ContentType": _content_type(filename)})
            logger.info("Stored incident image in S3: %s", filename)
            return f"s3:{filename}"
        except (BotoCoreError, ClientError, NoCredentialsError) as exc:
            logger.warning("S3 image upload failed; using local storage: %s", exc)
            stream.seek(0)

    destination = Path(upload_folder) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    stream.save(str(destination)) if hasattr(stream, "save") else destination.write_bytes(stream.read())
    return f"local:{filename}"


def image_url(key):
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        return None
    try:
        return _s3_client().generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    except (BotoCoreError, ClientError, NoCredentialsError) as exc:
        logger.warning("Could not generate S3 image link: %s", exc)
        return None


def _content_type(filename):
    extension = filename.rsplit(".", 1)[-1].lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(extension, "application/octet-stream")
