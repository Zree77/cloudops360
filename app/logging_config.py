import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    RESERVED_FIELDS = set(
        logging.LogRecord(
            name="",
            level=0,
            pathname="",
            lineno=0,
            msg="",
            args=(),
            exc_info=None,
        ).__dict__.keys()
    )

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "cloudops360",
            "environment": os.getenv("ENVIRONMENT", "development"),
        }

        for key, value in record.__dict__.items():
            if key not in self.RESERVED_FIELDS and not key.startswith("_"):
                log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def configure_logging() -> logging.Logger:
    """Configure structured logging for local development and AWS Lambda."""

    logger = logging.getLogger("cloudops360")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Avoid adding duplicate handlers if configuration is called repeatedly.
    if logger.handlers:
        return logger

    formatter = JsonFormatter()

    # Console logging works locally and in AWS Lambda.
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Local development can additionally write logs to a file.
    # Lambda uses CloudWatch and must not write under /var/task.
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return logger

    log_directory = Path(__file__).resolve().parent.parent / "logs"

    try:
        log_directory.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            log_directory / "cloudops360.jsonl",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    except OSError:
        # Keep console logging operational if local file logging is unavailable.
        logger.warning(
            "File logging is unavailable; continuing with console logging."
        )

    return logger