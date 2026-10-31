# Validation matrix

## Plan 09 — demo chín loại và QA tích hợp local, 31/10/2026

**Đạt code/local Plan 09; chờ Hải xác nhận QA trực tiếp, chưa nghiệm thu AWS.** Baseline `5cbf3878495679414ff2bdeb7ec5722adc1d7e35`, nhánh `codex/task-7-finding-observations`. Code commit `1d3d7c22efb78f5de16611c9493e50da2ca70e4a` — feat(demo): align nine-resource findings and observation state. Không thực hiện Plan 10 hoặc Task 13.

Demo dùng evaluator thuần thật cho chín loại trên inventory/metrics tổng hợp. Metadata account/region/rule/recommendation/evaluated_at, ngưỡng/window/unit/coverage và mốc first/last đồng bộ schema backend. Mặc định counts mẫu31/10 finding:8 REVIEW/1 OBSERVING/1 INSUFFICIENT_DATA. Registry RAM theo connection/region/finding cập nhật trước feedback; expiry last+30 ngày, first giữ qua level/absence/keep/ignore, last không lùi, reconnect reset. Các snapshot cũ không bị backfill. SES/control email tắt; PUT bật hoặc sai boolean bị từ chối. Không đổi src production, web runtime, template/IAM hoặc thêm dependency.

| Kiểm tra | Kết quả / giới hạn |
|---|---|
| Full backend Python 3.12.14 | **336 test: 335 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 144.922 giây toàn runner. 31/10/2026 15:02:34–15:04:59 UTC, CRG_AWS_E2E=0, metadata disabled. SHA-256 source trước/sau khớp; unit/mock/Moto, không AWS |
| Demo regression | **53/53 PASS** gồm12 mới trong full suite và lượt targeted độc lập. Chín schema, zeros/missing, settings/window, stable identity S3/ARN, timestamps qua hidden/level/absence/expiry/clockrollback/region/reconnect, legacy feedback, history và pagination. Bốn suite cũ save/restore registry mới; legacy missing-metadata vẫn kiểm tra bằng explicit fixture thiếu field |
| Browser integration mới | **12 nhóm PASS, 57 request, 0 page error**, qua demo HTTP thật. Chỉ intercept pending/503 có chủ đích để kiểm tra lỗi/retry; hơn20 record được thêm RAM trong process test, không có route QA mới. 45 history và45 feedback/ba region, scan tiếp giữ first/tăng last, cờ độc lập, immutable history, reconnect và401 |
| Bảy bộ browser hiện có | **7/7 PASS**: ui_smoke.py, ui_scope_filters.py, ui_finding_details.py, ui_finding_feedback.py, ui_feedback_management.py, ui_history_management.py, ui_redesign.py. Cùng integration là **8/8 bộ UI**. Smoke được cập nhật31/10/8 REVIEW và SES disabled, không bỏ kiểm tra save/reload/scan/history/expired session |
| Independent local QA | Subagent chạy độc lập **53/53 demo test và7/7 nhóm probe PASS**, review diff cùng visual không còn issue actionable được xác định. JSON/probe pin cùng demo hash cuối; đây không đại diện Hải QA |
| Visual/a11y | Bốn viewport **320/390/768/1440px**, năm trang/dialog, keyboard/Escape/focus và nội dung dài/HTML an toàn. Integration có12 ảnh overview/identity/evidence đã cuộn. Tác giả và reviewer đã xem overview1440 + S3 evidence scrolled390; không tràn ngang/cắt nội dung |
| Static | JS syntax PASS; AST8 Python demo/test đổi hoặc mới; cfn-lint **exit0** trên cả3 SAM/IAM template; target-role hai bản giống byte; link Markdown và whitespace/conflict check PASS. SAM CLI không có trong môi trường nên `sam validate`/`sam build` **CHƯA CHẠY**; cfn-lint đã kiểm SAM transform cục bộ |
| Bàn giao Hải | Người dùng chọn nhận gói để chuyển Hải. [QA-HANDOFF.md](QA-HANDOFF.md) có checklist H01–H12/lệnh chạy. **CHƯA NHẬN** kết quả hoặc chữ ký Hải; không đánh đồng với subagent review |
| AWS/CI/release | **CHƯA CHẠY** AWS E2E, tick EventBridge/retry/recovery thật, deploy/publish/CI. SES tắt, B1–B4 còn mở; không tạo artifact deploy hoặc bật harness cloud |

Artifact ignored tại `.preflight/duc-plan-09/`: `baseline.json`, `backend.txt`/`backend.json`, `static.json`, `validation.json`, tám log browser, acceptance JSON/ảnh và `independent-qa/`. `qa-handoff.zip` chứa snapshot source đã chọn, manifest SHA-256, checklist cùng evidence local để người dùng chuyển Hải; không có .env, config triển khai, Git metadata hay credentials. Gói QA này không phải ZIP Lambda được pin cho Plan 10. Source/hash và commit cuối được ghi trong manifest ZIP.

Phạm vi13 file: [demo.py](demo.py); mới [test_demo_integration.py](tests/test_demo_integration.py), [ui_integrated_demo.py](tests/ui_integrated_demo.py); cập nhật [test_demo_scope.py](tests/test_demo_scope.py), [test_demo_feedback.py](tests/test_demo_feedback.py), [test_demo_feedback_pagination.py](tests/test_demo_feedback_pagination.py), [test_demo_history_pagination.py](tests/test_demo_history_pagination.py), [ui_smoke.py](tests/ui_smoke.py); tài liệu [README.md](README.md), [FRONTEND-DESIGN.md](FRONTEND-DESIGN.md), [DUC-TASKS.md](DUC-TASKS.md), [QA-HANDOFF.md](QA-HANDOFF.md) và `VALIDATION.md`. **Dừng sau Plan 09, chờ người dùng yêu cầu Plan 10.**

## Plan 08 — lịch sử phân trang và chi tiết lượt quét, 31/10/2026

**Đạt code/local Plan 08, chưa nghiệm thu AWS và không thực hiện Plan 09 hoặc Task 13.** Baseline `da0922ef5c4763ce8404a881bea2c1fe7e37394c`, nhánh `codex/task-7-finding-observations`. Commit UI `4cfc103` — feat(web): paginate history and show complete scan details; commit API/demo `2b6de95` — fix(scans): retain all regions in historical scan details.

Lịch sử dùng GET /history limit20 + next_token opaque, dedup scan_id + region, reset cursor khi tải lại và giữ dữ liệu/selection khi trang sau lỗi. Xem mở đủ các region của cùng scan qua GET /scans/{id}; metadata/trigger/thời gian/trạng thái/lỗi theo region và finding evidence đều từ snapshot, không lấy settings/profile hiện tại để điền trường thiếu. Dữ liệu cũ thiếu ID chỉ mở snapshot đã tải và không gọi API bằng undefined. Phản hồi finding không sửa history.

Regression đã tái hiện GET /scans/{id} mất region khi RESULT ở một phần region bị scan mới thay. API nay gộp HISTORY cùng tenant/connection/scan còn hạn, ưu tiên snapshot terminal rồi bổ sung RESULT cho region khác; không ghi lại dữ liệu, không xuất candidates. Demo đồng bộ cách gộp, hỗ trợ history pagination route/connection-bound và giữ retention 30 ngày thay cap 20 hàng. Cursor history production giữ hợp đồng tenant/route-bound hiện có; UI reset cursor khi init/đổi kết nối. Không đổi schema request, IAM, collector/rule, Lambda async hoặc SQS failure destination.

| Kiểm tra | Kết quả / giới hạn |
|---|---|
| Full backend Python 3.12 | **324 test: 323 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 137.172 giây toàn runner. Chạy 31/10/2026 14:52:24–14:54:41 UTC trên source cuối; SHA-256 trước/sau khớp. AWS E2E tắt, metadata disabled; unit/mock/Moto |
| Backend contract mới | **10/10 PASS**; cùng API và Task 8 **63/63 PASS**. 45 history qua ba trang/nhiều region, TTL/version không cần cleanup, cursor tenant/route/xóa boundary, feedback bất biến, private candidates, RESULT bị thay từng region và HISTORY ưu tiên + RESULT RUNNING bổ sung |
| Demo history mới | **12/12 PASS**, cùng demo feedback/scope **41/41 PASS**. 45 rows/ba trang, limit/cursor/query, reconnect/expiry, bỏ cap 20, detail dedup và snapshot terminal ưu tiên, không overlay feedback |
| Browser history mới | **PASS 15 nhóm**, **58 request, 22 GET history, 13 GET scan**, 0 page/fixture error. Hơn 20/dedup/ba region, opaque cursor, lỗi/retry/reset, detail ngoài trang đầu, chín loại evidence/zero, legacy/XSS, snapshot bất biến, response cũ qua selection/refresh/reconnect và 401 |
| Sáu bộ UI hiện có | **PASS**: ui_smoke.py, ui_finding_details.py, ui_finding_feedback.py, ui_feedback_management.py, ui_scope_filters.py, ui_redesign.py. Ba fixture thêm route GET scan detail; scope fixture cập nhật matcher cho query limit20, giữ nguyên kiểm tra stale success/error |
| Review độc lập | Regression đóng lỗi region API. Chrome đóng lỗi retry detail mất focus về BODY: **4 assertion PASS**, không giành focus đã chuyển; thêm **3 ca async PASS** cho selection cũ success/error và refresh vô hiệu pending detail. Không còn issue actionable được xác định trong phạm vi đã review |
| Visual/responsive | **320/390/768/1440px**, 5 ảnh history gồm bốn viewport và lỗi trang sau; đã xem desktop1440/mobile390. ID, lỗi dài và dữ liệu thiếu wrap, không tràn ngang; keyboard pagination/reload/retry có regression |
| Static/Git | JS syntax, AST 10 Python demo/src/test mới hoặc đổi, Markdown links và whitespace/conflict check; stage allowlist, AGENTS.md cục bộ được giữ riêng. Mốc code và source hash trong manifest local |
| AWS/CI/release | **CHƯA CHẠY** AWS E2E/deploy/publish/CI; không chạy lại SAM lint/build vì template/IAM không đổi. SES tắt theo scope; blocker B1–B4 vẫn mở |

