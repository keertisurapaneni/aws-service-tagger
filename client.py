from ast import alias
from logging import Logger
import sys
import boto3
import botocore
from botocore.exceptions import ClientError, BotoCoreError, ProfileNotFound
import os
import dpath.util
import re


def get_account_alias():
    account_alias = ""
    try:
        account_alias = boto3.client('iam').list_account_aliases()["AccountAliases"][0]
    except IndexError as e:
        print("list_account_alias returned a list of length 0, will determine environment at the resource level")
    except ProfileNotFound:
        print("Unknown error occurred loading users account alias, will determine environment at the resource level")
    except (BotoCoreError, ClientError) as e:
        print("Unknown error occurred loading users account alias, will determine environment at the resource level")
    except Exception as e:
        print("Unknown error occurred loading users account alias, will determine environment at the resource level")
    return account_alias


CLOUDFRONT = 'cloudfront'
CLOUDWATCHLOGS = 'cloudwatchlogs'
LAMBDA = 'lambda'
S3 = 's3'
RDS = 'rds'
EC2 = 'ec2'
ELASTICACHE = 'elasticache'
EFS = 'efs'
ECS = 'ecs'
DYNAMODB = 'dynamodb'
OPENSEARCH = 'opensearch'
ECR = 'ecr'
FSX = 'fsx'
ACCOUNT_ALIAS = get_account_alias()
ACCOUNT_ID = boto3.client('sts').get_caller_identity()["Account"]


