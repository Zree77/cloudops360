import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_FILE = BASE_DIR / "logs" / "cloudwatch_logs.jsonl"

# Keep real AWS incidents separate from simulated incidents.
ALERT_FILE = BASE_DIR / "logs" / "cloudwatch_alerts.jsonl"
STATE_FILE = BASE_DIR / "logs" / "cloudwatch_incident_state.json"

ERROR_THRESHOLD = int(os.getenv("CLOUDWATCH_ERROR_THRESHOLD", "2"))
WINDOW_MINUTES = int(os.getenv("CLOUDWATCH_WINDOW_MINUTES", "5"))


def load_jsonl(path):
    """Load JSONL records, skipping malformed entries."""

    if not path.exists():
        return []

    records = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)

            except json.JSONDecodeError:
                print(
                    f"Warning: skipping malformed JSON in "
                    f"{path.name}, line {line_number}."
                )
                continue

            if isinstance(record, dict):
                records.append(record)

    return records


def parse_timestamp(value):
    """Parse an ISO timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value:
        return None

    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def load_state():
    """Load persisted CloudWatch incident state."""

    if not STATE_FILE.exists():
        return {"incidents": {}}

    try:
        with STATE_FILE.open("r", encoding="utf-8-sig") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            raise ValueError("State must be a JSON object.")

        if not isinstance(state.get("incidents"), dict):
            raise ValueError("The incidents field must be an object.")

        return state

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely read CloudWatch incident state: {exc}"
        ) from exc


def save_state(state):
    """Atomically save CloudWatch incident state."""

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temporary_file.replace(STATE_FILE)


def append_alert(event):
    """Append an incident lifecycle event to CloudWatch alert history."""

    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with ALERT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, default=str) + "\n")


def incident_key(component, fingerprint):
    """Build a stable key for an incident type."""

    return f"{component}:{fingerprint}"


def generate_incident_id(key, timestamp):
    """
    Generate a deterministic incident ID.

    The SHA-256 suffix is stable for the same incident key.
    The timestamp distinguishes incidents opened at different times.
    """

    timestamp_part = timestamp.strftime("%Y%m%dT%H%M%S")
    hash_part = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()[:10].upper()

    return f"CW-{timestamp_part}-{hash_part}"


def classify_error(event):
    """Classify a normalized CloudWatch application error."""

    if event.get("source") != "cloudwatch":
        return None

    if event.get("log_type") != "application":
        return None

    if str(event.get("level", "")).upper() != "ERROR":
        return None

    message = str(event.get("message", "Unknown error"))
    component = str(event.get("component", "cloudops360-api"))
    operation = str(event.get("operation", "unknown"))

    # Group repeated failures by component and operation.
    fingerprint = f"{component}:{operation}"

    return {
        "component": component,
        "fingerprint": fingerprint,
        "message": message,
    }


def main():
    if ERROR_THRESHOLD < 1:
        raise SystemExit("CLOUDWATCH_ERROR_THRESHOLD must be at least 1.")

    if WINDOW_MINUTES < 1:
        raise SystemExit("CLOUDWATCH_WINDOW_MINUTES must be at least 1.")

    events = load_jsonl(LOG_FILE)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=WINDOW_MINUTES)

    state = load_state()
    incidents = state["incidents"]

    # Analyze actual normalized CloudWatch application ERROR events.
    timestamped_errors = []

    for event in events:
        classification = classify_error(event)

        if classification is None:
            continue

        timestamp = parse_timestamp(event.get("timestamp"))

        if timestamp is None or timestamp > now:
            continue

        timestamped_errors.append(
            (timestamp, event, classification)
        )

    timestamped_errors.sort(key=lambda item: item[0])

    # Count errors by component and operation within the time window.
    recent_errors = defaultdict(list)

    for timestamp, event, classification in timestamped_errors:
        if timestamp < cutoff:
            continue

        key = incident_key(
            classification["component"],
            classification["fingerprint"],
        )

        recent_errors[key].append(
            (timestamp, event, classification)
        )

    qualifying = {
        key: records
        for key, records in recent_errors.items()
        if len(records) >= ERROR_THRESHOLD
    }

    opened_count = 0
    updated_count = 0

    for key, records in qualifying.items():
        latest_timestamp, _, classification = records[-1]

        incident = incidents.get(key)

        # Update an existing open incident without duplicating its alert.
        if incident and incident.get("status") == "OPEN":
            incident["last_error_at"] = latest_timestamp.isoformat()
            incident["error_count"] = len(records)
            updated_count += 1
            continue

        # Do not reopen a resolved incident using errors that occurred
        # before or at its recorded resolution time.
        if incident and incident.get("status") == "RESOLVED":
            resolved_at = parse_timestamp(
                incident.get("resolved_at")
            )

            if (
                resolved_at is not None
                and latest_timestamp <= resolved_at
            ):
                continue

        incident = {
            "incident_id": generate_incident_id(
                key,
                latest_timestamp,
            ),
            "source": "cloudwatch",
            "component": classification["component"],
            "fingerprint": classification["fingerprint"],
            "status": "OPEN",
            "opened_at": latest_timestamp.isoformat(),
            "resolved_at": None,
            "last_error_at": latest_timestamp.isoformat(),
            "error_count": len(records),
            "window_minutes": WINDOW_MINUTES,
            "threshold": ERROR_THRESHOLD,
            "evidence": [
                {
                    "timestamp": timestamp.isoformat(),
                    "message": item_classification["message"],
                }
                for timestamp, _, item_classification in records
            ],
        }

        incidents[key] = incident

        append_alert({
            "timestamp": now.isoformat(),
            "event": "INCIDENT_OPENED",
            **incident,
        })

        opened_count += 1

        print(
            f"OPENED: CloudWatch incident "
            f"{incident['incident_id']} "
            f"for {incident['component']} "
            f"({incident['error_count']} errors)"
        )

    save_state(state)

    open_count = sum(
        incident.get("status") == "OPEN"
        for incident in incidents.values()
    )

    resolved_count = sum(
        incident.get("status") == "RESOLVED"
        for incident in incidents.values()
    )

    print("\n========== CLOUDWATCH INCIDENT DETECTION ==========")
    print(f"CloudWatch events loaded: {len(events)}")
    print(f"Application error events: {len(timestamped_errors)}")
    print(f"Error threshold: {ERROR_THRESHOLD}")
    print(f"Detection window: {WINDOW_MINUTES} minutes")
    print(f"New incidents opened: {opened_count}")
    print(f"Existing incidents updated: {updated_count}")
    print(f"Open CloudWatch incidents: {open_count}")
    print(f"Resolved CloudWatch incidents: {resolved_count}")
    print(f"State file: {STATE_FILE}")
    print(f"Alert file: {ALERT_FILE}")
    print("===================================================\n")


if __name__ == "__main__":
    main()