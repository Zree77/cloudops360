import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

STATE_FILE = BASE_DIR / "logs" / "incident_state.json"
ALERT_FILE = BASE_DIR / "logs" / "alerts.jsonl"
REPORT_FILE = BASE_DIR / "logs" / "incident_report.txt"


def parse_timestamp(value):
    """Parse an ISO timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value:
        return None

    try:
        timestamp = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def load_incidents():
    """Load incident records from the persisted state file."""

    if not STATE_FILE.exists():
        return []

    try:
        with STATE_FILE.open("r", encoding="utf-8-sig") as file:
            state = json.load(file)

    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read incident state: {exc}"
        ) from exc

    if not isinstance(state, dict):
        raise RuntimeError("Incident state must be a JSON object.")

    incidents = state.get("incidents")

    if not isinstance(incidents, dict):
        raise RuntimeError(
            "Incident state must contain an incidents object."
        )

    return [
        incident
        for incident in incidents.values()
        if isinstance(incident, dict)
    ]


def load_alert_history():
    """Load alert events, skipping malformed JSONL records."""

    if not ALERT_FILE.exists():
        return []

    events = []

    try:
        with ALERT_FILE.open("r", encoding="utf-8-sig") as file:
            for line_number, line in enumerate(file, start=1):
                if not line.strip():
                    continue

                try:
                    event = json.loads(line)

                except json.JSONDecodeError:
                    print(
                        f"Warning: skipping malformed alert event "
                        f"on line {line_number}."
                    )
                    continue

                if isinstance(event, dict):
                    events.append(event)

    except OSError as exc:
        raise RuntimeError(
            f"Unable to read alert history: {exc}"
        ) from exc

    return events


def build_recovery_history(alert_history):
    """
    Index recorded resolution timestamps by component and incident ID.

    A matching incident ID alone is insufficient to verify recovery.
    The resolution timestamp must also match the persisted incident state.
    """

    recovery_events = {}

    for event in alert_history:
        if event.get("event") != "INCIDENT_RESOLVED":
            continue

        incident_id = event.get("incident_id")

        if not incident_id:
            continue

        component = event.get("component", "unknown")
        key = (component, incident_id)

        resolved_at = parse_timestamp(event.get("resolved_at"))

        if resolved_at is None:
            resolved_at = parse_timestamp(event.get("timestamp"))

        if resolved_at is not None:
            recovery_events.setdefault(key, set()).add(resolved_at)

    return recovery_events


def is_recovery_verified(incident, recovery_events):
    """Verify recovery evidence and validate incident chronology."""

    if incident.get("status") != "RESOLVED":
        return False

    opened_at = parse_timestamp(incident.get("opened_at"))
    resolved_at = parse_timestamp(incident.get("resolved_at"))

    # Both timestamps must be valid.
    if opened_at is None or resolved_at is None:
        return False

    # An incident cannot be resolved before it was opened.
    if resolved_at < opened_at:
        return False

    incident_id = incident.get("incident_id")
    component = incident.get("component", "unknown")

    if not incident_id:
        return False

    key = (component, incident_id)

    # A matching recorded resolution event is required.
    return resolved_at in recovery_events.get(key, set())
def calculate_duration(incident, now):
    """Calculate incident duration in seconds."""

    opened_at = parse_timestamp(incident.get("opened_at"))

    if opened_at is None:
        return None

    status = incident.get("status")

    if status == "RESOLVED":
        end_time = parse_timestamp(incident.get("resolved_at"))

        if end_time is None:
            return None

    elif status == "OPEN":
        end_time = now

    else:
        return None

    duration = (end_time - opened_at).total_seconds()

    if duration < 0:
        return None

    return duration


def format_duration(seconds):
    """Format seconds as hours, minutes, and seconds."""

    if seconds is None:
        return "Unknown"

    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def get_error_count(incident):
    """Return a non-negative integer error count."""

    count = incident.get("error_count", 0)

    if isinstance(count, bool):
        return 0

    if isinstance(count, int) and count >= 0:
        return count

    return 0


def generate_report():
    """Generate and save the operational incident summary."""

    incidents = load_incidents()
    alert_history = load_alert_history()
    recovery_events = build_recovery_history(alert_history)

    now = datetime.now(timezone.utc)

    open_incidents = [
        incident
        for incident in incidents
        if incident.get("status") == "OPEN"
    ]

    resolved_incidents = [
        incident
        for incident in incidents
        if incident.get("status") == "RESOLVED"
    ]

    verified_incidents = [
        incident
        for incident in resolved_incidents
        if is_recovery_verified(incident, recovery_events)
    ]

    unverified_incidents = [
        incident
        for incident in resolved_incidents
        if not is_recovery_verified(incident, recovery_events)
    ]

    component_counts = Counter(
        incident.get("component", "unknown")
        for incident in incidents
    )

    status_counts = Counter(
        incident.get("status", "UNKNOWN")
        for incident in incidents
    )

    total_errors = sum(
        get_error_count(incident)
        for incident in incidents
    )

    durations = [
        calculate_duration(incident, now)
        for incident in incidents
    ]

    known_durations = [
        duration
        for duration in durations
        if duration is not None
    ]

    average_duration = (
        sum(known_durations) / len(known_durations)
        if known_durations
        else None
    )

    lines = [
        "=" * 65,
        "CLOUDOPS360 - INCIDENT SUMMARY REPORT",
        "=" * 65,
        f"Report generated (UTC): {now.isoformat()}",
        "",
        "OVERVIEW",
        "-" * 65,
        f"Total incidents:                 {len(incidents)}",
        f"Open incidents:                  {len(open_incidents)}",
        f"Resolved incidents:              {len(resolved_incidents)}",
        f"Verified recoveries:             {len(verified_incidents)}",
        f"Resolved without verified event: {len(unverified_incidents)}",
        f"Recorded error count:            {total_errors}",
        f"Alert history events:            {len(alert_history)}",
        "",
        "INCIDENTS BY COMPONENT",
        "-" * 65,
    ]

    if component_counts:
        for component, count in sorted(component_counts.items()):
            lines.append(f"{component}: {count}")
    else:
        lines.append("No incidents recorded.")

    lines.extend([
        "",
        "INCIDENTS BY STATUS",
        "-" * 65,
    ])

    if status_counts:
        for status, count in sorted(status_counts.items()):
            lines.append(f"{status}: {count}")
    else:
        lines.append("No incident statuses recorded.")

    lines.extend([
        "",
        "INCIDENT DETAILS",
        "-" * 65,
    ])

    if not incidents:
        lines.append("No incident records are available.")

    sorted_incidents = sorted(
        incidents,
        key=lambda incident: (
            incident.get("opened_at")
            if isinstance(incident.get("opened_at"), str)
            else ""
        ),
    )

    for incident in sorted_incidents:
        incident_id = incident.get("incident_id", "Unknown")
        component = incident.get("component", "unknown")
        status = incident.get("status", "UNKNOWN")

        duration = calculate_duration(incident, now)
        recovery_verified = is_recovery_verified(
            incident,
            recovery_events,
        )

        lines.extend([
            f"Incident ID: {incident_id}",
            f"Component: {component}",
            f"Status: {status}",
            f"Opened at: {incident.get('opened_at', 'Unknown')}",
            f"Resolved at: {incident.get('resolved_at') or 'Not resolved'}",
            f"Recorded errors: {get_error_count(incident)}",
            f"Duration: {format_duration(duration)}",
        ])

        if status == "RESOLVED":
            lines.append(
                "Recovery event verified: "
                f"{'Yes' if recovery_verified else 'No'}"
            )

            if not recovery_verified:
                lines.append(
                    "Data quality warning: the incident's resolution "
                    "timestamp does not match a recorded recovery event."
                )

        elif status == "OPEN":
            lines.append("Recovery event verified: No")
            lines.append(
                "Action: investigate the incident and verify recovery."
            )

        else:
            lines.append(
                "Data quality warning: unrecognized incident status."
            )

        lines.append("")

    lines.extend([
        "DURATION SUMMARY",
        "-" * 65,
        f"Incidents with calculable duration: {len(known_durations)}",
        f"Average recorded duration: {format_duration(average_duration)}",
        "",
        "RECOMMENDATIONS",
        "-" * 65,
    ])

    recommendation_number = 1

    if open_incidents:
        lines.append(
            f"{recommendation_number}. Investigate open incidents and "
            "confirm service recovery."
        )
        recommendation_number += 1
    else:
        lines.append(
            f"{recommendation_number}. No open incidents are recorded "
            "in the current state file."
        )
        recommendation_number += 1

    if unverified_incidents:
        lines.append(
            f"{recommendation_number}. Audit resolved incidents without "
            "a matching recovery event."
        )
        recommendation_number += 1

    lines.append(
        f"{recommendation_number}. Review recurring errors and document "
        "root causes and remediation."
    )

    lines.extend([
        "",
        "=" * 65,
        "End of report",
        "=" * 65,
    ])

    report = "\n".join(lines) + "\n"

    try:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(report, encoding="utf-8")

    except OSError as exc:
        raise RuntimeError(
            f"Unable to write incident report: {exc}"
        ) from exc

    print(report)
    print(f"Report saved to: {REPORT_FILE}")


if __name__ == "__main__":
    try:
        generate_report()
    except RuntimeError as exc:
        raise SystemExit(f"Report generation failed: {exc}")