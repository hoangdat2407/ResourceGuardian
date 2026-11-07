# Cloud Resource Guardian — Real AWS Resource Detection Experiment

Thư mục này chứa toàn bộ Infrastructure as Code (CloudFormation), script quản lý vòng đời tài nguyên thử nghiệm (plan, apply, destroy, status) và manifest đối chiếu phục vụ cho:
1. Quay video demo tốt nghiệp (7–9 phút).
2. Dữ liệu thực nghiệm Chương 3 của báo cáo/luận văn.
3. Đánh giá tính chính xác: True Positive (TP), False Positive (FP), True Negative (TN), False Negative (FN), Insufficient Data và Partial Scan.

---

## 1. Nguyên tắc cốt lõi

- **Zero-Production Impact:** Tuyệt đối không can thiệp, sửa đổi hoặc xóa tài nguyên production (Stack `cloud-resource-guardian`, DynamoDB `Data`, Cognito User Pool, IAM roles production).
- **Chi phí tối thiểu:** Tổng chi phí cho toàn bộ 8 kịch bản trong 24 giờ là **~$0.133 USD** (~3,500 VND), trong 48 giờ là **~$0.256 USD** (~6,700 VND).
- **Nhận diện và phân loại rõ ràng qua Tags:**
  - `Project`: `CloudResourceGuardian`
  - `Environment`: `Demo`
  - `Purpose`: `UnusedResourceDetection`
  - `TestCase`: `TC01` ... `TC08`
- **Quản lý qua Manifest:** Mọi tài nguyên tạo ra đều được ghi lại trong `manifest.json` và xóa sạch qua CloudFormation khi kết thúc thí nghiệm.

---

## 2. Danh mục 8 Test Cases

| Test ID | Quy tắc kiểm tra (Rule ID) | Dịch vụ AWS | Tài nguyên thử nghiệm | Kỳ vọng ban đầu | Kỳ vọng sau ngưỡng | Chi phí 24h |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC01** | `EBS_UNATTACHED` | Amazon EBS | 1 Volume gp3 dung lượng 1 GiB (`available`, chưa gắn EC2) | `OBSERVING` (chưa đủ 24h) | `REVIEW` (sau 24h quan sát liên tục) | $0.0029 |
| **TC02** | `EIP_UNASSOCIATED` | Amazon VPC | 1 Elastic IP (allocate nhưng chưa associate ENI/EC2) | `OBSERVING` (chưa đủ 24h) | `REVIEW` (sau 24h quan sát liên tục) | $0.1200 |
| **TC03** | `SECURITY_GROUP_UNUSED` | Amazon EC2 | 1 Security Group không gắn ENI, không cross-reference | `OBSERVING` (chưa đủ 7 ngày) | `REVIEW` (sau 7 ngày quan sát) | $0.0000 |
| **TC04** | `ECR_NO_LIFECYCLE` | Amazon ECR | 1 Private Repository không cấu hình Lifecycle Policy | `REVIEW` ngay lập tức | `REVIEW` (kèm khuyến nghị thiết lập policy) | $0.0000 |
| **TC05** | `LAMBDA_UNUSED` | AWS Lambda | 1 Function Python 3.12 (128 MB, 0 invocation) | `REVIEW` (0 invocations & no triggers) | `REVIEW` (hiển thị thời gian quan sát) | $0.0000 |
| **TC06** | *False Positive Control* | IAM / Tags | 1 Security Group gắn tag `guardian:keep = true` + 1 Default SG | **Bị triệt tiêu (Suppressed)**: Không phát sinh finding | Không phát sinh finding (Chứng minh TN) | $0.0000 |
| **TC07** | *Insufficient Data* | Amazon EC2 | Tài nguyên mới tạo hoặc thiếu dữ liệu metrics | `INSUFFICIENT_DATA` (không gán thiếu = 0) | `OBSERVING` / `INSUFFICIENT_DATA` | $0.0100 |
| **TC08** | *Partial Scan Handling* | API / Scan Engine | Tình huống giới hạn quyền hoặc lỗi từng phần | `PARTIAL` (hiển thị badge cam, giữ nguyên findings khác) | Không mất findings thu thập được | $0.0000 |

---

## 3. Hướng dẫn sử dụng

### Bước 1: Xem trước kế hoạch và chi phí (Dry-run / Plan)
```bash
python tests/demo_aws/manage_experiment.py plan --profile datht --region ap-southeast-1
```

### Bước 2: Triển khai tài nguyên (Chỉ chạy sau khi được phê duyệt)
```bash
python tests/demo_aws/manage_experiment.py apply --profile datht --region ap-southeast-1
```
*Lệnh trên sẽ tạo stack `crg-demo-experiment-stack` và tự động sinh tệp `tests/demo_aws/manifest.json`.*

### Bước 3: Kiểm tra trạng thái manifest hiện tại
```bash
python tests/demo_aws/manage_experiment.py status
```

### Bước 4: Chạy Quét trên Cloud Resource Guardian
1. Mở https://d3qn9wabid8ws0.cloudfront.net/
2. Chọn kết nối AWS account `376129867108` tại region `ap-southeast-1`.
3. Bấm **Quét ngay** (`Scan Now`).
4. Theo dõi kết quả và ghi lại `ScanId`, `finding_id`, `evidence`.

### Bước 5: Dọn dẹp hoàn toàn tài nguyên (Teardown)
```bash
python tests/demo_aws/manage_experiment.py destroy --profile datht --region ap-southeast-1
```
*Lệnh trên sẽ xóa sạch stack CloudFormation và tệp manifest, đảm bảo không phát sinh chi phí duy trì.*
