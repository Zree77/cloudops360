# CloudOps360 — Cloud Incident Detection and Monitoring

CloudOps360 is a cloud-native incident detection and monitoring project built using Python, AWS services, and automated CI/CD. It processes application and AWS Lambda logs, identifies error patterns, tracks incidents, and verifies recovery using subsequent application events.

The project demonstrates practical DevOps skills in cloud deployment, automated testing, centralized logging, incident management, and CI/CD automation.

## Architecture

```text
                    Developer
                        |
                        v
                  GitHub Repository
                        |
                        v
                 GitHub Actions
                        |
                 Run Automated Tests
                        |
                        v
                  Deploy to AWS
                        |
                        v
                 Amazon API Gateway
                        |
                        v
                    AWS Lambda
                        |
              +---------+---------+
              |                   |
              v                   v
         Amazon DynamoDB     Amazon CloudWatch
              |                   |
              v                   v
         Task Storage         Application Logs
                                  |
                                  v
                         CloudWatch Log Retrieval
                                  |
                                  v
                         Log Analysis and Filtering
                                  |
                                  v
                          Incident Detection
                                  |
                                  v
                       Incident State and Reports
```

## Technology Stack

| Category | Technologies |
|---|---|
| Programming Language | Python |
| API Framework | FastAPI |
| Cloud Platform | Amazon Web Services |
| Serverless Compute | AWS Lambda |
| API Management | Amazon API Gateway |
| Database | Amazon DynamoDB |
| Logging | Amazon CloudWatch Logs |
| Testing | pytest |
| CI/CD | GitHub Actions |
| Version Control | Git and GitHub |
| AWS Integration | Boto3 |
| Lambda Adapter | Mangum |

## Features

### 1. Serverless REST API

- Built using FastAPI.
- Deployed to AWS Lambda.
- Exposed through Amazon API Gateway.
- Provides health and readiness endpoints.
- Supports task creation, retrieval, updating, and deletion.

### 2. DynamoDB Integration

- Stores application task records.
- Integrates with the FastAPI application through AWS services.
- Uses AWS IAM permissions to control access.

### 3. CloudWatch Log Processing

- Retrieves application and Lambda system logs from CloudWatch.
- Normalizes retrieved events into JSON Lines files.
- Analyzes application errors and warnings.
- Identifies relevant AWS Lambda runtime failure patterns.

### 4. Incident Detection

- Identifies recurring errors within a configurable time window.
- Uses an error threshold to determine when an incident should be opened.
- Tracks incident state and supporting evidence.
- Prevents duplicate incident creation for an already-open incident.
- Uses stable identifiers for incident tracking.

### 5. Incident Recovery Verification

- Identifies successful application events that may indicate recovery.
- Matches recovery evidence against the affected component and operation.
- Avoids resolving incidents based on stale or unrelated recovery events.
- Records incident lifecycle events.
- Generates incident reports that distinguish verified recovery from unverified recovery.

### 6. Automated Testing

- Uses pytest for automated testing.
- Covers API behavior and incident detection.
- Tests incident lifecycle and recovery verification scenarios.

### 7. CI/CD Automation

- Uses GitHub Actions to automate testing and deployment.
- Runs automated tests before deployment.
- Deploys the application to AWS Lambda.
- Performs deployment smoke tests.

## Project Structure

```text
cloudops360/
├── app/
│   ├── main.py
│   └── logging_config.py
├── scripts/
│   ├── simulate_incident.py
│   ├── analyze_logs.py
│   ├── detect_incidents.py
│   ├── generate_incident_report.py
│   ├── fetch_cloudwatch_logs.py
│   ├── analyze_cloudwatch_logs.py
│   └── detect_cloudwatch_incidents.py
├── tests/
│   ├── test_main.py
│   ├── test_detect_incidents.py
│   ├── test_generate_incident_report.py
│   └── test_detect_cloudwatch_incidents.py
├── logs/
├── pytest.ini
├── requirements.txt
└── README.md
```