Lượt full suite đầu có hai lỗi fixture API cũ thiếu region; đã bổ sung region đúng schema worker, không bỏ assertion UUID/candidates. Lượt sau **323 test: 322 PASS, 1 AWS E2E SKIPPED**. Sau đó thêm regression demo ưu tiên snapshot terminal để khớp API, chạy demo 41/41 và chạy lại full suite có pin hash trên source cuối. Không dùng lượt cũ làm kết quả cho source mới.

Artifact ignored tại `.preflight/duc-plan-08/`: `backend.txt`/`backend.json`, `validation.json`, log sáu suite UI hiện có; `ui-history/acceptance-results.json` và năm ảnh. Đây là evidence local, không phải GitHub CI, cloud deployment hoặc nghiệm thu AWS. Bốn tài liệu kỹ thuật được cập nhật; báo cáo Task 13 vẫn hoãn. **Dừng sau Plan 08, chờ người dùng yêu cầu Plan 09.**

Phạm vi 17 file:

- Runtime: [src/app.py](src/app.py), [demo.py](demo.py), [web/app.js](web/app.js), [web/index.html](web/index.html), [web/styles.css](web/styles.css).
- Regression mới: [test_history_management.py](tests/test_history_management.py), [test_demo_history_pagination.py](tests/test_demo_history_pagination.py), [ui_history_management.py](tests/ui_history_management.py).
- Fixture hiện có: [test_api.py](tests/test_api.py), [ui_finding_details.py](tests/ui_finding_details.py), [ui_finding_feedback.py](tests/ui_finding_feedback.py), [ui_feedback_management.py](tests/ui_feedback_management.py), [ui_scope_filters.py](tests/ui_scope_filters.py).
- Tài liệu: [README.md](README.md), [FRONTEND-DESIGN.md](FRONTEND-DESIGN.md), [DUC-TASKS.md](DUC-TASKS.md) và `VALIDATION.md`.

## Plan 07 — quản lý feedback đang ẩn, 30/10/2026

**Đạt code/local Plan 07, chưa nghiệm thu AWS; chưa thực hiện Plan 08 hoặc Task 13.** Baseline `6f09a8536fa64fcb466ac424f6daaa757d99c238`, nhánh `codex/task-7-finding-observations`. Commit code đã tạo sau validation:

- `576b382d0d6350c45dcf32ad7c02d6d7d51bd891` — feat(feedback): paginate demo records and verify management contracts.
- `03cd770337777ee11665ab4950094055922a649b` — feat(web): manage kept and ignored findings.

Card quản lý dưới findings dùng GET /feedback limit20/next_token, dedup identity và filter active kept/ignore. API có thể trả một trang toàn ack-only, nên vẫn cho tải tiếp nếu còn cursor. Bỏ giữ/hủy bỏ qua/đổi hạn gửi một cờ; cờ khác và history giữ nguyên. Legacy thiếu metadata dùng finding ID/region. Sau clear, fresh GET /findings có finding mới đủ để báo đang hiện lại; không thấy thì hướng dẫn scan mới/giới hạn, còn cờ ẩn thì giải thích cờ còn lại.

Giữ dữ liệu khi tải trang sau lỗi, reset cursor khi refresh, ignore GET/PUT cũ qua save/reconnect. Demo có cursor theo route/connection/key và validation query; không thay src/app.py/API production, collector/rule/IAM/template hoặc thêm dependency. Bốn fixture browser cũ chỉ bổ sung GET /feedback để phản ánh request mới; smoke demo hiện có không sửa.

| Kiểm tra | Kết quả / giới hạn |
|---|---|
| Full backend Python 3.12 | **302 test: 301 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 141.032 giây toàn runner (unittest 139.473 giây). Chạy 30/10/2026 11:18:06–11:20:27 UTC, CRG_AWS_E2E=0, EC2 metadata disabled; local unit/mock/Moto |
| Backend contract mới | **6/6 PASS** trong full suite; targeted trước đó 6/6. Trang 20 ack-only +11 kept, TTL/wrong-version skip, reconnect/history token rejection, legacy absent candidate/flags/history và expiry boundary |
| Demo pagination mới | **9/9 PASS** trong full suite; targeted cùng feedback/scope đạt 29/29. 45 records/ba trang, query HTTP, limits, cursor sai/reconnect/xóa record trang trước, expiry/foreign rows và legacy không fake restore |
| Browser manager mới | **PASS**, **14 nhóm/101 request/13 PUT**, 0 page/fixture error: hơn 20/dedup/opaque token, filtered-empty page, retry giữ data, clear từng cờ/candidate còn/mất, legacy, đổi 1/30 ngày, held GET/PUT và reconnect, history read-only, XSS, keyboard và 401 |
| Năm bộ UI hiện có | **PASS** trên source cuối: ui_smoke.py, ui_finding_feedback.py, ui_finding_details.py, ui_scope_filters.py, ui_redesign.py. Cùng manager là **sáu bộ browser**; fixture GET mới không bỏ qua pending/reconnect regression cũ |
| Review độc lập | Hai lỗi P2 tái hiện Chrome rồi đóng: current/manager trùng identity làm onchange null; load-more trang cuối làm focus BODY. Selector fix và focus summary có regression lâu dài. Focus probe độc lập **4/4 PASS**, không giành focus search hoặc idle refresh; không còn issue actionable được xác định |
| Visual/responsive | **320/390/768/1440px**, không tràn ngang; 6 ảnh gồm bốn viewport và pending/error component. Đã xem management-1440.png, management-390.png, management-error-1440.png; metadata legacy/ID dài/control đọc được |
| Static và Git | JS syntax; AST tám Python demo/test mới hoặc thay đổi; link checker mặc định + explicit bốn tài liệu; diff/cached whitespace, staged allowlist và source/blob normalization. Hash/result cuối pin manifest local |
| AWS/CI/release | **CHƯA CHẠY** AWS E2E/deploy/publish/CI; không chạy lại SAM lint/build vì template/IAM không đổi. SES giữ cấu hình tắt theo scope; B1–B4 vẫn chưa đóng |

Browser chạy qua venv Python và Chrome local với UI_QA_DIR riêng; runner backend lưu unittest discover verbose vào backend.txt/JSON. Test mới: [contract API](tests/test_feedback_management.py), [demo pagination](tests/test_demo_feedback_pagination.py), [browser manager](tests/ui_feedback_management.py). Các lệnh browser là tests/ui_smoke.py, tests/ui_finding_feedback.py, tests/ui_finding_details.py, tests/ui_scope_filters.py, tests/ui_redesign.py và tests/ui_feedback_management.py với python -X utf8 -B.

Evidence Git ignore tại `.preflight/duc-plan-07/`: backend.txt/backend.json có counts/skip/time/hashes; ui-management/acceptance-results.json và 6 ảnh; ui-feedback/, ui-details/, ui-scope/, ui-fixture/ có JSON/ảnh; ui-smoke/ có ảnh; *.txt lưu output năm bộ hiện có. validation.json pin source/test hashes, commit và kết quả static/browser. Đây là fixture/local/Moto, không phải AWS hoặc CI.

Thay đổi: demo.py, ba file web, ba test mới, bốn fixture cũ và bốn tài liệu README/FRONTEND-DESIGN/DUC-TASKS/VALIDATION. AGENTS.md cục bộ giữ riêng; commit theo tính năng, không có số Plan trong tên. **Dừng sau Plan 07, chờ người dùng yêu cầu Plan 08.**

## Plan 06 — phản hồi finding và metadata, 30/10/2026

**Đạt phạm vi backend/UI/demo và kiểm thử local. Chưa triển khai AWS; chưa thực hiện Plan 07 hoặc Task 13.** Baseline `40ceeb3c8f8c06cd2d1774ac1bd4948a2290094a`, nhánh `codex/task-7-finding-observations`. Code được commit local theo phần đã kiểm thử:

- `8770678572f71541b88dc7eba2dc19430e3d6a7a` — feat(feedback): enrich records and align demo state.
- `1d3a0263ac5be42a6a2ce7eb55ebfb22af1e5319` — feat(web): add finding feedback controls.

Current/priority có toggle đã xem, giữ lại và bỏ qua 1–30 ngày, mặc định 7. Mỗi PUT chỉ gửi region/finding_id và một cờ; chờ API thành công mới thay dữ liệu finding, sau đó tải lại. Trạng thái pending theo identity dùng chung giữa hai danh sách, polling không làm mất khóa hoặc hạn đã chọn. Lỗi PUT giữ trạng thái và cho thử lại; PUT thành công rồi GET lỗi báo đã lưu nhưng cần tải lại kết quả. Revision guard bỏ GET khởi đầu trước lần lưu thành công; generation guard bỏ PUT/error của scope cũ. History giữ snapshot, không thêm mutation control.

