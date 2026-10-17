from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_task():
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


def test_get_task():
    create_response = client.post(
        "/tasks",
        json={
            "title": "Retrieve Task",
            "description": "Test task retrieval",
        },
    )

    task_id = create_response.json()["id"]

    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    assert response.json()["id"] == task_id
    assert response.json()["title"] == "Retrieve Task"


def test_update_task():
    create_response = client.post(
        "/tasks",
        json={
            "title": "Update Task",
            "description": "Test task update",
        },
    )

    task_id = create_response.json()["id"]

    response = client.patch(
        f"/tasks/{task_id}",
        json={"status": "in_progress"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_delete_task():
    create_response = client.post(
        "/tasks",
        json={
            "title": "Delete Task",
            "description": "Test task deletion",
        },
    )

    task_id = create_response.json()["id"]

    response = client.delete(f"/tasks/{task_id}")

    assert response.status_code == 204

    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 404


def test_nonexistent_task():
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