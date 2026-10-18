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
    """Generate a deterministic incident ID."""

    timestamp_part = timestamp.strftime("%Y%m%dT%H%M%S")
    hash_part = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()[:10].upper()

    return f"CW-{timestamp_part}-{hash_part}"


def classify_error(event):
    """Classify application errors and AWS Lambda runtime failures."""

    if event.get("source") != "cloudwatch":
        return None

    log_type = event.get("log_type")
    message = str(event.get("message", "Unknown error"))
    component = str(event.get("component", "cloudops360-api"))

    # Structured application errors.
    if log_type == "application":
        if str(event.get("level", "")).upper() != "ERROR":
            return None

        operation = str(event.get("operation", "unknown"))
        fingerprint = f"{component}:{operation}"

        return {
            "component": component,
            "fingerprint": fingerprint,
            "message": message,
        }

    # Plain-text Lambda runtime failures.
    if log_type == "lambda_system":
        normalized_message = message.lower()

        runtime_failure_patterns = (
            "task timed out",
            "runtime.exiterror",
            "runtime.importmoduleerror",
            "runtime.handlernotfound",
            "runtime.invalidruntime",
            "init error",
            "initialization error",
        )

        matched_pattern = next(
            (
                pattern
                for pattern in runtime_failure_patterns
                if pattern in normalized_message
            ),
            None,
        )

        if matched_pattern is None:
            return None

        return {
            "component": "aws-lambda-runtime",
            "fingerprint": f"aws-lambda-runtime:{matched_pattern}",
            "message": message,
        }

    return None


def classify_recovery(event):
    """
    Classify explicit successful application events as recovery evidence.

    A recovery must identify the same component and operation as the
    incident and must occur after the latest known error.
    """

    if event.get("source") != "cloudwatch":
        return None

    if event.get("log_type") != "application":
        return None

    level = str(event.get("level", "")).upper()
    status = str(event.get("status", "")).lower()
    message = str(event.get("message", "")).lower()

    is_success = (
        level == "INFO"
        and (
            status in {"success", "healthy", "ok"}
            or "operation succeeded" in message
            or "operation successful" in message
        )
    )

    if not is_success:
        return None

    component = str(event.get("component", "cloudops360-api"))
    operation = str(event.get("operation", "unknown"))

    return {
        "component": component,
        "fingerprint": f"{component}:{operation}",
        "message": str(event.get("message", "Operation succeeded")),
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

    timestamped_errors = []
    timestamped_recoveries = []

    # Classify error and recovery events from the normalized log snapshot.
    for event in events:
        timestamp = parse_timestamp(event.get("timestamp"))

        if timestamp is None or timestamp > now:
            continue

        error_classification = classify_error(event)

        if error_classification is not None:
            timestamped_errors.append(
                (timestamp, event, error_classification)
            )
            continue

        recovery_classification = classify_recovery(event)

        if recovery_classification is not None:
            timestamped_recoveries.append(
                (timestamp, event, recovery_classification)
            )

    timestamped_errors.sort(key=lambda item: item[0])
    timestamped_recoveries.sort(key=lambda item: item[0])

    # Index all observed errors by incident key. This includes errors
    # below the opening threshold, so they cannot be ignored during recovery.
    latest_observed_error = {}

    for timestamp, _, classification in timestamped_errors:
        key = incident_key(
            classification["component"],
            classification["fingerprint"],
        )

        previous = latest_observed_error.get(key)

        if previous is None or timestamp > previous:
            latest_observed_error[key] = timestamp

    # Count errors by component and operation inside the detection window.
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
    resolved_this_run = 0

    # Open new incidents or update existing incidents.
    for key, records in qualifying.items():
        latest_timestamp, _, classification = records[-1]
        incident = incidents.get(key)

        if incident and incident.get("status") == "OPEN":
            incident["last_error_at"] = latest_timestamp.isoformat()
            incident["error_count"] = len(records)
            incident["evidence"] = [
                {
                    "timestamp": timestamp.isoformat(),
                    "message": item_classification["message"],
                }
                for timestamp, _, item_classification in records
            ]
            updated_count += 1
            continue

        # Do not reopen a resolved incident with an error that occurred
        # before or at its recorded resolution time.
        if incident and incident.get("status") == "RESOLVED":
            resolved_at = parse_timestamp(incident.get("resolved_at"))

            if (
                resolved_at is not None
                and latest_timestamp <= resolved_at
            ):
                continue

        incident = {
            "incident_id": generate_incident_id(key, latest_timestamp),
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
            f"OPENED: CloudWatch incident {incident['incident_id']} "
            f"for {incident['component']} "
            f"({incident['error_count']} errors)"
        )

    # Resolve only with a matching explicit success event that occurs
    # after the latest known error for that incident.
    for key, incident in incidents.items():
        if incident.get("status") != "OPEN":
            continue

        last_error_at = parse_timestamp(incident.get("last_error_at"))
        observed_error_at = latest_observed_error.get(key)

        if observed_error_at is not None and (
            last_error_at is None or observed_error_at > last_error_at
        ):
            last_error_at = observed_error_at

        if last_error_at is None:
            continue

        component = incident.get("component")
        fingerprint = incident.get("fingerprint")

        matching_recoveries = [
            (timestamp, classification)
            for timestamp, _, classification in timestamped_recoveries
            if timestamp > last_error_at
            and classification["component"] == component
            and classification["fingerprint"] == fingerprint
        ]

        if not matching_recoveries:
            continue

        recovery_timestamp, recovery_classification = matching_recoveries[-1]

        incident["status"] = "RESOLVED"
        incident["resolved_at"] = recovery_timestamp.isoformat()
        incident["resolution_evidence"] = {
            "timestamp": recovery_timestamp.isoformat(),
            "message": recovery_classification["message"],
            "reason": (
                "Matching successful application operation observed "
                "after the latest known error."
            ),
        }

        append_alert({
            "timestamp": now.isoformat(),
            "event": "INCIDENT_RESOLVED",
            **incident,
        })

        resolved_this_run += 1

        print(
            f"RESOLVED: CloudWatch incident {incident['incident_id']} "
            f"after verified operation recovery"
        )

    save_state(state)

    open_count = sum(
        incident.get("status") == "OPEN"
        for incident in incidents.values()
    )

    total_resolved_count = sum(
        incident.get("status") == "RESOLVED"
        for incident in incidents.values()
    )

    print("\n========== CLOUDWATCH INCIDENT DETECTION ==========")
    print(f"CloudWatch events loaded: {len(events)}")
    print(f"Application/runtime error events: {len(timestamped_errors)}")
    print(f"Error threshold: {ERROR_THRESHOLD}")
    print(f"Detection window: {WINDOW_MINUTES} minutes")
    print(f"New incidents opened: {opened_count}")
    print(f"Existing incidents updated: {updated_count}")
    print(f"Incidents resolved this run: {resolved_this_run}")
    print(f"Open CloudWatch incidents: {open_count}")
    print(f"Resolved CloudWatch incidents: {total_resolved_count}")
    print(f"State file: {STATE_FILE}")
    print(f"Alert file: {ALERT_FILE}")
    print("===================================================\n")


if __name__ == "__main__":
    main()
