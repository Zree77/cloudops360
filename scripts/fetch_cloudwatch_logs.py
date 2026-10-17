import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_FILE = BASE_DIR / "logs" / "cloudwatch_logs.jsonl"

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
LOG_GROUP = os.getenv(
    "CLOUDWATCH_LOG_GROUP",
    "/aws/lambda/cloudops360-dev-api",
)

DEFAULT_LOOKBACK_MINUTES = 60
MAX_EVENTS = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)

logger = logging.getLogger("cloudops360.cloudwatch")


def parse_application_message(message):
    """Parse a structured application log or preserve a Lambda system log."""

    message = message.rstrip("\r\n")

    try:
        parsed = json.loads(message)

        if isinstance(parsed, dict):
            parsed["source"] = "cloudwatch"
            parsed["log_type"] = "application"
            return parsed

    except json.JSONDecodeError:
        pass

    return {
        "source": "cloudwatch",
        "log_type": "lambda_system",
        "message": message,
    }


def fetch_cloudwatch_logs(
    lookback_minutes=DEFAULT_LOOKBACK_MINUTES,
    max_events=MAX_EVENTS,
):
    """Fetch recent Lambda log events and save them locally."""

    if lookback_minutes <= 0:
        raise ValueError("lookback_minutes must be greater than zero.")

    if max_events <= 0:
        raise ValueError("max_events must be greater than zero.")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=lookback_minutes)

    client = boto3.client("logs", region_name=AWS_REGION)

    logger.info("CloudWatch log retrieval started.")
    logger.info("Region: %s", AWS_REGION)
    logger.info("Log group: %s", LOG_GROUP)
    logger.info("Lookback: %s minutes", lookback_minutes)

    try:
        paginator = client.get_paginator("filter_log_events")

        events = []

        pages = paginator.paginate(
            logGroupName=LOG_GROUP,
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            PaginationConfig={
                "PageSize": 100,
            },
        )

        for page in pages:
            for event in page.get("events", []):
                normalized = parse_application_message(
                    event.get("message", "")
                )

                normalized["timestamp"] = datetime.fromtimestamp(
                    event["timestamp"] / 1000,
                    tz=timezone.utc,
                ).isoformat()

                normalized["ingestion_timestamp"] = datetime.fromtimestamp(
                    event["ingestionTime"] / 1000,
                    tz=timezone.utc,
                ).isoformat()

                normalized["log_group"] = LOG_GROUP
                normalized["log_stream"] = event.get("logStreamName")
                normalized["event_id"] = event.get("eventId")

                events.append(normalized)

                if len(events) >= max_events:
                    break

            if len(events) >= max_events:
                logger.warning(
                    "Reached the maximum event limit of %s.",
                    max_events,
                )
                break

    except (BotoCoreError, ClientError) as exc:
        logger.error("CloudWatch retrieval failed: %s", exc)
        raise RuntimeError(
            "Unable to retrieve CloudWatch logs. "
            "Check AWS credentials, permissions, region, and log group."
        ) from exc

    events.sort(key=lambda event: event["timestamp"])

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        for event in events:
            file.write(
                json.dumps(event, ensure_ascii=False, default=str) + "\n"
            )

    logger.info("Events retrieved: %s", len(events))
    logger.info("Output file: %s", OUTPUT_FILE)

    return events


def main():
    try:
        events = fetch_cloudwatch_logs()

    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    application_events = [
        event
        for event in events
        if event.get("log_type") == "application"
    ]

    system_events = [
        event
        for event in events
        if event.get("log_type") == "lambda_system"
    ]

    error_events = [
        event
        for event in application_events
        if str(event.get("level", "")).upper() == "ERROR"
    ]

    print("\n========== CLOUDWATCH LOG SUMMARY ==========")
    print(f"Total events: {len(events)}")
    print(f"Application events: {len(application_events)}")
    print(f"Lambda system events: {len(system_events)}")
    print(f"Application errors: {len(error_events)}")
    print(f"Saved to: {OUTPUT_FILE}")
    print("============================================\n")


if __name__ == "__main__":
    main()