Backend chọn candidate đúng finding/connection/region để lấy metadata type/resource_id/account_id/rule_id, fallback findings legacy. Field string không rỗng mới được cập nhật; candidate mất/thiếu trường giữ metadata cũ. Không nhận metadata trong payload, không suy từ profile/history. Demo cần đồng bộ tối thiểu cho thao tác mới: candidate snapshot + current overlay, strict validation, finding ID theo region và không lộ candidates. Demo vẫn chỉ bốn loại mẫu, thiếu metadata được giữ thiếu; đồng bộ toàn bộ demo chín loại/phân trang vẫn thuộc Plan 09.

| Kiểm tra | Kết quả / giới hạn |
|---|---|
| Full backend Python 3.12 | **287 test: 286 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 130.172 giây, 30/10/2026 11:06:45–11:08:55 UTC. CRG_AWS_E2E=0, EC2 metadata disabled; local unit/mock/Moto |
| Metadata mới | **12/12 PASS** trong full suite; trước đó metadata + API đạt 37/37. PUT/storage/GET, candidate ẩn/legacy/mất/thiếu, injection, region/connection/tenant, cờ độc lập và history bất biến |
| Demo feedback mới | **12/12 PASS** trong full suite; targeted cùng demo_scope đạt 20/20. Ack/toggle/refresh/scan tiếp, keep/ignore/expiry, metadata, validation trước mutation, region isolation, pending scan không sinh dữ liệu giả và private candidates |
| Browser feedback mới | **PASS**, 11 nhóm kiểm tra, 107 request/34 PUT, **0 page/fixture error**. Toggle đủ chín loại, default/biên 1/7/30 ngày, exact payload, pending/poll/duplicate khóa, PUT lỗi/retry, GET lỗi sau save, history, cờ độc lập, stale PUT success/error, stale GET ack/keep success/error, reconnect và 401 |
| Bốn bộ UI hiện có | **PASS**: ui_smoke.py với demo thật local; ui_finding_details.py 10 nhóm; ui_scope_filters.py 6 nhóm; ui_redesign.py 6 nhóm. Kết quả sau source cuối, không thay code sau các lượt này |
| Responsive/keyboard/ảnh | Feedback findings/priority tại **320/390/768/1440px**, 8 ảnh, không tràn ngang/clipping; tab order ack → keep → hạn → ignore. Đã xem findings-1440.png và priority-390.png; các nút xếp dọc đọc được, ID dài giữ layout |
| Review độc lập | Không có blocker local được xác định trong pending/retry/flags/history/scope/metadata/demo. Node VM probe dùng actual saveFindingFeedback/refresh giữ GET cũ qua PUT cũng PASS, sau đó được khóa bằng browser regression lâu dài |
| Static/tài liệu | node --check web/app.js; AST code/test Python thay đổi/mới; link Markdown mặc định và explicit năm tài liệu; git diff/cached --check, whitelist staged và source/blob chuẩn hóa CRLF/LF. Hash/evidence cuối pin tại manifest local |
| AWS/CI/release | **CHƯA CHẠY** AWS E2E, deploy/publish hoặc CI. Không đổi collector/rule/IAM/template, không thêm dependency; không chạy lại SAM lint/build. SES giữ tắt theo phạm vi, B1–B4 AWS chưa đóng |

Lệnh backend: `python -m unittest discover -s tests -v` qua unittest runner lưu log/JSON. Browser dùng venv với CHROMIUM_EXECUTABLE là Chrome local và UI_QA_DIR riêng cho từng script:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_finding_feedback.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_finding_details.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_scope_filters.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_redesign.py
```

Evidence Git ignore: `.preflight/duc-plan-06/backend.txt`, backend.json (counts/skip/time/source hashes); ui-feedback/acceptance-results.json và 8 ảnh; ui-details/, ui-scope/, ui-fixture/ có JSON/ảnh; ui-smoke/ có ảnh; log bốn bộ hiện có tương ứng *.txt. validation.json pin source/test hashes, commit code và kết quả static/browser. Artifact local không chứa credential và không phải AWS evidence.

Nguồn: [src/app.py](src/app.py), [demo.py](demo.py), [web/app.js](web/app.js), [web/index.html](web/index.html), [web/styles.css](web/styles.css); regression mới [metadata](tests/test_feedback_metadata.py), [demo](tests/test_demo_feedback.py), [browser](tests/ui_finding_feedback.py). Quản lý/bỏ giữ/bỏ ignore/phân trang feedback chưa triển khai; **dừng sau Plan 06 và chờ yêu cầu Plan 07**. Tên commit mô tả tính năng, không thêm số Plan theo yêu cầu người dùng.

## Mốc commit Plan 01–05, 30/10/2026

Theo yêu cầu mới của người dùng, các phần quan trọng đã hoàn tất được commit local theo phạm vi trên nhánh `codex/task-7-finding-observations`:

| Commit code | Nội dung |
|---|---|
| `8e140bb4df9e15c6c2720d8e9042ceec0f83f607` | Plan 02–03: registry DynamoDB, worker/API first/last, IAM và regression; 8 file |
| `d9313dda7af311ebe31eb2242eba185aa7454e04` | Plan 04–05: service groups/filters/settings, demo scope và shared finding details, browser fixture; 9 file |

Checklist/bằng chứng và hướng dẫn Plan 01–05 được gom trong commit tài liệu của cùng đợt bàn giao (7 file). Các dòng “chưa commit” trong snapshot từng plan bên dưới mô tả trạng thái lúc chạy/bàn giao plan đó, được thay thế bởi mốc commit này về trạng thái Git hiện tại. Không sửa code hoặc chạy lại suite trong lượt commit; đã đối chiếu file live với hash evidence mới nhất và staged blob với source sau chuẩn hóa CRLF/LF. Full backend và bốn bộ browser vẫn là kết quả thật của các lượt Plan 03–05 được ghi bên dưới.

Review độc lập xác nhận đủ 24 file theo ba nhóm, không có marker private key/AWS access key trong phạm vi; AGENTS.md cục bộ và thư mục evidence/skill/config không được đưa vào commit. Link tài liệu và git diff --cached --check được kiểm tra trước commit. Chưa push, mở PR hoặc thay đổi AWS. Từ mốc này, commit phần quan trọng sau kiểm thử trước khi bàn giao, vẫn dừng sau mỗi plan chờ yêu cầu tiếp theo.

## Plan 05 — chi tiết finding và evidence, 30/10/2026

**Đạt phạm vi UI/code và kiểm thử local Plan 05. Chưa triển khai AWS; chưa thực hiện Plan 06.** Nhánh `codex/task-7-finding-observations`, HEAD nền `a2201f5d8261d453d0de3e9873b9072773545848`; thay đổi chưa stage/commit/push. Giữ thay đổi Plan 01–04 và AGENTS.md cục bộ. Task 13 tiếp tục hoãn.

Thêm native dialog dùng chung cho finding từ tổng quan, danh sách hiện tại và history. Detail hiển thị account/region/resource/finding ID/rule/level/reason/recommendation, evaluated_at và first/last UTC; evidence theo đủ chín loại. Năm loại metric có window/start/end/period/statistics/units, ngưỡng, coverage và sample diagnostics. Rule phi metric có thời gian/quan hệ riêng, không giả lập độ phủ CloudWatch. Ngưỡng và context lấy từ snapshot finding/evidence, không từ profile/settings hiện tại; không backfill history hoặc suy timestamps.

Giữ số 0, boolean false và diagnostics rỗng; dữ liệu thiếu/null/thời gian sai hoặc thiếu timezone ghi Chưa có dữ liệu. Text được tạo bằng textContent. Bảng tóm tắt giới hạn ba dòng và tỷ lệ cột để ID dài vẫn dùng được, dialog hiển thị đầy đủ và wrap. Review tái hiện lỗi mất focus khi polling thay opener: đã sửa close handler tìm nút finding mới đúng identity/region trong danh sách gốc, hoặc control còn hiển thị nếu finding mất; navigation/init/reconnect/logout/401 đóng tự động không kéo focus về trang cũ.

| Kiểm tra Plan 05 trên bản UI cuối | Kết quả / giới hạn |
|---|---|
| Fixture chi tiết mới | **PASS**, 10 nhóm kiểm tra, 25 request, 0 page error, 0 fixture error. Chín schema tạo bằng evaluator thật rồi thêm context collector và timestamps fixture; không gọi AWS |
| Schema, giá trị và history | Đủ common field/evidence/threshold/units; zero và false; current/history cùng renderer và history giữ nguyên account/window/threshold/first-last sau current mới; legacy/null/invalid date/legacy threshold, không fallback profile |
| An toàn text và keyboard | ID/key/upload ID 1.000–1.200 ký tự, chuỗi HTML/XSS chỉ là text; native modal không focus vào page nền, Escape trả focus; poll thay opener rồi Escape/nút đóng và finding biến mất đều có regression |
| Vòng đời và responsive | Priority/history/current cùng detail; navigation/init/reconnect/401 đóng detail cũ. **320/390/768/1440px**, không tràn ngang; 12 ảnh: tám ảnh current/history ID dài và bốn ảnh EC2/metrics ở desktop/mobile |
| Ba bộ UI hiện có | **PASS**: tests/ui_smoke.py, tests/ui_redesign.py, tests/ui_scope_filters.py; chạy lại sau sửa JS/CSS cuối. Fixture trạng thái 6 nhóm/0 page error; fixture scope 6 nhóm/45 request/0 page hoặc fixture error |
| Review độc lập | Đối chiếu schema chín loại, zero/missing/history/text; lỗi focus đã đóng với **6/6 Chrome probe** (current refresh còn/mất candidate, Escape/nút đóng, history reload, navigation); không xác định blocker local còn lại |
| Visual QA | Đã xem ec2-current-1440.png, ec2-metrics-390.png, current-1440.png, history-320.png; modal wrap/cuộn đúng, metrics/UTC/zero rõ, bảng ID dài không bó nút thao tác thành từng ký tự |
| Static và tài liệu | node --check web/app.js; AST hai Python test mới/thay đổi; link Markdown mặc định và explicit bốn tài liệu; git diff --check/whitespace file test mới. Kết quả pin trong manifest local |
| Backend, SAM/IAM | **Không thay đổi trong Plan 05**, không chạy lại full backend hoặc lint/build SAM. Đối chiếu hash app/rules/collectors/demo/template với baseline Plan 05 và manifest backend Plan 04; kết quả 263 test ở Plan 04 là bằng chứng lượt trước, không tính là lượt test mới |
| AWS, artifact/deploy, CI | **CHƯA CHẠY trong Plan 05**; không thêm dependency. Demo vẫn bốn loại mẫu và thiếu metadata như trước, dùng để kiểm legacy. B1–B4 AWS chưa đóng |

Lệnh UI dùng Python venv 3.12, Chrome local qua CHROMIUM_EXECUTABLE; mỗi script có UI_QA_DIR riêng:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_finding_details.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_redesign.py
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_scope_filters.py
```

