import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Format application logs as structured JSON."""

    RESERVED_FIELDS = set(
        logging.makeLogRecord({}).__dict__.keys()
    ) | {
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "cloudops360"),
            "environment": os.getenv("APP_ENV", "dev"),
        }

        for key, value in record.__dict__.items():
            if key not in self.RESERVED_FIELDS and key not in log_entry:
                log_entry[key] = value

        if record.exc_info:
            log_entry["exception"] = self.formatException(
                record.exc_info
            )

        return json.dumps(log_entry, default=str)


def configure_logging() -> logging.Logger:
    """Configure JSON logging to the terminal and local file."""

    log_directory = Path(__file__).resolve().parent.parent / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers during module reloads.
    if not any(
        isinstance(handler.formatter, JSONFormatter)
        for handler in root_logger.handlers
    ):
        formatter = JSONFormatter()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)

        file_handler = logging.FileHandler(
            log_directory / "cloudops360.jsonl",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    return logging.getLogger("cloudops360")