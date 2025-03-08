output "rds_endpoint" {
  description = "RDS endpoint"
  value       = aws_db_instance.rds.address
}

output "rds_port" {
  description = "RDS port"
  value       = aws_db_instance.rds.port
}

output "rds_username" {
  description = "RDS master username"
  value       = aws_db_instance.rds.username
}

output "rds_database_name" {
  description = "RDS database name"
  value       = aws_db_instance.rds.db_name
}

output "secrets_manager_secret_arn" {
  description = "ARN of the Secrets Manager secret"
  value       = aws_secretsmanager_secret.rds_credentials.arn
}