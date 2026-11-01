# Live AWS State — Cloud Resource Guardian

**Thời điểm thu thập:** 2026-11-01 09:10:00 UTC  
**Phương thức thu thập:** AWS MCP stdio proxy (`aws___run_script` qua `call_boto3`), không dùng AWS CLI.

---

## 1. Account & Region & Identity

- **AWS Account ID:** `376129867108`
- **Region:** `ap-southeast-1` (Singapore)
- **Principal ARN:** `arn:aws:iam::376129867108:user/datht`
- **User ID:** `AIDAVPEYWJVSCPMFZR72X`
- **Session type:** Short-term auto-rotating credentials (`aws login`, AWS CLI 2.37.12).

---

## 2. Hai CloudFormation Stacks

### 2.1 Stack `cloud-resource-guardian`
- **Stack ID:** `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/cloud-resource-guardian/d75c87a0-c53a-11f1-a18d-0a8661642287`
- **Status:** `UPDATE_COMPLETE`
- **Parameters:**
  - `DomainPrefix`: `crg-376129867108-ap-southeast-1`
  - `SenderEmail`: `""` (SES tắt)
- **Outputs:**
  - `TableName`: `cloud-resource-guardian-Data-15ID2URED2G6T`
  - `ApiUrl`: `https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com`
  - `CognitoClientId`: `6gshdb16lafagprs48q21ifgjm`
  - `WebBucket`: `cloud-resource-guardian-webbucket-gdgpbgx4t8o5`
  - `ScanPrincipal`: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ScanRole-oykltlddshRl`
  - `DeadLetterQueueUrl`: `https://sqs.ap-southeast-1.amazonaws.com/376129867108/cloud-resource-guardian-DeadLetters-Dq7qdXMYHQ9d`
  - `WebUrl`: `https://d3qn9wabid8ws0.cloudfront.net/`
  - `DistributionId`: `ERUII98HKGJOG`
  - `ApiPrincipal`: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ApiRole-So7rB7aEKrFT`
  - `CognitoDomain`: `https://crg-376129867108-ap-southeast-1.auth.ap-southeast-1.amazoncognito.com`
- **Số lượng tài nguyên triển khai:** 33 resources

### 2.2 Stack `guardian-read-role-demo`
- **Stack ID:** `arn:aws:cloudformation:ap-southeast-1:376129867108:stack/guardian-read-role-demo/4b1fba80-c542-11f1-a054-0affe454644b`
- **Status:** `UPDATE_COMPLETE`
- **Parameters:**
  - `ApiPrincipal`: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ApiRole-So7rB7aEKrFT`
  - `ScanPrincipal`: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ScanRole-oykltlddshRl`
  - `ExternalId`: `d31fae05-6d60-4f49-9631-ef06d084280f`
  - `RoleSuffix`: `demo`
- **Outputs:**
  - `RoleArn`: `arn:aws:iam::376129867108:role/GuardianReadRole-demo`
- **Số lượng tài nguyên:** 1 resource (`AWS::IAM::Role`)

---

## 3. Cấu hình chi tiết các thành phần AWS thực tế

### 3.1 Lambda Functions
1. **ApiFunction:**
   - Physical Name: `cloud-resource-guardian-ApiFunction-b3gqpsw3XEW6`
   - Runtime: `python3.12`
   - Handler: `app.api`
   - Memory: 256 MB, Timeout: 29s
   - Role: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ApiRole-So7rB7aEKrFT`
   - Environment: `TABLE`, `WORKER_FUNCTION`, `SES_SENDER=""`, `WEB_URL`, `API_PRINCIPAL`, `SCAN_PRINCIPAL`
   - Code Size: 16,715,151 bytes (Last modified: 2026-10-19)

2. **WorkerFunction:**
   - Physical Name: `cloud-resource-guardian-WorkerFunction-WjbONL4eaYdT`
   - Runtime: `python3.12`
   - Handler: `app.worker`
   - Memory: 256 MB, Timeout: 300s
   - Role: `arn:aws:iam::376129867108:role/cloud-resource-guardian-ScanRole-oykltlddshRl`
   - Event Invoke Config: `MaximumRetryAttempts=2`, `MaximumEventAgeInSeconds=600`, `OnFailure` -> `arn:aws:sqs:ap-southeast-1:376129867108:cloud-resource-guardian-DeadLetters-Dq7qdXMYHQ9d`

3. **ScheduleFunction:**
   - Physical Name: `cloud-resource-guardian-ScheduleFunction-LyoJCcdNDe6l`
   - Runtime: `python3.12`
   - Handler: `app.scheduler`
   - Memory: 256 MB, Timeout: 60s
   - EventBridge Trigger: Rule `cloud-resource-guardian-ScheduleFunctionTick-...`, schedule `rate(1 hour)` ENABLED.

4. **Chưa có trên AWS (mới có trong template.yaml local):**
   - `RecoveryFunction` (consumer phục hồi tin nhắn lỗi từ DeadLetters)
   - `ReconcileFunction` (đối soát quét định kỳ 5 phút)
   - `OperationsDeadLetters`

### 3.2 DynamoDB
- **Table Name:** `cloud-resource-guardian-Data-15ID2URED2G6T`
- **Status:** `ACTIVE`
- **Billing Mode:** `PAY_PER_REQUEST` (On-Demand)
- **Key Schema:** `pk` (HASH, String), `sk` (RANGE, String)
- **TTL:** `AttributeName=expires`, Status `ENABLED`
- **PITR:** Status `DISABLED` (ContinuousBackups `ENABLED`)
- **Item Count:** 59 items, Size 39,551 bytes

### 3.3 HTTP API Gateway & Routes
- **API ID:** `l2qn7i2en9`
- **Endpoint:** `https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com`
- **Default Authorizer:** `CognitoJwt` (Issuer: `https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_wKqDqfW3t`, Audience: `[6gshdb16lafagprs48q21ifgjm]`, Scopes: `[openid]`)
- **CORS AllowOrigins:** `https://d3qn9wabid8ws0.cloudfront.net`
- **Routes:**
  - `GET /me` (Auth: JWT)
  - `PUT /connection` (Auth: JWT)
  - `PUT /settings` (Auth: JWT)
  - `POST /scans` (Auth: JWT)
  - `GET /scans/{scanId}` (Auth: JWT)
  - `GET /findings` (Auth: JWT)
  - `GET /history` (Auth: JWT)
  - `GET /feedback` (Auth: JWT)
  - `PUT /feedback` (Auth: JWT)
  - `PUT /notifications` (Auth: JWT)

