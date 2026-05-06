# infra

Infrastructure-as-code for accounting-parser.

- `terraform/` — baseline AWS resources (VPC, RDS, ECR, ECS, S3, KMS, Cognito) per design §6.
- `cdk/` — application-layer stacks composed on top of the Terraform baseline.

Populated in Task 30 (Deployment & rollout).
