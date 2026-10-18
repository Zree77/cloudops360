import pytest
from scripts import detect_cloudwatch_incidents as detector

@pytest.fixture(autouse=True)
def prevent_real_sns_during_tests(monkeypatch):
    """Safety guard to guarantee unit tests never publish to real AWS SNS."""
    monkeypatch.setenv("CLOUDOPS360_SNS_NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setattr(detector, "SNS_NOTIFICATIONS_ENABLED", False)
