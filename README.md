# Cloud Incident Reporter

A small Flask incident-management dashboard with SQLite storage and optional AWS integrations. It runs locally without AWS credentials and can be deployed to an EC2 instance.

## Features

- Dashboard metrics for total, open (pending/in progress), and resolved incidents.
- Incident submission with reporter contact, category, priority, location, description, and optional image.
- Search and status filtering, incident details, and status updates.
- AWS service health checks for EC2, S3, SQS, and SNS.
- Local SQLite and file-storage fallback; optional S3 uploads, SQS work queue, SNS notifications, and CloudWatch Logs.

## Run locally

1. Install Python 3.10+.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set `FLASK_SECRET_KEY` to a random value (optional for a local-only demo). Flask and the background worker load this file automatically.
4. Start the server:

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

5. Open http://127.0.0.1:5000. The SQLite database and local image uploads are created under `instance/` on first run.

The admin status controls are intentionally available in this starter application without authentication. Add login/authorization before exposing it publicly.

## Tests

Run the smoke and route tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## AWS architecture and configuration

The AWS integrations are split into `aws_services/` modules so each is easy to adapt:

- `storage.py`: uploads images to the bucket in `S3_BUCKET`; falls back to local disk if S3 is unset or unavailable.
- `queue.py`: sends a JSON incident record to `SQS_QUEUE_URL`. Run `python worker.py` as a separate worker to consume messages and send submission notifications. The app sends notifications itself when SQS is not configured or unavailable.
- `notifications.py`: publishes incident-submitted/resolved messages to `SNS_TOPIC_ARN`; without SNS it logs a local notification.
- `monitoring.py`: configures standard application logs and optionally streams them to CloudWatch Logs when `CLOUDWATCH_LOG_GROUP` is set. The dashboard checks connectivity to EC2, S3, SQS, and SNS.

Set `AWS_REGION` and the resource variables from `.env.example`. The application uses the standard Boto3 credential chain. On EC2, attach an instance profile/role with least-privilege permissions for the bucket, queue, topic, and CloudWatch log group. Do not commit access keys or `.env` files. Keep the S3 bucket private; incident image links use short-lived presigned URLs. Configure the SNS topic subscription and confirm its email endpoint before relying on delivery.

### Suggested IAM permissions

Grant only actions needed by your selected setup: `s3:PutObject`, `s3:GetObject`, and `s3:HeadBucket` for the bucket; `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, and `sqs:GetQueueAttributes` for the queue; `sns:Publish` and `sns:GetTopicAttributes` for the topic; and `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs. The EC2 health check calls `ec2:DescribeRegions`. Scope resources and actions to your deployment as tightly as practical.

### EC2 deployment outline

1. Launch a Linux EC2 instance, install Python 3 and Git, and attach an instance role with the permissions above. Restrict inbound traffic to SSH from trusted addresses and HTTPS through a load balancer or reverse proxy.
2. Clone this project, create a virtual environment, and install `requirements.txt`. Copy `.env.example` to `.env`; set a strong `FLASK_SECRET_KEY`, the region, S3 bucket, SQS queue URL, SNS topic ARN, and optional CloudWatch log group.
3. Run the web process with `gunicorn --workers 2 --bind 127.0.0.1:8000 app:app` (the included `Procfile` shows the process command). Put Nginx or an AWS load balancer with TLS in front of Gunicorn; do not expose the Flask development server to the internet.
4. Run `python worker.py` as a separate supervised process (for example, a systemd service) when SQS is enabled. Keep the web and worker processes on the instance role and monitor their output in CloudWatch Logs.
5. Confirm the SNS email subscription, then submit a test incident and verify the image in S3, queue processing, notification, and CloudWatch log events.

For production, secure admin routes with authentication and use a managed database if multiple app instances need shared data. SQLite and the local upload fallback are intended for local development or a single-instance demo.