*Note: The structure above describes the main project files; the exact contents of individual directories may evolve.*

## Prerequisites

- Python 3.12
- Git
- An AWS account
- AWS CLI
- Configured AWS credentials with appropriate permissions
- An AWS Lambda deployment and API Gateway endpoint

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/Zree77/cloudops360.git
cd cloudops360
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Run automated tests

```powershell
pytest -q
```

The latest recorded local test run completed with 35 passing tests and two dependency deprecation warnings.

## AWS Configuration

The deployed project uses AWS Lambda, API Gateway, DynamoDB, and CloudWatch Logs.

Before running AWS integration scripts:

1. Configure AWS CLI credentials.
2. Verify access to the intended AWS account.
3. Select the correct AWS region.
4. Ensure the IAM identity has the required permissions.
5. Confirm that the target Lambda function and CloudWatch log group exist.

Do not commit AWS access keys, secrets, environment files containing credentials, or Terraform state files to GitHub.

## API Endpoints

The application provides the following endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Root endpoint |
| GET | `/health` | Application health check |
| GET | `/ready` | Readiness check |
| POST | `/tasks` | Create a task |
| GET | `/tasks` | Retrieve tasks |
| GET | `/tasks/{task_id}` | Retrieve a task |
| PATCH | `/tasks/{task_id}` | Update a task |
| DELETE | `/tasks/{task_id}` | Delete a task |

Use the deployed API Gateway endpoint or run the application locally to access the API.

## CloudWatch Log Processing

The CloudWatch workflow consists of three primary operations.

### Retrieve logs

```powershell
python scripts/fetch_cloudwatch_logs.py
```

Retrieves CloudWatch log events and saves normalized events locally.

### Analyze logs

```powershell
python scripts/analyze_cloudwatch_logs.py
```

Summarizes retrieved logs, including application events, Lambda system events, errors, and warnings.

### Detect incidents

```powershell
python scripts/detect_cloudwatch_incidents.py
```

Processes retrieved CloudWatch events, evaluates error thresholds, and updates incident state and alert history.

Run the scripts from the project root. The AWS scripts require appropriate AWS credentials and permissions.

## Incident Reports

Generate a report from the local incident history:

```powershell
python scripts/generate_incident_report.py
```

The report summarizes incident counts, resolution status, and recovery verification.

The project distinguishes simulated/local incident data from data retrieved from AWS CloudWatch.

## CI/CD Workflow

The GitHub Actions workflow automates the following stages:

1. Check out the repository.
2. Set up Python.
3. Install dependencies.
4. Run automated tests.
5. Package the application for AWS Lambda.
6. Deploy the application.
7. Execute a deployment smoke test.

Deployment behavior depends on the workflow configuration and its trigger conditions.

## Security Considerations

- Follow the principle of least privilege when configuring IAM.
- Store deployment credentials securely.
- Prefer GitHub Actions OIDC for AWS authentication where configured.
- Avoid exposing sensitive application data in logs.
- Review API authentication and authorization before exposing task-management endpoints publicly.
- Monitor AWS usage and remove unused resources to control costs.

## Current Status

The project has implemented:

- A FastAPI application deployed on AWS Lambda.
- API Gateway integration.
- DynamoDB-backed task operations.
- CloudWatch log retrieval and analysis.
- Application error and Lambda runtime failure classification.
- Incident tracking and recovery verification.
- Automated tests.
- GitHub Actions CI/CD deployment.

The latest recorded test run passed all 35 tests. Additional enhancements, including expanded observability, notifications, and broader cloud-tool integrations, can be developed as separate improvements.

## Future Enhancements

- Amazon SNS incident notifications.
- Terraform-based infrastructure management.
- Enhanced incident severity classification.
- MTTD and MTTR metrics.
- Additional monitoring dashboards and alerts.
- Loki-based centralized log aggregation.
- Improved security and deployment safeguards.

## Author

**Sreehari S.**

GitHub: https://github.com/Zree77

Project: [CloudOps360](https://github.com/Zree77/cloudops360)