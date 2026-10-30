# Frontend design — 2026-10-11

Apply the provided `skill.md`. Audience: Vietnamese AWS newcomers connecting a read role, then reviewing evidence before taking action.

## Plan and critique before implementation

Palette: ink #193849, sea #126782, mist #eef4f6, paper #ffffff, amber #995c12, error #a52e38. Typography: locally available Segoe UI for Vietnamese interface text; Georgia only for the welcome statement, with Vietnamese fallback. Body 15px, labels 14px, section 20px, page 32px. Left aligned; comfortable line lengths.

Initial idea: four equal KPI cards above a card grid. Rejected because this repeats a generic SaaS layout and makes unscanned accounts look like measured data. Revised: one continuous inventory strip, a prominent actionable scan-state panel, then evidence rows. The connection workflow is the distinctive element: a numbered procedural rail paired with a practical parameter sheet, followed by the connection form and first-scan instructions. Numbers represent actual sequential actions.

```text
navigation | page title                      scan
           | current state + next action
           | inventory strip
           | account scope | scan by region
           | evidence table

connection | 1. download and create stack | copy parameters
           | 2. Role ARN, regions and service groups
           | 3. first scan and interpretation
```

On mobile: compact two-column navigation, single-column steps, evidence rows become labeled blocks. Use visible focus, native controls, 44px targets, no ambient animation, reduced-motion support. No gradients or decorative statistics; amber marks review candidates, blue denotes observation, red denotes failures. Never use zero to mean unknown. Partial results must describe scope and truncation. Keep authentication, backend API contracts, rules and infrastructure unchanged.

## Verification

Use the existing local demo smoke test plus isolated API fixtures for new-user, failed connection, partial/empty/queued/running/failed/timed-out scans, unavailable SES, API outage and responsive layouts. Fixtures stay in tests. Inspect screenshots before delivery. AWS deployment is a separate gate requiring available AWS MCP, identity, stack Outputs, online backup and preserved production config.

CloudFormation console wording was checked against the [official create-stack guide](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html) and [IAM capabilities guidance](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/control-access-with-iam.html). No IAM policy was changed.

## Plan 04 — scope, settings and filters, 2026-10-29

Giữ palette, navigation, inventory strip và luồng kết nối hiện có. Form kết nối thêm bốn nhóm compute/storage/database/network theo hợp đồng API đã có; payload frontend gửi role_arn, regions, service_groups. Đây là nối trường được backend hỗ trợ, không thay route/auth/schema API hoặc quyền AWS của lượt này.

- Sáu control lọc: tìm kiếm, nhóm dịch vụ, một trong chín loại tài nguyên, region, level và đã xem/chưa xem; kết hợp AND. Scope counter luôn giải thích PARTIAL/lỗi/chưa quét, kể cả khi không có hàng khớp. Bộ lọc là dữ liệu cục bộ của kết quả đã tải, không khẳng định mọi tài nguyên AWS đã được đọc.
- Desktop ba cột, kích thước trung gian hai cột, mobile dưới 480px một cột; checkbox nhóm dịch vụ hai cột rồi một cột trên mobile. Giữ focus/label/target 44px, không thêm animation hoặc đổi layout các phần khác.
- Mười một setting theo LIMITS backend; decimal dùng step=any, trường nguyên dùng step=1. Cửa sổ metrics dùng chung EC2/RDS/NAT/ALB/NLB; S3 multipart vẫn cố định quá bảy ngày. Không thêm setting hoặc production dependency mới.
- Save/reload giữ lựa chọn nhóm, frontend chặn nhóm rỗng trước request; legacy profile thiếu nhóm mặc định đủ bốn. Khởi tạo lại scope xóa filter/history cũ, hủy poll cũ và dùng generation guard để bỏ response findings/history đến muộn, cả success/error; init cũ không ghi đè profile/status mới.
- Demo chỉ đồng bộ phần lưu/lọc scope và cấu hình; bộ dữ liệu bốn loại hiện có giữ nguyên. Chi tiết evidence, hành động feedback mới và history pagination chưa được triển khai trong Plan 04.

QA bằng demo smoke, [fixture scope/filter](tests/ui_scope_filters.py) và [fixture trạng thái hiện có](tests/ui_redesign.py) trên Chrome local. Chụp findings/connection/settings tại 320/390/768/1440px và xem ảnh desktop/mobile; kết quả/evidence cụ thể ở [VALIDATION.md](VALIDATION.md). Browser fixture và ảnh không phải AWS E2E; sau Plan 04 dừng và chờ người dùng yêu cầu Plan 05.

## Plan 05 — chi tiết finding và evidence, 2026-10-30

