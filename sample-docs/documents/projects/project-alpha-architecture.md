# Project Alpha: Architecture Overview

Document owner: Platform Engineering. Version 2.1, March 2026.

## Purpose
Project Alpha is the new customer onboarding platform that replaces the legacy onboarding portal by Q3 2026.

## Architecture
- Frontend: React single-page app served through Amazon CloudFront.
- API layer: Amazon API Gateway (HTTP API) with AWS Lambda functions written in Python 3.12.
- Database: Amazon Aurora PostgreSQL Serverless v2, deployed in two availability zones in ap-south-1.
- Documents uploaded by customers are stored in Amazon S3 with SSE-KMS encryption.
- Asynchronous tasks (KYC checks, welcome emails) run through Amazon SQS and AWS Step Functions.

## Environments
Development, staging and production run in separate AWS accounts managed by AWS Organizations.
All infrastructure is defined in Terraform and deployed through GitHub Actions.

## Non-functional targets
- Availability: 99.9% monthly.
- API p95 latency: under 400 ms.
- Recovery point objective: 5 minutes. Recovery time objective: 1 hour.

## Team
Tech lead: Priya Raman. Product owner: Arjun Mehta.
