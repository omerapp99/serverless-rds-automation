import json
import os
import logging
import uuid
from datetime import datetime, timedelta

import boto3
from github import Github, GithubException

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Clients
cloudwatch_client = boto3.client('cloudwatch')
rds_client = boto3.client('rds')

# GitHub configuration
github_token = os.environ.get('GITHUB_TOKEN')
github_repo_name = os.environ.get('GITHUB_REPO')

def lambda_handler(event, context):
    """
    Main Lambda handler to identify and delete unused RDS instances
    """
    try:
        # Get all RDS instances
        rds_instances = get_rds_instances()
        
        # Track number of instances processed
        deleted_instances = 0
        
        # Check and delete unused instances
        for instance in rds_instances:
            if is_rds_unused(instance):
                cleanup_unused_instance(instance)
                deleted_instances += 1
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Processed {len(rds_instances)} instances. Deleted {deleted_instances} unused instances.'
            })
        }
    
    except Exception as e:
        logger.error(f"Error in RDS auto-cleanup: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'RDS auto-cleanup failed'})
        }

def get_rds_instances():
    """
    Retrieve all RDS instances with specific tags for auto-cleanup
    """
    try:
        # Describe DB instances with a specific tag for auto-cleanup
        response = rds_client.describe_db_instances(
            Filters=[
                {
                    'Name': 'tag:auto-cleanup',
                    'Values': ['true']
                }
            ]
        )
        
        return [
            {
                'identifier': instance['DBInstanceIdentifier'],
                'engine': instance['Engine'],
                'environment': next((tag['Value'] for tag in instance.get('TagList', []) if tag['Key'] == 'Environment'), 'unknown'),
                'arn': instance['DBInstanceArn']
            }
            for instance in response['DBInstances']
        ]
    except Exception as e:
        logger.error(f"Error getting RDS instances: {str(e)}")
        raise

def is_rds_unused(instance):
    """
    Check if an RDS instance has been unused for more than a week
    
    Checks multiple CloudWatch metrics:
    1. DatabaseConnections
    2. CPUUtilization
    3. NetworkReceiveThroughput
    4. NetworkTransmitThroughput
    """
    try:
        # Define the time range (last week)
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)
        
        # Metrics to check for usage
        metrics_to_check = [
            'DatabaseConnections',
            'CPUUtilization', 
            'NetworkReceiveThroughput',
            'NetworkTransmitThroughput'
        ]
        
        # Check each metric
        for metric_name in metrics_to_check:
            response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName=metric_name,
                Dimensions=[
                    {
                        'Name': 'DBInstanceIdentifier',
                        'Value': instance['identifier']
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=86400,  # Daily aggregation
                Statistics=['Sum', 'Average']
            )
            
            # If any metric shows significant activity, consider the instance in use
            datapoints = response.get('Datapoints', [])
            if datapoints:
                # Different thresholds for different metrics
                if metric_name == 'DatabaseConnections' and max(dp.get('Sum', 0) for dp in datapoints) > 100:
                    return False
                if metric_name == 'CPUUtilization' and max(dp.get('Average', 0) for dp in datapoints) > 5:
                    return False
                if metric_name in ['NetworkReceiveThroughput', 'NetworkTransmitThroughput']:
                    if max(dp.get('Sum', 0) for dp in datapoints) > 1024*1024:  # 1 MB
                        return False
        
        # If no significant activity found, mark for cleanup
        return True
    
    except Exception as e:
        logger.error(f"Error checking usage for {instance['identifier']}: {str(e)}")
        # Default to not cleaning up if there's an error checking metrics
        return False

def cleanup_unused_instance(instance):
    """
    Cleanup unused RDS instances
    1. Create final snapshot
    2. Delete RDS instance
    3. Create GitHub PR to remove Terraform configuration
    """
    try:
        # Create final snapshot
        create_final_snapshot(instance)
        
        # Delete RDS instance
        delete_rds_instance(instance)
        
        # Initialize GitHub client
        g = Github(github_token)
        repo = g.get_repo(github_repo_name)
        
        # Create GitHub PR to remove Terraform configuration
        create_cleanup_pr(repo, instance)
        
        logger.info(f"Cleaned up unused RDS instance: {instance['identifier']}")
    
    except Exception as e:
        logger.error(f"Error in cleanup process for {instance['identifier']}: {str(e)}")
        raise

def create_final_snapshot(instance):
    """
    Create a final snapshot before deletion for safety
    """
    try:
        snapshot_identifier = f"{instance['identifier']}-final-snapshot-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        rds_client.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_identifier,
            DBInstanceIdentifier=instance['identifier']
        )
        
        logger.info(f"Created final snapshot: {snapshot_identifier}")
    except Exception as e:
        logger.warning(f"Could not create final snapshot for {instance['identifier']}: {str(e)}")

def delete_rds_instance(instance):
    """
    Delete the RDS instance
    """
    try:
        rds_client.delete_db_instance(
            DBInstanceIdentifier=instance['identifier'],
            SkipFinalSnapshot=False,  # Ensures a final snapshot is created
            FinalDBSnapshotIdentifier=f"{instance['identifier']}-final-snapshot-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        )
        
        logger.info(f"Deleted RDS instance: {instance['identifier']}")
    except Exception as e:
        logger.error(f"Error deleting RDS instance {instance['identifier']}: {str(e)}")
        raise

def create_cleanup_pr(repo, instance):
    """
    Create a GitHub PR to remove Terraform configuration
    """
    try:
        # Generate a unique branch name
        branch_name = f"cleanup-rds-{instance['identifier']}-{str(uuid.uuid4())[:8]}"
        
        # Get the default branch
        default_branch = repo.default_branch
        
        # Get the SHA of the latest commit on the default branch
        default_branch_ref = repo.get_git_ref(f"heads/{default_branch}")
        sha = default_branch_ref.object.sha
        
        # Create a new branch
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        
        # Path to the Terraform configuration file
        file_path = f"terraform/rds_{instance['identifier']}.tf"
        
        # Get the file's current content and SHA
        try:
            file_content = repo.get_contents(file_path, ref=repo.default_branch)
            
            # Delete the file
            repo.delete_file(
                path=file_path,
                message=f'Remove unused RDS cluster {instance["identifier"]}',
                sha=file_content.sha,
                branch=branch_name
            )
        except Exception as not_found_error:
            logger.warning(f"Terraform configuration file not found: {file_path}")
        
        # Create Pull Request
        pr = repo.create_pull(
            title=f'Remove Unused RDS: {instance["identifier"]}',
            body=f'''
## Automated RDS Cleanup

Unused RDS instance identified and removed:
- **Instance Identifier**: {instance['identifier']}
- **Database Engine**: {instance['engine']}
- **Environment**: {instance['environment']}

Cleanup performed due to inactivity over the last week.
            ''',
            head=branch_name,
            base=default_branch
        )
        
        logger.info(f"Created cleanup PR: {pr.html_url}")
    
    except Exception as e:
        logger.error(f"Error creating cleanup PR: {str(e)}")
        raise