output "aws_region" {
  description = "AWS region selected for deployment"
  value       = var.aws_region
}
output "project_name" {
  description = "CloudOps360 project name"
  value       = var.project_name
}
output "dynamodb_table_name" {
  description = "DynamoDB table used to store CloudOps360 tasks"
  value       = aws_dynamodb_table.tasks.name
}
output "dynamodb_table_arn" {
  description = "ARN of the CloudOps360 DynamoDB table"
  value       = aws_dynamodb_table.tasks.arn
}
output "api_gateway_endpoint" {
  description = "Public HTTPS endpoint for CloudOps360"
  value       = aws_apigatewayv2_api.api.api_endpoint
}