Evidence Git ignore tại `.preflight/duc-plan-05/`: baseline.json; validation.json pin hash asset/test và kết quả static; ui-details/acceptance-results.json và 12 ảnh; ui-fixture/acceptance-results.json; ui-scope-filters/acceptance-results.json; ui-smoke/desktop.png và mobile.png. Log ba bộ hiện có là ui-smoke.txt, ui-fixture.txt và ui-scope-filters.txt. Kết quả chi tiết mới được lưu bởi fixture; hash fixture được pin trong manifest.

File Plan 05: [web/app.js](web/app.js), [web/index.html](web/index.html), [web/styles.css](web/styles.css), [tests/ui_finding_details.py](tests/ui_finding_details.py), [tests/ui_smoke.py](tests/ui_smoke.py), [README.md](README.md), [FRONTEND-DESIGN.md](FRONTEND-DESIGN.md), [DUC-TASKS.md](DUC-TASKS.md) và tài liệu này. **Dừng sau Plan 05, chờ người dùng yêu cầu Plan 06.** Các phần bên dưới là snapshot bằng chứng các lượt trước.

## Plan 04 — phạm vi, cấu hình và bộ lọc, 30/10/2026

**Đạt phạm vi code và kiểm thử local Plan 04. Chưa triển khai AWS; chưa thực hiện Plan 05.** Nhánh `codex/task-7-finding-observations`, HEAD nền `a2201f5d8261d453d0de3e9873b9072773545848`; thay đổi còn trong working tree, chưa stage/commit/push. Giữ các thay đổi Plan 01–03 và AGENTS.md cục bộ. Task 13 tiếp tục hoãn; tài liệu này chỉ ghi bằng chứng kỹ thuật cho Task 7–9.

Form kết nối lưu một đến bốn nhóm compute/storage/database/network qua trường service_groups có sẵn của backend. Dashboard có catalog chín loại và sáu control lọc kết hợp AND: tìm kiếm, nhóm, loại, region, level, đã xem/chưa xem. Form cấu hình có đủ 11 setting theo bounds/type backend, decimal step=any và integer step=1. PARTIAL/lỗi/chưa quét vẫn có cảnh báo khi bộ lọc không trả hàng, không diễn giải dữ liệu thiếu thành zero.

Demo đồng bộ validation, scope/counts, 11 cấu hình và reset connection version/pending/history/feedback khi kết nối mới. Dữ liệu mẫu vẫn chỉ EC2/EBS/EIP/snapshot; chín loại được kiểm tra bằng API fixture riêng, chưa phải demo đầy đủ của Plan 09. Review phát hiện và tái hiện response findings/history cũ có thể ghi đè scope mới; generation guard bỏ success/error cũ, hủy poll và reset history/filter khi init. Regression giữ rồi nhả response sau reconnect kiểm tra đủ bốn trường hợp findings/history thành công/lỗi.

| Kiểm tra Plan 04 | Kết quả / giới hạn |
|---|---|
| Full backend, Python 3.12.14 | **263 test: 262 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 54.844 giây. Chạy 29/10/2026, 15:39:25–15:40:20 UTC; CRG_AWS_E2E=0, EC2 metadata disabled; local unit/mock/Moto |
| Demo scope mới | **8/8 PASS** trong full suite: save/reload groups/settings, invalid payload không mutate, legacy/missing/null groups, pending/reset và phạm vi counts/findings |
| UI scope/filter mới | **PASS**, sáu nhóm kiểm tra, 45 request, 0 page/fixture error: chín loại, bốn nhóm, ba region, sáu bộ lọc AND, PARTIAL/unknown, scope save/reload/reset, 11 setting/biên/số nguyên/decimal và bốn ca stale response |
| Demo UI smoke hiện có | **PASS** trên bản JS cuối: dashboard/filter, feedback hiện có, settings validation, region validation, scan/poll/history, mobile và hết phiên |
| UI fixture trạng thái hiện có | **PASS**, sáu nhóm kiểm tra, 0 page error: onboarding, role download/copy, connection payload, lỗi và scan lifecycle/PARTIAL/zero, SES tắt, keyboard và responsive |
| Responsive và ảnh | Scope fixture chụp findings/connection/settings ở **320/390/768/1440px**, 12 ảnh, không tràn ngang; xem ảnh findings desktop/mobile, connection mobile/desktop và settings mobile/desktop. Smoke/fixture hiện có cũng đạt; ảnh là dữ liệu local |
| Review độc lập | Lỗi response cũ đã đóng bằng generation guard và regression trình duyệt; không còn blocker correctness được xác định trong scope/filter/settings local |
| Cú pháp, tài liệu, whitespace | node --check web/app.js; AST Python demo/test thay đổi; checker Markdown mặc định và explicit bốn tài liệu; git diff --check và whitespace file mới. Kết quả cuối ghi cùng manifest local bên dưới |
| AWS, build/artifact/deploy, CI | **CHƯA CHẠY trong Plan 04**. Không đổi src/app.py/rules/collectors/template/IAM ở lượt này; không thêm dependency. B1–B4 vẫn chưa đóng; ảnh/test local không chứng minh AWS acceptance |

Evidence Git ignore:

- `.preflight/duc-plan-04/backend.txt` và `backend.json`: kết quả runner, thời gian UTC, base SHA/branch, module counts, skip reason, SHA-256 Python/template đã kiểm thử.
- `.preflight/plan04/ui-scope-filters/acceptance-results.json` và 12 ảnh findings/connection/settings; các ca kiểm tra ở [tests/ui_scope_filters.py](tests/ui_scope_filters.py).
- `.preflight/duc-plan-04/ui-fixture/acceptance-results.json`, ảnh fixture; `.preflight/duc-plan-04/ui-smoke/desktop.png`, `mobile.png`.
- `.preflight/duc-plan-04/ui-validation.json`: pin hash asset/demo/test cuối, đường dẫn các kết quả UI và static verification. Hash backend được đối chiếu khớp backend.json sau cập nhật tài liệu; không thay code sau các lượt UI cuối.

Nguồn thay đổi: [web/app.js](web/app.js), [web/index.html](web/index.html), [web/styles.css](web/styles.css), [demo.py](demo.py), [test demo scope](tests/test_demo_scope.py), [UI scope fixture](tests/ui_scope_filters.py), [UI trạng thái](tests/ui_redesign.py); hướng dẫn ở [README.md](README.md), [FRONTEND-DESIGN.md](FRONTEND-DESIGN.md), [DUC-TASKS.md](DUC-TASKS.md). **Dừng sau Plan 04, chờ yêu cầu trực tiếp cho Plan 05.** Các mục cũ bên dưới là snapshot lúc bàn giao từng lượt.

## Plan 03 — tích hợp timestamps vào worker/API, 29/10/2026

**Đạt phạm vi code và kiểm thử local Plan 03. Chưa triển khai AWS; chưa thực hiện Plan 04.** Nhánh chung Plan 02–03 `codex/task-7-finding-observations`, HEAD nền `a2201f5d8261d453d0de3e9873b9072773545848`; code/test/tài liệu còn trong working tree. Giữ các thay đổi Plan 01–02 và AGENTS.md cục bộ; không commit/push hoặc thay đổi cloud. Theo yêu cầu người dùng, hoàn tất plan thì báo cáo tóm tắt và dừng, chỉ thực hiện plan tiếp khi có yêu cầu mới.

Worker gọi registry sau collector, trước legacy suppression, feedback và cap. Findings mới được sao chép và gắn first_seen_at/last_seen_at ISO UTC dạng +00:00 từ epoch đã lưu; GET /findings, /scans/{id}, /history giữ các mốc cùng snapshot. Không backfill history cũ hoặc lấy evaluated_at/tuổi tài nguyên làm first giả. Registry None dừng trước terminal write; ClientError hạ tầng/CAS tiếp tục retry.