class Client:
    def __init__(self, service, region):
        self.service = service
        self.region = region
        self.nonprod_keywords = ["dev", "stag", "qa", "nonprod", "non-prod"]
        self.vpcs = self.get_all_vpcs()

        if self.service == LAMBDA:
            self.client = boto3.client('lambda', self.region)
        elif self.service == CLOUDWATCHLOGS:
            self.client = boto3.client('logs', self.region)
        elif self.service == CLOUDFRONT:
            self.client = boto3.client('cloudfront', self.region)
        elif self.service == S3:
            self.client = boto3.client('s3', self.region)
        elif self.service == RDS:
            self.client = boto3.client('rds', self.region)
        elif self.service == EC2:
            self.client = boto3.client('ec2', self.region)
        elif self.service == ELASTICACHE:
            self.client = boto3.client('elasticache', self.region)
        elif self.service == EFS:
            self.client = boto3.client('efs', self.region)
        elif self.service == ECS:
            self.client = boto3.client('ecs', self.region)
        elif self.service == DYNAMODB:
            self.client = boto3.client('dynamodb', self.region)
        elif self.service == OPENSEARCH:
            self.client = boto3.client('opensearch', self.region)
        elif self.service == ECR:
            self.client = boto3.client('ecr', self.region)
        elif self.service == FSX:
            self.client = boto3.client('fsx', self.region)
        else:
            raise Exception(f'Service {self.service} is not yet supported.')

    def get_resources(self, target_tags):
        resources = []
        if self.service == LAMBDA:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda.html#Lambda.Paginator.ListFunctions
            for page in self.client.get_paginator('list_functions').paginate():
                resources.extend(page.get('Functions'))
            resources.sort(key=lambda x: x['FunctionArn'])
            for r in resources:
                r['tagger_id'] = r['tag_string'] = r['FunctionArn']
                if 'IsProduction' in target_tags:
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    else:
                        vpc_name = self.get_vpc_name(r, "/VpcConfig/VpcId")
                        if self.substring_in_string(self.nonprod_keywords, vpc_name):
                            environment = "development"
                        elif self.substring_in_string(["prod"], vpc_name):
                            environment = "production"
                        else:
                            tags = self.client.list_tags(Resource=r['FunctionArn'])['Tags']
                            if any(key.lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tags[key]) for key in tags.keys()):
                                environment = "development"
                            # If the environment tag exists then set it to production (if the above if condition returns false, and this tag still exists, then it must be a prod value)
                            elif any(key.lower() == 'environment' for key in tags.keys()):
                                environment = "production"
                            # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                            elif any(key.lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tags[key]) for key in tags.keys()):
                                environment = "development"
                            # If name tag is missing or exists and does not contain a nonprod keyword, then set env variable to "production"
                            else:
                                environment = "production"
                    r['tag_string'] = r['FunctionArn'] + "-" + environment
        elif self.service == CLOUDWATCHLOGS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/logs.html#CloudWatchLogs.Paginator.DescribeLogGroups
            for page in self.client.get_paginator('describe_log_groups').paginate():
                resources.extend(page.get('logGroups'))
            resources.sort(key=lambda x: x['logGroupName'])
            for r in resources:
                r['tagger_id'] = r['logGroupName']
                r['tag_string'] = r['logGroupName']
        elif self.service == CLOUDFRONT:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.list_distributions
            for page in self.client.get_paginator('list_distributions').paginate():
                resources.extend(page.get('DistributionList', {}).get('Items', []))
            resources.sort(key=lambda x: x['ARN'])
            for r in resources:
                r['tagger_id'] = r['ARN']
                r['tag_string'] = {r['ARN']}
        elif self.service == S3:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Paginator.ListObjects
            for bucket in self.client.list_buckets()['Buckets']:
                name = bucket['Name']
                if 'DataClassification' in target_tags:
                    public = ""
                    # print("--------------------------------------------------------------")
                    # print(f"Bucket name: {name}")
                    # https://stackoverflow.com/questions/59002558/boto-find-if-bucket-is-public-or-private
                    try:
                        response = self.client.get_bucket_policy_status(Bucket=bucket['Name'])
                        public = response['PolicyStatus']['IsPublic']
                        # if public:
                            # print(f"Bucket is public: {public}")
                        # else:
                            # print(f"Bucket is public: {public}")
                    except:
                        # print(f"No bucket policy attached")
                        # print(f"Checking if public access block option is set")
                        try:
                            response = self.client.get_public_access_block(Bucket=bucket['Name'])
                            if response['PublicAccessBlockConfiguration']['BlockPublicAcls'] and response['PublicAccessBlockConfiguration']['BlockPublicPolicy']:
                                public = False
                                # print(f"Bucket is public: {public}")
                            else:
                                public = True
                                # print(f"Bucket is public: {public}")
                        except botocore.exceptions.ClientError as e:
                            if e.response['Error']['Code'] == 'NoSuchPublicAccessBlockConfiguration':
                                # The above error is thrown when Public access is turned off meaning bucket is private
                                # print(f"Public access block option is not set")
                                try:
                                    response = self.client.get_bucket_acl(Bucket=bucket['Name'])
                                    if any(self.substring_in_string(["AllUsers","AuthenticatedUsers"], grant['Grantee']['URI']) for grant in response['Grants'] if 'URI' in grant['Grantee'].keys()):
                                        public = True
                                        # print(f"Bucket is public: {public}")
                                except:
                                    public = False
                            # else:
                                # print("unexpected error: %s" % (e.response))
                    if public:
                        access = "Public"
                    else:
                        access = "Private"
                    resources.append({'Name': name, 'Access': access})
                if 'IsProduction' in target_tags:
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    # Check for non-prod keywords in S3 bucket name
                    elif self.substring_in_string(self.nonprod_keywords, name):
                        environment = "development"
                    # check for prod keywords in S3 bucket name
                    elif "prod" in name.lower():
                        environment = "production"
                    else:
                        # If keywords don't exist in S3 bucket name, look into S3 tags
                        tags = self.client.get_bucket_tagging(Bucket=bucket['Name'])['TagSet']
                        # If environment tag exists and contains a nonprod keyword, set tag string to development
                        if any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in tags):
                            environment = "development"
                        # If environment tag still exists while the above is false, set tag string to production
                        elif any(tag['Key'].lower() == 'environment' for tag in tags):
                            environment = "production"
                        # If name tag exists and includes a prod keyword as the value and does not include a nonprod keyword, set env variable to "production"
                        elif any(tag['Key'].lower() == 'name' and 'production' in tag['Value'].lower() or ((not self.substring_in_string(self.nonprod_keywords, tag['Value'])) and 'prod' in tag['Value'].lower()) for tag in tags):
                            environment = "production"
                        # If name tag is missing or exists and does not contain a nonprod keyword, then set env variable to "development"
                        else:
                            environment = "development"
                    arn = f'arn:aws:s3:::{name}-{environment}'
                else:
                    arn = f'arn:aws:s3:::{name}'
                resources.append({'Name': name, 'ARN': arn})
            for r in resources:
                r['tagger_id'] = r['Name']
                r['tag_string'] = r['Access'] if 'Access' in r.keys() else r['ARN']
        elif self.service == RDS:
            resources = []
            clusters = []
            instances = []
            cluster_snapshots = []
            snapshots = []
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Paginator.DescribeDBInstances
            for page in self.client.get_paginator('describe_db_instances').paginate():
                instances.extend(page.get('DBInstances'))
            for page in self.client.get_paginator('describe_db_clusters').paginate():
                clusters.extend(page.get('DBClusters'))
            # Snapshot ARNs can have either :snapshot: or :cluster-snapshot: in the ARN, we are covering both use cases. Cloudability seems to be reporting only tags for cluster snapshots
            for page in self.client.get_paginator('describe_db_cluster_snapshots').paginate():
                cluster_snapshots.extend(page.get('DBClusterSnapshots'))
            for page in self.client.get_paginator('describe_db_snapshots').paginate():
                snapshots.extend(page.get('DBSnapshots'))

            for cluster in clusters:
                cluster['tagger_id'] = cluster['tag_string'] = f'arn:aws:rds:{self.region}:{ACCOUNT_ID}:cluster:{cluster["DBClusterIdentifier"]}'
                if 'IsProduction' in target_tags:
                    # check for account alias
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    # If the environment tag exists and has a value with nonprod keywords, set tag string to development
                    elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in cluster['TagList']):
                        environment = "development"
                    # If the environment tag still exists while the above is false, set tag string to production
                    elif any(tag['Key'].lower() == 'environment' for tag in cluster['TagList']):
                        environment = "production"
                    # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                    elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in cluster['TagList']):
                        environment = "development"
                    else:
                        environment = "production"
                    cluster['tag_string'] = cluster['tag_string'] + environment
            for instance in instances:
                instance['tagger_id'] = instance['tag_string'] = f'arn:aws:rds:{self.region}:{ACCOUNT_ID}:db:{instance["DBInstanceIdentifier"]}'
                if 'IsProduction' in target_tags:
                    if 'DBClusterIdentifier' in instance.keys():
                        correlated_cluster = [cluster for cluster in clusters if cluster['DBClusterIdentifier'] == instance['DBClusterIdentifier']][0]
                        if 'production' in correlated_cluster['tag_string']:
                            environment = "production"
                        else:
                            environment = "development"
                    else:
                        # check for account alias
                        if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                            environment = "development"
                        elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                            environment = "production"
                        else:
                            vpc_name = self.get_vpc_name(instance, "/DBSubnetGroup/VpcId")
                            if self.substring_in_string(self.nonprod_keywords, vpc_name):
                                environment = "development"
                            elif self.substring_in_string(["prod"], vpc_name):
                                environment = "production"
                            # If the environment tag exists and contains a nonprod value, set tag string to development
                            elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in instance['TagList']):
                                environment = "development"
                            # If the environment tag still exists while the above is false, set tag string to production
                            elif any(tag['Key'].lower() == 'environment' for tag in instance['TagList']):
                                environment = "production"
                            # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                            elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in instance['TagList']):
                                environment = "development"
                            else:
                                environment = "production"
                    instance['tag_string'] = instance['tag_string'] + environment
            for cluster_snapshot in cluster_snapshots:
                cluster_snapshot['tagger_id'] = cluster_snapshot['tag_string'] = cluster_snapshot["DBClusterSnapshotArn"]
                # print(f"{cluster_snapshot['tagger_id']}")
                if 'IsProduction' in target_tags:
                    if 'DBInstanceIdentifier' in cluster_snapshot.keys():
                        try:
                            correlated_cluster = [cluster for cluster in clusters if cluster['DBClusterIdentifier'] == cluster_snapshot['DBClusterIdentifier']][0]
                            if 'production' in correlated_cluster['tag_string']:
                                environment = "production"
                            else:
                                environment = "development"
                        # The below errors occur when the DB cluster no longer exists but the snapshot exists
                        except IndexError:
                            pass
                    else:
                        # check for account alias
                        if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                            environment = "development"
                        elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                            environment = "production"
                        else:
                            vpc_name = self.get_vpc_name(cluster_snapshot, "/DBSubnetGroup/VpcId")
                            if self.substring_in_string(self.nonprod_keywords, vpc_name):
                                environment = "development"
                            elif self.substring_in_string(["prod"], vpc_name):
                                environment = "production"
                            # If the environment tag exists and contains a nonprod value, set tag string to development
                            elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in cluster_snapshot['TagList']):
                                environment = "development"
                            # If the environment tag still exists while the above is false, set tag string to production
                            elif any(tag['Key'].lower() == 'environment' for tag in cluster_snapshot['TagList']):
                                environment = "production"
                            # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                            elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in cluster_snapshot['TagList']):
                                environment = "development"
                            else:
                                environment = "production"
                    cluster_snapshot['tag_string'] = cluster_snapshot['tag_string'] + environment
            # Below is instance snapshots which are not being tracked by Cloudability
            for snapshot in snapshots:
                snapshot['tagger_id'] = snapshot['tag_string'] = snapshot["DBSnapshotArn"]
                # print(f"{snapshot['tagger_id']}")
                if 'IsProduction' in target_tags:
                    if 'DBInstanceIdentifier' in snapshot.keys():
                        try:
                            correlated_instance = [instance for instance in instances if instance['DBInstanceIdentifier'] == snapshot['DBInstanceIdentifier']][0]
                            if 'production' in correlated_instance['tag_string']:
                                environment = "production"
                            else:
                                environment = "development"
                        # The below errors occur when the DB cluster/instance no longer exists but the snapshot exists
                        except IndexError:
                            pass
                    else:
                        # check for account alias
                        if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                            environment = "development"
                        elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                            environment = "production"
                        else:
                            vpc_name = self.get_vpc_name(snapshot, "/DBSubnetGroup/VpcId")
                            if self.substring_in_string(self.nonprod_keywords, vpc_name):
                                environment = "development"
                            elif self.substring_in_string(["prod"], vpc_name):
                                environment = "production"
                            # If the environment tag exists and contains a nonprod value, set tag string to development
                            elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in snapshot['TagList']):
                                environment = "development"
                            # If the environment tag still exists while the above is false, set tag string to production
                            elif any(tag['Key'].lower() == 'environment' for tag in snapshot['TagList']):
                                environment = "production"
                            # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                            elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in snapshot['TagList']):
                                environment = "development"
                            else:
                                environment = "production"
                    snapshot['tag_string'] = snapshot['tag_string'] + environment
            for list in [clusters, instances, cluster_snapshots, snapshots]:
                resources.extend(list)
        elif self.service == EC2:
            resources = []
            instances = self.get_instances()
            volumes = self.get_volumes()
            snapshots = self.get_snapshots()
           # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Paginator.DescribeInstances
            for instance in instances:
                instance['tagger_id'] = instance['tag_string'] = instance['InstanceId']
                if 'IsProduction' in target_tags:
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    else:
                        vpc_name = self.get_vpc_name(instance)
                        if self.substring_in_string(self.nonprod_keywords, vpc_name):
                            environment = "development"
                        elif self.substring_in_string(["prod"], vpc_name):
                            environment = "production"
                        # For each tag in the list r['Tags'], if any tag has the key 'Key' with a value of "environment" and also has the key 'Value' with a value of "production" then return true
                        # Example list of tags as returned by Boto3
                        # Tags = [
                        #       { 'Key': 'Environment', 'Value': 'production'},
                        #       { 'Key': 'DataClassification', 'Value': 'echo'}
                        #]
                        # If the environment tag exists and contains a nonprod keyword, set tag string to development
                        elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in instance['Tags']):
                            environment = "development"
                        # If the environment tag still exists while the above is false, set tag string to production
                        elif any(tag['Key'].lower() == 'environment' for tag in instance['Tags']):
                            environment = "production"
                        # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                        elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in instance['Tags']):
                            environment = "development"
                        # If name tag is missing or exists and does not contain a nonprod keyword, then set env variable to "production"
                        else:
                            environment = "production"
                    instance['tag_string'] = f'{instance["tag_string"]}-{environment}'
                if 'DataClassification' in target_tags:
                    if any(self.subnet_is_public(interface['SubnetId']) for interface in instance['NetworkInterfaces']):
                        classification = "Public"
                    else:
                        classification = "Private"
                    instance['tag_string'] = f'{instance["tag_string"]}-{classification}'


            for volume in volumes:
                volume['tagger_id'] = volume['tag_string'] = volume['VolumeId']
                if 'IsProduction' in target_tags:
                    attached_instances = [instance for a in volume['Attachments'] for instance in instances if instance['InstanceId'] == a['InstanceId']]
                    if len(attached_instances) > 0:
                        if any('production' in instance['tagger_id'] for instance in attached_instances):
                            environment = "production"
                        else:
                            environment = "development"
                    elif self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    elif 'Tags' in volume.keys():
                        if any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in volume['Tags']):
                            environment = "development"
                        elif any(tag['Key'].lower() == 'environment' for tag in volume['Tags']):
                            environment = "production"
                        elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in volume['Tags']):
                            environment = "development"
                        # if production is not env than check for volume name tag
                        elif any(tag['Key'].lower() == 'name' and self.substring_in_string(['prod'], tag['Value']) for tag in volume['Tags']):
                            environment = "production"
                        else:
                            environment = "production"
                    volume['tag_string'] = f"{volume['tag_string']}-{environment}"

            for snapshot in snapshots:
                snapshot['tagger_id'] = snapshot['tag_string'] = snapshot['SnapshotId']
                if "IsProduction" in target_tags:
                    if any(snapshot['SnapshotId'] == volume['SnapshotId'] for volume in volumes):
                        corrolated_volume = [volume for volume in volumes if snapshot['SnapshotId'] == volume['SnapshotId']][0]
                        if "production" in corrolated_volume['tag_string']:
                            environment = "production"
                        elif "development" in corrolated_volume['tag_string']:
                            environment = "development"
                    elif self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    elif 'Tags' in snapshot.keys():
                        if any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in snapshot['Tags']):
                            environment = "development"
                        elif any(tag['Key'].lower() == 'environment' for tag in snapshot['Tags']):
                            environment = "production"
                        elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in snapshot['Tags']):
                            environment = "development"
                        # if production is not env than check for snapshot name tag
                        elif any(tag['Key'].lower() == 'name' and self.substring_in_string(['prod'], tag['Value']) for tag in snapshot['Tags']):
                            environment = "production"
                        else:
                            environment = "production"
                    snapshot['tag_string'] = f'{snapshot["tag_string"]}-{environment}'

            resources = []
            for list in [instances, volumes, snapshots]:
                resources.extend(list)


        elif self.service == ELASTICACHE:
            resources = []
           # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Paginator.DescribeInstances
            for page in self.client.get_paginator('describe_cache_clusters').paginate():
                resources.extend(page.get('CacheClusters'))
            resources.sort(key=lambda x: x['ARN'])
            for r in resources:
                r['tagger_id'] = r['ARN']
                r['tag_string'] = r['ARN']
        elif self.service == EFS:
            resources = []
           # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/efs.html#EFS.Paginator.DescribeFileSystems
            for page in self.client.get_paginator('describe_file_systems').paginate():
                resources.extend(page.get('FileSystems'))
            resources.sort(key=lambda x: x['FileSystemId'])
            for r in resources:
                r['tagger_id'] = r['tag_string'] = r['FileSystemId']
                if 'IsProduction' in target_tags:
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    # If the environment tag exists then set it to development (if the above if condition returns false, and this tag still exists, then it must be a nonprod value)
                    elif any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in r['Tags']):
                        environment = "development"
                    elif any(tag['Key'].lower() == 'environment' for tag in r['Tags']):
                        environment = "production"
                    # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                    elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in r['Tags']):
                        environment = "development"
                    # If name tag is missing or exists and does not contain a nonprod keyword, then set env variable to "production"
                    else:
                        environment = "production"
                r['tag_string'] = r['FileSystemId'] + "-" + environment
        elif self.service == ECS:
            # Getting ECS clusters
            clusters = self.get_ecs_clusters()
            # Getting cluster arns for use in fetching services and tasks
            cluster_arns = [cluster['clusterArn'] for cluster in clusters]
            # Getting ECS services for each cluster
            services = self.get_ecs_services(cluster_arns)
            # Getting ECS tasks for each cluster, and containers for each task
            tasks, containers = self.get_ecs_tasks_and_containers(cluster_arns)

            # Iterate through clusters first, and then tagging decisions for tasks and services will be based on the decision made for its cluster
            for cluster in clusters:
                cluster['tagger_id'] = cluster['tag_string'] = cluster['clusterArn']
                if 'IsProduction' in target_tags:
                    if self.substring_in_string(self.nonprod_keywords, cluster['clusterName']):
                        environment = 'development'
                    elif self.substring_in_string(['prod'], cluster['clusterName']):
                        environment = 'production'
                    elif any(tag['key'].lower == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['value']) for tag in cluster['tags']):
                        environment = 'development'
                    elif any(tag['key'].lower() == 'environment' for tag in cluster['tags']):
                        environment = 'production'
                    elif any(tag['key'].lower() == 'name' and 'production' in tag['value'].lower() or ((not self.substring_in_string(self.nonprod_keywords, tag['value'])) and 'prod' in tag['value'].lower()) for tag in cluster['tags']):
                        environment = 'production'
                    # Catch all
                    else:
                        environment = 'production'
                    cluster['tag_string'] = cluster['tag_string'] + '-' + environment


            for service in services:
                service['tagger_id'] = service['tag_string'] = service['serviceArn']
                 # For each service, check the environment of the corrolated cluster
                if 'IsProduction' in target_tags:
                    corrolated_cluster = [cluster for cluster in clusters if cluster['clusterArn'] == service['clusterArn']][0]
                    if 'production' in corrolated_cluster['tag_string']:
                        environment = 'production'
                    else:
                        environment = 'development'
                    service['tag_string'] = service['tag_string'] + '-' + environment


            for task in tasks:
                task['tag_string'] = task['tagger_id'] = task['taskArn']
                # For each task, check the environment of the corrolated cluster
                if 'IsProduction' in target_tags:
                    corrolated_cluster = [cluster for cluster in clusters if cluster['clusterArn'] == task['clusterArn']][0]
                    if 'production' in corrolated_cluster['tag_string']:
                        environment = 'production'
                    else:
                        environment = 'development'
                    task['tag_string'] = task['tag_string'] + '-' + environment

            # for container in containers:
            #     container['tag_string'] = container['containerArn']
            #     # For each container, check the environment of the corrolated cluster
            #     if 'IsProduction' in target_tags:
            #         corrolated_cluster = [cluster for cluster in clusters if cluster['clusterArn'] == container['clusterArn']][0]
            #         if 'production' in corrolated_cluster['tag_string']:
            #             environment = 'production'
            #         else:
            #             environment = 'development'
            #         container['tagger_id'] = container['containerArn']
            #         container['tag_string'] = container['tag_string'] + '-' + environment



            # Combining clusters, services, and tasks into the resources array to be returned to tagger.py
            resources = []
            for list in [clusters, services, tasks]:
                resources.extend(list)
        elif self.service == DYNAMODB:
            resources = []
           # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/efs.html#EFS.Paginator.DescribeFileSystems
            for page in self.client.get_paginator('list_tables').paginate():
                for tablename in page['TableNames']:
                    arn = f'arn:aws:dynamodb:{self.region}:{ACCOUNT_ID}:table/{tablename}'
                    resources.append({'ARN': arn, 'Name': tablename})
            for r in resources:
                r['tagger_id'] = r['tag_string'] = r['ARN']
                if 'IsProduction' in target_tags:
                    # check for account alias
                    if self.substring_in_string(self.nonprod_keywords, ACCOUNT_ALIAS):
                        environment = "development"
                    elif self.substring_in_string(["prod"], ACCOUNT_ALIAS):
                        environment = "production"
                    else:
                        tags = self.client.list_tags_of_resource(ResourceArn=r['ARN'])['Tags']
                        # if production is not env than check for table name tag
                        if any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in tags):
                            environment = "development"
                        elif any(tag['Key'].lower() == 'environment' for tag in tags):
                            environment = "production"
                        elif any(tag['Key'] == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in tags):
                            environment = "development"
                        else:
                            environment = "production"
                    r['tag_string'] = r['tag_string'] + environment
        elif self.service == OPENSEARCH:
            resources = []
           # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/efs.html#EFS.Paginator.DescribeFileSystems
            for page in self.client.describe_domain(self.name):
                resources.extend(page.get('DomainStatus'))
            resources.sort(key=lambda x: x['DomainName'])
            for r in resources:
                r['tagger_id'] = r['DomainName']
                r['tag_string'] = r['DomainName']
        elif self.service == ECR:
            resources = []
            for page in self.client.get_paginator('describe_repositories').paginate():
                for repository in page['repositories']:
                    repository['tagger_id'] = repository['tag_string'] = repository['repositoryArn']
                    if 'IsProduction' in target_tags:
                        if self.substring_in_string(self.nonprod_keywords, repository['repositoryName']):
                            environment = 'development'
                        elif self.substring_in_string(['prod'], repository['repositoryName']):
                            environment = 'production'
                        else:
                            tags = self.client.list_tags_for_resource(resourceArn=repository['tagger_id'])['tags']
                            # If the environment tag exists and contains a nonprod keyword, set tag string to development
                            if any(tag['Key'].lower() == 'environment' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in tags):
                                environment = "development"
                            elif any(tag['Key'].lower() == 'environment' for tag in tags):
                                environment = "production"
                            # If name tag exists and includes a nonprod keyword as the value, set env variable to "development"
                            elif any(tag['Key'].lower() == 'name' and self.substring_in_string(self.nonprod_keywords, tag['Value']) for tag in tags):
                                environment = "development"
                            # If name tag is missing or exists and does not contain a nonprod keyword, then set env variable to "production"
                            else:
                                environment = "production"
                        repository['tag_string'] = f'{repository["tag_string"]}-{environment}'
                    resources.append(repository)

        return resources


    def get_tags(self, tagger_id):
        if self.service == LAMBDA:
            return self.client.list_tags(Resource=tagger_id).get('Tags', [])
        elif self.service == CLOUDWATCHLOGS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/logs.html#CloudWatchLogs.Client.list_tags_log_group
            return self.client.list_tags_log_group(logGroupName=tagger_id).get('tags', [])
        elif self.service == CLOUDFRONT:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.list_tags_for_resource
            result = {}
            for item in self.client.list_tags_for_resource(Resource=tagger_id).get('Tags', {}).get('Items', []):
                result[item['Key']] = item['Value']
            return result
        elif self.service == S3:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.get_bucket_tagging
            result = {}
            try:
                for item in self.client.get_bucket_tagging(Bucket=tagger_id).get('TagSet'):
                    result[item['Key']] = item['Value']
            except:
                None
            return result
        elif self.service == RDS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Client.list_tags_for_resource
            result = {}
            for item in self.client.list_tags_for_resource(ResourceName=tagger_id).get('TagList', []):
                result[item['Key']] = item['Value']
            return result
        elif self.service == EC2:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.describe_tags
            result = {}
            for item in self.client.describe_tags(
                Filters=[
                    {
                        'Name': 'resource-id',
                        'Values': [
                            tagger_id,
                        ],
                    },
                    ],
                )['Tags']:
                result[item['Key']] = item['Value']
            return result
               # result[item['Key']] = item['Value']
        elif self.service == ELASTICACHE:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.describe_tags
            return self.client.list_tags_for_resource(ResourceName=tagger_id).get('TagList', [])
        elif self.service == EFS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/efs.html#EFS.Client.describe_tags
            return {tag['Key']:tag['Value'] for tag in self.client.list_tags_for_resource(ResourceId=tagger_id).get('Tags', [])}
        elif self.service == ECS:
            try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.list_tags_for_resource
                return {tag['key']:tag['value'] for tag in self.client.list_tags_for_resource(resourceArn=tagger_id).get('tags', [])}
            except self.client.exceptions.InvalidParameterException as e:
                print("Failed to list tags for resource: " + tagger_id + "\nThis is likely due to the short arn format:\n")
                print(e)
                return []
        elif self.service == DYNAMODB:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.list_tags_of_resource
            return {tag['Key']:tag['Value'] for tag in self.client.list_tags_of_resource(ResourceArn=tagger_id).get('Tags', [])}
        elif self.service == ECR:
            return {tag['Key']:tag['Value'] for tag in self.client.list_tags_for_resource(resourceArn=tagger_id).get('tags', [])}

    def write_tags(self, tagger_id, new_tags):
        if self.service == LAMBDA:
            self.client.tag_resource(Resource=tagger_id, Tags=new_tags)
        elif self.service == CLOUDWATCHLOGS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/logs.html#CloudWatchLogs.Client.tag_log_group
            self.client.tag_log_group(logGroupName=tagger_id, tags=new_tags)
        elif self.service == CLOUDFRONT:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudfront.html#CloudFront.Client.tag_resource
            items = []
            for key, value in new_tags.items():
                items.append({
                    'Key': key,
                    'Value': value
                })
            self.client.tag_resource(Resource=tagger_id, Tags={'Items': items})
        elif self.service == S3:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.get_bucket_tagging
            try:
                old = self.client.get_bucket_tagging(Bucket=tagger_id)
                old_tags = {i['Key']: i['Value'] for i in old['TagSet']}
                new_tags = {**old_tags, **new_tags}
            except botocore.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchTagSet':
                    new_tags = {**new_tags}
            response = self.client.put_bucket_tagging(Bucket=tagger_id,
                    Tagging={
                        'TagSet': [{'Key': str(k), 'Value': str(v)} for k, v in new_tags.items()]
                    }
                )
        elif self.service == RDS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Client.add_tags_to_resource
             tags = [{"Key": key, "Value": new_tags[key]} for key in new_tags.keys()]
             self.client.add_tags_to_resource(ResourceName=tagger_id, Tags=tags)
        elif self.service == EC2:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.create_tags
            tags = [{"Key" : key, "Value": new_tags[key]} for key in new_tags.keys()]
            self.client.create_tags(Resources=[tagger_id], Tags=tags)
        elif self.service == EFS:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/efs.html#EFS.Client.tag_resource
            tags = [{"Key" : key, "Value": new_tags[key]} for key in new_tags.keys()]
            self.client.tag_resource(ResourceId=tagger_id, Tags=tags)
        elif self.service == ECS:
            try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.tag_resource
                tags = [{"key" : key, "value": new_tags[key]} for key in new_tags.keys()]
                self.client.tag_resource(resourceArn=tagger_id, tags=tags)
            except:
                with open("error.log", 'a') as f:
                    f.write("Failed to apply tags for resource: " + tagger_id + "\nThis is likely due to a mismatching ARN format\n")
        elif self.service == ELASTICACHE:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/elasticache.html#ElastiCache.Client.add_tags_to_resource
            self.client.add_tags_to_resource(ResourceName=tagger_id, Tags=[{'Key':'string','Value':'string'}])
        elif self.service == DYNAMODB:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/dynamodb.html#DynamoDB.Client.tag_resource
            self.client.tag_resource(ResourceArn=tagger_id, Tags=[{"Key": key, "Value": new_tags[key]} for key in new_tags.keys()])
        elif self.service == ECR:
            tags = [{"Key": key, "Value": new_tags[key]} for key in new_tags.keys()]
            self.client.tag_resource(resourceArn=tagger_id, tags=tags)


    # HELPER FUNCTIONS

    def get_all_vpcs(self):
        paginator = boto3.client('ec2').get_paginator('describe_vpcs')
        response_iterator = paginator.paginate()
        vpcs = [vpc for page in response_iterator for vpc in page["Vpcs"]]
        return vpcs

    def get_vpc_name(self, resource, path_to_vpc_id="VpcId"):
        name = ""
        # Some resources will conditionally have VPC fields (ex. lambda fn), meaning an error would be thrown when the field does not exist
        try:
            vpc_id = dpath.util.get(resource, path_to_vpc_id)
            vpc = [vpc for vpc in self.vpcs if vpc["VpcId"] == vpc_id]
            if len(vpc) == 1:
                name = [tag['Value'] for tag in vpc['Tags'] if tag['Key'].lower() == 'name']
                name = "" if len(name) == 0 else name[0]
            return name
        except:
            return name

    def substring_in_string(self, substrings, string):
        return any(x in string.lower() for x in substrings)

    # ECS HELPERS
    def get_ecs_clusters(self):
        cluster_arns = []
        for page in self.client.get_paginator('list_clusters').paginate():
            for arn in page['clusterArns']:
                cluster_arns.append(arn)
        clusters = self.client.describe_clusters(clusters=cluster_arns)
        return clusters['clusters']

    def get_ecs_services(self, cluster_arns):
        services = []
        for arn in cluster_arns:
            for page in self.client.get_paginator('list_services').paginate(cluster=arn):
                if len(page.get('serviceArns')) > 0:
                    services.extend(self.client.describe_services(cluster=arn, services=page.get('serviceArns'))['services'])
        return services

    def get_ecs_tasks_and_containers(self, cluster_arns):
        tasks = []
        containers = []
        for arn in cluster_arns:
            for page in self.client.get_paginator('list_tasks').paginate(cluster=arn):
                if len(page.get('taskArns')) > 0:
                    tasks_sub_arr = self.client.describe_tasks(tasks=page.get('taskArns'), cluster=arn)['tasks']
                    for task in tasks_sub_arr:
                        containers_sub_arr = task['containers']
                        for container in containers_sub_arr:
                            container['clusterArn'] = arn
                        containers.extend(containers_sub_arr)
                    tasks.extend(tasks_sub_arr)
        return tasks, containers



    def get_instances(self):
        instances = []
        for page in self.client.get_paginator('describe_instances').paginate():
            for reservation in page.get('Reservations', []):
                for instance in reservation['Instances']:
                    instances.append(instance)
        return instances

    def get_volumes(self):
        volumes = []
        for page in self.client.get_paginator('describe_volumes').paginate():
            for volume in page['Volumes']:
                volumes.append(volume)
        return volumes


    def get_snapshots(self):
        snapshots = []
        for page in self.client.get_paginator('describe_snapshots').paginate(OwnerIds=[ACCOUNT_ID]):
            for snapshot in page['Snapshots']:
                snapshots.append(snapshot)
        return snapshots

    def subnet_is_public(self, subnet_id):
        ec2_client = boto3.client('ec2')
        for page in ec2_client.get_paginator('describe_route_tables').paginate(
            Filters=[
            {
                'Name':'association.subnet-id',
                'Values':[subnet_id]
            }
            ]
        ):
            for table in page['RouteTables']:
                for route in table['Routes']:
                    if 'GatewayId' in route.keys() and 'igw' in route['GatewayId']:
                        return True
        return False

