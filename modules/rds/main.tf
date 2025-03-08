provider "aws" {
  region = var.aws_region
}

resource "aws_db_subnet_group" "rds" {
  name       = "${var.database_name}-${var.environment}"
  subnet_ids = var.subnet_ids

  tags = {
    Name        = "${var.database_name}-${var.environment}"
    Environment = var.environment
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.database_name}-${var.environment}-rds-sg"
  description = "Security group for ${var.database_name} RDS instance"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = var.database_engine == "mysql" ? 3306 : 5432
    to_port     = var.database_engine == "mysql" ? 3306 : 5432
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.database_name}-${var.environment}-rds-sg"
    Environment = var.environment
  }
}

resource "random_password" "rds" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "rds_credentials" {
  name        = "${var.database_name}-${var.environment}-rds-credentials"
  description = "Credentials for ${var.database_name} ${var.environment} RDS instance"

  tags = {
    Name        = "${var.database_name}-${var.environment}-rds-credentials"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    username = var.master_username
    password = random_password.rds.result
    engine   = var.database_engine
    host     = aws_db_instance.rds.address
    port     = aws_db_instance.rds.port
    dbname   = var.database_name
  })
}

resource "aws_db_instance" "rds" {
  identifier           = "${var.database_name}-${var.environment}"
  allocated_storage    = var.allocated_storage
  storage_type         = var.storage_type
  engine               = var.database_engine
  engine_version       = var.engine_version
  instance_class       = var.instance_class
  db_name              = var.database_name
  username             = var.master_username
  password             = random_password.rds.result
  parameter_group_name = var.parameter_group_name
  skip_final_snapshot  = var.skip_final_snapshot
  publicly_accessible  = var.publicly_accessible
  db_subnet_group_name = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  
  tags = {
    Name        = "${var.database_name}-${var.environment}"
    Environment = var.environment
  }
}