Hai điều chỉnh cần thiết cho tích hợp: persistence có budget riêng chừa 10 giây theo context/lease/deadline, để PARTIAL có finding khi collector dừng ở ngưỡng dự trữ 60 giây vẫn được lưu; thật sự thiếu budget thì finish_scan TIMED_OUT/TIME_BUDGET bằng run_token, không trả finding thiếu mốc. Marker legacy thiếu deadline_at được gắn bằng if_not_exists theo mốc created_at/started_at gốc, không theo giờ retry. RESULT + HISTORY vẫn nguyên tử; không đổi IAM thêm ở Plan 03.

| Kiểm tra mới trong Plan 03 | Kết quả / giới hạn |
|---|---|
| Full backend, Python 3.12.14 | **255 test: 254 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 75.265 giây toàn runner, unittest báo 75.134 giây. CRG_AWS_E2E=0, EC2 metadata disabled; local unit/mock/Moto |
| Tích hợp timestamps mới | **14/14 PASS** trong full suite; chạy targeted trước đó 14/14 trong 11.779 giây. Hai scan/chín loại/API, level change, absence/FAILED/PARTIAL/30-day expiry, feedback/legacy suppression, reconnect/tenant/region, None ownership, partial registry commit, terminal commit retry/replay, UnprocessedKeys, budget 59/9 giây, legacy deadline và old history |
| Workflow/API/notification hiện có | **93/93 PASS** targeted trước full suite: 50 workflow, 25 API, 18 notification; mock collector bổ sung metadata đúng schema hiện có, không mock bỏ registry. Chín loại qua collector thật và ba API có timestamps nhất quán; byte-cap regression buộc prune khi tính thêm timestamp bytes |
| Lifecycle/budget Task 8 hiện có | **37/37 PASS** targeted: 28 Task 8 + 9 collector budget, trước full suite; không đổi semantics orphan observation hoặc transaction terminal |
| Review độc lập | Không có blocker correctness. Ba Moto probe PASS: PARTIAL + finding còn 59 giây, timeout nhất quán empty/nonempty khi chỉ còn 5 giây, và legacy deadline bám marker tạo trước 100 giây. Source finding không bị mutate |
| AST/docs/whitespace | AST 5 Python thay đổi/mới PASS; checker explicit 6 tài liệu (có DUC-TASKS.md) 0 link hỏng; git diff --check PASS. Hash code/test cuối phải khớp manifest full suite |
| UI/browser, build/artifact/deploy, AWS | **CHƯA CHẠY trong Plan 03**; UI/collector/rule/template không đổi ở lượt này. Bằng chứng mới chỉ local/mock/Moto, không phải CI hoặc AWS acceptance; B1–B4 chưa được đóng |

Evidence Git ignore: `.preflight/duc-plan-03/backend.txt` và `backend.json`, có thời gian UTC, base SHA/branch, module counts/skip reason và SHA-256 của 8 file code/template/test. Hai hash chính:

```text
src/app.py:                                  db19ad610d9cdba9d49293e47f990bc317e805aba02ba99c30393752fc5ab235
tests/test_finding_observation_workflow.py:  adc4772713a872e83c38e3883b359443f25dab0bd324c2f0712d50244f9c7259
```

Test/schema chi tiết ở [tests/test_finding_observation_workflow.py](tests/test_finding_observation_workflow.py) và [RULES.md](RULES.md); trạng thái từng plan ở [DUC-TASKS.md](DUC-TASKS.md). Plan 02–03 đã đạt phạm vi code/local chung; phát hành/AWS vẫn cần artifact mới được pin và điều kiện nghiệm thu hiện có. **Dừng sau Plan 03, chờ yêu cầu trực tiếp cho Plan 04.** Các mục Plan 02/01 dưới đây là snapshot lúc bàn giao từng lượt, không phủ nhận trạng thái tích hợp mới ở mục này.

## Plan 02 — registry mốc quan sát finding, 29/10/2026

**Đạt phạm vi helper persistence + IAM + regression local. Chưa nối vào worker/API (Plan 03), chưa triển khai AWS hoặc phát hành.** Nhánh chung Plan 02–03: `codex/task-7-finding-observations`, HEAD nền `a2201f5d8261d453d0de3e9873b9072773545848`; thay đổi còn ở working tree, giữ nguyên tài liệu Plan 01 và AGENTS.md cục bộ. Các hash bên dưới pin nội dung code/test đã chạy, không phải commit mới.

`record_finding_observations(marker, findings, time_check)` lưu registry OBSF theo tenant/version/region/finding, first/last epoch và TTL 30 ngày từ last. Dedup/strong BatchGet tối đa 100 key, retry UnprocessedKeys tối đa 3 request có backoff và budget; ghi tối đa 98 registry item + 2 marker/profile guards. Snapshot CAS ngăn đọc cũ ghi đè last/first mới. Mất ownership trả None; CAS còn ownership hoặc lỗi hạ tầng truyền ra để retry. Worker hiện chưa gọi helper; evaluator, collector, demo, UI và terminal RESULT + HISTORY giữ nguyên luồng. IAM chỉ thêm BatchGetItem trên Data.Arn cho ScanRole/guardian-worker.

| Kiểm tra mới trong Plan 02 | Kết quả / giới hạn |
|---|---|
| Full backend, Python 3.12.14 | **241 test: 240 PASS, 1 AWS E2E SKIPPED**, 0 failure/error; 82.125 giây đo toàn lượt runner, unittest báo 82.019 giây. CRG_AWS_E2E=0, EC2 metadata disabled; local unit/mock/Moto |
| Registry mới | **24/24 PASS** trong full suite: retention/gap/boundary, monotonic/replay, tenant/version/region, 205 ID/dedup, UnprocessedKeys, read lỗi/response lỗi, stale worker/lease/profile, CAS update/insert/TTL deletion, mixed cancellation, partial write + retry, time budget và input/stored-data validation |
| IAM/template mới | **7 template invariant + 2 read-only PASS**; test mới kiểm tra cả ba template, kể cả wildcard grant, yêu cầu BatchGetItem chỉ ở ScanRole/guardian-worker/Data.Arn. Regression IAM đã FAIL trước cấp quyền và PASS sau sửa |
| Review độc lập | Không có blocker correctness: BatchGet native SDK, 98 + 2 guard, CAS conflict khác mất ownership, TTL tính từ observation và nhiều batch. Ba Moto probe race bổ sung PASS; các ca tương ứng đã được giữ trong suite |
| SAM/IAM lint | **PASS:** cfn-lint template.yaml target-role.yaml web/target-role.yaml; hai target-role template không đổi |
| Docs/AST/whitespace | **PASS:** checker mặc định 12 file/0 link hỏng; explicit 6 tài liệu/0 link hỏng, gồm DUC-TASKS.md mới; AST của 3 Python thay đổi; git diff --check và kiểm tra UTF-8/whitespace/conflict marker cho cả 8 file Plan 02. Hash 4 file code/template/test không đổi từ full-suite |
| Worker/API timestamps, UI, artifact cuối và AWS | **CHƯA CHẠY/CHƯA TÍCH HỢP** trong Plan 02; nối worker/API và kiểm tra byte cap thuộc Plan 03. B1–B4 ở dưới chưa được đóng; Task 13 tiếp tục hoãn |

Kết quả thử nghiệm trung gian: bộ 20 registry test đầu có 19 PASS/1 FAIL do test chỉ đếm Update thay vì chấp nhận Put CAS; đã sửa test theo hành vi và bổ sung race cases. Full suite cuối ở trên mới là kết quả bàn giao. Không có lỗi runtime đã xác minh bị che bởi thay đổi test này.

Evidence cục bộ (Git ignore): `.preflight/duc-plan-02/backend.txt` và `backend.json`, gồm thời gian UTC, Python, base SHA/branch, số test từng module, skip reason và SHA-256 working tree:

```text
src/app.py:                          01e01f83fb476ff20a65ffb2d78f554f18f58ae5cbfca0b075bc80651bd734e7
template.yaml:                       5999408a55491ff33b37a3b213a82a1539a1de9096d6d06ea14ab3071e63b8b8
tests/test_finding_observations.py:  20a893cccb475370a6171f4523c94582fc0cd2628aff8e8541806b5cb341e504
tests/test_task8_template.py:        ba19e67d49ec4df3102ba7413a3395a0ed3484ab24eb153c1e596a9e3476d2b5
```

Hợp đồng và điều kiện tiếp tục Plan 03 ở [DUC-TASKS.md](DUC-TASKS.md); semantics persistence ở [RULES.md](RULES.md). Không phát hành riêng Plan 02; source/template thay đổi làm artifact Task 8 cũ không còn đại diện cho bản này, cần đóng gói và pin lại sau Plan 03 và local validation phù hợp.

## Plan 01 — baseline Task 7–9 của Đức, 29/10/2026

**Lượt này chỉ chốt baseline/checklist/hợp đồng kỹ thuật cho Task 7, 8, 9.** Task 13 báo cáo/slide/kịch bản demo được hoãn theo yêu cầu người dùng. Xem [checklist yêu cầu và hợp đồng backend/demo/UI](DUC-TASKS.md). Chưa triển khai registry first/last, metadata feedback hoặc UI của các plan sau; không sửa runtime source/template và không gọi AWS.

