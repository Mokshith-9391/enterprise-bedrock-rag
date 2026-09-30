# Information Security Policy

Document owner: Chief Information Security Officer. Effective: 1 January 2026.

## Passwords and MFA
- Passwords must be at least 14 characters and are changed every 180 days.
- Multi-factor authentication is mandatory for email, VPN, cloud consoles and the Git server.

## AWS and cloud access
- No IAM users with long-lived access keys are allowed for humans. Engineers sign in through AWS IAM Identity Center.
- Production accounts require a second approver for any change outside the CI/CD pipeline.
- All S3 buckets must block public access unless the Security team approves a documented exception.
- Root user credentials are stored in the security vault and used only for account-level tasks.

## Data classification
- Public: may be shared outside the company.
- Internal: for employees only.
- Confidential: restricted to named teams; must be encrypted at rest and in transit.

## Reporting incidents
Report suspected phishing, lost devices or data leaks to security@example-corp.in within 1 hour of discovery.
