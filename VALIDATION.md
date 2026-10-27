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

Release cannot pass without real evidence for EC2, EBS, EIP, Snapshot and stale S3 multipart. RDS/NAT/ALB/NLB may be `SKIPPED` only for `RESOURCE_NOT_AVAILABLE` or `COST_NOT_APPROVED`. Do not create paid resources solely for evidence without separate approval. Do not update deployed-state claims in `DEPLOYMENT.md` or `HANDOFF.md` until the executor has actual results; source-change runbooks must explicitly say they are not deployed.

## Audit nhiệm vụ 10–12 — Nguyễn Trung Hải — 2026-10-27

Nguồn đối chiếu: [Cloud-T9, Report 1 và Report 2 / Action Plan](https://docs.google.com/document/d/1kzggr_OWzw0jQOhjNoaFMdBOjqmL0QK12olEBmIxHiY/edit?tab=t.0), bốn sơ đồ BC1–BC4 trong `diagrams/`, source/API/IAM/tests và các nhánh remote. Report 2 chốt **9 loại tài nguyên / 4 nhóm**; AI/Analytics/Containers và thu thập chi phí target là kế hoạch mở rộng, không phải lý do thay kiến trúc hiện tại. Không sửa sơ đồ, thiết kế frontend, API công khai, target-role hay dịch vụ nền.

### Đối chiếu nhánh và plan

| Nhánh / hạng mục | Kết quả đối chiếu |
|---|---|
| `main` / `origin/main` tại `debea62` | Baseline của audit; đã có API, collectors, rules, feedback, lịch quét và kiểm thử. Không suy từ source sang trạng thái cloud hiện tại. |
| `origin/datht` tại `ef35d90` | Đã có trong lịch sử `main` qua PR #1. |
| `origin/duc` tại `767f32a`, PR #3 → `main` | Rule/evidence task 7 còn mở; không nhập lại/ghi đè phần đồng đội trong PR nhiệm vụ 10–12. |
| `origin/codex/task-8-scheduling-recovery` tại `a8034f9`, PR #4 → `duc` | Recovery/scheduling task 8 còn mở và phụ thuộc nhánh `duc`; cần review và kiểm chứng riêng, không coi đã phát hành. |
| 10 — SES | Sửa cạnh tranh đọc–gửi–ghi bằng conditional claim, cooldown theo lịch quét; lưu trạng thái và SES receipt, digest có ngữ cảnh/bằng chứng. SES vẫn tắt mặc định; semantics và hạn chế exactly-once ở README §3.5. |
| 11 — tích hợp | Bổ sung API → enqueue → worker → DynamoDB qua hai region, tenant/cursor/feedback isolation; siết harness cloud để không nhận kết quả thiếu region, sai scan ID, history chưa đầy đủ hoặc manifest trùng service. Chờ history có giới hạn vì worker ghi terminal RESULT trước HISTORY. |
| 12 — vận hành | Thêm 12 alarm CloudWatch cho Lambda, async delivery, EventBridge và failure queue; runbook inspection/recovery/inventory/chi phí trong DEPLOYMENT.md. Alarm không có action; cần người vận hành xem CloudWatch, không tự gửi thông báo hoặc khắc phục. |

### Phát hiện toàn hệ thống ngoài phần code của nhiệm vụ 10–12

- `main` còn lỗi người dùng mới chưa có `connection_version` khi gọi findings/feedback; PR #3 có xử lý. Cùng PR sửa metric RDS/NAT/ELB, mẫu timestamp và việc giữ finding bị ẩn qua lượt quét sau. Không tuyên bố các sửa đổi này đã có trên baseline.
- PR #4 xử lý admission/persistence race, worker claim, timeout/recovery, scheduler isolation và phân loại lỗi hạ tầng so với lỗi target-role. Cần nghiệm thu theo thứ tự **PR #3 → PR #4**, rồi tích hợp lại phần thông báo/monitoring; `src/app.py` và `template.yaml` là điểm có thể conflict. Không merge tự động hoặc thay kiến trúc để né conflict.
- Dashboard hiện chỉ có bộ lọc 4 loại trong khi backend có 9 loại (`web/index.html`); form hiển thị 6 trong 11 setting API hỗ trợ (`web/app.js`, `src/rules.py`). Các measurements/diagnostics mở rộng chưa được render đầy đủ.
- API có acknowledged/kept/ignoreUntil và clear qua feedback; UI mới chỉ cung cấp bỏ qua 7 ngày cùng luồng xem/xóa ngoại lệ, chưa cung cấp đủ hành động đã xem/giữ lại trong danh sách finding. Không coi API coverage là UI acceptance.
- Lịch sử trên UI tải 20 kết quả region gần nhất và chưa có điều khiển phân trang, dù API hỗ trợ cursor. Một lượt nhiều region chiếm nhiều hàng. Đây là giới hạn UX hiện tại, không phải mất dữ liệu đã chứng minh.

### Bằng chứng đã chạy trong audit này

- `python -m unittest discover -s tests -p 'test_*.py' -v`: **119 ca, 118 PASS, 1 SKIPPED** (AWS harness mặc định tắt); chạy bằng Python 3.13.13 trong virtualenv tạm. Các traceback AccessDenied/SES rejection/throttling trong output là fault injection có chủ đích, suite kết thúc `OK (skipped=1)`.
- `cfn-lint template.yaml target-role.yaml web/target-role.yaml`: PASS; SAM transform được lint, không tạo change set.
- `node --check web/app.js` và `cmp target-role.yaml web/target-role.yaml`: PASS.
- Smoke runtime tạm: API tạo scan `f298d199-abd7-436c-987c-9b5d3a52dd0c`; worker xử lý `ap-southeast-1` và `ap-southeast-2` đều `SUCCEEDED`, Moto SES nhận 2 yêu cầu, 2 NOTICE lưu MessageId, gọi lặp trả `UNCHANGED`, tenant khác đọc scan trả 404. **DynamoDB/SES là Moto, inventory và Lambda dispatch là mock**, không phải AWS thật.
- Chromium mở `demo.py`, đăng nhập demo, quét và thấy kết quả hoàn tất. Kiểm tra bốn trạng thái email `FAILED`, `UNKNOWN`, `STATE_FAILED`, `SENT_UNRECORDED` qua response fixture tại HTTP boundary: ghi chú tương ứng hiện trên dashboard, không lỗi JavaScript. Không thay layout/visual design.
- Tái hiện trước sửa: harness ở `main` chấp nhận manifest lặp một required service; regression sau sửa từ chối. Notification regression kiểm tra cạnh tranh cùng snapshot, cooldown boundary, SES rejection/timeout/5xx, lỗi ghi trạng thái và giữ kết quả/history.
- Review độc lập phát hiện race giữa terminal RESULT và HISTORY trong harness; đã đổi sang chờ coverage có deadline. Review notification state machine và monitoring không còn phát hiện lỗi cụ thể.

### Chưa được chứng minh / điều kiện nghiệm thu cloud

Không triển khai AWS, không bật SES, không gửi email thật, không tạo/xóa tài nguyên trial hoặc sửa tài nguyên target. Không chạy `sam build`/SAM CLI; lint và runtime local không chứng minh CloudFormation deploy thành công.

Môi trường audit chưa có bộ đầu vào `CRG_AWS_E2E_*`: API URL đã được xác minh, hai access token Cognito còn hạn thuộc hai người dùng khác nhau, manifest tài nguyên được phép và đường dẫn lưu evidence. Harness vì vậy SKIPPED, không ghi PASS giả cho Web → Cognito/API Gateway → Lambda → AWS thật. Các thông tin cloud trong HANDOFF.md và mục 2.8 Report 2 (EBS OBSERVING ngày 26/10) là bằng chứng lịch sử do nhóm cung cấp, không phải đã tái kiểm chứng trong lượt này.

Còn cần người thực thi được ủy quyền: reviewed change set và xác nhận không replacement, test hai tenant/hai region với tài nguyên thật, quan sát REVIEW sau đủ cửa sổ, IAM denied/missing metrics/pagination thật, alarm state transitions và failure destination, SES verified identity/recipient nếu quyết định bật, inventory trial hiện tại và Billing/Cost Explorer có phạm vi/UTC/currency. Không dùng empty inventory hay mô phỏng để ký nghiệm thu các mục này. Không ghi chi phí bằng 0 khi chưa có hóa đơn và phân bổ chi phí.
