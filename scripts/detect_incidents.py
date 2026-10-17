import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LOG_FILE = BASE_DIR / "logs" / "cloudops360.jsonl"
ALERT_FILE = BASE_DIR / "logs" / "alerts.jsonl"
STATE_FILE = BASE_DIR / "logs" / "incident_state.json"

ERROR_THRESHOLD = 2
WINDOW_MINUTES = 5


def load_jsonl(path):
    """Read JSON Lines while skipping malformed records."""

    if not path.exists():
        return []

    records = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON in {path.name}, line {line_number}")

    return records


def parse_timestamp(value):
    """Return a timezone-aware UTC datetime, or None."""

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
    """Load persisted incident state."""

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
            f"Cannot safely read incident state: {exc}"
        ) from exc


def save_state(state):
    """Persist state using an atomic file replacement."""

    temporary_file = STATE_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temporary_file.replace(STATE_FILE)


def append_alert(event):
    """Append one lifecycle event to the alert history."""

    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with ALERT_FILE.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event) + "\n")


def make_key(component, incident_id):
    return f"{component}:{incident_id}"


def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=WINDOW_MINUTES)

    log_events = load_jsonl(LOG_FILE)
    state = load_state()
    incidents = state["incidents"]

    timestamped_events = []

    for event in log_events:
        timestamp = parse_timestamp(event.get("timestamp"))

        if timestamp is not None and timestamp <= now:
            timestamped_events.append((timestamp, event))

    timestamped_events.sort(key=lambda item: item[0])

    # Identify incidents that meet the error threshold in the time window.
    recent_errors = defaultdict(list)

    for timestamp, event in timestamped_events:
        if timestamp < cutoff:
            continue

        if event.get("level") != "ERROR":
            continue

        incident_id = event.get("incident_id")

        if not incident_id:
            continue

        component = event.get("component", "unknown")
        key = make_key(component, incident_id)

        recent_errors[key].append(timestamp)

    qualifying = {
        key: timestamps
        for key, timestamps in recent_errors.items()
        if len(timestamps) >= ERROR_THRESHOLD
    }

    opened_count = 0
    resolved_count = 0

    # Process qualifying failures and recovery events in chronological order.
    for timestamp, event in timestamped_events:
        incident_id = event.get("incident_id")

        if not incident_id:
            continue

        component = event.get("component", "unknown")
        key = make_key(component, incident_id)

        if event.get("level") == "ERROR":
            if key not in qualifying:
                continue

            if timestamp not in qualifying[key]:
                continue

            incident = incidents.get(key)

            if incident and incident.get("status") == "OPEN":
                last_error = parse_timestamp(incident.get("last_error_at"))

                if last_error is None or timestamp > last_error:
                    incident["last_error_at"] = timestamp.isoformat()

                incident["error_count"] = len(qualifying[key])
                continue

            if incident and incident.get("status") == "RESOLVED":
                resolved_at = parse_timestamp(incident.get("resolved_at"))

                if resolved_at and timestamp <= resolved_at:
                    continue

            incident = {
                "incident_id": incident_id,
                "component": component,
                "status": "OPEN",
                "opened_at": timestamp.isoformat(),
                "resolved_at": None,
                "last_error_at": timestamp.isoformat(),
                "error_count": len(qualifying[key]),
            }

            incidents[key] = incident

            append_alert({
                "timestamp": timestamp.isoformat(),
                "event": "INCIDENT_OPENED",
                **incident,
            })

            opened_count += 1
            print(f"OPENED: {component} incident {incident_id}")

        elif event.get("recovery_verified") is True:
            incident = incidents.get(key)

            if not incident or incident.get("status") != "OPEN":
                continue

            last_error = parse_timestamp(incident.get("last_error_at"))

            if last_error is None or timestamp <= last_error:
                continue

            incident["status"] = "RESOLVED"
            incident["resolved_at"] = timestamp.isoformat()

            append_alert({
                "timestamp": timestamp.isoformat(),
                "event": "INCIDENT_RESOLVED",
                **incident,
            })

            resolved_count += 1
            print(f"RESOLVED: {component} incident {incident_id}")

    # Preserve existing state. Do not silently rewrite inconsistent history.
    save_state(state)

    open_count = sum(
        incident.get("status") == "OPEN"
        for incident in incidents.values()
    )

    resolved_total = sum(
        incident.get("status") == "RESOLVED"
        for incident in incidents.values()
    )

    print(f"\nLog events analyzed: {len(log_events)}")
    print(f"New incidents opened: {opened_count}")
    print(f"Incidents resolved this run: {resolved_count}")
    print(f"Open incidents: {open_count}")
    print(f"Resolved incidents: {resolved_total}")
    print(f"State saved to: {STATE_FILE}")


if __name__ == "__main__":
    main()