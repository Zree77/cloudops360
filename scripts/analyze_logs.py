import json
from collections import Counter
from pathlib import Path


LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "cloudops360.jsonl"


def load_logs():
    """Read JSONL application logs."""

    events = []

    if not LOG_FILE.exists():
        raise FileNotFoundError(f"Log file not found: {LOG_FILE}")

    with LOG_FILE.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"Skipping invalid JSON on line {line_number}: {exc}")

    return events


def main():
    events = load_logs()

    errors = [
        event for event in events
        if event.get("level") == "ERROR"
    ]

    warnings = [
        event for event in events
        if event.get("level") == "WARNING"
    ]

    component_counts = Counter(
        event.get("component", "unknown")
        for event in errors
    )

    status_counts = Counter(
        str(event["http_status"])
        for event in events
        if "http_status" in event
    )

    incidents = sorted({
        event["incident_id"]
        for event in events
        if "incident_id" in event
    })

    print("\n========== CLOUDOPS360 LOG ANALYSIS ==========")
    print(f"Total events: {len(events)}")
    print(f"Error events: {len(errors)}")
    print(f"Warning events: {len(warnings)}")

    print("\nErrors by component:")
    for component, count in component_counts.items():
        print(f"  {component}: {count}")

    print("\nHTTP status counts:")
    for http_status, count in sorted(status_counts.items()):
        print(f"  HTTP {http_status}: {count}")

    print("\nIncidents found:")
    for incident_id in incidents:
        incident_events = [
            event for event in events
            if event.get("incident_id") == incident_id
        ]

        incident_errors = [
            event for event in incident_events
            if event.get("level") == "ERROR"
        ]

        print(f"\n  Incident: {incident_id}")
        print(f"  Events: {len(incident_events)}")
        print(f"  Errors: {len(incident_errors)}")

        for event in incident_errors:
            print(
                f"    - {event.get('message')} "
                f"(operation={event.get('operation', 'N/A')})"
            )

    print("\n==============================================\n")


if __name__ == "__main__":
    main()