import json
import os
import logging
import uuid
import base64
from github import Github, GithubException

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# GitHub configuration
github_token = os.environ.get('GITHUB_TOKEN')
github_repo_name = os.environ.get('GITHUB_REPO')  # Format: username/repo

def lambda_handler(event, context):
    try:
        # Process SQS messages
        for record in event['Records']:
            logger.info(f"Processing message: {record['messageId']}")
            process_message(record)
            
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Messages processed successfully'})
        }
    
    except Exception as e:
        logger.error(f"Error processing messages: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }

def process_message(record):
    # Parse the message
    message_body = json.loads(record['body'])
    
    # If the message came from SNS, extract the actual message
    if 'Type' in message_body and message_body['Type'] == 'Notification':
        message_body = json.loads(message_body['Message'])
    
    # Validate required fields
    required_fields = ['database_name', 'database_engine', 'environment']
    for field in required_fields:
        if field not in message_body:
            logger.error(f"Missing required field: {field}")
            raise ValueError(f"Missing required field: {field}")
    
    # Extract request details
    database_name = message_body['database_name']
    database_engine = message_body['database_engine'].lower()
    environment = message_body['environment'].lower()
    
    # Validate database engine
    valid_engines = ['mysql', 'postgresql']
    if database_engine not in valid_engines:
        logger.error(f"Invalid database engine: {database_engine}")
        raise ValueError(f"Invalid database engine. Supported engines: {', '.join(valid_engines)}")
    
    # Validate environment
    valid_environments = ['dev', 'prod']
    if environment not in valid_environments:
        logger.error(f"Invalid environment: {environment}")
        raise ValueError(f"Invalid environment. Supported environments: {', '.join(valid_environments)}")
    
    # Initialize GitHub client
    g = Github(github_token)
    repo = g.get_repo(github_repo_name)
    
    # Generate a unique branch name
    branch_name = f"rds-request-{database_name}-{str(uuid.uuid4())[:8]}"
    
    # Get the default branch
    default_branch = repo.default_branch
    
    # Create a new branch
    create_branch(repo, default_branch, branch_name)
    
    # Generate Terraform configuration
    tf_config = generate_terraform_config(database_name, database_engine, environment)
    
    # Commit Terraform configuration
    commit_terraform_config(repo, branch_name, database_name, tf_config)
    
    # Create a pull request
    create_pull_request(repo, branch_name, database_name, database_engine, environment, default_branch)
    
    logger.info(f"Pull request created for {database_name} {database_engine} database in {environment} environment")

def create_branch(repo, default_branch, branch_name):
    try:
        # Get the SHA of the latest commit on the default branch
        default_branch_ref = repo.get_git_ref(f"heads/{default_branch}")
        sha = default_branch_ref.object.sha
        
        # Create a new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        logger.info(f"Created branch: {branch_name}")
    except GithubException as e:
        logger.error(f"GitHub error creating branch: {str(e)}")
        raise

def generate_terraform_config(database_name, database_engine, environment):
    # Generate Terraform configuration based on the request
    instance_class = 'db.t3.micro' if environment == 'dev' else 'db.t3.small'
    
    tf_config = f'''
# RDS Cluster for {database_name}
module "rds_{database_name}" {{
  source  = "../modules/rds"
  
  database_name       = "{database_name}"
  database_engine     = "{database_engine}"
  environment         = "{environment}"
  instance_class      = "{instance_class}"
  
  vpc_id              = "vpc-0699cc0e1df9817df"
  subnet_ids          = ["subnet-060138b65d7d9df55", "subnet-05c05a3a9519c0eea"]
  allowed_cidr_blocks = ["10.0.0.0/16"]
    
  # Auto-cleanup tag for unused RDS instances
  tags = {{
    Name            = "{database_name}"
    Environment     = "{environment}"
    auto-cleanup    = "true"
    managed-by      = "terraform"
    database-engine = "{database_engine}"
  }}
}}
'''
    
    return tf_config

def commit_terraform_config(repo, branch_name, database_name, tf_config):
    try:
        # Create a new file in the repository
        file_path = f"terraform/rds_{database_name}.tf"
        
        # Encode content to base64
        content = base64.b64encode(tf_config.encode()).decode()
        
        # Create the file in the repository
        repo.create_file(
            path=file_path,
            message=f'Add Terraform configuration for {database_name} RDS cluster',
            content=tf_config,
            branch=branch_name
        )
        
        logger.info(f"Committed Terraform configuration to {file_path}")
    except GithubException as e:
        logger.error(f"GitHub error committing file: {str(e)}")
        raise

def create_pull_request(repo, branch_name, database_name, database_engine, environment, default_branch):
    try:
        pr_title = f'Provision {database_name} {database_engine} RDS cluster for {environment}'
        pr_body = f'''
## RDS Cluster Request

- **Database Name**: {database_name}
- **Database Engine**: {database_engine}
- **Environment**: {environment}

This PR was automatically generated by the RDS Cluster Automation Lambda.
        '''
        
        # Create the pull request
        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base=default_branch
        )
        
        logger.info(f"Created pull request: {pr.html_url}")
    except GithubException as e:
        logger.error(f"GitHub error creating pull request: {str(e)}")
        raise