Baseline code: `main` tại **a2201f5d8261d453d0de3e9873b9072773545848**; nhánh tài liệu `codex/duc-plan-01-baseline`. Đã kiểm tra `git status`, branch, SHA và lịch sử checkout; `AGENTS.md` untracked được giữ nguyên. Chưa refresh remote/GitHub hoặc kiểm tra revision deployed.

| Kiểm tra mới trong Plan 01 | Kết quả / lớp bằng chứng |
|---|---|
| Backend baseline, Python 3.12.14 | **216 test: 215 PASS, 1 SKIPPED**, 0 failure/error, 48.359 giây; local unit/mock/Moto, CRG_AWS_E2E=0 và EC2 metadata disabled |
| Phạm vi suite | 57 rule, 25 API, 50 workflow, 9 collector budget, 28 Task 8, 6 template, 17 harness offline, 18 notification, 3 E2E-evidence mock, 2 read-only; 1 AWS E2E bị skip |
| Git integration | PR #4 đã trong lịch sử tại f1e6cd1; PR #3 tại a2201f5. D1 chờ tích hợp vào main đã gỡ ở lớp Git cục bộ |
| Report 2 / contract | Đối chiếu tr. 10, 15, 18, 20–21 với source/API/demo/UI và template; các trường mới được đánh dấu CHƯA TRIỂN KHAI |
| Tài liệu / cú pháp / template | **PASS:** checker mặc định 12 file/0 link hỏng; checker explicit đủ 6 file thay đổi (gồm DUC-TASKS.md mới)/0 link hỏng; node --check web/app.js; cfn-lint cả ba template; git diff --check và kiểm tra UTF-8/whitespace/conflict marker cho cả file mới |
| Review tài liệu độc lập | **APPROVE:** đối chiếu contract với source/template, kiểm tra tách Git/AWS và scope Task 7–9; checker riêng file mới 1 file/0 link hỏng |
| UI/browser, SAM build, AWS E2E/Task 8 cloud | **CHƯA CHẠY trong Plan 01**; không đổi UI/runtime/hạ tầng. Browser cũ hoặc AWS EBS OBSERVING trong Report 2 là evidence lịch sử, không phải kiểm tra mới |

Transcript và summary JSON cục bộ ở `.preflight/duc-plan-01/backend.txt` và `backend.json` (Git ignore), có baseline SHA, Python, thời gian UTC, số test theo module và skip reason. Harness AWS bị skip chủ động; kết quả này không phải GitHub CI hoặc cloud acceptance. Runtime source/template giữ nguyên baseline trong lượt tài liệu này.

Trạng thái đầu vào và evidence cloud của đợt Task 7–9:

| ID | Trạng thái tại 29/10/2026 | Điều kiện đóng |
|---|---|---|
| B1 — Phiên AWS/account/executor | **CHƯA XÁC MINH LIVE**; không dùng kết quả thiếu credentials ngày 26/10 để khẳng định phiên hiện tại | Xác nhận STS identity, account/region và quyền executor trong phạm vi được duyệt |
| B2 — Stack/fixture | **CHƯA XÁC MINH LIVE**; chưa xác nhận stack thử, hai user/read role và ZIP đang chạy | Manifest/fixture đủ, change set/IAM được review, SES tắt, hash/handler của artifact cuối khớp |
| B3 — AWS của bản cuối | **CHƯA CHẠY** cho đợt Task 7–9 | Evidence rule/web thật Plan 11, scheduler/recovery Plan 12 và final-smoke trên artifact chuẩn |
| B4 — Coverage manual cloud | **CHƯA CÓ EVIDENCE MỚI**; giữ các ca chưa tự động hóa trong runbook Task 8 | Ghi oracle/kết quả từng ca trong phạm vi nghiệm thu hoặc lý do chưa chạy; không đổi local mock thành PASS cloud |
| D1 — Tích hợp Task 7/8 vào main | **ĐÃ GỠ VỀ GIT** tại baseline nêu trên | Không cần merge/retarget lại PR đã có trong lịch sử; deployment và AWS acceptance vẫn cần bằng chứng riêng |

Các mục có ngày cũ bên dưới giữ bằng chứng lịch sử; mô tả branch/PR/credentials tại thời điểm đó không thay thế baseline và trạng thái hiện tại ở mục này.

## Task 8 — bàn giao local và harness, 27/10/2026

**Snapshot bàn giao ngày 27/10: hoàn tất phạm vi local + harness; AWS acceptance chưa chạy.** Nhánh lúc bàn giao `codex/task-8-scheduling-recovery`, nền `767f32ad3da911f803f221ff271631a51ed66809`. Revision bàn giao là head của PR Task 8; SHA nền không đại diện cho thay đổi Task 8. Khi mở, PR đặt base `duc` để diff chỉ gồm Task 8. **Kiểm tra lại ngày 29/10: PR #4 và #3 đã có trong lịch sử main; D1 đã gỡ về Git.** `AGENTS.md` có sẵn và vẫn giữ untracked. Xem [hợp đồng/ma trận/runbook Task 8](TASK8.md) và [quy trình harness AWS](TASK8-AWS.md).

Thay đổi gồm admission/worker lease có điều kiện theo tenant/connection, RESULT + HISTORY nguyên tử, lịch theo tenant được cô lập lỗi và phân trang, giới hạn thời gian trước STS/từng trang collector, SQS recovery và đối soát deadline. SAM thêm recovery/reconcile, DLQ vận hành, đường lỗi delivery/async, IAM theo bảng/queue và alarm. `deploy.py --artifact` dùng nguyên byte ZIP đã review; validation tùy chọn này và mọi thử nghiệm deploy trong unittest đều dùng SDK mock, không upload AWS.

### Điểm chặn Task 8 và điều kiện gỡ

**Không còn blocker code/local đã xác minh trong phạm vi bàn giao Task 8 ngày 27/10. Task 8 vẫn chưa được nghiệm thu AWS.** B1–B4 dưới đây ghi bằng chứng snapshot lúc bàn giao; xem trạng thái hiện tại trong mục Plan 01. D1 đã được giải quyết về tích hợp Git, không còn là bước chờ merge.

| ID / điểm chặn | Trạng thái và bằng chứng | Phần bị chặn | Điều kiện gỡ |
|---|---|---|---|
| B1 — Phiên AWS và account lab | **THIẾU ĐẦU VÀO.** Kiểm tra môi trường ngày 26/10/2026 không có named profile/credentials khả dụng; người dùng chọn bàn giao local + harness trước. Chưa xác minh lại phiên AWS live trong lượt bổ sung tài liệu này | Thực thi kiểm thử AWS | Chuẩn bị phiên AWS hợp lệ tại máy, xác nhận danh tính bằng STS, account lab, region `ap-southeast-1` và quyền executor trong phạm vi stack thử |
| B2 — Stack và fixture nghiệm thu | **CHƯA XÁC MINH.** Chưa có bằng chứng live cho stack Task 8, hai Cognito subject và hai read role riêng, IAM/SES hoặc ZIP đang triển khai. Không kết luận các tài nguyên này chưa tồn tại | Điều kiện đầu vào của AWS E2E | Xác minh stack `cloud-resource-guardian-task8-test`, hai user/role riêng và manifest; review change set/IAM theo release gate hiện có; SES tắt; cả năm Lambda dùng đúng handler và `CodeSha256` của ZIP đã pin |
| B3 — Luồng AWS và artifact cuối | **CHƯA CHẠY.** Các kết quả PASS hiện là local/mock/Moto/browser fixture/offline, chưa có evidence AWS Task 8 | Kết luận Task 8 hoàn tất AWS và phát hành revision này | Lưu evidence đạt cho tick EventBridge thật, manual/race/duplicate/reconnect, retry transient/exhausted, hard timeout, OnFailure → SQS → recovery, consumer redrive/DLQ và orphan reconciliation; bỏ wrapper, xác minh hash/config rồi chạy `final-smoke` trên artifact cuối |
| B4 — Coverage cloud chưa tự động hóa đầy đủ | **CHƯA CÓ EVIDENCE** cho các ca nêu trong [harness AWS](TASK8-AWS.md): STS/service denial thật, dừng tiến trình đúng điểm dispatch, DynamoDB throttling/conflict thật, reconnect chắc chắn khi worker đang đọc, và destination alarm thực sự phát sinh. Local regression không thay thế evidence này | Việc công nhận các tiêu chí cloud tương ứng đã được kiểm chứng; không tự biến tất cả thành gate bắt buộc mới | Khi nghiệm thu phần tương ứng, bổ sung kịch bản manual được review hoặc mở rộng harness; ghi kết quả/evidence hoặc lý do ngoài phạm vi rõ ràng, không đổi ca chưa chạy thành PASS |
| D1 — Phụ thuộc PR Task 7 #3 | **ĐÃ GỠ VỀ GIT, kiểm tra 29/10.** PR #4 tại f1e6cd1 và PR #3 tại a2201f5 đã trong lịch sử main cục bộ | Không còn chặn tích hợp ở baseline này; AWS vẫn chưa nghiệm thu | Giữ bằng chứng Git và revalidate bản tích hợp; không yêu cầu retarget/merge lại PR lịch sử |

**Giới hạn khác tại thời điểm bàn giao 27/10:** chưa có check runs/commit statuses GitHub cho commit Task 8; không ghi là CI PASS hay CI FAIL. Plan 01 chưa kiểm tra GitHub lại. Alarm chưa có SNS/người nhận tự động là giới hạn thông báo vận hành đã công bố; chỉ chặn khi phạm vi nghiệm thu bao gồm gửi thông báo tự động. Không có cloud mutation trong lượt bổ sung blocker này.

