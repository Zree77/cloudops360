import json
from datetime import datetime, timedelta, timezone

import scripts.detect_incidents as detector


def write_jsonl(path, events):
    """Write test events to a temporary JSONL file."""

    with path.open("w", encoding="utf-8") as file:
        for event in events:
            file.write(json.dumps(event) + "\n")


def make_event(timestamp, level, incident_id, **extra):
    """Create a structured application log event."""

    return {
        "timestamp": timestamp.isoformat(),
        "level": level,
        "incident_id": incident_id,
        "component": "dynamodb",
        "message": f"Test event for {incident_id}",
        **extra,
    }


def configure_test_files(monkeypatch, tmp_path):
    """Redirect detector file operations to isolated test files."""

    log_file = tmp_path / "cloudops360.jsonl"
    alert_file = tmp_path / "alerts.jsonl"
    state_file = tmp_path / "incident_state.json"

    monkeypatch.setattr(detector, "LOG_FILE", log_file)
    monkeypatch.setattr(detector, "ALERT_FILE", alert_file)
    monkeypatch.setattr(detector, "STATE_FILE", state_file)

    return log_file, alert_file, state_file


def read_state(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)["incidents"]


def read_alerts(path):
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def test_opens_incident_after_error_threshold(monkeypatch, tmp_path):
    log_file, alert_file, state_file = configure_test_files(
        monkeypatch, tmp_path
    )

    now = datetime.now(timezone.utc)
    incident_id = "INC-TEST-001"

    events = [
        make_event(now - timedelta(seconds=10), "ERROR", incident_id),
        make_event(now - timedelta(seconds=5), "ERROR", incident_id),
    ]

    write_jsonl(log_file, events)

    detector.main()

    incidents = read_state(state_file)
    incident = incidents[f"dynamodb:{incident_id}"]

    assert incident["status"] == "OPEN"
    assert incident["error_count"] == 2

    alerts = read_alerts(alert_file)

    assert len(alerts) == 1
    assert alerts[0]["event"] == "INCIDENT_OPENED"


def test_repeated_execution_does_not_duplicate_open_alert(
    monkeypatch, tmp_path
):
    log_file, alert_file, state_file = configure_test_files(
        monkeypatch, tmp_path
    )

    now = datetime.now(timezone.utc)
    incident_id = "INC-TEST-002"

    write_jsonl(
        log_file,
        [
            make_event(now - timedelta(seconds=10), "ERROR", incident_id),
            make_event(now - timedelta(seconds=5), "ERROR", incident_id),
        ],
    )

    detector.main()
    detector.main()

    alerts = read_alerts(alert_file)

    assert sum(
        event.get("event") == "INCIDENT_OPENED"
        for event in alerts
    ) == 1

    assert read_state(state_file)[f"dynamodb:{incident_id}"]["status"] == "OPEN"


def test_recovery_resolves_open_incident(monkeypatch, tmp_path):
    log_file, alert_file, state_file = configure_test_files(
        monkeypatch, tmp_path
    )

    now = datetime.now(timezone.utc)
    incident_id = "INC-TEST-003"

    write_jsonl(
        log_file,
        [
            make_event(now - timedelta(seconds=20), "ERROR", incident_id),
            make_event(now - timedelta(seconds=10), "ERROR", incident_id),
            make_event(
                now - timedelta(seconds=2),
                "INFO",
                incident_id,
                recovery_verified=True,
            ),
        ],
    )

    detector.main()

    incident = read_state(state_file)[f"dynamodb:{incident_id}"]

    assert incident["status"] == "RESOLVED"
    assert incident["resolved_at"] is not None

    alerts = read_alerts(alert_file)

    assert [
        event["event"] for event in alerts
    ] == ["INCIDENT_OPENED", "INCIDENT_RESOLVED"]


def test_old_recovery_does_not_resolve_new_incident(
    monkeypatch, tmp_path
):
    log_file, alert_file, state_file = configure_test_files(
        monkeypatch, tmp_path
    )

    now = datetime.now(timezone.utc)
    incident_id = "INC-TEST-004"

    write_jsonl(
        log_file,
        [
            make_event(now - timedelta(seconds=30), "ERROR", incident_id),
            make_event(now - timedelta(seconds=25), "ERROR", incident_id),
            make_event(
                now - timedelta(seconds=20),
                "INFO",
                incident_id,
                recovery_verified=True,
            ),
            make_event(now - timedelta(seconds=10), "ERROR", incident_id),
            make_event(now - timedelta(seconds=5), "ERROR", incident_id),
        ],
    )

    detector.main()

    incident = read_state(state_file)[f"dynamodb:{incident_id}"]

    assert incident["status"] == "OPEN"
    assert incident["last_error_at"] == (
        now - timedelta(seconds=5)
    ).isoformat()


def test_incidents_are_tracked_independently(monkeypatch, tmp_path):
    log_file, alert_file, state_file = configure_test_files(
        monkeypatch, tmp_path
    )

    now = datetime.now(timezone.utc)

    events = [
        make_event(now - timedelta(seconds=20), "ERROR", "INC-TEST-A"),
        make_event(now - timedelta(seconds=15), "ERROR", "INC-TEST-A"),
        make_event(now - timedelta(seconds=10), "ERROR", "INC-TEST-B"),
        make_event(now - timedelta(seconds=5), "ERROR", "INC-TEST-B"),
    ]

    write_jsonl(log_file, events)

    detector.main()

    incidents = read_state(state_file)

    assert incidents["dynamodb:INC-TEST-A"]["status"] == "OPEN"
    assert incidents["dynamodb:INC-TEST-B"]["status"] == "OPEN"

    assert sum(
        event.get("event") == "INCIDENT_OPENED"
        for event in read_alerts(alert_file)
    ) == 2
