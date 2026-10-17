from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@patch("app.main.tasks_table")
def test_create_task(mock_table):
    response = client.post(
        "/tasks",
        json={
            "title": "Test CloudOps360",
            "description": "Test task creation",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["title"] == "Test CloudOps360"
    assert data["description"] == "Test task creation"
    assert data["status"] == "pending"
    assert "id" in data

    mock_table.put_item.assert_called_once()


@patch("app.main.tasks_table")
def test_get_task(mock_table):
    task_id = str(uuid4())

    mock_table.get_item.return_value = {
        "Item": {
            "task_id": task_id,
            "title": "Retrieve Task",
            "description": "Test task retrieval",
            "status": "pending",
            "created_at": "2026-10-17T10:00:00+00:00",
            "updated_at": "2026-10-17T10:00:00+00:00",
        }
    }

    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["title"] == "Retrieve Task"

    mock_table.get_item.assert_called_once()


@patch("app.main.tasks_table")
def test_update_task(mock_table):
    task_id = str(uuid4())

    original_task = {
        "task_id": task_id,
        "title": "Update Task",
        "description": "Test task update",
        "status": "pending",
        "created_at": "2026-10-17T10:00:00+00:00",
        "updated_at": "2026-10-17T10:00:00+00:00",
    }

    updated_task = {
        **original_task,
        "status": "in_progress",
        "updated_at": "2026-10-17T10:05:00+00:00",
    }

    # First get_item: task exists before the update.
    # Second get_item: return the updated task.
    mock_table.get_item.side_effect = [
        {"Item": original_task},
        {"Item": updated_task},
        {"Item": updated_task},
    ]

    response = client.patch(
        f"/tasks/{task_id}",
        json={"status": "in_progress"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    mock_table.update_item.assert_called_once()
    assert mock_table.get_item.call_count == 2

@patch("app.main.tasks_table")
def test_delete_task(mock_table):
    task_id = str(uuid4())

    response = client.delete(f"/tasks/{task_id}")

    assert response.status_code == 204

    mock_table.delete_item.assert_called_once()


@patch("app.main.tasks_table")
def test_nonexistent_task(mock_table):
    mock_table.get_item.return_value = {}

    response = client.get(
        "/tasks/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404


def test_invalid_task():
    response = client.post(
        "/tasks",
        json={
            "title": "",
            "description": "Invalid task",
        },
    )

    assert response.status_code == 422


@patch("app.main.tasks_table")
def test_list_tasks(mock_table):
    mock_table.scan.return_value = {
        "Items": [
            {
                "task_id": str(uuid4()),
                "title": "Listed Task",
                "description": "Test task listing",
                "status": "pending",
                "created_at": "2026-10-17T10:00:00+00:00",
                "updated_at": "2026-10-17T10:00:00+00:00",
            }
        ]
    }

    response = client.get("/tasks")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Listed Task"

    mock_table.scan.assert_called_once()