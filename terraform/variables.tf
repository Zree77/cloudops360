variable "aws_region" {
  description = "AWS region for CloudOps360 resources"
  type        = string
  default     = "ap-south-1"
}
variable "project_name" {
  description = "Name used to identify CloudOps360 resources"
  type        = string
  default     = "cloudops360"
}
variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}