### 3.4 Cognito User Pool & Client
- **User Pool ID:** `ap-southeast-1_wKqDqfW3t`
- **User Pool Name:** `cloud-resource-guardian-UserPool-...`
- **Username Attributes:** `email`
- **Auto Verified Attributes:** `email`
- **Admin Create User Only:** `true`
- **Client ID:** `6gshdb16lafagprs48q21ifgjm` (GenerateSecret: `false`, Flow: `code`, Scopes: `openid, email, aws.cognito.signin.user.admin`)
- **Domain:** `https://crg-376129867108-ap-southeast-1.auth.ap-southeast-1.amazoncognito.com`

### 3.5 S3 WebBucket & CloudFront
- **Bucket:** `cloud-resource-guardian-webbucket-gdgpbgx4t8o5`
- **SSE:** AES256 (`aws:kms` / `AES256`)
- **Public Access Block:** `BlockPublicAcls=true`, `IgnorePublicAcls=true`, `BlockPublicPolicy=true`, `RestrictPublicBuckets=true`
- **Bucket Policy:** Cho phép `s3:GetObject` duy nhất từ CloudFront OAC `ERUII98HKGJOG`. Direct anonymous GET bị 403 Forbidden.
- **Current Objects:**
  - `app.js` (24,876 bytes, 2026-10-18)
  - `config.json` (266 bytes, 2026-10-18)
  - `index.html` (11,462 bytes, 2026-10-18)
  - `styles.css` (11,036 bytes, 2026-10-18)
  - `target-role.yaml` (1,661 bytes, 2026-10-18)
- **CloudFront Distribution ID:** `ERUII98HKGJOG`
- **Web URL:** `https://d3qn9wabid8ws0.cloudfront.net/`
- **Status:** `Deployed`

### 3.6 IAM Roles & Permissions
1. **ApiRole (`cloud-resource-guardian-ApiRole-So7rB7aEKrFT`):**
   - Trust: `lambda.amazonaws.com`
   - Inlines: `guardian-api` (DynamoDB Get/Put/Update/Delete/Query/ConditionCheck on Data table, Lambda Invoke on WorkerFunction, STS AssumeRole on `arn:aws:iam::*:role/GuardianReadRole-*`)
   - Attached: `AWSLambdaBasicExecutionRole`

2. **ScanRole (`cloud-resource-guardian-ScanRole-oykltlddshRl`):**
   - Trust: `lambda.amazonaws.com`
   - Inlines: `guardian-worker` (DynamoDB Get/Put/Update/Delete/Query/ConditionCheck on Data table, SQS SendMessage to DeadLetters, STS AssumeRole on `arn:aws:iam::*:role/GuardianReadRole-*`)
   - Attached: `AWSLambdaBasicExecutionRole`

3. **GuardianReadRole-demo (`GuardianReadRole-demo`):**
   - Trust: ApiRole ARN & ScanRole ARN, Condition `StringEquals` `sts:ExternalId = d31fae05-6d60-4f49-9631-ef06d084280f`
   - Permissions: Strictly read-only (`ec2:DescribeInstances, DescribeVolumes, DescribeAddresses, DescribeSnapshots, DescribeImages, DescribeNatGateways`, `cloudwatch:GetMetricData`, `rds:DescribeDBInstances`, `elasticloadbalancing:DescribeLoadBalancers`, `s3:ListAllMyBuckets`, `s3:ListBucketMultipartUploads`).
   - Mutations: **0**. Không có quyền stop/terminate/delete/modify.

### 3.7 SQS & DLQ
- `DeadLetters` queue URL: `https://sqs.ap-southeast-1.amazonaws.com/376129867108/cloud-resource-guardian-DeadLetters-Dq7qdXMYHQ9d`
- Tin nhắn hiện có: 1 tin nhắn cũ ngày 2026-10-18 (`condition: RetriesExhausted`, requestId `6a2ba044-c141-4099-9450-78f1b9087406`).

---

## 4. Sai lệch giữa AWS hiện tại và Repository (Drift Analysis)

1. **Lambda & Template:**
   - Code Lambda trên AWS mang timestamp 2026-10-19.
   - Template local `template.yaml` đã tích hợp Task 8:
     - Thêm `RecoveryFunction` (SQS DeadLetters consumer)
     - Thêm `ReconcileFunction` (đối soát định kỳ mỗi 5 phút)
     - Thêm `OperationsDeadLetters` và policy
     - Thêm các CloudWatch Alarm
   - Stack `cloud-resource-guardian` trên AWS hiện tại chưa được cập nhật gói Task 8 này.
2. **Frontend:**
   - Frontend trên S3 WebBucket mang timestamp 2026-10-18. Cần được kiểm tra và xuất bản bản mới nhất đồng bộ với mã nguồn repo.
3. **SES:**
   - Stack parameter `SenderEmail` đang để rỗng `""`. Điều kiện `EmailEnabled=false`, SES identity không tạo và không gửi mail ngoài (đúng yêu cầu).
