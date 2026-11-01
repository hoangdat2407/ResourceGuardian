# Plan 10 — artifact nghiệm thu AWS và điều kiện tiếp tục

Ngày 01/11/2026. **Đã chuẩn bị artifact/review local; Plan 10 chưa hoàn tất triển khai AWS.** Người dùng xác nhận Hải QA OK và cho tiếp tục. Source triển khai được pin tại revision `3342085ae15c698fd8c2c1be64e495472a65c938`, nhánh `codex/task-7-finding-observations`; các commit tài liệu sau đó không đổi source tree của artifact.

## Artifact đã chốt

| Thuộc tính | Giá trị |
|---|---|
| Final ZIP | `.preflight/duc-plan-10/artifacts/task8-final.zip` |
| SHA-256 | `7f7ef6e4233fbd1a9603644e58e9fdfe896ef2b249031890841c3020326e9ead` |
| Lambda CodeSha256 dự kiến, base64 | `f3725CM/vRqWA2ROWOn9/olu8rJJAxiQhBwwIDJunq0=` |
| Kích thước | 16.840.945 byte, 2.202 entry; giải nén23.160.667 byte |
| Source tree SHA-256 | `634b2693418ea9bc2953d62a26a517fc3960efb16e3a6042a4195b7232bba048` |
| Manifest artifact | `.preflight/duc-plan-10/artifacts/artifacts.json` |
| Runtime đích | Linux x86_64, Python3.12, wheel-only; source khớp byte checkout |

ZIP cuối có app/rules/collectors ở root, cùng dependencies đã resolve. CRC/entry/path/source guards đạt; không có fault wrapper hoặc DLL/PYD/EXE/SO. Gói `task8-faults.zip` do harness tạo riêng để Plan 12 dùng khi được giao, không deploy ở Plan 10.

SDK đã chốt: boto3 1.43.111, botocore1.43.123, s3transfer0.19.3, jmespath1.1.0, python-dateutil2.9.0.post0, urllib3 2.8.0, six1.17.0. Packaging dùng pip global với platform/Python/ABI đích chỉ định rõ vì venv Python3.12 không có pip; không đổi requirements hoặc venv. Manifest/hash pin byte artifact thực tế, không giả định pip resolve lại sẽ tạo cùng ZIP.

## Bằng chứng local và review

- Plan 09 trên cùng source runtime: 336 backend test,335 PASS/1 AWS skip; tám bộ UI PASS. Không chạy lại toàn bộ vì Plan 10 chưa sửa runtime.
- Review độc lập code/template/IAM:33/33 targeted test PASS; harness/deploy archive gates:17/17 PASS; cfn-lint ba template exit0.
- Python3.12 `-I -S` từ ZIP giải nén:10 module resolve trong bundle, năm handler callable,14 service model; API thiếu token401 và EBS/EIP rule smoke đạt. Socket bị chặn, không có network attempt.
- **115/115 targeted test PASS** bằng SDK lấy từ chính ZIP giải nén: API/rules/collector budget/finding observations,19.031 giây toàn runner. SDK không lấy từ venv; source khớp raw bytes; socket bị chặn và0 network attempt.
- Review ZIP độc lập xác nhận hash/source/requirements và guard giữ exact bytes; deploy từ chối gói fault.
- Reviewer local: `Codex independent subagent /root/plan10_release_review`. Hải QA OK được ghi theo thông báo người dùng, không dùng tên Hải để ký review IAM/change set chưa được Hải thực hiện.

IAM diff từ baseline `a2201f5`: chỉ thêm `dynamodb:BatchGetItem` cho ScanRole trên đúng `Data.Arn`. Target role hai bản giống byte,11 API đọc, không có quyền sửa tài nguyên đích. Lambda Invoke async và OnFailure → SQS → recovery giữ nguyên. Cognito admin-only, SES mặc định tắt; số user thực tế/quota/replacement cần kiểm tra live. Template có43 tài nguyên khai báo trước SAM expansion; không suy đây là số thay đổi của change set.

## Điều kiện chưa có