Một native dialog dùng chung từ priority, findings và bảng finding trong history. Nút Xem chi tiết đặt dưới tóm tắt evidence; không thay navigation hoặc luồng feedback hiện có. Bảng giới hạn resource ID/tóm tắt ba dòng, có tỷ lệ cột cố định để ID/key dài không ép nút thao tác xuống từng ký tự; dialog hiển thị đầy đủ text có wrap và cuộn dọc. Desktop dùng hai cột thông tin, mobile một cột; resource/reason/recommendation trải hết chiều ngang.

Thông tin lấy từ finding đã chọn: account/region/evaluated_at có thể fallback sang evidence của cùng snapshot; không fallback profile hay cấu hình hiện tại. Hai mốc first/last chỉ lấy trường top-level, hiển thị UTC và giải thích khác cửa sổ metrics. Trường thiếu/null hoặc timestamp sai/không có timezone ghi Chưa có dữ liệu; không backfill hoặc suy từ tuổi tài nguyên. Số 0, boolean false và danh sách diagnostics rỗng giữ nghĩa riêng.

Catalog evidence đúng schema chín loại: EC2 CPU/network/launch; EBS dung lượng/thời gian chưa gắn; EIP thời gian chưa liên kết; snapshot tuổi/volume/quan hệ AMI; RDS CPU/kết nối/engine/class; NAT traffic/VPC/subnet; ALB request/scheme; NLB flow/scheme; S3 bucket/key/upload ID/tuổi/thời điểm bắt đầu. Năm loại metric hiển thị cửa sổ đầu/cuối, period/statistics/units, coverage, sample counts/required/invalid/missing và data issues. Các rule phi metric giải thích không áp dụng độ phủ CloudWatch. Ngưỡng lấy từ evidence.thresholds, có fallback các trường ngưỡng legacy trong cùng evidence.

Native dialog có accessible name/description, autofocus nút đóng, Escape và trả focus. Polling thay DOM opener thì handler close tìm lại nút cùng finding ID/region/resource trong đúng danh sách; finding biến mất dùng control còn hiển thị. Navigation/init/reconnect/logout/401 tự đóng và không kéo focus về trang cũ. Nội dung dùng textContent, không chèn HTML hoặc tự tạo link từ resource ID.

[Fixture chi tiết](tests/ui_finding_details.py) tạo chín schema bằng evaluator thật và kiểm tra current/history snapshot, zero/missing/false, thời gian, XSS, ID dài, focus sau polling và responsive 320/390/768/1440px. Demo giữ dữ liệu mẫu bốn loại và có thể thiếu metadata; đây là ca legacy, không thêm metadata giả. Không đổi backend/API/IAM, không triển khai AWS. Evidence local cụ thể ghi ở [VALIDATION.md](VALIDATION.md); dừng sau Plan 05, chờ yêu cầu Plan 06.

## Plan 06 — phản hồi finding, 2026-10-30

Action cell trên current/priority có Đánh dấu đã xem/Bỏ đã xem, Giữ lại, select 1–30 ngày mặc định 7 và nút Bỏ qua theo hạn đã chọn. Đã xem vẫn hiện, có nhãn trạng thái và tham gia bộ lọc đã xem; keep/ignore ẩn sau PUT thành công. Mỗi request chỉ gửi identity + một cờ, không gửi metadata. History tiếp tục chỉ xem evidence, không thêm thao tác phản hồi vào snapshot.

Trạng thái pending/message/ignore days được giữ theo finding ID + region trong scope hiện tại, dùng chung hai danh sách. Các control cùng finding bị khóa khi đang lưu, polling dựng lại bảng vẫn giữ pending và focus. Lỗi PUT không đổi dữ liệu finding và cho thử lại; PUT thành công rồi GET lỗi báo đã lưu nhưng cần tải lại kết quả. Revision guard loại findings GET khởi đầu trước lần lưu thành công; generation guard loại kết quả PUT/error của kết nối cũ. Init reset trạng thái; 401 quay về đăng nhập. Sau khi hàng bị ẩn, focus về control còn hiển thị.

Demo dùng candidate snapshot + overlay như backend để acknowledge/keep/ignore tồn tại qua refresh/scan tiếp và không sửa history. Metadata feedback chỉ copy field hiện có từ candidate; demo bốn loại legacy không được thêm account/rule giả. Payload strict giống backend; finding ID theo region để cờ không ảnh hưởng region khác. Backend enrich metadata nhưng không đổi request schema, IAM hoặc rule.

[Fixture phản hồi](tests/ui_finding_feedback.py), smoke demo và các fixture hiện có kiểm tra API thành công/lỗi/retry, held PUT/GET, reconnect/401, cờ độc lập và responsive/keyboard. Plan 07 mới thêm quản lý feedback ẩn/bỏ giữ/bỏ ignore/phân trang. Kết quả và ảnh local ở [VALIDATION.md](VALIDATION.md); không phải AWS E2E.
