# Kịch bản demo nghiệm thu an toàn — Cloud Resource Guardian

Thời lượng mục tiêu: 10 phút. Chỉ dùng deployment đã qua release gate trong `DEPLOYMENT.md`. Nếu route inventory/IAM/frontend chưa deploy, chạy local demo và nói rõ `LOCAL FIXTURE`; không trộn screenshot local với AWS evidence.

## Preflight trước khi quay

- Ghi revision/artifact hash, stack, account, region và thời gian.
- Xác nhận CloudFront đang phục vụ đúng revision.
- Xác nhận `GET /inventory` đã có route nếu demo inventory identity.
- Xác nhận target role có `ecr:DescribeImages`; quyền `rds:DescribeDBClusters` hiện hữu phục vụ DocumentDB/Neptune.
- Không hiển thị token, OTP, password, AWS credentials, ExternalId đầy đủ hoặc log có secret.
- Không nói “38/38 production verified”, “100% accuracy”, “an toàn tuyệt đối” hoặc số tiết kiệm chưa đo.

## 00:00–00:40 — 1. Mục tiêu và kiến trúc

Mở sơ đồ CloudFront/S3 → Cognito → API Gateway → Lambda → DynamoDB; bổ sung STS target role, EventBridge, SQS/DLQ, CloudWatch và SES.

> Cloud Resource Guardian là hệ thống chỉ đọc để kiểm kê và tạo ứng viên cần xem xét. Findings không tự động là severity cao và hệ thống không dừng/xóa tài nguyên AWS. Source khai báo 38 loại; phạm vi AWS được xác minh phải dựa trên evidence của deployment này.

## 00:40–01:30 — 2. Register/Login

1. Nếu môi trường cho self-sign-up, đăng ký và xác minh email; nếu account nội bộ, dùng user được phê duyệt.
2. Đăng nhập Cognito Authorization Code + PKCE.
3. Chỉ ra phiên hết hạn sẽ quay lại màn đăng nhập.

Evidence: redirect không còn authorization code; app hiển thị sau login. Không mở DevTools chứa token khi quay.

## 01:30–02:20 — 3. Kết nối AWS

Mở `Kết nối AWS`, chọn 1–3 region và service group cần demo, nhập `GuardianReadRole-*`, lưu.

> Browser không nhận AWS access key. Backend dùng STS AssumeRole với ExternalId và role chỉ đọc. Mỗi lần đổi connection tạo version mới, dữ liệu job cũ không trộn vào connection mới.

Evidence: trạng thái connected, account expected, selected regions/groups.

## 02:20–03:00 — 4. Cấu hình rule

Mở `Cấu hình`, thay một threshold trong khoảng hợp lệ, lưu và reload. Thử một giá trị ngoài giới hạn để chứng minh request bị chặn.

> REVIEW, OBSERVING và INSUFFICIENT_DATA là trạng thái đánh giá. Missing metric không được thay bằng zero.

## 03:00–03:50 — 5. Quét ngay và trạng thái

Nhấn `Quét ngay`. Chỉ ra QUEUED/RUNNING rồi terminal. Nếu không được phép chạy scan thật, dùng fixture local và nói rõ.

Evidence:

- scan ID trong panel kỹ thuật;
- cooldown;
- SUCCEEDED hoặc PARTIAL/FAILED/TIMED_OUT đúng thực tế;
- PARTIAL hiện thông báo ngắn và dialog service/error code.

## 03:50–04:40 — 6. Dashboard

Chỉ các KPI: total resources checked, resource cần review, observing, insufficient data, scan status/last scan.

> Resource count và finding count là hai số khác nhau. Một resource có thể có nhiều findings; resource 0 finding vẫn thuộc inventory. PARTIAL chỉ phản ánh phần đã đọc được.

## 04:40–06:10 — 7. Search & Filter

### Tất cả tài nguyên đã quét

- Tìm Resource ID dài và tên Unicode.
- Filter service/type/region.
- Chọn type có 0 finding nếu dataset có.
- Chỉ ra finding count bên cạnh identity không phải inventory count.

Nếu scan legacy/API chưa có identity, hiển thị notice aggregate-only; không giả Resource ID.

### Tài nguyên có cảnh báo

- Tìm theo Resource ID/name, Finding ID hoặc Rule ID.
- Lọc REVIEW, OBSERVING, INSUFFICIENT_DATA.
- Kết hợp service + type + region + rule theo AND.
- Reset và chỉ ra option cập nhật khi đổi scan.

### Tìm trong lịch sử

- Chọn khoảng ngày theo `Asia/Ho_Chi_Minh`, scan status/type/rule/resource ID.
- Nói rõ history hiện là findings history; full historical inventory identity search chưa có.

## 06:10–07:00 — 8. Evidence

Mở side panel một finding. Chỉ resource/service/rule/status/reason/recommendation, threshold, sample/coverage và thời gian scan.

> Evidence là snapshot của lần đánh giá. INSUFFICIENT_DATA không được coi là an toàn. Finding là ứng viên cần người dùng xác nhận, không phải lệnh xóa.

## 07:00–07:50 — 9. Acknowledge / Keep / Ignore

1. Acknowledge rồi reload.
2. Keep, mở tab quản lý, Unkeep.
3. Ignore 1–30 ngày, chỉ expiry, sau đó Cancel Ignore.
4. Mở history để chứng minh feedback mới không rewrite snapshot cũ.

> Feedback chỉ thay đổi cách hệ thống hiển thị và theo dõi; không gọi API phá hủy resource AWS.

## 07:50–08:40 — 10. History và recovery

Mở nhiều scan/region, load trang tiếp theo, xem terminal status/error. Trình bày async retry → SQS failure destination → recovery/reconcile.

Chỉ nói `VERIFIED ON AWS` nếu có request ID/scan ID/tick evidence từ release gate. Alarm `OK` hoặc queue rỗng không tự chứng minh failure path đã chạy.

## 08:40–09:30 — 11. Email

Nếu chưa có phê duyệt SES:

- render HTML/text bằng local fixture;
- chỉ subject, summary, top 5, CTA, PARTIAL warning;
- nói rõ `NOT SENT`.

Nếu đã được phê duyệt:

- xác nhận sender/domain identity, sandbox/recipient, DKIM/SPF/DMARC/MAIL FROM;
- gửi một email test;
- lưu SES Message ID/delivery event và kiểm tra Gmail desktop/mobile.

Không dùng raw evidence JSON và không tuyên bố delivery chỉ từ trạng thái `SENT` của API.

## 09:30–10:00 — Kết luận

> Local regression hiện pass 422 test, một AWS E2E được skip theo gate, và 13 UI scripts pass. Inventory identity current-scan đã implement trong source nhưng production chỉ được coi là hoạt động sau khi route, IAM, backend và frontend cùng được deploy/smoke. Full historical inventory search, AWS verification 38 loại và SES domain authentication vẫn là phần chưa nghiệm thu.

## Checklist evidence sau demo

- [ ] Revision/hash và stack.
- [ ] Auth/tenant evidence đã redacted.
- [ ] Scan ID, region, terminal state và request ID.
- [ ] Inventory identity hoặc aggregate-only notice đúng deployment.
- [ ] PARTIAL/permission evidence nếu được exercise.
- [ ] Feedback + immutable history.
- [ ] SES Message ID/delivery hoặc ghi rõ `NOT_SENT`.
- [ ] Không có console/network error ngoài scenario chủ đích.
- [ ] Không có tuyên bố vượt quá evidence.
