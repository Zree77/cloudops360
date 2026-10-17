import json
from datetime import datetime, timedelta, timezone

from scripts import detect_cloudwatch_incidents as detector


def make_error(timestamp, operation="get_task", message="Database operation failed"):
    return {
        "source": "cloudwatch",
        "log_type": "application",
        "level": "ERROR",
        "component": "dynamodb",
        "operation": operation,
        "message": message,
        "timestamp": timestamp.isoformat(),
    }


def prepare_files(tmp_path, monkeypatch, events):
    log_file = tmp_path / "cloudwatch_logs.jsonl"
    state_file = tmp_path / "cloudwatch_incident_state.json"
    alert_file = tmp_path / "cloudwatch_alerts.jsonl"

    with log_file.open("w", encoding="utf-8") as file:
        for event in events:
            file.write(json.dumps(event) + "\n")

    monkeypatch.setattr(detector, "LOG_FILE", log_file)
    monkeypatch.setattr(detector, "STATE_FILE", state_file)
    monkeypatch.setattr(detector, "ALERT_FILE", alert_file)

    monkeypatch.setattr(detector, "ERROR_THRESHOLD", 2)
    monkeypatch.setattr(detector, "WINDOW_MINUTES", 5)

    return state_file, alert_file


def test_two_recent_errors_open_incident(tmp_path, monkeypatch, capsys):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
    ]

    state_file, alert_file = prepare_files(
        tmp_path, monkeypatch, events
    )

    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    alerts = [
        json.loads(line)
        for line in alert_file.read_text(encoding="utf-8").splitlines()
    ]

    assert len(state["incidents"]) == 1

    incident = next(iter(state["incidents"].values()))

    assert incident["status"] == "OPEN"
    assert incident["error_count"] == 2
    assert len(alerts) == 1
    assert alerts[0]["event"] == "INCIDENT_OPENED"

    assert "New incidents opened: 1" in capsys.readouterr().out


def test_single_error_does_not_open_incident(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    state_file, alert_file = prepare_files(
        tmp_path,
        monkeypatch,
        [make_error(now - timedelta(minutes=1))],
    )

    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert state["incidents"] == {}
    assert not alert_file.exists()


def test_old_errors_outside_window_are_ignored(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=10)),
        make_error(now - timedelta(minutes=8)),
    ]

    state_file, alert_file = prepare_files(
        tmp_path, monkeypatch, events
    )

    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert state["incidents"] == {}
    assert not alert_file.exists()


def test_non_cloudwatch_and_non_error_events_are_ignored(
    tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
        {
            **make_error(now - timedelta(seconds=30)),
            "source": "local",
        },
        {
            **make_error(now - timedelta(seconds=20)),
            "level": "INFO",
        },
        {
            **make_error(now - timedelta(seconds=10)),
            "log_type": "lambda_system",
        },
    ]

    state_file, alert_file = prepare_files(
        tmp_path, monkeypatch, events
    )

    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))

    assert len(state["incidents"]) == 1

    incident = next(iter(state["incidents"].values()))

    assert incident["error_count"] == 2
    assert alert_file.exists()


def test_repeated_execution_does_not_duplicate_open_alert(
    tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
    ]

    state_file, alert_file = prepare_files(
        tmp_path, monkeypatch, events
    )

    detector.main()
    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    alerts = [
        json.loads(line)
        for line in alert_file.read_text(encoding="utf-8").splitlines()
    ]

    assert len(state["incidents"]) == 1
    assert len(alerts) == 1
    assert alerts[0]["event"] == "INCIDENT_OPENED"