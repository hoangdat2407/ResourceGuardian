# Validation matrix

## Mục 7 & Nhánh main — luật đánh giá, collectors và bằng chứng, 18/10/2026

Kiểm tra tích hợp giữa nhánh `duc` (luật đánh giá, lịch quét, xử lý lỗi, dashboard) và nhánh `origin/main` (API, collectors chỉ đọc AWS, feedback lifecycle, IAM và kiểm thử mở rộng). Toàn bộ dữ liệu AWS đọc và SES được mock; DynamoDB được mô phỏng bằng Moto. Không gọi AWS thật, không triển khai hoặc thay đổi tài nguyên cloud.

Các kiểm tra tại môi trường phát triển:
- **Toàn bộ backend:** 95/95 unittest PASS (36 rule tests, 21 API tests, 33 workflow tests, 2 contract tests, 1 test AWS E2E skipped).
- **Rule & Collectors:** Đầy đủ 9 loại tài nguyên (EC2, EBS, EIP, Snapshot, RDS, NAT, ALB, NLB, S3 multipart). Mốc 80% coverage boundary, zero thật, thiếu metric, NaN/inf/số âm/kiểu sai, threshold bằng ngưỡng; network đo riêng từng chiều; snapshot unreferenced và AMI IncludeDisabled; bằng chứng bổ sung rule_id và recommendation.
- **Feedback & Ngoại lệ:** Feedback lifecycle (/feedback GET & PUT), acknowledged, kept, ignoreUntil; tương thích ngược API /keep và /ignore nội bộ; tag guardian:keep=true.
- **Cấu hình số lớn:** Ngưỡng nhận ±10**400 bị từ chối bằng ValueError/HTTP 400, không ghi DynamoDB, không gây OverflowError; window_hours hỗ trợ 24–168 giờ.
- **UI smoke:** PASS với demo cục bộ (dashboard, filters, feedback hide/list/clear, ignore, settings 24/168 giờ, email, mobile 390px, session expired).
- **UI acceptance:** PASS với fixture cục bộ (ui_redesign.py).

Status vocabulary:

- `LOCAL MOCK`: exercised locally with mocked target-account AWS reads and Moto DynamoDB.
- `AWS E2E`: exercised against a deployed stack and real target-account resources.
- `SKIPPED`: permitted only for optional AWS scanners, with an approved exact reason.
- `NOT RUN`: no evidence exists; never equivalent to pass.

## Current branch evidence

| Surface | Status | Evidence / limit |
|---|---|---|
| Pure rules and settings bounds | LOCAL MOCK | `tests/test_rules.py`; includes 80% coverage boundary, real zero, missing series and strict S3 age |
| Tenant/auth/API/feedback/pagination | LOCAL MOCK | `tests/test_api.py`, `tests/test_workflows.py`; mocked JWT claims and Moto DynamoDB, not real Cognito/API Gateway |
| EC2/EBS/EIP/Snapshot collectors | LOCAL MOCK | Inventory, metric, observation, cap, partial and time-budget paths use mocked target-account clients |
| S3 multipart collector | LOCAL MOCK | Bucket/upload pagination, structured upload identity and >7 day rule use direct S3 mocks |
| RDS/NAT/ALB/NLB collectors | LOCAL MOCK | Missing metrics, real zeros, REVIEW and denied-service isolation use mocked clients |
| Read-only IAM/API invariant | LOCAL MOCK | `tests/test_read_only.py` parses both target-role templates and `template.yaml` semantically |
| Browser feedback workflow | LOCAL MOCK | `tests/ui_smoke.py` exercises hide, GET feedback, clear and reappearance against `demo.py` |
| Cognito admin-only, <=5 users | NOT RUN | Template is checked locally; actual UserPool change set and `ListUsers` require manual release gate |
| EC2 real finding | NOT RUN | Required before release |
| EBS real finding | NOT RUN | Required before release |
| EIP real finding | NOT RUN | Required before release |
| Snapshot real finding | NOT RUN | Required before release |
| Stale S3 multipart real finding | NOT RUN | Required before release; initiating or aborting an upload is an AWS mutation |
| RDS real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| NAT Gateway real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| ALB real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| NLB real finding | NOT RUN | May become `SKIPPED` only with `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED` |
| Wrong ExternalId and two-tenant isolation on AWS | NOT RUN | Required manual evidence; local mocks are insufficient |
| Denied service gives PARTIAL on AWS | NOT RUN | Required manual evidence |
| Missing AWS metric is not REVIEW | NOT RUN | Required manual evidence; empty inventory does not prove this rule |
| SES | NOT RUN | Default off, optional, and excluded from the release gate |

## Local branch gate

Run from the repository root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests demo.py
node --check web/app.js
cfn-lint template.yaml target-role.yaml web/target-role.yaml
cmp target-role.yaml web/target-role.yaml
sam validate --lint --region ap-southeast-1
sam build
python tests/ui_smoke.py
```

The AWS harness is skipped by default. It requires all five inputs plus explicit enablement:

```bash
CRG_AWS_E2E=1 python -m unittest discover -s tests -p 'test_aws_e2e.py' -v
```

Required variables: `CRG_AWS_E2E_API_URL`, `CRG_AWS_E2E_ACCESS_TOKEN`, `CRG_AWS_E2E_SECOND_ACCESS_TOKEN`, `CRG_AWS_E2E_MANIFEST`, `CRG_AWS_E2E_EVIDENCE`.

## Manual release gate

A reviewer records commit, stack/account/region, exact template and IAM diff, UserPool replacement assessment, Cognito user count <=5, and the read-only action allowlist. A different authorized executor deploys that reviewed change set and runs `tests/test_aws_e2e.py`. Preserve sanitized scan IDs, timestamps, account, regions, responses/log references and distinct reviewer/executor identities. Never preserve passwords, OTPs, access tokens, access keys, session credentials or presigned URLs.

Release cannot pass without real evidence for EC2, EBS, EIP, Snapshot and stale S3 multipart. RDS/NAT/ALB/NLB may be `SKIPPED` only for `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED`. Do not create paid resources solely for evidence without separate approval. Do not update `DEPLOYMENT.md` or `HANDOFF.md` until the executor has actual results.
