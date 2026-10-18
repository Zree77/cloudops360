import json

from scripts.generate_incident_report import (
    build_recovery_history,
    format_duration,
    is_recovery_verified,
    load_alert_history,
    load_incidents,
)


def test_format_duration():
    assert format_duration(15) == "15s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3661) == "1h 1m 1s"
    assert format_duration(None) == "Unknown"


def test_matching_recovery_event_is_verified():
    incident = {
    "incident_id": "INC-001",
    "component": "dynamodb",
    "status": "RESOLVED",
    "opened_at": "2026-10-17T17:45:06.761327+00:00",
    "resolved_at": "2026-10-17T17:45:22.897800+00:00",
}

    alert_history = [
        {
            "event": "INCIDENT_RESOLVED",
            "incident_id": "INC-001",
            "component": "dynamodb",
            "resolved_at": "2026-10-17T17:45:22.897800+00:00",
        }
    ]

    recovery_events = build_recovery_history(alert_history)

    assert is_recovery_verified(incident, recovery_events) is True


def test_old_recovery_event_does_not_verify_new_resolution():
    incident = {
        "incident_id": "INC-001",
        "component": "dynamodb",
        "status": "RESOLVED",
        "resolved_at": "2026-10-17T17:44:00+00:00",
    }

    alert_history = [
        {
            "event": "INCIDENT_RESOLVED",
            "incident_id": "INC-001",
            "component": "dynamodb",
            "resolved_at": "2026-10-17T17:42:54+00:00",
        }
    ]

    recovery_events = build_recovery_history(alert_history)

    assert is_recovery_verified(incident, recovery_events) is False


def test_open_incident_is_not_verified():
    incident = {
        "incident_id": "INC-002",
        "component": "dynamodb",
        "status": "OPEN",
        "resolved_at": None,
    }

    recovery_events = build_recovery_history([])

    assert is_recovery_verified(incident, recovery_events) is False


def test_malformed_alert_entries_are_ignored():
    alert_history = [
        {
            "event": "INCIDENT_RESOLVED",
            "incident_id": "INC-003",
            "component": "dynamodb",
            "resolved_at": "not-a-timestamp",
        },
        {
            "event": "INCIDENT_OPENED",
            "incident_id": "INC-004",
            "component": "dynamodb",
        },
    ]

    recovery_events = build_recovery_history(alert_history)

    assert recovery_events == {}


def test_load_alert_history_skips_malformed_json(tmp_path, monkeypatch):
    alert_file = tmp_path / "alerts.jsonl"

    alert_file.write_text(
        '{"event": "INCIDENT_OPENED"}\n'
        'this is not valid JSON\n'
        '{"event": "INCIDENT_RESOLVED"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.generate_incident_report.ALERT_FILE",
        alert_file,
    )

    events = load_alert_history()

    assert len(events) == 2


def test_load_incidents_reads_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "incident_state.json"

    state_file.write_text(
        json.dumps(
            {
                "incidents": {
                    "dynamodb:INC-001": {
                        "incident_id": "INC-001",
                        "component": "dynamodb",
                        "status": "OPEN",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.generate_incident_report.STATE_FILE",
        state_file,
    )

    incidents = load_incidents()

    assert len(incidents) == 1
    assert incidents[0]["incident_id"] == "INC-001"