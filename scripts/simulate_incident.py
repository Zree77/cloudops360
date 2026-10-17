import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.logging_config import configure_logging


logger = configure_logging()

BASE_DIR = Path(__file__).resolve().parent.parent
INCIDENT_STATE_FILE = BASE_DIR / "logs" / "simulated_incident.json"


def generate_incident_id():
    """Generate a unique incident identifier."""

    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_part = uuid.uuid4().hex[:8].upper()

    return f"INC-{date_part}-{unique_part}"


def save_simulated_incident(incident_id):
    """Save the current incident ID for the recovery command."""

    INCIDENT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = INCIDENT_STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "incident_id": incident_id,
                "component": "dynamodb",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            file,
            indent=2,
        )

    temporary_file.replace(INCIDENT_STATE_FILE)


def load_simulated_incident():
    """Load the incident ID that should be recovered."""

    if not INCIDENT_STATE_FILE.exists():
        raise RuntimeError(
            "No simulated incident was found. "
            "Run 'python -m scripts.simulate_incident incident' first."
        )

    with INCIDENT_STATE_FILE.open("r", encoding="utf-8-sig") as file:
        incident = json.load(file)

    incident_id = incident.get("incident_id")

    if not incident_id:
        raise RuntimeError(
            "The simulated incident file has no incident ID."
        )

    return incident_id


def simulate_normal_operations():
    """Generate normal application activity."""

    logger.info(
        "Health check successful",
        extra={
            "endpoint": "/health",
            "http_status": 200,
            "response_time_ms": 18,
        },
    )

    logger.info(
        "Task created",
        extra={
            "task_id": "task-1001",
            "task_status": "pending",
            "http_status": 201,
        },
    )

    logger.info(
        "Tasks listed",
        extra={
            "task_count": 4,
            "http_status": 200,
        },
    )


def simulate_incident():
    """Generate a new DynamoDB availability incident."""

    incident_id = generate_incident_id()

    # Persist the ID before logging failures so recovery can reference it.
    save_simulated_incident(incident_id)

    print(f"Generated incident ID: {incident_id}")

    logger.error(
        "Task creation failed",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "operation": "PutItem",
            "error_code": "ServiceUnavailable",
            "http_status": 503,
        },
    )

    logger.error(
        "Task retrieval failed",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "operation": "GetItem",
            "error_code": "ServiceUnavailable",
            "http_status": 503,
        },
    )

    logger.warning(
        "Retry attempt initiated",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "retry_attempt": 1,
        },
    )

    logger.error(
        "Task creation failed after retry",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "operation": "PutItem",
            "error_code": "ServiceUnavailable",
            "http_status": 503,
            "retry_attempt": 1,
        },
    )

    logger.info(
        "Incident simulation completed",
        extra={
            "incident_id": incident_id,
            "component": "simulation",
            "result": "completed",
        },
    )

    print("Incident simulation completed.")
    print(f"Incident ID saved to: {INCIDENT_STATE_FILE}")


def simulate_recovery():
    """Generate recovery events for the most recently simulated incident."""

    incident_id = load_simulated_incident()

    print(f"Recovering incident: {incident_id}")

    logger.info(
        "DynamoDB operation recovered",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "recovery_verified": True,
            "http_status": 200,
        },
    )

    logger.info(
        "Task creation successful after recovery",
        extra={
            "incident_id": incident_id,
            "component": "dynamodb",
            "recovery_verified": True,
            "http_status": 201,
        },
    )

    print("Recovery simulation completed.")


def main():
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "incident"

    if command == "recover":
        simulate_recovery()
        return

    if command != "incident":
        print(
            "Usage: python -m scripts.simulate_incident "
            "[incident|recover]"
        )
        raise SystemExit(2)

    print("Generating normal application activity...")
    simulate_normal_operations()

    time.sleep(1)

    print("Simulating a DynamoDB availability incident...")
    simulate_incident()

    print("Simulation completed.")
    print("Log file: logs/cloudops360.jsonl")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Simulation error: {exc}")
        raise SystemExit(1)