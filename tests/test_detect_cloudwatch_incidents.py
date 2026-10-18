import json
from datetime import datetime, timedelta, timezone

from scripts import detect_cloudwatch_incidents as detector
import subprocess
import sys

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
def test_incident_id_is_stable_across_processes():
    code = (
        "from datetime import datetime, timezone; "
        "from scripts.detect_cloudwatch_incidents import generate_incident_id; "
        "print(generate_incident_id("
        "'dynamodb:dynamodb:get_task', "
        "datetime(2026, 10, 18, tzinfo=timezone.utc)))"
    )

    first = subprocess.check_output(
        [sys.executable, "-c", code],
        text=True,
    ).strip()

    second = subprocess.check_output(
        [sys.executable, "-c", code],
        text=True,
    ).strip()

    assert first == second
    assert first.startswith("CW-20261018T000000-")
    assert len(first.split("-")[-1]) == 10

def test_lambda_timeout_is_classified():
    event = {
        "source": "cloudwatch",
        "log_type": "lambda_system",
        "message": "Task timed out after 15.00 seconds",
    }

    result = detector.classify_error(event)

    assert result is not None
    assert result["component"] == "aws-lambda-runtime"
    assert "task timed out" in result["fingerprint"]


def test_lambda_runtime_exit_error_is_classified():
    event = {
        "source": "cloudwatch",
        "log_type": "lambda_system",
        "message": "Runtime.ExitError: Runtime exited with error",
    }

    result = detector.classify_error(event)

    assert result is not None
    assert result["component"] == "aws-lambda-runtime"
    assert "runtime.exiterror" in result["fingerprint"]


def test_lambda_import_module_error_is_classified():
    event = {
        "source": "cloudwatch",
        "log_type": "lambda_system",
        "message": "Runtime.ImportModuleError: No module named 'missing_module'",
    }

    result = detector.classify_error(event)

    assert result is not None
    assert "runtime.importmoduleerror" in result["fingerprint"]


def test_normal_lambda_system_message_is_ignored():
    event = {
        "source": "cloudwatch",
        "log_type": "lambda_system",
        "message": "REPORT RequestId: abc Duration: 12.5 ms",
    }

    assert detector.classify_error(event) is None


def test_local_runtime_error_is_ignored():
    event = {
        "source": "local",
        "log_type": "lambda_system",
        "message": "Task timed out after 15.00 seconds",
    }

    assert detector.classify_error(event) is None

def test_verified_recovery_resolves_open_incident(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
        {
            "source": "cloudwatch",
            "log_type": "application",
            "level": "INFO",
            "component": "dynamodb",
            "operation": "get_task",
            "status": "success",
            "message": "Operation succeeded",
            "timestamp": now.isoformat(),
        },
    ]

    state_file, alert_file = prepare_files(tmp_path, monkeypatch, events)
    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    incident = next(iter(state["incidents"].values()))

    assert incident["status"] == "RESOLVED"
    assert incident["resolved_at"] is not None

    alerts = [
        json.loads(line)
        for line in alert_file.read_text(encoding="utf-8").splitlines()
    ]
    assert any(a["event"] == "INCIDENT_OPENED" for a in alerts)
    assert any(a["event"] == "INCIDENT_RESOLVED" for a in alerts)


def test_incident_stays_open_without_recovery_evidence(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
    ]

    state_file, _ = prepare_files(tmp_path, monkeypatch, events)
    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    incident = next(iter(state["incidents"].values()))

    assert incident["status"] == "OPEN"
    assert incident["resolved_at"] is None


def test_stale_recovery_does_not_resolve_incident(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)

    events = [
        {
            "source": "cloudwatch",
            "log_type": "application",
            "level": "INFO",
            "component": "dynamodb",
            "operation": "get_task",
            "status": "success",
            "message": "Operation succeeded",
            "timestamp": (now - timedelta(minutes=3)).isoformat(),
        },
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
    ]

    state_file, _ = prepare_files(tmp_path, monkeypatch, events)
    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    incident = next(iter(state["incidents"].values()))

    assert incident["status"] == "OPEN"
    assert incident["resolved_at"] is None


def test_unrelated_operation_recovery_does_not_resolve_incident(
    tmp_path, monkeypatch
):
    now = datetime.now(timezone.utc)

    events = [
        make_error(now - timedelta(minutes=2)),
        make_error(now - timedelta(minutes=1)),
        {
            "source": "cloudwatch",
            "log_type": "application",
            "level": "INFO",
            "component": "dynamodb",
            "operation": "delete_task",
            "status": "success",
            "message": "Operation succeeded",
            "timestamp": now.isoformat(),
        },
    ]

    state_file, _ = prepare_files(tmp_path, monkeypatch, events)
    detector.main()

    state = json.loads(state_file.read_text(encoding="utf-8"))
    incident = next(iter(state["incidents"].values()))

    assert incident["status"] == "OPEN"
    assert incident["resolved_at"] is None