# Service Tagger for AWS
A tool to retroactively tag AWS services.

# How to use it?

Follow this doc: https://docs.google.com/document/d/1woCL_89iG21HBdY_Gi0gJXi5EjQwEdb_tcpzd9-6DiQ/

## :white_check_mark: Supported Services

* `dynamodb`
* `ec2 (includes volumes [both attached and unattached], snapshots)`
* `ecs (includes services, tasks)`
* `ecr (tags images)`
* `efs`
* `lambda`
* `rds (includes clusters, instances, cluster snapshots, instance snapshots)`
* `s3`
* `elasticache`


## :yellow_circle: Future services
* `cloudfront`
* `cloudwatchlogs`


## :factory: Install dependencies

`pip install -r requirements.txt`


## :triangular_ruler: Config structure

The yaml config specifies which tags and which functions should get which tag values.

### Structure
```yaml
target_tag:
    tag_value:
      - arn_part
```

The `target_tag` specifies the key of the tag. The `tag_value` specifies the value of the tag. This tag is applied to every resource of the given service whose `tag_string` contains the `arn_part`. `tag_string` is a custom string variable defined for each resource type that often begins with the `arn` of a given resource (hence, `arn_part`). For example, for an S3 bucket, the `tag_string` may be `arn:aws:s3:us-east-1:123456789:bucket-Public-production` where `arn:aws:s3:us-east-1:123456789:bucket` is the `arn`, `Public` is a string to match for a `DataClassification` tag, and `production` is a string to match for an `IsProduction` tag. In conjunction with the example below, the concept of the `tag_string` should make more sense.

### Example
```yaml
IsProduction:
  "false":
    - development
  "true":
    - production
DataClassification:
  India:
    - log
    - lambda
    - Private # For private S3 buckets
    - rds
    - ec2 # for ec2 instances
    - vol
    - cluster
    - container
    - service
    - task
    - fs
    - service
    - dynamodb
  Echo:
    - cloudfront
    - Public # For public S3 buckets
ResiliencyTier:
    bronze:
    - log
    - lambda
    - s3
    - rds
    - ec2 # for ec2 instances
    - vol
    - cluster
    - container
    - service
    - task
    - fs
    - service
    - cloudfront
    - dynamodb
```

## :rocket: Run
* Show the help: `python tagger.py --help`
* Show existing tags: `python tagger.py lambda TAG_1,TAG_2,TAG_N`
* Use the region `eu-central-1` instead of the default `us-east-1`: `python tagger.py lambda TAG --region eu-central-1`
* Do a dry run for writing new tags: `python tagger.py lambda TAG --write --dry-run`
* Use a different yaml file than `tag_config.yarml`: `python tagger.py lambda TAG --write --file my_config.yaml`
* Overwrite existing tags: `python tagger.py lambda TAG --write --overwrite`
  > :warning: **Note:** Use the `--overwrite` only on accounts which have mostly manually created resources. We ideally do not want to overwrite tags on resources created by Terraform since this script may not cover application specific requirements. For ex: All resources for `ResiliencyTier` key are tagged with a value of `bronze` using this script. That is not ideal for all scenarios.

### How are untagged resources tagged?

We will provide an example!

For `IsProduction` tag, for all resources, the script first looks for an account alias and checks for Production or Development keywords. All keywords are case-insensitive.

Keywords:
* Production: _production_
* Development: _dev, nonprod, non-prod, stag_

If it finds either, it tags the resource accordingly. If not, and the resource is VPC bound, the script will then check the resources VPC for the environment keywords above.
If the script is not VPC bound, or the name of the VPC does not contain an environment keyword, it then looks at the resources current tags or the resource name (if name is separate than tags, example S3).
The script looks for keywords in `Environment` tag of the resource, if it doesn't find the keywords or tag doesn't exist, the script then looks for `Name` tag.
* EC2: We assume an EC2 instance is Production unless the script finds a Development keyword.
* S3: We assume an S3 bucket is Development unless the script finds a Production keyword.
* ECS: We assume an ECS cluster is Production unless the script finds a Production keyword. For services and tasks, the tag value applied to their corresponding clusters are used
* Lambda: We assume a Lambda function is Production unless the script finds a Development keyword.
* EBS: We assume an EBS Volume is Production unless the script finds a Development keyword. The script will also check the tag values of any attached EC2 instances if the above steps fail to make a decision.


## :question: Won't the script overwrite Terraform tags?

Good question! Answer is it won't overwrite TF tags if we ignore the tags. Well, how do we do that?

:tada: As of version 2.60.0 of the Terraform AWS Provider, there is support for ignoring tag changes across all resources under a provider. This simplifies situations where certain tags may be externally applied more globally or using scripts.

> :memo: **Note:** Make sure to modify your AWS provider in Terraform to ignore tags before running any above commands.

In this example, all resources will ignore any addition of IsProduction/DataClassification/ResiliencyTier tags:

```hcl
provider "aws" {
  region = var.aws_region

  allowed_account_ids = [var.account_id]

  ignore_tags {
    keys = ["IsProduction", "DataClassification", "ResiliencyTier"]
  }
}
```

## :wrench: Contributions

Yes please! Open a ticket or send a pull request.
