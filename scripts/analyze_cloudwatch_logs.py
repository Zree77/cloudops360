import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "logs" / "cloudwatch_logs.jsonl"


def load_logs():
    """Load normalized CloudWatch events from the local JSONL file."""

    if not LOG_FILE.exists():
        raise FileNotFoundError(
            f"CloudWatch log file not found: {LOG_FILE}. "
            "Run scripts/fetch_cloudwatch_logs.py first."
        )

    events = []

    with LOG_FILE.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                event = json.loads(line)

            except json.JSONDecodeError:
                print(
                    f"Skipping malformed JSON on line {line_number}."
                )
                continue

            if isinstance(event, dict):
                events.append(event)

    return events


def main():
    events = load_logs()

    application_events = [
        event for event in events
        if event.get("log_type") == "application"
    ]

    system_events = [
        event for event in events
        if event.get("log_type") == "lambda_system"
    ]

    error_events = [
        event for event in application_events
        if str(event.get("level", "")).upper() == "ERROR"
    ]

    warning_events = [
        event for event in application_events
        if str(event.get("level", "")).upper() == "WARNING"
    ]

    component_counts = Counter(
        event.get("component", "unknown")
        for event in error_events
    )

    message_counts = Counter(
        event.get("message", "Unknown error")
        for event in error_events
    )

    print("\n========== CLOUDOPS360 CLOUDWATCH ANALYSIS ==========")
    print("Source: AWS CloudWatch")
    print(f"Log group: {events[0].get('log_group', 'Unknown') if events else 'No events'}")
    print(f"Total events: {len(events)}")
    print(f"Application events: {len(application_events)}")
    print(f"Lambda system events: {len(system_events)}")
    print(f"Application errors: {len(error_events)}")
    print(f"Application warnings: {len(warning_events)}")

    print("\nErrors by component:")
    if component_counts:
        for component, count in sorted(component_counts.items()):
            print(f"  {component}: {count}")
    else:
        print("  No application errors found.")

    print("\nError messages:")
    if message_counts:
        for message, count in message_counts.most_common():
            print(f"  {message}: {count}")
    else:
        print("  No application error messages found.")

    print("\nRecent application events:")
    for event in application_events[-5:]:
        print(
            f"  [{event.get('timestamp', 'Unknown')}] "
            f"{event.get('level', 'UNKNOWN')}: "
            f"{event.get('message', '')}"
        )

    print("\n======================================================\n")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"CloudWatch analysis failed: {exc}")