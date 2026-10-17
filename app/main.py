import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from mangum import Mangum

from app.logging_config import configure_logging

logger = configure_logging()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DYNAMODB_TABLE = os.getenv(
    "DYNAMODB_TABLE",
    "cloudops360-dev-tasks",
)

# Use the standard AWS credential provider chain.
# Locally, credentials can come from the AWS CLI.
# On Lambda, credentials come from the execution role.
dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
)

tasks_table = dynamodb.Table(DYNAMODB_TABLE)


# --------------------------------------------------
# Request and response models
# --------------------------------------------------

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


# --------------------------------------------------
# Helper functions
# --------------------------------------------------

def get_task_or_404(task_id: UUID) -> dict:
    """Retrieve a task from DynamoDB or raise an HTTP error."""

    try:
        response = tasks_table.get_item(
            Key={"task_id": str(task_id)}
        )

    except ClientError as exc:
        logger.exception(
            "DynamoDB get_item failed",
            extra={"task_id": str(task_id)},
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to retrieve task from storage",
        ) from exc

    task = response.get("Item")

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    return {
        "id": task["task_id"],
        "title": task["title"],
        "description": task.get("description", ""),
        "status": task["status"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


# --------------------------------------------------
# Application lifecycle
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "CloudOps360 API starting",
        extra={
            "aws_region": AWS_REGION,
            "dynamodb_table": DYNAMODB_TABLE,
        },
    )

    yield

    logger.info("CloudOps360 API shutting down")


app = FastAPI(
    title="CloudOps360 API",
    description="Serverless task management and operations platform",
    version="0.3.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# Root and health endpoints
# --------------------------------------------------

@app.get("/")
def root():
    logger.info("Root endpoint requested")

    return {
        "application": "CloudOps360",
        "message": "Welcome to CloudOps360 API",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    logger.info("Health check requested")

    return {
        "status": "healthy",
        "application": "CloudOps360",
    }


# --------------------------------------------------
# Create task
# --------------------------------------------------

@app.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(payload: TaskCreate):
    now = datetime.now(timezone.utc)
    task_id = uuid4()

    task = {
        "task_id": str(task_id),
        "title": payload.title,
        "description": payload.description,
        "status": "pending",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    try:
        tasks_table.put_item(
            Item=task,
            ConditionExpression="attribute_not_exists(task_id)",
        )

    except ClientError as exc:
        logger.exception(
            "DynamoDB put_item failed",
            extra={"task_id": str(task_id)},
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to save task",
        ) from exc

    logger.info(
        "Task created",
        extra={
            "task_id": str(task_id),
            "task_status": task["status"],
        },
    )

    return {
        "id": task["task_id"],
        "title": task["title"],
        "description": task["description"],
        "status": task["status"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


# --------------------------------------------------
# List tasks
# --------------------------------------------------

@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks():
    try:
        response = tasks_table.scan()
        items = response.get("Items", [])

        # Retrieve subsequent pages if the table contains
        # more items than can be returned in one scan.
        while "LastEvaluatedKey" in response:
            response = tasks_table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )

            items.extend(response.get("Items", []))

    except ClientError as exc:
        logger.exception("DynamoDB scan failed")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to list tasks",
        ) from exc

    logger.info(
        "Tasks listed",
        extra={"task_count": len(items)},
    )

    return [
        {
            "id": item["task_id"],
            "title": item["title"],
            "description": item.get("description", ""),
            "status": item["status"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
        }
        for item in items
    ]


# --------------------------------------------------
# Retrieve individual task
# --------------------------------------------------

@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: UUID):
    task = get_task_or_404(task_id)

    logger.info(
        "Task retrieved",
        extra={"task_id": str(task_id)},
    )

    return task


# --------------------------------------------------
# Update task
# --------------------------------------------------

@app.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: UUID, payload: TaskUpdate):
    # Check whether the task exists before updating it.
    get_task_or_404(task_id)

    try:
        tasks_table.update_item(
            Key={"task_id": str(task_id)},
            UpdateExpression=(
                "SET #task_status = :new_status, "
                "updated_at = :updated_at"
            ),
            ExpressionAttributeNames={
                "#task_status": "status",
            },
            ExpressionAttributeValues={
                ":new_status": payload.status,
                ":updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_exists(task_id)",
        )

    except ClientError as exc:
        logger.exception(
            "DynamoDB update_item failed",
            extra={"task_id": str(task_id)},
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to update task",
        ) from exc

    updated_task = get_task_or_404(task_id)

    logger.info(
        "Task status updated",
        extra={
            "task_id": str(task_id),
            "task_status": updated_task["status"],
        },
    )

    return updated_task


# --------------------------------------------------
# Delete task
# --------------------------------------------------

@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task(task_id: UUID):
    try:
        tasks_table.delete_item(
            Key={"task_id": str(task_id)},
            ConditionExpression="attribute_exists(task_id)",
        )

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        if error_code == "ConditionalCheckFailedException":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            ) from exc

        logger.exception(
            "DynamoDB delete_item failed",
            extra={"task_id": str(task_id)},
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to delete task",
        ) from exc

    logger.info(
        "Task deleted",
        extra={"task_id": str(task_id)},
    )

    return None


# --------------------------------------------------
# AWS Lambda entry point
# --------------------------------------------------

handler = Mangum(app)