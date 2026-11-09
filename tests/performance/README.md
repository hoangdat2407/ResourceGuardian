# Kế hoạch & Hướng dẫn Kiểm thử Hiệu năng (Performance Test)
## CLOUD RESOURCE GUARDIAN

Tài liệu này hướng dẫn cách thực thi và giải thích các chỉ số kiểm thử phi chức năng (Non-Functional Requirements - Performance) cho hệ thống Cloud Resource Guardian.

---

## 1. Nguyên tắc An toàn & Giới hạn Tải (Safety Bounds)

- **Chỉ đo tải trên các điểm cuối đọc (Read-only endpoints):**
  - Static Assets trên CloudFront CDN: `/`, `/styles.css`, `/app.js`, `/config.json`.
  - Read-Only API Endpoints: `/me`, `/findings`, `/history`.
- **Tuyệt đối không đo tải vào các điểm cuối sau:**
  - `Cognito SignUp` / `ConfirmSignUp` (tránh kích hoạt rate limit của SES/Cognito OTP).
  - `Cognito ForgotPassword` (tránh spam gửi email OTP).
  - `POST /scans` (tránh kích hoạt hàng loạt Worker Lambda quét song song tốn tài nguyên AWS).
  - `PUT /settings`, `PUT /connection`, `PUT /feedback` (tránh ghi đè dữ liệu trạng thái).
- **Giới hạn tốc độ yêu cầu (Rate Limit Guard):**
  - Tốc độ trung bình: $\le 2$ requests/giây trên toàn bộ bài kiểm tra production.
  - Ngưỡng tự động hủy (Abort Thresholds): Hủy bài test nếu tỷ lệ lỗi HTTP 5xx hoặc connection error $> 1\%$, hoặc latency P95 $> 2000$ ms.

---

## 2. Kịch bản tải 3 giai đoạn (3-Stage Load Profile)

| Giai đoạn | Số Virtual Users (VU) | Thời lượng | Mục đích đo lường |
| :--- | :---: | :---: | :--- |
| **Stage 1: Baseline** | 1 VU | 30 giây | Đo độ trễ cơ sở trong điều kiện lý tưởng (cold start vs warm cache). |
| **Stage 2: Light Load** | 2 VUs | 60 giây | Mô phỏng lưu lượng người dùng thông thường truy cập đồng thời. |
| **Stage 3: Moderate Load** | 5 VUs | 60 giây | Kiểm tra khả năng chịu tải nhẹ trên các nút biên CloudFront và API Gateway. |
| **Ramp-down** | 0 VU | 15 giây | Hạ tải an toàn. |

---

## 3. Hướng dẫn chạy thử nghiệm

### Kiểm thử Phân phối Tĩnh qua CloudFront CDN
```bash
./.venv/bin/k6 run tests/performance/k6_readonly.js
```

### Kiểm thử Điểm cuối API Đọc (Có xác thực)
```bash
# Đối với môi trường staging/local demo:
API_URL=http://127.0.0.1:8080 AUTH_TOKEN=demo-local-only ./.venv/bin/k6 run tests/performance/k6_api_authenticated.js

# Hoặc kiểm tra cơ chế chặn truy cập trái phép 401 trên API Gateway production:
API_URL=https://l2qn7i2en9.execute-api.ap-southeast-1.amazonaws.com ./.venv/bin/k6 run tests/performance/k6_api_authenticated.js
```

---

## 4. Các chỉ số đo lường thu thập (Metrics Collected)

- **Total Requests & RPS:** Tổng số yêu cầu và thông lượng trung bình.
- **Latency Percentiles:**
  - `avg`: Độ trễ trung bình.
  - `p(50)`: Median latency (50% requests nhanh hơn mức này).
  - `p(90)` / `p(95)`: Độ trễ đuôi (Tail latency).
  - `p(99)`: Mức trễ xấu nhất cho 1% người dùng.
- **Error Rates:**
  - `http_req_failed`: Tỷ lệ lỗi HTTP (yêu cầu $< 0.01$ tức $< 1\%$).
- **CloudFront Cache Hit Ratio:** Tỷ lệ phản hồi trúng bộ nhớ đệm tại máy chủ biên (`X-Cache: Hit from cloudfront`).