### Bằng chứng local đã đạt

| Kiểm tra trên source bàn giao | Kết quả và giới hạn |
|---|---|
| Toàn bộ backend, Python 3.12.14 | **194 test: 193 PASS, 1 AWS E2E SKIPPED**, 0 failure/error, 35.016 giây. Gồm 28 regression Task 8, 9 collector budget, 6 template invariant và 17 harness/deploy offline mới; giữ các suite rule/API/workflow hiện có |
| SDK trong artifact cuối | **111/111 PASS**, 67.735 giây: API/workflow/Task 8/collector budget dùng boto3 1.43.111 và botocore 1.43.118 giải nén từ ZIP cuối; source được đối chiếu byte với ZIP. AWS vẫn mock/Moto, không phải chạy Lambda thật |
| Bốn regression trước sửa | 2 FAIL + 2 ERROR trên nền: history transaction chưa có, terminal race vẫn đọc AWS, STS denial thiếu metadata/history, profile lỗi chặn scheduler. Sau sửa đều PASS |
| UI smoke | PASS bằng Chrome headless trên máy: polling, feedback, cấu hình, history, mobile, phiên hết hạn |
| UI fixture acceptance | PASS: trạng thái queued/running/failed/timed-out/partial/success-zero, lỗi/cooldown/phục hồi, 320/390/768/1440 px; đã xem ảnh timeout desktop và overview mobile |
| Template | `cfn-lint template.yaml target-role.yaml --regions ap-southeast-1` PASS; 6 invariant PASS |
| SAM transform offline | Reviewer dùng aws-sam-translator 1.115.0 trong môi trường công cụ riêng: PASS, 50 resource, không cycle trong đồ thị dependency. Thay CodeUri trong RAM bằng URI giả, không gọi AWS |
| Review độc lập app/SAM | APPROVE sau khi đóng lỗi claim connection race, lease release khi GetItem lỗi, metadata/history, IAM DeleteItem và metric EventBridge |
| Review độc lập harness/deploy | Không còn phát hiện actionable local/static; 17 offline tests PASS. Hard timeout phải có log runtime khớp request ID; exhausted phải có retry/condition/error code đúng; không lấy hết tuổi sự kiện làm bằng chứng hard timeout |
| JavaScript/AST/docs/whitespace | `node --check web/app.js`, AST Python liên quan, checker Markdown và `git diff --check` PASS |
| AWS | **CHƯA CHẠY**, không có cloud mutation. Không có profile/credentials khả dụng; người dùng chọn bàn giao local + harness trước |