| Đầu vào / bước | Trạng thái mới nhất | Điều kiện gỡ |
|---|---|---|
| Phiên AWS trên máy | **THIẾU ĐẦU VÀO**: boto3 profiles rỗng, credential source null; không có config/credentials file hoặc AWS env credentials; AWS CLI/SAM chưa có | Người giữ quyền hỗ trợ cách đăng nhập được nhóm sử dụng; STS xác minh được identity/account |
| Account lab | **CHƯA XÁC NHẬN**;376129867108 chỉ là account trong lịch sử | Đạt/Hải/người quản lý xác nhận account được phép dùng |
| Stack thử | **CHƯA ĐỌC AWS**; đích runbook là `cloud-resource-guardian-task8-test`, `ap-southeast-1` | DescribeStacks/Outputs, xác nhận thử riêng; không cập nhật stack đang dùng |
| Hai Cognito user/read role | **CHƯA XÁC MINH** | Hai user thật khác nhau, tối đa5 user/pool; GuardianReadRole-task8-alice/bob và trust/API-worker/ExternalId đúng stack thử |
| Fixture/phạm vi tài nguyên | **CHƯA XÁC NHẬN** | Manifest region/resource được phép, giới hạn chi phí cho fixture; không tự tạo tài nguyên trả phí ngoài phạm vi |
| Change set/backup/rollback | **CHƯA TẠO** | Account/stack/phiên hợp lệ, backup khi UPDATE; reviewer rà tác động thật trước executor execute |
| Deploy/hash/handler/SES thực tế | **CHƯA CHẠY** | Deploy đúng ZIP đã pin, cả năm Lambda có hash/handler/config chuẩn; SenderEmail và SES_SENDER rỗng |

Người dùng hiện chưa rõ ai quản lý AWS và sẽ hỏi Đạt/Hải. Tìm plugin chưa cung cấp được capability triển khai CloudFormation cho phiên này; không coi lịch sử AWS MCP là kết nối đang hoạt động. Không có AWS request triển khai hoặc thay đổi cloud trong lượt chuẩn bị này.

## Việc nhờ người quản lý AWS

Có thể chuyển đoạn sau cho Đạt/Hải:

> Bản Task 7–9 đã QA local OK, artifact Lambda đã pin hash và sẵn sàng chuẩn bị stack thử. Nhờ xác nhận nhóm tiếp tục dùng AWS account nào, ai có quyền triển khai và nhóm đang đăng nhập bằng cách nào. Cần hỗ trợ tạo phiên truy cập AWS hợp lệ tại máy triển khai hoặc một executor được nhóm giao thực hiện. Chỉ dùng stack thử cloud-resource-guardian-task8-test tại ap-southeast-1, giữ SES tắt. Không gửi mật khẩu, access key hoặc token qua chat.

Chưa cần tạo tài khoản AWS mới. Console là web quản trị AWS; SSO là cổng đăng nhập của tổ chức. Sau khi biết cách nhóm đăng nhập, chọn công cụ/credential chain tương ứng và xác minh STS; không yêu cầu người dùng tự chọn thuật ngữ họ chưa biết.

## Trình tự cloud sau khi có đầu vào

1. Xác minh STS/account, region, quyền executor và stack thử. Nếu UPDATE, lấy template/Outputs/artifact/function config/frontend hiện tại và lưu backup theo phạm vi; không ghi token/presigned URL vào evidence.
2. Hoàn thiện manifest môi trường có hai tenant/role/region, reviewer/executor thật và hash từ artifacts.json. `release-manifest.json` hiện chỉ là readiness record; không dùng thay manifest môi trường hợp lệ của harness.
3. Review artifact bucket vì `deploy.py --plan` có thể cấu hình bucket, upload ZIP và tạo change set. Dùng `--artifact` chính ZIP đã pin, `--stack` thử và SenderEmail rỗng. Rà CREATE/UPDATE/replacement/IAM/UserPool/quota trên change set thật theo [manual release gate](VALIDATION.md#manual-release-gate).
4. Execute đúng change set đã review, đối chiếu cả năm Lambda CodeSha256/handler và timeout/retry/queue/SES. Nếu chưa deploy được, giữ blocker thay vì chuyển sang Plan 11–12.
5. Publish frontend của stack thử bằng bytes đã pin cùng config lấy từ Outputs. Có **năm object**: config.json/index.html/styles.css/app.js/target-role.yaml. `publish.py` hiện bỏ target-role.yaml nên executor phải bổ sung object này trong thao tác publish; verify bytes/MIME/cache/invalidation và config không có demo. Không ghi đè config của stack đang dùng.
6. Nếu có sự cố, dùng CloudFormation rollback hoặc artifact/config/assets backup của chính thay đổi được giao; không tự xóa stack/bucket. Chưa chạy fault injection tại Plan 10. Kết thúc Plan 10 báo trạng thái và chờ yêu cầu Plan 11.

Lệnh/checklist chi tiết ở [TASK8-AWS.md](TASK8-AWS.md), [DEPLOYMENT.md](DEPLOYMENT.md) và [VALIDATION.md](VALIDATION.md). **Chưa nghiệm thu AWS, chưa có change set để duyệt hoặc triển khai.**
