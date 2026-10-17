from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


# Temporary in-memory storage.
# We will replace this with DynamoDB later.
tasks: dict[UUID, dict] = {}


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class TaskUpdate(BaseModel):
    status: Literal["pending", "in_progress", "completed"]


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: Literal["pending", "in_progress", "completed"]
    created_at: datetime
    updated_at: datetime


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("CloudOps360 API starting...")
    yield
    print("CloudOps360 API shutting down...")


app = FastAPI(
    title="CloudOps360 API",
    description="Serverless task management and operations platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "application": "CloudOps360",
        "message": "Welcome to CloudOps360 API",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "application": "CloudOps360",
    }


@app.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(payload: TaskCreate):
    now = datetime.now(timezone.utc)
    task_id = uuid4()

    task = {
        "id": task_id,
        "title": payload.title,
        "description": payload.description,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }

    tasks[task_id] = task
    return task


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks():
    return list(tasks.values())


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: UUID):
    task = tasks.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return task


@app.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: UUID, payload: TaskUpdate):
    task = tasks.get(task_id)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task["status"] = payload.status
    task["updated_at"] = datetime.now(timezone.utc)

    return task


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task(task_id: UUID):
    task = tasks.pop(task_id, None)

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return None