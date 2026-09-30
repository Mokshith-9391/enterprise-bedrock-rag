# Security Incident Response Runbook (Confidential)

Document owner: Security Operations. Classification: confidential.

## Severity levels
- SEV1: confirmed data breach or production outage affecting customers. Response within 15 minutes, 24x7.
- SEV2: suspected compromise of a single system. Response within 1 hour.
- SEV3: policy violation without evidence of compromise. Response next business day.

## SEV1 first hour
1. The on-call security engineer opens a bridge call and an incident channel.
2. Isolate affected hosts by moving them to the quarantine security group.
3. Rotate credentials for any exposed IAM roles and revoke active sessions.
4. Preserve evidence: snapshot EBS volumes and export CloudTrail logs for the last 7 days.
5. Notify the CISO and Legal. Regulatory notification to CERT-In must be made within 6 hours of noticing the incident.

## Escalation contacts
The current on-call rota and phone bridge numbers are kept in the Security Operations vault.
