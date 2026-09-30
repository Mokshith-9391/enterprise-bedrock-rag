// For local testing only (make web-local writes config.js from Terraform outputs).
// This file is never uploaded: Terraform generates config.js for CloudFront.
window.APP_CONFIG = {
  apiUrl: "https://abc123.execute-api.ap-south-1.amazonaws.com",
  region: "ap-south-1",
  cognitoDomain: "https://enterprise-rag-dev-111122223333.auth.ap-south-1.amazoncognito.com",
  clientId: "your-app-client-id",
  appName: "Company knowledge assistant",
};
