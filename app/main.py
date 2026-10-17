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

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
DYNAMODB_TABLE = os.getenv(
    "DYNAMODB_TABLE",
    "cloudops360-dev-tasks",
)

# Use the normal AWS credential provider chain.
# Locally, this can use credentials from the AWS CLI.
# On AWS Lambda, use the Lambda execution role.
dynamodb = boto3.resource(
    "dynamodb",
    region_name=AWS_REGION,
)

tasks_table = dynamodb.Table(DYNAMODB_TABLE)


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


def get_task_or_404(task_id: UUID) -> dict:
    try:
        response = tasks_table.get_item(
            Key={"task_id": str(task_id)}
        )
    except ClientError as exc:
        print(f"DynamoDB get_item failed: {exc}")
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("CloudOps360 API starting...")
    print(f"AWS region: {AWS_REGION}")
    print(f"DynamoDB table: {DYNAMODB_TABLE}")
    yield
    print("CloudOps360 API shutting down...")


app = FastAPI(
    title="CloudOps360 API",
    description="Serverless task management and operations platform",
    version="0.2.0",
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
        print(f"DynamoDB put_item failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to save task",
        ) from exc

    return {
        "id": task["task_id"],
        "title": task["title"],
        "description": task["description"],
        "status": task["status"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


@app.get("/tasks", response_model=list[TaskResponse])
def list_tasks():
    try:
        response = tasks_table.scan()
        items = response.get("Items", [])

        # Read all pages if the table contains more than one page.
        while "LastEvaluatedKey" in response:
            response = tasks_table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            items.extend(response.get("Items", []))

    except ClientError as exc:
        print(f"DynamoDB scan failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to list tasks",
        ) from exc

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


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: UUID):
    return get_task_or_404(task_id)


@app.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: UUID, payload: TaskUpdate):
    # First check that the task exists.
    get_task_or_404(task_id)

    try:
        tasks_table.update_item(
            Key={"task_id": str(task_id)},
            UpdateExpression="SET #task_status = :new_status, updated_at = :updated_at",
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
        print(f"DynamoDB update_item failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to update task",
        ) from exc

    return get_task_or_404(task_id)


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

        print(f"DynamoDB delete_item failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to delete task",
        ) from exc

    return None
# AWS Lambda entry point
handler = Mangum(app)