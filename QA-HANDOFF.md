# Bàn giao QA local Task 7–9 cho Hải

Gói này phục vụ kiểm tra độc lập bản tích hợp Plan 09. Người dùng nhận và chuyển cho Hải theo yêu cầu ngày 31/10/2026. Đây là checklist kỹ thuật và evidence local; Task 13 báo cáo/slide vẫn hoãn. **Xác nhận trực tiếp của Hải: CHƯA NHẬN.** Review bằng subagent được ghi riêng, không thay chữ ký của Hải.

## Phiên bản và nội dung gói

- Nhánh: `codex/task-7-finding-observations`; baseline Plan 09: `5cbf3878495679414ff2bdeb7ec5722adc1d7e35`.
- Code đã kiểm chứng: `1d3d7c22efb78f5de16611c9493e50da2ca70e4a`. Trạng thái tự động: backend336 test/335 PASS/1 AWS skip; tám bộ UI PASS. Đây là đầu vào để Hải kiểm lại, không điền sẵn PASS vào cột Hải.
- Revision cuối và SHA-256 từng file nằm trong `manifest.json` của ZIP bàn giao. `source/` chứa snapshot source/test/template/tài liệu đã được chọn; không cần có branch local của tác giả để chạy demo.
- `evidence/` gồm kết quả backend/browser/static, ảnh desktop/mobile và review local. Thời gian giả lập của test retention/expiry không phải bằng chứng thời gian thật trên AWS.
- Chi tiết kết quả/giới hạn: [VALIDATION.md](VALIDATION.md). ZIP và evidence gốc nằm trong `.preflight/duc-plan-09/` tại máy tác giả, không được commit. Người dùng cần gửi ZIP cho Hải; chỉ gửi đường dẫn cục bộ không làm file xuất hiện ở máy khác.

## Chạy lại trên PowerShell

Giải nén gói, vào thư mục `source`, dùng Python 3.12 và Node đã cài:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m playwright install chromium
$env:CRG_AWS_E2E = '0'
$env:AWS_EC2_METADATA_DISABLED = 'true'
$env:UI_QA_DIR = Join-Path (Get-Location) '.preflight\hai-qa'
.\.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_integrated_demo.py
node --check web/app.js
.\.venv\Scripts\cfn-lint.exe template.yaml target-role.yaml web/target-role.yaml
```

Các bộ UI còn lại chạy bằng cùng Python: `ui_scope_filters.py`, `ui_finding_details.py`, `ui_finding_feedback.py`, `ui_feedback_management.py`, `ui_history_management.py`, `ui_redesign.py`. Chúng tự mở HTTP server local. Nếu dùng Chrome có sẵn, đặt `CHROMIUM_EXECUTABLE` tới executable thực tế. Có thể mở demo thủ công bằng `python demo.py`, vào `http://127.0.0.1:8080`.

## Checklist Hải kiểm tra và ghi kết quả

Điền PASS/FAIL/CHƯA CHẠY cùng revision, môi trường và evidence quan sát được. Bảng chưa điền dưới đây không phải PASS.

| Ca | Thao tác và kết quả cần quan sát | Kết quả của Hải |
|---|---|---|
| H01 | Profile mặc định: bốn nhóm, chín loại, counts mẫu31/10 finding; 8 REVIEW/1 OBSERVING/1 INSUFFICIENT_DATA. SES tắt, nút email disabled | CHƯA CHẠY |
| H02 | Lọc kết hợp type/group/region/level/ack/search; xóa bộ lọc lấy lại đúng dữ liệu. Lưu/tải lại 11 cấu hình và phạm vi | CHƯA CHẠY |
| H03 | Chi tiết đủ chín loại: identity/account/rule, lý do/khuyến nghị, ngưỡng/cửa sổ/đơn vị/độ phủ và first/last ISO UTC; 0 thật giữ nguyên, thiếu ghi rõ | CHƯA CHẠY |
| H04 | Đã xem vẫn hiện qua refresh/scan; bỏ đã xem không xóa keep/ignore | CHƯA CHẠY |
| H05 | Giữ/bỏ giữ; bỏ qua 1 và 30 ngày/hủy bỏ qua/đổi hạn. Chỉ cập nhật sau PUT thành công; các cờ độc lập, metadata legacy vẫn quản lý được | CHƯA CHẠY |
| H06 | Scan tiếp giữ first, tăng last; hidden candidate vẫn cập nhật; đổi level/tạm mất finding không reset first. Reconnect tách version và reset dữ liệu demo | CHƯA CHẠY |
| H07 | History/feedback hơn20 record: tải thêm không trùng/mất region; refresh reset cursor; trang sau lỗi giữ hàng và cho retry | CHƯA CHẠY |
| H08 | Chi tiết scan đủ region ngoài trang đầu, trigger/thời gian/status/lỗi đúng snapshot; feedback/settings mới không sửa history | CHƯA CHẠY |
| H09 | QUEUED/RUNNING/PARTIAL/FAILED/TIMED_OUT và dữ liệu thiếu không thành kết luận đã kiểm tra đủ/zero. Loading, lỗi API, retry và 401 đúng | CHƯA CHẠY |
| H10 | Keyboard, focus sau poll/save/tải thêm/retry; dialog Escape/trả focus. Response cũ sau refresh/chọn scan/reconnect không ghi đè | CHƯA CHẠY |
| H11 | Desktop1440/tablet768/mobile390/320; ID/lỗi dài không tràn ngang, text HTML hiển thị an toàn; lưu ảnh | CHƯA CHẠY |
| H12 | Full backend và tám bộ UI kết thúc đúng exit code, không có page/fixture error; ghi rõ AWS E2E mặc định skip | CHƯA CHẠY |

## Phản hồi cần gửi lại

Hải ghi tên/ngày, revision hoặc manifest hash, OS/Python/browser, kết quả H01–H12 và lỗi có bước tái hiện/ảnh/log. Nếu có lỗi, ghi hành vi thực tế và mong đợi; không cần sửa trực tiếp để báo QA. Tác giả xử lý lỗi được tái hiện và chạy lại phần liên quan trước khi bàn giao revision mới.

AWS/Cognito/STS thật, cửa sổ EBS/EIP 24 giờ, EventBridge/retry/SQS recovery, hai tenant và artifact deploy chưa được nghiệm thu bởi gói local. Không bật AWS harness hoặc chạy deploy/publish từ checklist này; các bước đó thuộc Plan 10–12 và phạm vi được ủy quyền riêng.