Lệnh backend cuối đã chạy với `CRG_AWS_E2E=0` trong tiến trình kiểm thử; log có AccessDenied/Throttling là dữ liệu mock có chủ đích. Bằng chứng cục bộ bị gitignore: `.preflight/task8/backend-final.txt`, `backend-final.json`, `artifact-sdk-tests.txt`, `artifact-sdk-tests.json`, `local-validation.json`; ảnh dưới `.preflight/task8/ui-smoke/` và `ui-fixture/`. Playwright bundled Chromium chưa được cài nên lần launch đầu không chạy được; chạy lại thành công bằng `CHROMIUM_EXECUTABLE=C:\Program Files\Google\Chrome\Application\chrome.exe`.

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os,unittest; os.environ['CRG_AWS_E2E']='0'; r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests')); raise SystemExit(not r.wasSuccessful())"
$env:CHROMIUM_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:UI_QA_DIR = '.preflight/task8/ui-smoke'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_smoke.py
$env:UI_QA_DIR = '.preflight/task8/ui-fixture'
.\.venv\Scripts\python.exe -X utf8 -B tests/ui_redesign.py
.\.venv\Scripts\cfn-lint.exe template.yaml target-role.yaml --regions ap-southeast-1
node --check web/app.js
node .agents/skills/resourceguardian-delivering-task/scripts/check-doc-links.mjs
git diff --check
```

Artifact đã đóng gói cho Python 3.12/Linux x86_64 từ `src/requirements.txt`, dùng Python runtime có pip vì `.venv` hiện không có pip. Gói cuối `.preflight/task8-artifacts/task8-final.zip`, **16.774.834 byte**, không chứa fault wrapper. Gói gây lỗi riêng chỉ thêm `task8_faults.py`. `artifacts.json` lưu snapshot tại thời điểm đóng gói trước commit: từng source hash, Git SHA nền, cờ `source_dirty=true`, tree hash và cả hai ZIP hash. Khi bàn giao commit, đối chiếu source tree/ZIP dưới đây với head PR:

```text
source_tree_sha256: 3d17a178a82f7811967c1443167ad28039c19c5723e4d20d3e39b9b7f665c1e6
final_zip_sha256:   e059c4785ff216819ae4125780b6bcd19846e7b0278f017df0a6dd91cdcf1c50
fault_zip_sha256:   e646b4d11767428462ecec829f3a9a03628d783e9d092a9036f519fd3db5073d
```

Khi có môi trường cloud: commit source đã review trước nghiệm thu, xác nhận account/stack test/region và hai user/role riêng, deploy đúng ZIP hash qua change set đã review, chạy đủ scenario và smoke lại artifact cuối sau khi loại wrapper. Harness từ chối AWS acceptance nếu source/template chưa commit. SHA commit có thể đổi sau bàn giao nhưng source tree/ZIP phải vẫn khớp manifest. Bộ kiểm tra local và artifact tồn tại không xác nhận IAM enforcement, tick EventBridge, async retry, hard timeout, SQS/redrive hoặc isolation trên AWS thật.

## Task 7 — nghiệm thu chín loại hiện có, 26/10/2026

**Hoàn tất ở lớp code và kiểm thử local trong phạm vi người dùng đã chốt:** EC2, EBS volume, EIP, EBS snapshot, S3 multipart, RDS instance, NAT Gateway, ALB và NLB. Kiểm tra trên nhánh `duc`, sau commit nền `d9a3b26`, bằng Python 3.12.14; commit bàn giao và head được xác nhận trong PR. Kết quả này thay thế snapshot local cũ bên dưới khi đánh giá hành vi hiện tại.

Theo PDF trang 17, Task 7 là luật đánh giá và bằng chứng, nhận dữ liệu từ Task 6. Báo cáo định hướng sáu nhóm dịch vụ và đối chiếu chi phí; chín loại đang có thuộc bốn nhóm. **THIẾU ĐẦU VÀO / chưa triển khai:** collector cho nhóm AI/analytics, giám sát/tích hợp, các dịch vụ khác chưa có trong bốn nhóm và billing/cost. Cần Task 6 bàn giao dữ liệu/quan hệ/quyền đọc cùng bộ rule được chốt trước khi nghiệm thu các phần này. Dashboard hiển thị đầy đủ evidence thuộc Task 9, ngoài phạm vi backend đã chốt cho lượt này. Xem [RULES.md](RULES.md) để biết hợp đồng chi tiết.

| Tiêu chí Task 7 | Kết quả và bằng chứng hiện tại | Lớp xác minh |
|---|---|---|
| Evaluator và finding cho đủ chín loại | Mỗi finding có rule ID, lý do, khuyến nghị, ngưỡng, account/region/mốc scan; metric có đơn vị, statistic, cửa sổ và counts. `test_all_nine_types_have_context_thresholds_and_persisted_explanations` đối chiếu collector → worker → API/scan status/history | Unit + mock/Moto PASS |
| Metric lỗi không dẫn đến ít hoạt động | Âm, boolean, sai kiểu, None, NaN/infinity, số nguyên cực lớn và aggregate overflow trả insufficient với diagnostics JSON hợp lệ; không lưu mẫu lỗi thô. Mẫu zero thật vẫn hợp lệ | `test_rules.py`, `test_workflows.py` PASS |
| Độ phủ và ngưỡng đúng | Mỗi metric đủ 20/24 hoặc 135/168 mẫu; kiểm tra trước/bằng/sau ngưỡng, p95 nearest-rank, mean và NAT/EC2 trung bình riêng hai chiều. Tài nguyên mới/thiếu ngày tạo trả insufficient, không gọi CloudWatch | Unit + mock/Moto PASS |
| Chất lượng timestamp và pagination | Giữ zero, lọc `[start,end)`, khử trùng timestamp; từ chối duplicate xung đột, sai status/ID/shape, token lặp và timestamp lệch lưới giờ. 24 điểm zero trong 24 phút không được coi là 24 giờ; test riêng năm namespace, phần dịch vụ hợp lệ vẫn được giữ | Mock/Moto PASS |
| EBS/EIP và snapshot/S3 | Tách observation theo type/connection/region, migrate key cũ chỉ khi native ID nhận diện được loại; kiểm tra reset khi dùng lại, gap >48 giờ, expiry/clock rollback. Snapshot bỏ AMI tham chiếu, AMI disabled và AWS Backup; lỗi/truncation AMI không tạo review. Multipart đúng 7 ngày chưa stale | Unit + mock/Moto PASS |
| Ngoại lệ và phục hồi finding | Tag suppression cho sáu loại có tag đầu vào; phản hồi nội bộ dùng ID ổn định cho mọi finding. Private candidates giữ finding bị feedback ẩn qua scan để clear/expiry có thể hiện lại; acknowledged/kept/ignore độc lập; lịch sử bất biến; API không lộ candidates | API + mock/Moto PASS |
| Lỗi, giới hạn và lưu trữ | Lỗi theo dịch vụ tạo PARTIAL, giữ phần kết quả có bằng chứng. Cap 100 tài nguyên/loại, 50 hiển thị, 100 candidates và result JSON 300 KiB; truncation ghi rõ PARTIAL/CANDIDATE_LIMIT và giới hạn số đếm | Mock/Moto PASS |
| Isolation và quyền đọc | Auth/tenant/connection/region, feedback ownership, observation và legacy migration được regression; hai bản target role được test invariant chỉ đọc | API + mock/Moto + static PASS |

**Kết quả chạy trên source cuối:** 134 test, **133 PASS, 1 SKIPPED**, 0 failure/error; gồm 57 rule, 25 API, 49 workflow, 2 read-only contract và 1 AWS E2E bị tắt. Số lượng là phương thức test, chưa tính các subtest. Log AccessDenied/Throttling trong suite là dữ liệu mock của ca lỗi/retry có chủ đích.

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os, unittest; os.environ['CRG_AWS_E2E'] = '0'; suite = unittest.defaultTestLoader.discover('tests'); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

AST parse của sáu file Python sửa đổi PASS; `git diff --check` PASS. Checker tài liệu offline kiểm tra 13 file, không có link hỏng. Review độc lập đọc diff ba module, kiểm tra oracle regression và chạy riêng 82 test rule/API PASS; verdict APPROVE, không còn phát hiện actionable trong phạm vi được giao.

**CHƯA CHẠY:** AWS E2E với CloudWatch/inventory thật, Cognito/STS và deployment. Không có cloud mutation trong lượt này. Không chạy lại UI/browser hoặc SAM build vì không sửa UI/hạ tầng; kết quả UI cũ ở dưới là bằng chứng lịch sử. Local/mock/Moto không chứng minh hoàn tất release hoặc toàn bộ sáu nhóm của PDF.

### Điểm chặn và điều kiện gỡ

Không còn lỗi chặn đã biết đối với commit/push và review code trong phạm vi chín loại đã chốt. Các mục dưới đây chặn nghiệm thu AWS hoặc toàn bộ phạm vi PDF; không chuyển chúng thành PASS từ kết quả local.

| Mục | Trạng thái / phạm vi bị chặn | Điều kiện gỡ |
|---|---|---|
| Revision Task 7 trên AWS | CHƯA XÁC MINH — release AWS của bản thay đổi này | Reviewer và executor khác nhau xác nhận commit, account/region/stack, template/IAM diff, UserPool không bị replace, Cognito admin-only và <=5 user, allowlist chỉ đọc; executor triển khai đúng revision đã review theo manual release gate bên dưới |
| Finding thật và luồng tích hợp | CHƯA CHẠY — nghiệm thu rule trên AWS | Chạy harness sau deploy với hai tenant và manifest hợp lệ; có finding thật EC2/EBS/EIP/snapshot/S3 multipart, đủ thời gian quan sát/metric. RDS/NAT/ALB/NLB có evidence hoặc lý do skip chính xác `RESOURCE_NOT_AVAILABLE`/`COST_NOT_APPROVED`. Xác minh sai ExternalId, isolation, lỗi quyền PARTIAL và metric thiếu không thành REVIEW; các ca lỗi không do harness tự kiểm tra cần bằng chứng manual riêng. Lưu bằng chứng đã loại secrets |
| Dịch vụ và chi phí còn thiếu trong PDF | THIẾU ĐẦU VÀO — nghiệm thu toàn bộ sáu nhóm/cost | Task 6 bổ sung collector, schema, quan hệ, quyền đọc và dữ liệu cost cho phần chưa hỗ trợ; sau đó chốt rule/ngưỡng, triển khai và kiểm thử tương ứng |

Task 9 (dashboard hiển thị/thao tác đầy đủ) nằm ngoài phạm vi backend Task 7 đã chốt, cần nghiệm thu riêng. Tag chưa được đọc cho ALB/NLB/S3 multipart và việc chỉ phục hồi ứng viên còn giữ sau truncation là giới hạn đã công bố trong [RULES.md](RULES.md), không phải tính năng đã xác minh trên AWS.

[DEPLOYMENT.md](DEPLOYMENT.md) và [HANDOFF.md](HANDOFF.md) có lịch sử triển khai/quét AWS trước đây; inventory rỗng hoặc bằng chứng của revision cũ không xác minh rule mới hay finding thật của lượt Task 7 này. Không lấy các vấn đề trong preflight cũ (ví dụ reserved concurrency đã được bỏ) làm blocker code hiện tại.

## Gia cố metric RDS/NAT/ALB/NLB — 26/10/2026

Phạm vi: kiểm tra tính hợp lệ của mẫu, độ phủ, ngưỡng và công thức NAT trong helper thuần, cùng đường collector → worker → DynamoDB mô phỏng. Không đổi API, UI, IAM hoặc triển khai AWS.

- **Trước sửa:** tái hiện RDS CPU âm và NLB flow âm bị `REVIEW`; ALB nhận NaN trả `OK` với evidence NaN; mẫu `None`/chuỗi/số nguyên cực lớn có thể gây lỗi tính toán. NAT có 24 mẫu source và 20 mẫu destination, mỗi mẫu 0.48 MiB, bị tính thành 1.056 thay vì 0.96 MiB/giờ.
- **Regression mới:** 13 phương thức test rule và 2 phương thức test workflow, dùng subtest cho từng metric, dữ liệu âm/boolean/None/chuỗi/dict/NaN/±infinity/số nguyên gây overflow; mẫu lỗi vẫn bị từ chối khi đã có đủ mẫu hợp lệ. Kiểm tra zero thật, từng chuỗi ở mốc 19/20 mẫu trong 24 giờ và 134/135 mẫu trong 168 giờ, ngưỡng trước/bằng/sau, p95 RDS, mean ALB/NLB và overflow tổng.
- **NAT:** trung bình từng chiều theo số mẫu thực đo, cộng rồi đổi MiB/giờ. Test cả hoán đổi số mẫu hai chiều và trường hợp ở dưới/bằng/trên ngưỡng.
- **Workflow mock/Moto:** 14 lượt scan cho dữ liệu lỗi ở bốn loại, cùng 2 lượt scan NAT 24/20 và 20/24 mẫu. Finding lỗi metric được lưu là `INSUFFICIENT_DATA`; kết quả không có NaN/infinity khi serialize bằng `json.dumps(..., allow_nan=False)`.
- **Suite backend local:** chạy 112 test, **111 PASS, 1 SKIPPED** (AWS E2E bị tắt có chủ đích), 0 failure/error. Số test phương thức không bao gồm số lượng subtest bên trong.
- **Review độc lập:** đối chiếu diff/caller và kiểm tra thêm bằng snippet rule thuần; không phát hiện lỗi chặn trong phạm vi này.

Lệnh đã chạy từ root; `CRG_AWS_E2E` chỉ được đặt bằng `0` trong tiến trình test này:

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -c "import os, unittest; os.environ['CRG_AWS_E2E'] = '0'; suite = unittest.defaultTestLoader.discover('tests'); result = unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

Đây là bằng chứng local/mock/Moto, chưa xác minh CloudWatch metrics hoặc scan trên AWS thật. Các trạng thái AWS E2E bên dưới vẫn chưa được nâng thành PASS. Không chạy lại UI/SAM vì không thay đổi các lớp đó.

## Mục 7 & Nhánh main — luật đánh giá, collectors và bằng chứng, 18/10/2026

Kiểm tra tích hợp giữa nhánh `duc` (luật đánh giá, lịch quét, xử lý lỗi, dashboard) và nhánh `origin/main` (API, collectors chỉ đọc AWS, feedback lifecycle, IAM và kiểm thử mở rộng). Toàn bộ dữ liệu AWS đọc và SES được mock; DynamoDB được mô phỏng bằng Moto. Không gọi AWS thật, không triển khai hoặc thay đổi tài nguyên cloud.

Các kiểm tra tại môi trường phát triển:
- **Toàn bộ backend:** 95/95 unittest PASS (36 rule tests, 21 API tests, 33 workflow tests, 2 contract tests, 1 test AWS E2E skipped).
- **Rule & Collectors:** Có collector cho 9 loại tài nguyên (EC2, EBS, EIP, Snapshot, RDS, NAT, ALB, NLB, S3 multipart). Bản ghi tổng hợp cũ này không chứng minh mọi helper mở rộng đã xử lý đầy đủ mẫu không hợp lệ hoặc NAT đã tính riêng từng chiều; các regression và sửa lỗi tương ứng được xác minh tại mục 26/10/2026 ở trên. Các kiểm tra khác gồm snapshot/AMI IncludeDisabled, rule_id và recommendation.
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

**Bảng và các phát hiện dưới đây là snapshot audit ngày 27/10 tại debea62.** Baseline 29/10 đã có merge PR #3/#4/#5 trong lịch sử; các ghi chú PR còn mở hoặc cần tích hợp lại dưới đây không phải bước chờ hiện tại. Task 8 trên baseline mới ghi RESULT + HISTORY nguyên tử; đoạn chờ history của harness phản ánh khả năng tương thích với baseline cũ. Xem mục Plan 01 và [checklist Task 7–9](DUC-TASKS.md) cho trạng thái hiện hành.

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
