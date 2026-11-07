'use strict';
const $=id=>document.getElementById(id);
let cfg,profile,results=[],historyRows=[],token=sessionStorage.getItem('crg-token'),pollTimer,pollCount=0,loadingResults=true,resultsError=false,scanPending=false,scopeGeneration=0,detailFocus=null;
let findingsRevision=0;
let historyCursor=null,historyLoading=false,historyError='',historyRequest=0,historyDetailRequest=0,historySelection=null,historyDetailRows=[],historyDetailLoading=false,historyDetailError='';
const feedbackState=new Map(),feedbackDays=new Map();
let feedbackRows=[],feedbackCursor=null,feedbackLoaded=false,feedbackLoading=false,feedbackError='',feedbackRequest=0,feedbackRevision=0;
const managedDays=new Map();
const pages={
 overview:['Tổng quan',''],
 findings:['Tài nguyên cần kiểm tra',''],
 history:['Lịch sử quét',''],
 connection:['Kết nối AWS',''],
 settings:['Cấu hình','']
};
const guestViewTitles={
 login:'Đăng nhập',
 register:'Đăng ký',
 verify:'Xác minh email',
 forgot:'Quên mật khẩu',
 reset:'Đặt lại mật khẩu'
};
const regions=['ap-southeast-1','ap-southeast-2','ap-northeast-1','us-east-1','us-west-2','eu-west-1'];
const serviceGroups={compute:{label:'Tính toán (EC2)',types:['EC2']},storage:{label:'Lưu trữ & Sao lưu',types:['EBS','SNAPSHOT','S3_MULTIPART']},database:{label:'Cơ sở dữ liệu (RDS)',types:['RDS']},network:{label:'Mạng (EIP, NAT, Load Balancer)',types:['EIP','NAT_GATEWAY','ALB','NLB']},serverless:{label:'Serverless (Lambda)',types:['LAMBDA_FUNCTION']},monitoring:{label:'Giám sát & Logs',types:['LOG_GROUP']},security:{label:'Bảo mật (Security Groups, VPC Endpoints)',types:['SECURITY_GROUP','VPC_ENDPOINT']},backup:{label:'Sao lưu mở rộng (RDS Snapshots, EFS, ECR)',types:['RDS_SNAPSHOT','EFS_FILE_SYSTEM','ECR_REPOSITORY']},nosql:{label:'NoSQL & Cache (DynamoDB, ElastiCache)',types:['DYNAMODB_TABLE','ELASTICACHE_CLUSTER']},containers:{label:'Containers (ASG, ECS)',types:['AUTO_SCALING_GROUP','ECS_CLUSTER','ECS_SERVICE']},integration:{label:'Tích hợp & Hàng đợi (SQS, SNS, EventBridge, Step Functions, API Gateway)',types:['SQS_QUEUE','SNS_TOPIC','EVENTBRIDGE_RULE','STEP_FUNCTION','API_GATEWAY']}};
const resourceGroups=Object.fromEntries(Object.entries(serviceGroups).flatMap(([group,value])=>value.types.map(type=>[type,group])));
const thresholdGroupTitles={compute:'1. Tính toán & Container',storage:'2. Lưu trữ & Sao lưu',database:'3. Cơ sở dữ liệu & Cache',network:'4. Mạng & Phân phối nội dung',analytics:'5. Phân tích dữ liệu & AI',integration:'6. Giám sát & Tích hợp'};
const serviceHierarchy=[
 {group:'compute',title:'1. Tính toán & Container',services:[
  {name:'Amazon EC2',fields:['cpu_percent','network_mib_hour','window_hours','interval_hours']},
  {name:'AWS Lambda',fields:['lambda_unused_days','lambda_max_invocations']},
  {name:'Auto Scaling Groups',fields:['asg_zero_days']},
  {name:'Amazon ECS',fields:['ecs_empty_days']},
  {name:'Amazon EKS',fields:['eks_idle_days']}
 ]},
 {group:'storage',title:'2. Lưu trữ & Sao lưu',services:[
  {name:'Amazon EBS',fields:['orphan_hours','snapshot_days']},
  {name:'RDS Snapshots',fields:['rds_snapshot_days']},
  {name:'Amazon EFS',fields:['efs_no_mount_days']},
  {name:'Amazon ECR',fields:['ecr_image_days']},
  {name:'Amazon FSx',fields:['fsx_idle_days']},
  {name:'AWS Backup',fields:['backup_point_days']}
 ]},
 {group:'database',title:'3. Cơ sở dữ liệu & Cache',services:[
  {name:'Amazon RDS',fields:['rds_cpu_percent','rds_connections']},
  {name:'Amazon DynamoDB',fields:['dynamodb_idle_days']},
  {name:'Amazon ElastiCache',fields:['elasticache_idle_days']},
  {name:'Amazon MemoryDB',fields:['memorydb_idle_days']},
  {name:'Amazon DocumentDB',fields:['documentdb_idle_days']},
  {name:'Amazon Neptune',fields:['neptune_idle_days']}
 ]},
 {group:'network',title:'4. Mạng & Phân phối nội dung',services:[
  {name:'NAT Gateway',fields:['nat_mib_hour']},
  {name:'Load Balancers (ALB / NLB)',fields:['alb_requests_hour','nlb_new_flows_hour']},
  {name:'Security Groups',fields:['sg_unused_days']},
  {name:'VPC Endpoints',fields:['vpc_endpoint_unused_days']},
  {name:'Amazon CloudFront',fields:['cloudfront_requests_day']}
 ]},
 {group:'analytics',title:'5. Phân tích dữ liệu & AI',services:[
  {name:'Amazon SageMaker',fields:['sagemaker_idle_days']},
  {name:'Amazon OpenSearch',fields:['opensearch_idle_days']},
  {name:'Amazon Redshift',fields:['redshift_idle_days']},
  {name:'Amazon MSK (Kafka)',fields:['msk_idle_days']},
  {name:'Amazon Kinesis',fields:['kinesis_idle_days']}
 ]},
 {group:'integration',title:'6. Giám sát & Tích hợp',services:[
  {name:'Amazon CloudWatch Logs',fields:['log_group_retention_days']},
  {name:'Amazon SQS',fields:['sqs_idle_days']},
  {name:'Amazon SNS',fields:['sns_unused_days']},
  {name:'Amazon EventBridge',fields:['eventbridge_unused_days']},
  {name:'AWS Step Functions',fields:['stepfunctions_unused_days']},
  {name:'Amazon API Gateway',fields:['apigateway_unused_days']}
 ]}
];
const friendlyFieldMeta={
 cpu_percent:{label:'CPU thấp hơn',unit:'%',help:'Cảnh báo khi CPU p95 thấp hơn mức này trong toàn bộ cửa sổ metrics.'},
 network_mib_hour:{label:'Lưu lượng mạng thấp hơn',unit:'MiB/giờ',help:'Cảnh báo khi tổng lưu lượng mạng vào/ra trung bình thấp hơn mức này.'},
 window_hours:{label:'Thời gian quan sát',unit:'giờ',help:'Khoảng thời gian đo lường CloudWatch mẫu (24–168 giờ, mặc định 24).'},
 interval_hours:{label:'Khoảng cách giữa các lần quét',unit:'giờ',help:'Thời gian giãn cách tối thiểu giữa các lần quét định kỳ (1–24 giờ).'},
 lambda_unused_days:{label:'Không hoạt động trong',unit:'ngày',help:'Kiểm tra hàm Lambda không có lệnh gọi trong số ngày quy định.'},
 lambda_max_invocations:{label:'Lượt gọi tối đa',unit:'lượt',help:'Coi là ít hoạt động nếu tổng lượt gọi nhỏ hơn hoặc bằng ngưỡng này.'},
 asg_zero_days:{label:'Dung lượng bằng 0 trong',unit:'ngày',help:'Cảnh báo Auto Scaling Group có desired và min size bằng 0 liên tục.'},
 ecs_empty_days:{label:'Cluster rỗng trong',unit:'ngày',help:'Cảnh báo ECS Cluster không có task hay container instance nào đang chạy.'},
 eks_idle_days:{label:'Không có workload trong',unit:'ngày',help:'Cảnh báo EKS control plane không có Node Group hoặc Fargate profile hoạt động.'},
 orphan_hours:{label:'Ổ đĩa chưa gắn trong',unit:'giờ',help:'Cảnh báo EBS volume ở trạng thái available (chưa gắn vào EC2).'},
 snapshot_days:{label:'Snapshot cũ hơn',unit:'ngày',help:'Cảnh báo EBS snapshot cũ và không thuộc bất kỳ AMI nào đang tồn tại.'},
 rds_snapshot_days:{label:'Bản chụp thủ công cũ hơn',unit:'ngày',help:'Cảnh báo snapshot RDS tạo thủ công tích lũy lâu ngày gây tốn chi phí lưu trữ.'},
 efs_no_mount_days:{label:'Không có điểm gắn kết trong',unit:'ngày',help:'Cảnh báo hệ thống tệp EFS có 0 mount target (chưa gắn vào compute).'},
 ecr_image_days:{label:'Ảnh container cũ hơn',unit:'ngày',help:'Khuyến nghị dọn dẹp các image ECR cũ hoặc thiết lập Lifecycle Policy.'},
 fsx_idle_days:{label:'Không có I/O trong',unit:'ngày',help:'Cảnh báo hệ thống tệp FSx không có dữ liệu truy xuất qua thời gian theo dõi.'},
 backup_point_days:{label:'Điểm khôi phục cũ hơn',unit:'ngày',help:'Rà soát các recovery point trong AWS Backup đã hết hạn hoặc quá hạn lưu giữ.'},
 rds_cpu_percent:{label:'CPU cơ sở dữ liệu thấp hơn',unit:'%',help:'Cảnh báo RDS instance có CPU p95 thấp hơn mức này.'},
 rds_connections:{label:'Số kết nối client thấp hơn',unit:'kết nối',help:'Cảnh báo cơ sở dữ liệu có số kết nối đồng thời p95 gần như bằng 0.'},
 dynamodb_idle_days:{label:'Bảng không có đọc/ghi trong',unit:'ngày',help:'Cảnh báo bảng DynamoDB có 0 consumed read/write units trong cửa sổ quan sát.'},
 elasticache_idle_days:{label:'Cụm cache không có kết nối trong',unit:'ngày',help:'Cảnh báo cụm Redis/Memcached có số kết nối client bằng 0.'},
 memorydb_idle_days:{label:'Cụm MemoryDB không có kết nối trong',unit:'ngày',help:'Cảnh báo cụm MemoryDB rảnh rỗi không có kết nối ứng dụng.'},
 documentdb_idle_days:{label:'Cụm DocumentDB không có kết nối trong',unit:'ngày',help:'Rà soát cụm DocumentDB không có lưu lượng truy vấn.'},
 neptune_idle_days:{label:'Cụm Neptune không có kết nối trong',unit:'ngày',help:'Rà soát cơ sở dữ liệu đồ thị Neptune không có kết nối client.'},
 nat_mib_hour:{label:'Lưu lượng qua cổng NAT thấp hơn',unit:'MiB/giờ',help:'Cảnh báo NAT Gateway tốn phí theo giờ nhưng lưu lượng qua rất thấp.'},
 alb_requests_hour:{label:'Request ALB thấp hơn',unit:'req/giờ',help:'Cảnh báo Application Load Balancer nhận ít hơn số request quy định.'},
 nlb_new_flows_hour:{label:'Flow mới NLB thấp hơn',unit:'flow/giờ',help:'Cảnh báo Network Load Balancer có số luồng kết nối mới thấp.'},
 sg_unused_days:{label:'Nhóm bảo mật không gắn trong',unit:'ngày',help:'Cảnh báo Security Group không gắn vào bất kỳ ENI nào hoặc được tham chiếu.'},
 vpc_endpoint_unused_days:{label:'Điểm cuối VPC không dùng trong',unit:'ngày',help:'Cảnh báo Interface VPC Endpoint có lưu lượng truyền tải bằng 0.'},
 cloudfront_requests_day:{label:'Lưu lượng phân phối thấp hơn',unit:'req/ngày',help:'Cảnh báo CloudFront distribution nhận được ít hơn số request quy định mỗi ngày.'},
 sagemaker_idle_days:{label:'Endpoint ML không gọi trong',unit:'ngày',help:'Cảnh báo SageMaker endpoint chạy máy chủ tốn kém nhưng 0 có lệnh gọi suy luận.'},
 opensearch_idle_days:{label:'Miền tìm kiếm không có truy vấn trong',unit:'ngày',help:'Cảnh báo cụm OpenSearch không có yêu cầu search hoặc index nào.'},
 redshift_idle_days:{label:'Kho dữ liệu không có kết nối trong',unit:'ngày',help:'Cảnh báo cụm Redshift không có kết nối truy vấn từ người dùng hay ứng dụng.'},
 msk_idle_days:{label:'Cụm Kafka không có tin nhắn trong',unit:'ngày',help:'Cảnh báo cụm MSK không có dữ liệu produce hoặc consume.'},
 kinesis_idle_days:{label:'Luồng dữ liệu không có record trong',unit:'ngày',help:'Cảnh báo Kinesis Data Stream không có dữ liệu đưa vào stream.'},
 log_group_retention_days:{label:'Thời gian lưu trữ log đề xuất',unit:'ngày',help:'Cảnh báo nhóm log để chế độ lưu vô hạn (Never Expire), khuyến nghị đặt hạn lưu.'},
 sqs_idle_days:{label:'Hàng đợi không có tin nhắn trong',unit:'ngày',help:'Cảnh báo hàng đợi SQS không có tin nhắn gửi hoặc nhận qua thời gian theo dõi.'},
 sns_unused_days:{label:'Kênh thông báo không hoạt động trong',unit:'ngày',help:'Cảnh báo SNS topic không có người đăng ký nhận tin hoặc không có thông điệp gửi đi.'},
 eventbridge_unused_days:{label:'Quy tắc sự kiện không hoạt động trong',unit:'ngày',help:'Cảnh báo rule EventBridge đang bị tắt (DISABLED) hoặc không có đích xử lý (target).'},
 stepfunctions_unused_days:{label:'Quy trình không có lượt chạy trong',unit:'ngày',help:'Cảnh báo State Machine không có bất kỳ lượt thực thi (execution) nào được bắt đầu.'},
 apigateway_unused_days:{label:'Cổng API không nhận request trong',unit:'ngày',help:'Cảnh báo REST/HTTP API không có lưu lượng truy cập qua thời gian theo dõi.'}
};
const defaultThresholdConfig={
 cpu_percent:{group:'compute',resource:'EC2',rule:'EC2_LOW_UTILIZATION',label:'Ngưỡng CPU EC2 (%)',min:1,max:50,integer:false,default:5,unit:'%'},
 network_mib_hour:{group:'compute',resource:'EC2',rule:'EC2_LOW_UTILIZATION',label:'Ngưỡng network EC2 (MiB/giờ)',min:0.1,max:100,integer:false,default:1,unit:'MiB/giờ'},
 window_hours:{group:'compute',resource:'ALL',rule:'METRIC_WINDOW',label:'Cửa sổ metrics (giờ)',min:24,max:168,integer:true,default:24,unit:'giờ'},
 interval_hours:{group:'compute',resource:'ALL',rule:'SCAN_INTERVAL',label:'Khoảng cách giữa các lần quét (giờ)',min:1,max:24,integer:true,default:6,unit:'giờ'},
 lambda_unused_days:{group:'compute',resource:'LAMBDA_FUNCTION',rule:'LAMBDA_UNUSED',label:'Thời gian Lambda không hoạt động (ngày)',min:7,max:90,integer:true,default:30,unit:'ngày'},
 asg_zero_days:{group:'compute',resource:'AUTO_SCALING_GROUP',rule:'ASG_ZERO_CAPACITY_OLD',label:'Thời gian ASG dung lượng 0 (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 ecs_empty_days:{group:'compute',resource:'ECS_CLUSTER',rule:'ECS_CLUSTER_EMPTY',label:'Thời gian ECS Cluster rỗng (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 lambda_max_invocations:{group:'compute',resource:'LAMBDA_FUNCTION',rule:'LAMBDA_UNUSED',label:'Lượt gọi Lambda tối đa',min:0,max:10000,integer:true,default:0,unit:'lượt'},
 eks_idle_days:{group:'compute',resource:'EKS_CLUSTER',rule:'EKS_IDLE_CANDIDATE',label:'Thời gian EKS không có Node (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 orphan_hours:{group:'storage',resource:'EBS',rule:'EBS_UNATTACHED',label:'Thời gian theo dõi EBS / EIP (giờ)',min:1,max:168,integer:true,default:24,unit:'giờ'},
 snapshot_days:{group:'storage',resource:'SNAPSHOT',rule:'SNAPSHOT_OLD_UNREFERENCED',label:'Tuổi EBS Snapshot (ngày)',min:7,max:365,integer:true,default:30,unit:'ngày'},
 rds_snapshot_days:{group:'storage',resource:'RDS_SNAPSHOT',rule:'RDS_SNAPSHOT_OLD',label:'Tuổi RDS Snapshot thủ công (ngày)',min:7,max:365,integer:true,default:90,unit:'ngày'},
 efs_no_mount_days:{group:'storage',resource:'EFS_FILE_SYSTEM',rule:'EFS_NO_MOUNT_TARGET',label:'Thời gian EFS không có Mount Target (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 ecr_image_days:{group:'storage',resource:'ECR_REPOSITORY',rule:'ECR_NO_LIFECYCLE',label:'Tuổi Image ECR khuyến nghị (ngày)',min:7,max:365,integer:true,default:90,unit:'ngày'},
 fsx_idle_days:{group:'storage',resource:'FSX_FILE_SYSTEM',rule:'FSX_LOW_ACTIVITY',label:'Thời gian FSx không có I/O (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 backup_point_days:{group:'storage',resource:'BACKUP_VAULT',rule:'BACKUP_OLD_RECOVERY_POINT',label:'Tuổi Recovery Point AWS Backup (ngày)',min:30,max:365,integer:true,default:180,unit:'ngày'},
 rds_cpu_percent:{group:'database',resource:'RDS',rule:'RDS_LOW_UTILIZATION',label:'Ngưỡng CPU RDS (%)',min:1,max:50,integer:false,default:5,unit:'%'},
 rds_connections:{group:'database',resource:'RDS',rule:'RDS_LOW_UTILIZATION',label:'Ngưỡng kết nối RDS',min:1,max:1000,integer:true,default:1,unit:'kết nối'},
 dynamodb_idle_days:{group:'database',resource:'DYNAMODB_TABLE',rule:'DYNAMODB_IDLE',label:'Thời gian DynamoDB rảnh (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 elasticache_idle_days:{group:'database',resource:'ELASTICACHE_CLUSTER',rule:'ELASTICACHE_IDLE',label:'Thời gian ElastiCache rảnh (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 memorydb_idle_days:{group:'database',resource:'MEMORYDB_CLUSTER',rule:'MEMORYDB_IDLE',label:'Thời gian MemoryDB rảnh (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 documentdb_idle_days:{group:'database',resource:'DOCUMENTDB_CLUSTER',rule:'DOCUMENTDB_IDLE',label:'Thời gian DocumentDB rảnh (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 neptune_idle_days:{group:'database',resource:'NEPTUNE_CLUSTER',rule:'NEPTUNE_IDLE',label:'Thời gian Neptune rảnh (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 nat_mib_hour:{group:'network',resource:'NAT_GATEWAY',rule:'NAT_LOW_UTILIZATION',label:'Ngưỡng lưu lượng NAT (MiB/giờ)',min:0.1,max:10000,integer:false,default:1,unit:'MiB/giờ'},
 alb_requests_hour:{group:'network',resource:'ALB',rule:'ALB_LOW_UTILIZATION',label:'Ngưỡng request ALB (request/giờ)',min:1,max:1000000,integer:true,default:1,unit:'request/giờ'},
 nlb_new_flows_hour:{group:'network',resource:'NLB',rule:'NLB_LOW_UTILIZATION',label:'Ngưỡng flow mới NLB (flow/giờ)',min:1,max:1000000,integer:true,default:1,unit:'flow/giờ'},
 sg_unused_days:{group:'network',resource:'SECURITY_GROUP',rule:'SECURITY_GROUP_UNUSED',label:'Thời gian Security Group không gắn (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 vpc_endpoint_unused_days:{group:'network',resource:'VPC_ENDPOINT',rule:'VPC_ENDPOINT_UNUSED',label:'Thời gian VPC Endpoint không dùng (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 cloudfront_requests_day:{group:'network',resource:'CLOUDFRONT_DISTRIBUTION',rule:'CLOUDFRONT_LOW_TRAFFIC',label:'Ngưỡng request CloudFront (req/ngày)',min:1,max:1000000,integer:true,default:100,unit:'req/ngày'},
 sagemaker_idle_days:{group:'analytics',resource:'SAGEMAKER_ENDPOINT',rule:'SAGEMAKER_ENDPOINT_IDLE',label:'Thời gian SageMaker không gọi (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 opensearch_idle_days:{group:'analytics',resource:'OPENSEARCH_DOMAIN',rule:'OPENSEARCH_IDLE',label:'Thời gian OpenSearch không có query (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 redshift_idle_days:{group:'analytics',resource:'REDSHIFT_CLUSTER',rule:'REDSHIFT_IDLE',label:'Thời gian Redshift không có kết nối (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 msk_idle_days:{group:'analytics',resource:'MSK_CLUSTER',rule:'MSK_IDLE',label:'Thời gian MSK không có lưu lượng (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 kinesis_idle_days:{group:'analytics',resource:'KINESIS_STREAM',rule:'KINESIS_IDLE',label:'Thời gian Kinesis không có record (ngày)',min:1,max:90,integer:true,default:7,unit:'ngày'},
 log_group_retention_days:{group:'integration',resource:'LOG_GROUP',rule:'LOG_GROUP_NO_RETENTION',label:'Thời gian lưu Log Group đề xuất (ngày)',min:7,max:365,integer:true,default:30,unit:'ngày'},
 sqs_idle_days:{group:'integration',resource:'SQS_QUEUE',rule:'SQS_QUEUE_IDLE',label:'Thời gian SQS không có traffic (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'},
 sns_unused_days:{group:'integration',resource:'SNS_TOPIC',rule:'SNS_TOPIC_UNUSED',label:'Thời gian SNS không hoạt động (ngày)',min:1,max:90,integer:true,default:30,unit:'ngày'},
 eventbridge_unused_days:{group:'integration',resource:'EVENTBRIDGE_RULE',rule:'EVENTBRIDGE_RULE_UNUSED',label:'Thời gian EventBridge rule không dùng (ngày)',min:1,max:90,integer:true,default:30,unit:'ngày'},
 stepfunctions_unused_days:{group:'integration',resource:'STEP_FUNCTION',rule:'STEP_FUNCTION_UNUSED',label:'Thời gian Step Functions không chạy (ngày)',min:1,max:90,integer:true,default:30,unit:'ngày'},
 apigateway_unused_days:{group:'integration',resource:'API_GATEWAY',rule:'API_GATEWAY_UNUSED',label:'Thời gian API Gateway không có request (ngày)',min:1,max:90,integer:true,default:14,unit:'ngày'}
};
const fields=Object.fromEntries(Object.entries(defaultThresholdConfig).map(([k,v])=>[k,[v.label,v.min,v.max,v.integer?1:'any']]));
const stateLabels={KEPT:'Đang giữ',REVIEW:'Cần kiểm tra',OBSERVING:'Đang quan sát',INSUFFICIENT_DATA:'Thiếu dữ liệu',QUEUED:'Đang chờ',RUNNING:'Đang quét',SUCCEEDED:'Hoàn tất',PARTIAL:'Chưa đầy đủ',FAILED:'Lỗi',TIMED_OUT:'Quá hạn'};
const reasons={
 'Low CPU and network; confirm intended workload':'CPU và network thấp; kiểm tra mục đích sử dụng.',
 'Missing CloudWatch metrics; not classified as idle':'Thiếu metrics CloudWatch; chưa thể kết luận ít hoạt động.',
 'Instance younger than observation window':'Instance mới hơn cửa sổ quan sát.',
 'Unattached volume; validate data retention':'Volume chưa gắn vào instance; kiểm tra nhu cầu giữ dữ liệu.',
 'Unassociated public IPv4; may be intentionally reserved':'Elastic IP chưa liên kết; có thể đang được giữ có chủ đích.',
 'Old snapshot not referenced by listed AMIs; backup purpose requires review':'Snapshot cũ, không được các AMI đã đọc tham chiếu; kiểm tra mục đích sao lưu.',
 'Lambda function has 0 invocations; has configured triggers or permissions that may be dormant':'Lambda function có 0 lượt gọi; có cấu hình trigger hoặc quyền nhưng không hoạt động.',
 'Unused Lambda function with 0 invocations and no event source mappings':'Lambda function không có lượt gọi và không có event source mapping.',
 'Log group has no retention policy set (Never Expire); accumulating storage costs':'Log group không đặt thời gian lưu giữ (Never Expire); tích tụ chi phí lưu trữ log.',
 'Security Group is not attached to any network interface or referenced by another group':'Security Group không gắn vào bất kỳ ENI nào hoặc được group khác tham chiếu.',
 'Manual RDS snapshot older than retention threshold; verify backup necessity':'Bản chụp thủ công RDS cũ hơn ngưỡng lưu trữ; kiểm tra nhu cầu giữ backup.',
 'DynamoDB table has zero read/write activity in observation window':'Bảng DynamoDB không có hoạt động đọc/ghi trong cửa sổ quan sát.',
 'ECR repository has no lifecycle policy configured; images accumulate indefinitely':'Repository ECR không có Lifecycle Policy; image tích tụ vô hạn.',
 'SQS queue has zero message traffic in observation window':'Hàng đợi SQS không có message đến/đi trong cửa sổ quan sát.',
 'ElastiCache cluster has zero client connections in observation window':'Cụm ElastiCache không có kết nối client nào trong cửa sổ quan sát.',
 'EFS file system has no mount targets configured; not connected to any compute instance':'Hệ thống tệp EFS không có mount target nào; chưa kết nối tới compute.',
 'ECS cluster has zero running tasks, container instances, and active services':'Cluster ECS không có task, container instance hay service nào hoạt động.',
 'ECS service has desired count set to 0':'Service ECS đang cấu hình desired count bằng 0.',
 'Auto Scaling Group has 0 desired capacity, 0 min size, and 0 running instances':'Auto Scaling Group có desired và min capacity bằng 0, không có instance.',
 'API Gateway received zero requests in observation window':'API Gateway không nhận được request nào trong cửa sổ quan sát.',
 'SNS topic has zero confirmed subscriptions and zero published messages in observation window':'Topic SNS không có subscription xác nhận và không có tin nhắn publish.',
 'EventBridge rule is DISABLED':'Rule EventBridge đang ở trạng thái DISABLED.',
 'EventBridge rule has no targets configured':'Rule EventBridge không có target nào được cấu hình.',
 'Step Functions state machine had zero executions started in observation window':'State Machine Step Functions không có lượt thực thi nào trong cửa sổ quan sát.',
 'VPC Endpoint has zero data transfer or connections in observation window':'VPC Endpoint không có lưu lượng truyền tải hoặc kết nối trong cửa sổ quan sát.',
 'SageMaker endpoint has zero invocations in observation window':'SageMaker endpoint không có lượt gọi nào trong cửa sổ quan sát.',
 'OpenSearch domain has zero search or indexing requests in observation window':'OpenSearch domain không có request tìm kiếm hoặc indexing nào trong cửa sổ quan sát.',
 'Redshift cluster has zero database connections in observation window':'Redshift cluster không có kết nối client nào trong cửa sổ quan sát.',
 'MSK Kafka cluster has zero incoming or outgoing message traffic in observation window':'Cụm MSK Kafka không có lưu lượng tin nhắn vào/ra trong cửa sổ quan sát.',
 'Kinesis Data Stream has zero incoming records in observation window':'Kinesis Data Stream không có record nào nạp vào trong cửa sổ quan sát.',
 'AWS Backup vault contains expired recovery points that were not deleted':'AWS Backup vault chứa các điểm khôi phục đã hết hạn chưa được dọn dẹp.',
 'EKS cluster has no active managed nodegroups or Fargate profiles':'EKS cluster không có node group hay Fargate profile nào hoạt động.',
 'FSx file system has zero data read/write throughput in observation window':'Hệ thống tệp FSx không có thông lượng đọc/ghi trong cửa sổ quan sát.',
 'MemoryDB cluster has zero client connections in observation window':'Cụm MemoryDB không có kết nối client nào trong cửa sổ quan sát.',
 'DocumentDB cluster has zero client connections in observation window':'Cụm DocumentDB không có kết nối client nào trong cửa sổ quan sát.',
 'Neptune graph database cluster has zero client connections in observation window':'Cụm Neptune Graph DB không có kết nối client nào trong cửa sổ quan sát.'
};
const evidenceFields={
 EC2:[['cpu_p95','CPU p95','%'],['network_mib_hour','Network trung bình','MiB/giờ'],['launch_time','Thời điểm khởi chạy','time']],
 EBS:[['size_gib','Dung lượng volume','GiB'],['observed_hours','Theo dõi chưa gắn','giờ'],['threshold_hours','Ngưỡng theo dõi','giờ']],
 EIP:[['observed_hours','Theo dõi chưa liên kết','giờ'],['threshold_hours','Ngưỡng theo dõi','giờ']],
 SNAPSHOT:[['age_days','Tuổi snapshot','ngày'],['snapshot_days','Ngưỡng tuổi snapshot','ngày'],['volume_id','Volume nguồn'],['logical_volume_gib','Dung lượng logic của volume','GiB'],['relationships_complete','Đã đọc đầy đủ quan hệ AMI'],['snapshot_started_at','Thời điểm tạo snapshot','time'],['relationship_scope','Phạm vi đối chiếu AMI']],
 S3_MULTIPART:[['bucket','Bucket'],['key','Object key'],['upload_id','Upload ID'],['age_days','Tuổi upload','ngày'],['threshold_days','Ngưỡng tuổi upload','ngày'],['initiated_at','Thời điểm bắt đầu upload','time']],
 RDS:[['cpu_p95','CPU p95','%'],['connections_p95','Kết nối p95','kết nối'],['engine','Engine'],['instance_class','Instance class'],['created_at','Thời điểm tạo','time']],
 NAT_GATEWAY:[['nat_mib_hour','Lưu lượng NAT trung bình','MiB/giờ'],['vpc_id','VPC ID'],['subnet_id','Subnet ID'],['created_at','Thời điểm tạo','time']],
 ALB:[['requests_hour','Request trung bình','request/giờ'],['scheme','Scheme'],['created_at','Thời điểm tạo','time']],
 NLB:[['new_flows_hour','Flow mới trung bình','flow mới/giờ'],['scheme','Scheme'],['created_at','Thời điểm tạo','time']],
 LAMBDA_FUNCTION:[['function_name','Tên function'],['runtime','Runtime'],['code_size_mib','Dung lượng code','MiB'],['invocations','Lượt gọi','lượt'],['event_source_mappings','Event Source Mappings','trigger'],['has_resource_policy','Có Resource Policy'],['last_modified','Lần sửa đổi cuối','time']],
 LOG_GROUP:[['log_group_name','Tên Log Group'],['stored_mib','Dung lượng lưu trữ','MiB'],['retention_in_days','Thời gian lưu giữ (ngày)'],['recommended_retention_days','Khuyến nghị lưu giữ','ngày'],['creation_time','Thời điểm tạo','time']],
 SECURITY_GROUP:[['group_id','Security Group ID'],['group_name','Tên Security Group'],['vpc_id','VPC ID'],['description','Mô tả']],
 DYNAMODB_TABLE:[['table_name','Tên bảng'],['item_count','Số lượng item'],['table_size_bytes','Dung lượng (Bytes)'],['billing_mode','Chế độ thanh toán'],['read_units','Đơn vị Read tiêu thụ'],['write_units','Đơn vị Write tiêu thụ']],
 ECR_REPOSITORY:[['repository_name','Tên Repository'],['registry_id','Registry ID'],['has_lifecycle_policy','Có Lifecycle Policy'],['recommended_lifecycle_days','Khuyến nghị dọn dẹp','ngày']],
 SQS_QUEUE:[['queue_name','Tên hàng đợi'],['approximate_messages','Số tin nhắn tồn'],['messages_sent','Tin nhắn gửi đến'],['messages_received','Tin nhắn tiêu thụ'],['queue_url','URL hàng đợi']],
 ELASTICACHE_CLUSTER:[['cluster_id','ID cụm'],['engine','Engine'],['cache_node_type','Loại Node'],['connections_sum','Số kết nối khách']],
 EFS_FILE_SYSTEM:[['file_system_id','ID hệ thống tệp'],['mount_targets_count','Số Mount Target'],['size_in_bytes','Dung lượng (Bytes)'],['creation_time','Thời điểm tạo','time']],
 ECS_CLUSTER:[['cluster_name','Tên Cluster'],['running_tasks','Tasks đang chạy'],['active_services','Services hoạt động'],['cluster_arn','ARN Cluster']],
 ECS_SERVICE:[['service_name','Tên Service'],['desired_count','Desired Count'],['running_count','Running Count'],['cluster_arn','ARN Cluster']],
 AUTO_SCALING_GROUP:[['auto_scaling_group_name','Tên ASG'],['desired_capacity','Desired Capacity'],['min_size','Min Size'],['instance_count','Số Instance đang chạy'],['created_time','Thời điểm tạo','time']],
 API_GATEWAY:[['api_id','ID API'],['api_name','Tên API'],['request_count','Tổng Request nhận được']],
 SNS_TOPIC:[['topic_name','Tên Topic'],['subscriptions_confirmed','Số Subscriptions'],['messages_published','Tin nhắn đã publish'],['topic_arn','ARN Topic']],
 EVENTBRIDGE_RULE:[['rule_name','Tên Rule'],['state','Trạng thái'],['targets_count','Số Target'],['schedule_expression','Lịch kích hoạt'],['event_pattern','Event Pattern']],
 STEP_FUNCTION:[['state_machine_name','Tên State Machine'],['type','Loại State Machine'],['executions_count','Lượt thực thi'],['state_machine_arn','ARN']],
 VPC_ENDPOINT:[['vpc_endpoint_id','ID VPC Endpoint'],['vpc_id','VPC ID'],['service_name','Tên Service kết nối'],['vpc_endpoint_type','Loại Endpoint']],
 SAGEMAKER_ENDPOINT:[['endpoint_name','Tên Endpoint'],['endpoint_status','Trạng thái'],['invocations_sum','Tổng Invocation trong cửa sổ']],
 OPENSEARCH_DOMAIN:[['domain_name','Tên Domain'],['engine_version','Engine Version'],['requests_sum','Tổng Request Search/Indexing']],
 REDSHIFT_CLUSTER:[['cluster_identifier','Cluster ID'],['node_type','Node Type'],['number_of_nodes','Số lượng Node'],['database_connections','Số kết nối']],
 MSK_CLUSTER:[['cluster_name','Tên Cluster'],['number_of_nodes','Số Broker'],['traffic_sum','Lưu lượng truyền tải (Bytes)']],
 KINESIS_STREAM:[['stream_name','Tên Stream'],['records_sum','Tổng Records nạp vào']],
 CLOUDFRONT_DISTRIBUTION:[['distribution_id','Distribution ID'],['domain_name','Domain Name'],['requests_count','Tổng Requests trong ngày'],['threshold_requests_day','Ngưỡng tối thiểu/ngày']],
 BACKUP_VAULT:[['vault_name','Tên Backup Vault'],['expired_recovery_points','Điểm khôi phục hết hạn'],['total_recovery_points','Tổng điểm khôi phục']],
 EKS_CLUSTER:[['cluster_name','Tên Cluster EKS'],['version','Kubernetes Version'],['nodegroups_count','Số Node Groups'],['fargate_profiles_count','Số Fargate Profiles']],
 FSX_FILE_SYSTEM:[['file_system_id','FSx File System ID'],['file_system_type','Loại FSx'],['storage_capacity','Dung lượng cấp phát'],['total_io_bytes','Lưu lượng I/O (Bytes)']],
 MEMORYDB_CLUSTER:[['cluster_name','Tên Cluster MemoryDB'],['node_type','Loại Node'],['connections_sum','Số kết nối khách']],
 DOCUMENTDB_CLUSTER:[['cluster_identifier','DocumentDB Cluster ID'],['engine','Engine'],['cluster_members_count','Số Instance trong cụm'],['database_connections','Số kết nối']],
 NEPTUNE_CLUSTER:[['cluster_identifier','Neptune Cluster ID'],['engine','Engine'],['cluster_members_count','Số Instance trong cụm'],['database_connections','Số kết nối']]
};
const thresholdFields={
 EC2:['cpu_percent','network_mib_hour'],EBS:['orphan_hours'],EIP:['orphan_hours'],SNAPSHOT:['snapshot_days'],S3_MULTIPART:['multipart_days'],
 RDS:['rds_cpu_percent','rds_connections'],RDS_SNAPSHOT:['rds_snapshot_days'],NAT_GATEWAY:['nat_mib_hour'],ALB:['alb_requests_hour'],NLB:['nlb_new_flows_hour'],
 LAMBDA_FUNCTION:['lambda_unused_days','lambda_max_invocations'],LOG_GROUP:['log_group_retention_days'],SECURITY_GROUP:['sg_unused_days'],DYNAMODB_TABLE:['dynamodb_idle_days'],
 ECR_REPOSITORY:['ecr_image_days'],SQS_QUEUE:['sqs_idle_days'],ELASTICACHE_CLUSTER:['elasticache_idle_days'],EFS_FILE_SYSTEM:['efs_no_mount_days'],
 ECS_CLUSTER:['ecs_empty_days'],ECS_SERVICE:[],AUTO_SCALING_GROUP:['asg_zero_days'],API_GATEWAY:['apigateway_unused_days'],
 SNS_TOPIC:['sns_unused_days'],EVENTBRIDGE_RULE:['eventbridge_unused_days'],STEP_FUNCTION:['stepfunctions_unused_days'],VPC_ENDPOINT:['vpc_endpoint_unused_days'],
 SAGEMAKER_ENDPOINT:['sagemaker_idle_days'],OPENSEARCH_DOMAIN:['opensearch_idle_days'],REDSHIFT_CLUSTER:['redshift_idle_days'],MSK_CLUSTER:['msk_idle_days'],
 KINESIS_STREAM:['kinesis_idle_days'],CLOUDFRONT_DISTRIBUTION:['cloudfront_requests_day'],BACKUP_VAULT:['backup_point_days'],EKS_CLUSTER:['eks_idle_days'],
 FSX_FILE_SYSTEM:['fsx_idle_days'],MEMORYDB_CLUSTER:['memorydb_idle_days'],DOCUMENTDB_CLUSTER:['documentdb_idle_days'],NEPTUNE_CLUSTER:['neptune_idle_days']
};
const thresholdLabels={cpu_percent:['CPU EC2','%'],network_mib_hour:['Network EC2','MiB/giờ'],orphan_hours:['Theo dõi không sử dụng','giờ'],snapshot_days:['Tuổi snapshot','ngày'],multipart_days:['Tuổi multipart upload (lớn hơn)','ngày'],rds_cpu_percent:['CPU RDS','%'],rds_connections:['Kết nối RDS','kết nối'],nat_mib_hour:['Lưu lượng NAT','MiB/giờ'],alb_requests_hour:['Request ALB','request/giờ'],nlb_new_flows_hour:['Flow mới NLB','flow mới/giờ']};

function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function status(text,error=false){$('status').hidden=!text;$('status').textContent=text;$('status').className=error?'error':'';}
function badge(s){return node('span',stateLabels[s]||s,'badge '+(s==='REVIEW'?'review':s==='FAILED'||s==='PARTIAL'||s==='TIMED_OUT'?'error':s==='SUCCEEDED'?'good':'observing'));}
function date(t){return t?new Date(t*1000).toLocaleString('vi-VN'):'Chưa có thời gian';}
function b64(b){return btoa(String.fromCharCode(...b)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function random(){const b=new Uint8Array(32);crypto.getRandomValues(b);return b64(b);}

const demoAuth={
 pending:new Map(),
 verified:new Set(['demo@example.com']),
 resetCodes:new Map()
};

function isValidEmail(email){
 return typeof email==='string'&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
}

function validatePassword(password){
 if(!password||typeof password!=='string')return 'Vui lòng nhập mật khẩu.';
 if(password.length<12)return 'Mật khẩu phải có ít nhất 12 ký tự.';
 if(!/[A-Z]/.test(password))return 'Mật khẩu phải chứa ít nhất một chữ hoa.';
 if(!/[a-z]/.test(password))return 'Mật khẩu phải chứa ít nhất một chữ thường.';
 if(!/[0-9]/.test(password))return 'Mật khẩu phải chứa ít nhất một chữ số.';
 if(!/[^A-Za-z0-9]/.test(password))return 'Mật khẩu phải chứa ít nhất một ký tự đặc biệt.';
 return null;
}

async function cognitoIdp(action,params){
 if(!cfg){try{const r=await fetch('config.json',{cache:'no-store'});if(r.ok){cfg=await r.json();window.cfg=cfg;}}catch{}}
 if(params&&!params.ClientId&&cfg?.clientId)params.ClientId=cfg.clientId;
 const region=cfg?.region||(cfg?.auth&&cfg.auth.match(/\.auth\.([a-z0-9-]+)\.amazoncognito\.com/)?.[1])||'ap-southeast-1';
 const res=await fetch('https://cognito-idp.'+region+'.amazonaws.com/',{
  method:'POST',
  headers:{
   'Content-Type':'application/x-amz-json-1.1',
   'X-Amz-Target':'AWSCognitoIdentityProviderService.'+action
  },
  body:JSON.stringify(params)
 });
 let data={};
 try{data=await res.json();}catch{}
 if(!res.ok){
  const type=(data.__type||'').split('#').pop()||data.code||'CognitoError';
  const err=new Error(friendlyCognitoError(type,data.message));
  err.code=type;
  throw err;
 }
 return data;
}

function friendlyCognitoError(type,message){
 if(type==='UsernameExistsException')return 'Email này đã được đăng ký.';
 if(type==='CodeMismatchException')return 'Mã xác minh không chính xác.';
 if(type==='ExpiredCodeException')return 'Mã xác minh đã hết hạn. Vui lòng gửi lại mã mới.';
 if(type==='UserNotFoundException')return 'Không tìm thấy tài khoản với email này.';
 if(type==='InvalidPasswordException')return 'Mật khẩu phải có ít nhất 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt.';
 if(type==='InvalidParameterException')return 'Thông tin nhập không hợp lệ hoặc mật khẩu chưa đúng định dạng.';
 if(type==='LimitExceededException')return 'Đã vượt quá số lần thử. Vui lòng đợi trong giây lát.';
 if(type==='NotAuthorizedException'){
  if(message&&message.includes('SignUp is not permitted')){
   return 'Chức năng tự đăng ký đang chờ phê duyệt cấu hình User Pool trên hệ thống.';
  }
  return 'Thao tác không được phép hoặc tài khoản chưa được xác minh.';
 }
 if(type==='TooManyRequestsException')return 'Quá nhiều yêu cầu. Vui lòng thử lại sau.';
 return message||'Lỗi xác thực Cognito.';
}

function showGuestView(view){
 const views=['login','register','verify','forgot','reset'];
 if(!views.includes(view))view='login';
 for(const v of views){
  const el=$('view-'+v);
  if(el)el.hidden=(v!==view);
 }
 document.querySelectorAll('#nav-guest button').forEach(b=>{
  b.classList.toggle('active',b.dataset.guest===view);
 });
 $('breadcrumb').textContent=guestViewTitles[view]||'Đăng nhập';
 status('');
}

async function login(){
 if(!cfg)return;
 if(cfg.demo){
  token='demo-local-only';
  sessionStorage.setItem('crg-token',token);
  await run(init);
  return;
 }
 const verifier=random(),state=random();
 sessionStorage.setItem('crg-verifier',verifier);
 sessionStorage.setItem('crg-state',state);
 const challenge=b64(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(verifier))));
 location.assign(cfg.auth+'/oauth2/authorize?'+new URLSearchParams({
  client_id:cfg.clientId,
  response_type:'code',
  scope:'openid email aws.cognito.signin.user.admin',
  redirect_uri:cfg.redirect,
  state,
  code_challenge:challenge,
  code_challenge_method:'S256'
 }));
}

function logout(){
 closeFindingDetail();
 clearTimeout(pollTimer);
 sessionStorage.removeItem('crg-token');
 token=null;
 $('app').hidden=true;
 $('welcome').hidden=false;
 $('nav-auth').hidden=true;
 $('nav-guest').hidden=false;
 $('login').textContent='Đăng nhập';
 $('login').onclick=()=>showGuestView('login');
 showGuestView('login');
 if(cfg&&!cfg.demo){
  location.assign(cfg.auth+'/logout?'+new URLSearchParams({client_id:cfg.clientId,logout_uri:cfg.redirect}));
 }
}

async function api(path,method='GET',data){
 const r=await fetch(cfg.api+path,{
  method,
  headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
  ...(data!==undefined?{body:JSON.stringify(data)}:{})
 });
 let v;
 try{v=await r.json();}catch{throw Error('Máy chủ trả phản hồi không hợp lệ.');}
 if(r.status===401){
  closeFindingDetail();
  clearTimeout(pollTimer);
  token=null;
  sessionStorage.removeItem('crg-token');
  $('app').hidden=true;
  $('welcome').hidden=false;
  $('nav-auth').hidden=true;
  $('nav-guest').hidden=false;
  $('login').textContent='Đăng nhập';
  $('login').onclick=()=>showGuestView('login');
  showGuestView('login');
 }
 if(!r.ok)throw Error(friendlyError(v.error||v.message||'HTTP '+r.status));
 return v;
}

async function run(fn,button){
 if(button)button.disabled=true;
 try{await fn();}
 catch(e){status(friendlyError(e.message),true);}
 finally{
  if(button){
   const feedback=$(button.id+'-feedback')||$(button.id.replace(/-submit$/,'')+'-feedback');
   if(feedback){
    feedback.hidden=$('status').hidden;
    feedback.textContent=$('status').textContent;
    feedback.className='inline-feedback '+$('status').className;
   }
   button.disabled=button.dataset.saved==='true';
  }
  if(button===$('scan')&&profile)render();
 }
}

function showPage(page){
 if(!profile)return;
 closeFindingDetail();
 if(!pages[page])page='overview';
 for(const key of Object.keys(pages))$('page-'+key).hidden=key!==page;
 document.querySelectorAll('#nav-auth button[data-page]').forEach(b=>{
  const match=b.dataset.page===page;
  b.classList.toggle('active',match);
  if(match)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
 });
 $('page-title').textContent=pages[page][0];
 $('page-subtitle').textContent=pages[page][1];
 $('page-subtitle').hidden=!pages[page][1];
 $('breadcrumb').textContent=pages[page][0];
 document.title=pages[page][0]+' | Cloud Guardian';
 if(page==='history')run(loadHistory);
 if(page==='findings'&&!feedbackLoaded&&!feedbackLoading)loadFeedback();
}

function detailValue(value,unit){
 if(value===undefined||value===null||value==='')return 'Chưa có dữ liệu';
 if(unit==='time'){
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))return 'Chưa có dữ liệu';
  return new Date(value).toISOString().replace('T',' ').replace(/\.000Z$/,' UTC').replace(/Z$/,' UTC');
 }
 if(typeof value==='number'&&!Number.isFinite(value))return 'Chưa có dữ liệu';
 if(unit==='coverage')return typeof value==='number'?Number((value*100).toFixed(1))+'%':'Chưa có dữ liệu';
 if(typeof value==='boolean')return value?'Có':'Không';
 if(Array.isArray(value))return value.length?value.map(item=>detailValue(item)).join(' · '):'Không ghi nhận';
 if(typeof value==='object')return Object.keys(value).length?Object.entries(value).map(([key,item])=>key+': '+detailValue(item)).join(' · '):'Không ghi nhận';
 return String(value)+(unit?' '+unit:'');
}

function detailSection(container,title,rows){
 const section=node('section',undefined,'finding-detail-section'),list=node('dl',undefined,'finding-detail-grid');
 section.append(node('h3',title));
 for(const [key,label,value,unit] of rows){
  const item=node('div');item.dataset.field=key;
  item.append(node('dt',label),node('dd',detailValue(value,unit)));
  list.append(item);
 }
 section.append(list);container.append(section);return section;
}

function closeFindingDetail(){detailFocus=null;if($('finding-dialog').open)$('finding-dialog').close();$('finding-detail-content').replaceChildren();}
function restoreFindingFocus(){
 const previous=detailFocus;
 detailFocus=null;
 if(!previous||previous.element?.isConnected||$('app').hidden)return;
 const container=$(previous.container);
 const replacement=container&&[...container.querySelectorAll('.finding-open')].find(button=>button.dataset.findingId===previous.id&&button.dataset.region===previous.region&&button.dataset.resourceId===previous.resource);
 const fallback=previous.container==='findings-list'?$('search'):previous.container==='history-detail'?$('refresh-history'):$('refresh');
 const target=replacement||fallback;
 if(target){
  target.focus();
  queueMicrotask(()=>target.focus());
 }
}

function openFindingDetail(f,history=false,opener=document.activeElement){
 detailFocus={element:opener,container:opener.closest('[id]')?.id,id:String(f.finding_id??''),region:String(f.region??''),resource:String(f.resource_id??'')};
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{},content=$('finding-detail-content');
 content.replaceChildren();
 $('finding-detail-context').textContent=history?'Snapshot lịch sử đã lưu.':'Bằng chứng đã lưu của finding tại lần đánh giá này.';
 detailSection(content,'Thông tin finding',[
  ['type','Loại tài nguyên',f.type],['resource_id','Resource ID',f.resource_id],['account_id','AWS account',f.account_id??v.account_id],['region','Region',f.region??v.region],['finding_id','Finding ID',f.finding_id],['rule_id','Rule',f.rule_id],['level','Mức cảnh báo',stateLabels[f.level]||f.level],['reason','Lý do',reasons[f.reason]||f.reason],['recommendation','Khuyến nghị',f.recommendation]
 ]);
 const times=detailSection(content,'Mốc quan sát finding',[
  ['first_seen_at','Quan sát lần đầu',f.first_seen_at,'time'],['last_seen_at','Quan sát gần nhất',f.last_seen_at,'time'],['evaluated_at','Thời điểm đánh giá',f.evaluated_at??v.evaluated_at,'time']
 ]);
 detailSection(content,'Evidence '+(f.type||''),(evidenceFields[f.type]||[]).map(([key,label,unit])=>[key,label,v[key],unit]));
 const thresholds=thresholdFields[f.type]||Object.keys(v.thresholds||{}),legacy={orphan_hours:v.threshold_hours,snapshot_days:v.snapshot_days,multipart_days:v.threshold_days};
 detailSection(content,'Ngưỡng tại lần đánh giá',thresholds.map(key=>['thresholds.'+key,thresholdLabels[key]?.[0]||key,v.thresholds?.[key]??legacy[key],thresholdLabels[key]?.[1]]));
 if(['EC2','RDS','NAT_GATEWAY','ALB','NLB'].includes(f.type)){
  detailSection(content,'Cửa sổ và độ phủ metrics',[
   ['window_hours','Cửa sổ metrics',v.window_hours,'giờ'],['observation_start','Bắt đầu cửa sổ',v.observation_start,'time'],['observation_end','Kết thúc cửa sổ',v.observation_end,'time'],['metric_period_seconds','Chu kỳ mẫu',v.metric_period_seconds,'giây'],['coverage','Độ phủ mẫu hợp lệ',v.coverage,'coverage'],['required_samples','Số mẫu tối thiểu mỗi metric',v.required_samples],['sample_counts','Số mẫu hợp lệ',v.sample_counts],['received_sample_counts','Số mẫu nhận được',v.received_sample_counts],['invalid_sample_counts','Số mẫu không hợp lệ',v.invalid_sample_counts],['metric_units','Đơn vị metric đầu vào',v.metric_units],['metric_statistics','Thống kê mỗi chu kỳ',v.metric_statistics]
  ]);
 }
 const quality=['EC2','RDS','NAT_GATEWAY','ALB','NLB'].includes(f.type)?[['missing_metrics','Metric thiếu mẫu',v.missing_metrics],['invalid_metrics','Metric không hợp lệ',v.invalid_metrics],['calculation_errors','Lỗi tính toán',v.calculation_errors],['data_issues','Vấn đề dữ liệu',v.data_issues]]:v.data_issues!==undefined?[['data_issues','Vấn đề dữ liệu',v.data_issues]]:[];
 if(quality.length)detailSection(content,'Chất lượng dữ liệu',quality);
 $('finding-dialog').showModal();
}

function evidence(f){
 const v=f.evidence||{},lines=(evidenceFields[f.type]||[]).filter(([key,,unit])=>unit!=='time'&&v[key]!==undefined&&v[key]!==null).slice(0,3).map(([key,label,unit])=>label+': '+detailValue(v[key],unit));
 if(v.coverage!==undefined&&v.coverage!==null)lines.push('Độ phủ: '+detailValue(v.coverage,'coverage'));
 return lines.join(' · ')||'Chưa có dữ liệu';
}
function findings(){return results.flatMap(r=>(r.findings||[]).map(f=>({...f,region:r.region})));}
function feedbackKey(f){return JSON.stringify([f.region,f.finding_id]);}
function feedbackFocus(container){
 const active=document.activeElement,group=active.closest('.finding-feedback');
 if(!group||!container.contains(active))return null;
 return {key:group.dataset.feedbackKey,selector:['feedback-ack','feedback-keep','feedback-ignore','feedback-days','feedback-unkeep','feedback-unignore','feedback-manage-days','feedback-extend','feedback-status'].find(name=>active.classList.contains(name))||'feedback-status'};
}
function restoreFeedbackFocus(container,previous){
 if(!previous||$('app').hidden)return;
 const group=[...container.querySelectorAll('.finding-feedback')].find(item=>item.dataset.feedbackKey===previous.key),control=group?.querySelector('.'+previous.selector),target=control&&!control.disabled?control:group?.querySelector('.feedback-status');
 (target||(container.id==='feedback-list'?$('refresh-feedback'):container.id==='findings-list'?$('search'):$('refresh')))?.focus();
}

function feedbackHidden(record){return record.expires<=Date.now()/1000?false:!!record.kept||record.ignore_until>Date.now()/1000;}
function feedbackSaveMessage(record,patch,confirmed=false){
 if('acknowledged' in patch)return record.acknowledged?'Đã đánh dấu đã xem.':'Đã bỏ trạng thái đã xem.';
 if(patch.kept===true)return 'Đã giữ lại. Cảnh báo đã được ẩn.';
 if(patch.ignoreUntil)return 'Đã bỏ qua '+Math.round((Date.parse(patch.ignoreUntil)-Date.now())/86400000)+' ngày. Cảnh báo đã được ẩn.';
 const cleared=patch.kept===false?'Đã bỏ giữ. ':'Đã hủy bỏ qua. ';
 if(record.kept)return cleared+'Finding vẫn đang được giữ lại.';
 if(record.ignore_until>Date.now()/1000)return cleared+'Finding vẫn đang được bỏ qua đến '+date(record.ignore_until)+'.';
 if(!confirmed)return cleared+'Đang tải lại kết quả để kiểm tra.';
 return cleared+(findings().some(item=>feedbackKey(item)===feedbackKey(record))?'Finding đã hiện lại trong kết quả hiện tại.':'Finding chưa hiện trong kết quả hiện tại; cần quét mới để kiểm tra lại.');
}

async function saveFindingFeedback(f,patch,generation,managed=false){
 const key=feedbackKey(f);if(generation!==scopeGeneration||feedbackState.get(key)?.pending)return;
 const operation={pending:true,message:'Đang lưu…',error:false};feedbackState.set(key,operation);render();
 let saved=false;
 try{
  const record=await api('/feedback','PUT',{region:f.region,finding_id:f.finding_id,...patch});
  if(generation!==scopeGeneration||!token)return;
  saved=true;findingsRevision++;feedbackRevision++;feedbackRequest++;feedbackLoading=false;feedbackError='';
  const index=feedbackRows.findIndex(item=>feedbackKey(item)===key);
  if(index<0)feedbackRows.unshift(record);else feedbackRows[index]=record;
  results=results.map(row=>{
   if(row.region!==f.region)return row;
   const items=(row.findings||[]).flatMap(item=>item.finding_id!==f.finding_id?[item]:record.kept||record.ignore_until>Date.now()/1000?[]:[{...item,acknowledged:record.acknowledged===true}]);
   return {...row,findings:items};
  });
  operation.pending=false;operation.message=feedbackSaveMessage(record,patch);
  render();status(operation.message);
  const confirmed=await refresh();
  if(generation!==scopeGeneration||!token||feedbackState.get(key)!==operation)return;
  operation.message=feedbackSaveMessage(record,patch,confirmed===true&&!resultsError);
  renderFeedback();status(operation.message);
  if(!feedbackLoaded&&!$('page-findings').hidden)loadFeedback();
 }catch(error){
  if(generation!==scopeGeneration||!token||feedbackState.get(key)!==operation)return;
  operation.pending=false;operation.error=true;operation.message=saved?'Phản hồi đã lưu, nhưng chưa tải được kết quả mới.':'Chưa lưu được phản hồi. '+friendlyError(error.message);
  render();status(operation.message,true);
 }
}

async function loadFeedback(more=false){
 if(!profile)return;
 const generation=scopeGeneration,revision=feedbackRevision,request=++feedbackRequest,cursor=more?feedbackCursor:null;
 if(more&&!cursor)return;
 feedbackLoading=true;if(!more)feedbackError='';renderFeedback();
 try{
  const query=new URLSearchParams({limit:'20'});if(cursor)query.set('next_token',cursor);
  const reply=await api('/feedback?'+query);
  if(generation!==scopeGeneration||revision!==feedbackRevision||request!==feedbackRequest||!token)return;
  if(!Array.isArray(reply.results)||(reply.next_token!=null&&typeof reply.next_token!=='string'))throw Error('Phản hồi danh sách không hợp lệ.');
  const rows=reply.results.filter(item=>typeof item.finding_id==='string'&&(profile.regions||[]).includes(item.region));
  feedbackRows=[...new Map([...(more?feedbackRows:[]),...rows].map(item=>[feedbackKey(item),item])).values()];
  feedbackCursor=reply.next_token||null;feedbackLoaded=true;
 }catch(error){
  if(generation!==scopeGeneration||revision!==feedbackRevision||request!==feedbackRequest||!token)return;
  feedbackError='Không tải được phản hồi. '+friendlyError(error.message);
 }finally{
  if(generation===scopeGeneration&&request===feedbackRequest){feedbackLoading=false;renderFeedback();}
 }
}
function renderFeedback(){
 const list=$('feedback-list'),previous=feedbackFocus(list),pageControl=document.activeElement,active=feedbackRows.filter(feedbackHidden);list.replaceChildren();
 $('feedback-summary').textContent=feedbackError||(feedbackLoading?'Đang tải phản hồi…':active.length+' finding đang giữ hoặc bỏ qua trong '+feedbackRows.length+' phản hồi đã tải.'+(feedbackCursor?' Còn phản hồi ở trang sau.':''));
 $('feedback-summary').className=feedbackError?'error':'muted';$('refresh-feedback').disabled=feedbackLoading;
 $('feedback-load-more').hidden=!feedbackCursor;$('feedback-load-more').disabled=feedbackLoading;$('feedback-load-more').textContent=feedbackLoading?'Đang tải…':'Tải thêm';
 if([$('refresh-feedback'),$('feedback-load-more')].includes(pageControl)&&(pageControl.disabled||pageControl.hidden))$('feedback-summary').focus();
 if(!active.length)emptyState(list,feedbackLoading?'Đang tải danh sách':feedbackCursor?'Chưa có finding đang ẩn trong phần đã tải':feedbackLoaded?'Không có finding đang giữ hoặc bỏ qua trong danh sách đã tải':'Chưa tải phản hồi',feedbackCursor?'Chọn Tải thêm để kiểm tra trang tiếp theo.':'Chọn Tải lại để cập nhật phản hồi của kết nối hiện tại.');
 for(const record of active){
  const key=feedbackKey(record),generation=scopeGeneration,state=feedbackState.get(key),article=node('article',undefined,'feedback-record'),info=node('div'),actions=node('div',undefined,'finding-feedback feedback-manager-actions');article.dataset.feedbackKey=key;actions.dataset.feedbackKey=key;
  info.append(node('h3',record.type||'Finding cũ'),node('code',record.resource_id||record.finding_id),node('p','Region: '+record.region,'muted'));
  if(record.resource_id)info.append(node('small','Finding ID: '+record.finding_id,'muted'));else info.append(node('p','Feedback cũ thiếu metadata; quản lý bằng Finding ID và region.','footnote'));
  info.append(node('p','Account: '+(record.account_id||'Chưa có dữ liệu')+' · Rule: '+(record.rule_id||'Chưa có dữ liệu'),'muted'));
  if(record.kept)info.append(badge('KEPT'));
  if(record.ignore_until>Date.now()/1000)info.append(node('p','Bỏ qua đến: '+date(record.ignore_until),'muted'));
  if(record.acknowledged)info.append(node('p','Đã xem','acknowledged-state'));
  const unkeep=node('button','Bỏ giữ','button secondary feedback-unkeep'),unignore=node('button','Hủy bỏ qua','button secondary feedback-unignore'),label=node('label','Hạn bỏ qua mới'),days=node('select',undefined,'feedback-manage-days'),extend=node('button','Đổi hạn bỏ qua','button secondary feedback-extend');
  if(!managedDays.has(key))managedDays.set(key,7);for(let day=1;day<=30;day++)days.append(new Option(day+' ngày',day));days.value=managedDays.get(key);days.setAttribute('aria-label','Hạn bỏ qua mới cho '+(record.resource_id||record.finding_id));label.append(days);days.onchange=()=>managedDays.set(key,Number(days.value));
  unkeep.disabled=!record.kept||!!state?.pending;unignore.disabled=!(record.ignore_until>Date.now()/1000)||!!state?.pending;days.disabled=extend.disabled=!!state?.pending;
  unkeep.onclick=()=>saveFindingFeedback(record,{kept:false},generation,true);unignore.onclick=()=>saveFindingFeedback(record,{ignoreUntil:null},generation,true);extend.onclick=()=>{const count=Number(days.value);if(Number.isInteger(count)&&count>=1&&count<=30)saveFindingFeedback(record,{ignoreUntil:new Date(Date.now()+count*86400000).toISOString()},generation,true);};
  for(const button of [unkeep,unignore,extend])button.type='button';
  const note=node('p',state?.message||'','feedback-status'+(state?.error?' error':''));note.setAttribute('role','status');note.tabIndex=-1;
  actions.append(unkeep,unignore,label,extend,note);article.append(info,actions);list.append(article);
 }
 restoreFeedbackFocus(list,previous);
}
function findingFeedback(f){
 const key=feedbackKey(f),generation=scopeGeneration,state=feedbackState.get(key),group=node('div',undefined,'finding-feedback');group.dataset.feedbackKey=key;
 const valid=typeof f.finding_id==='string'&&/^[a-f0-9]{64}$/.test(f.finding_id)&&(profile.regions||[]).includes(f.region);
 const ack=node('button',f.acknowledged?'Bỏ đã xem':'Đánh dấu đã xem','button secondary feedback-ack'),keep=node('button','Giữ lại','button secondary feedback-keep'),label=node('label','Bỏ qua trong'),days=node('select',undefined,'feedback-days'),ignore=node('button',undefined,'button secondary feedback-ignore');
 if(!feedbackDays.has(key))feedbackDays.set(key,7);
 for(let day=1;day<=30;day++)days.append(new Option(day+' ngày',day));days.value=feedbackDays.get(key);days.setAttribute('aria-label','Thời hạn bỏ qua cho '+f.resource_id);label.append(days);
 ignore.textContent='Bỏ qua '+days.value+' ngày';
 days.onchange=()=>{feedbackDays.set(key,Number(days.value));for(const other of document.querySelectorAll('.finding-feedback:not(.feedback-manager-actions)'))if(other.dataset.feedbackKey===key){other.querySelector('.feedback-days').value=days.value;other.querySelector('.feedback-ignore').textContent='Bỏ qua '+days.value+' ngày';}};
 ack.onclick=()=>saveFindingFeedback(f,{acknowledged:!f.acknowledged},generation);keep.onclick=()=>saveFindingFeedback(f,{kept:true},generation);
 ignore.onclick=()=>{const count=Number(days.value);if(!Number.isInteger(count)||count<1||count>30)return;saveFindingFeedback(f,{ignoreUntil:new Date(Date.now()+count*86400000).toISOString()},generation);};
 for(const button of [ack,keep,ignore])button.type='button';
 for(const control of [ack,keep,ignore,days])control.disabled=!valid||!!state?.pending;
 const note=node('p',!valid?'Cảnh báo cũ thiếu mã hợp lệ; cần quét mới để phản hồi.':state?.message||'','feedback-status'+(state?.error?' error':''));note.setAttribute('role','status');note.tabIndex=-1;
 group.append(ack,keep,label,ignore,note);return group;
}

function renderTable(container,items,allowIgnore=true){
 const previous=feedbackFocus(container);container.replaceChildren();
 if(!items.length){container.append(node('div','Không có tài nguyên phù hợp.','empty'));restoreFeedbackFocus(container,previous);return;}
 const wrap=node('div',undefined,'table-wrap'),table=node('table',undefined,'finding-table'+(allowIgnore?' with-actions':'')),thead=node('thead'),tr=node('tr');
 for(const h of ['Tài nguyên','Trạng thái & lý do','Bằng chứng',...(allowIgnore?['Thao tác']:[])]){
  const th=node('th',h);th.scope='col';tr.append(th);
 }
 thead.append(tr);table.append(thead);
 const body=node('tbody');
 for(const f of items){
  const row=node('tr'),resource=node('td');
  resource.append(node('div',f.type,'resource-type'),node('code',f.resource_id),node('small',f.region));
  const detail=node('td');
  detail.append(badge(f.level),node('p',reasons[f.reason]||f.reason));
  if(allowIgnore)detail.append(node('small',f.acknowledged?'Đã xem':'Chưa xem','acknowledged-state'));
  const proof=node('td',undefined,'evidence'),open=node('button','Xem chi tiết','text-button finding-open');
  open.type='button';open.dataset.findingId=f.finding_id??'';open.dataset.region=f.region??'';open.dataset.resourceId=f.resource_id??'';
  open.setAttribute('aria-label','Xem chi tiết '+f.resource_id);
  open.onclick=()=>openFindingDetail(f,!allowIgnore,open);
  proof.append(node('div',evidence(f)),open);
  row.append(resource,detail,proof);
  if(allowIgnore){
   const td=node('td');td.append(findingFeedback(f));row.append(td);
  }
  [...row.children].forEach((td,i)=>td.dataset.label=['Tài nguyên','Trạng thái & lý do','Bằng chứng','Thao tác'][i]);
  body.append(row);
 }
 table.append(body);wrap.append(table);container.append(wrap);
 restoreFeedbackFocus(container,previous);
}

function renderFindings(){
 const q=$('search').value.trim().toLowerCase(),type=$('filter-type').value,level=$('filter-level').value,group=$('filter-group').value,region=$('filter-region').value,ack=$('filter-acknowledged').value;
 const all=findings(),filtered=all.filter(f=>(!type||f.type===type)&&(!level||f.level===level)&&(!group||resourceGroups[f.type]===group)&&(!region||f.region===region)&&(!ack||(ack==='acknowledged'?f.acknowledged===true:f.acknowledged!==true))&&[f.resource_id,f.reason,reasons[f.reason]||''].some(s=>String(s||'').toLowerCase().includes(q)));
 const active=Boolean(q||type||level||group||region||ack),incomplete=loadingResults||resultsError||results.some(r=>['QUEUED','RUNNING','PARTIAL','FAILED','TIMED_OUT'].includes(r.status));
 $('findings-scope').textContent=filtered.length+' / '+all.length+' tài nguyên trong kết quả.'+(incomplete?' '+resultMessage():'');
 renderTable($('findings-list'),filtered);
 if(!filtered.length)emptyState($('findings-list'),active?'Không khớp bộ lọc':'Chưa có cảnh báo để hiển thị',active?'Thử xóa từ khóa hoặc chọn Tất cả.':resultMessage());
}

function render(){
 const fs=findings(),measured=results.some(r=>Object.keys(r.counts||{}).length>0&&['SUCCEEDED','PARTIAL'].includes(r.status));
 const busy=scanPending||results.some(r=>['QUEUED','RUNNING'].includes(r.status));
 $('total').textContent=measured?results.reduce((sum,r)=>sum+Object.values(r.counts||{}).reduce((a,b)=>a+b,0),0):'—';
 for(const [id,level] of [['review','REVIEW'],['observing','OBSERVING'],['insufficient','INSUFFICIENT_DATA']])$(id).textContent=measured?fs.filter(f=>f.level===level).length:'—';
 $('nav-count').textContent=measured?fs.filter(f=>f.level==='REVIEW').length:'—';
 $('account-name').textContent=profile.account_id||'Chưa kết nối AWS';
 $('account-regions').textContent=(profile.regions||[]).join(' / ');
 $('account-service-groups').textContent='Nhóm: '+(profile.service_groups||Object.keys(serviceGroups)).map(group=>serviceGroups[group]?.label||group).join(' / ');
 $('account-badge').textContent=profile.role_arn?'Đã kết nối':'Chưa kết nối';
 $('account-badge').className='badge '+(profile.role_arn?'good':'');
 for(const id of ['scan','first-scan']){$(id).disabled=!profile.role_arn||busy;$(id).textContent=busy?'Đang quét…':'Quét ngay';}
 $('first-scan-note').textContent=!profile.role_arn?'Lưu kết nối ở bước 2 để bắt đầu quét.':busy?'Đang thực hiện quét tài nguyên.':'Chọn Quét ngay để bắt đầu.';
 const panel=$('overview-state');panel.replaceChildren();panel.className='state-panel';
 const bad=results.some(r=>['FAILED','TIMED_OUT'].includes(r.status)),partial=results.some(r=>r.status==='PARTIAL');
 const title=loadingResults?'Đang tải kết quả':resultsError?'Không tải được kết quả':!profile.role_arn?'Chưa kết nối AWS':busy?'Đang quét tài nguyên':!results.length?'Sẵn sàng quét':bad?'Có region quét lỗi':partial?'Kết quả chưa đầy đủ':'Kết quả hoàn tất';
 if(bad||resultsError)panel.classList.add('error');else if(partial)panel.classList.add('warning');
 panel.append(node('h2',title),node('p',resultMessage()));
 if(!profile.role_arn){const b=node('button','Kết nối AWS','button primary');b.onclick=()=>navigate('connection');panel.append(b);}
 $('scan-summary').replaceChildren();
 if(!results.length)$('scan-summary').append(node('p',resultMessage(),'muted'));
 for(const r of results){
  const div=node('div',undefined,'scan-row');div.append(node('span',r.region),badge(r.status));
  $('scan-summary').append(div,node('small',date(r.completed_at||r.started_at),'muted'));
  appendResultNotes($('scan-summary'),r);
 }
 renderTable($('priority-list'),fs.filter(f=>f.level==='REVIEW').slice(0,5));
 if(!fs.some(f=>f.level==='REVIEW'))emptyState($('priority-list'),'Không có tài nguyên cần kiểm tra',resultMessage());
 renderFindings();renderFeedback();
}

async function refresh(){
 const generation=scopeGeneration,revision=findingsRevision;
 try{
  const reply=await api('/findings');if(generation!==scopeGeneration||revision!==findingsRevision)return false;
  results=reply.results;resultsError=false;loadingResults=false;render();
  if(results.some(r=>['QUEUED','RUNNING'].includes(r.status))&&pollCount<185){
   clearTimeout(pollTimer);pollTimer=setTimeout(()=>{pollCount++;run(refresh);},5000);
  }else clearTimeout(pollTimer);
  return true;
 }catch(e){
  if(generation!==scopeGeneration||revision!==findingsRevision)return false;
  loadingResults=false;resultsError=true;clearTimeout(pollTimer);render();throw e;
 }
}

function historyKey(row){return JSON.stringify(row.scan_id?[row.scan_id,row.region]:[null,row.region,row.created_at??null,row.started_at??null,row.completed_at??null]);}
function historyTrigger(value){return {manual:'Thủ công',scheduled:'Theo lịch'}[value]||detailValue(value);}
function validHistoryRows(rows){return rows.filter(row=>row&&typeof row.region==='string'&&(profile.regions||[]).includes(row.region));}
function mergeHistoryRows(oldRows,newRows){const rows=new Map(oldRows.map(row=>[historyKey(row),row]));for(const row of newRows)rows.set(historyKey(row),row);return [...rows.values()];}

function renderHistory(){
 const c=$('history-list');c.replaceChildren();
 $('refresh-history').disabled=historyLoading;$('history-load-more').hidden=!historyCursor;$('history-load-more').disabled=historyLoading;
 $('history-load-more').textContent=historyLoading?'Đang tải…':'Tải thêm';
 const summary=$('history-summary');summary.className=historyError?'error':'muted';
 summary.textContent=historyError?historyError:historyLoading?'Đang tải lịch sử…':historyRows.length+' kết quả đã tải.';
 if(!historyRows.length){
  emptyState(c,historyError?'Không tải được lịch sử':historyLoading?'Đang tải lịch sử…':'Chưa có lịch sử quét','Lịch sử lưu kết quả tối đa 30 ngày cho kết nối hiện tại.');
  return;
 }
 const wrap=node('div',undefined,'table-wrap'),table=node('table',undefined,'history-table'),thead=node('thead'),tr=node('tr');
 for(const h of ['Thời gian','Region','Trạng thái','Chi tiết']){const th=node('th',h);th.scope='col';tr.append(th);}
 thead.append(tr);table.append(thead);
 const body=node('tbody');
 for(const row of historyRows){
  const tr=node('tr');
  tr.append(node('td',date(row.completed_at||row.started_at)),node('td',row.region),node('td',badge(row.status)));
  const action=node('td'),btn=node('button','Xem','button secondary history-open');
  btn.type='button';btn.onclick=()=>openHistoryScan(row);action.append(btn);tr.append(action);body.append(tr);
 }
 table.append(body);wrap.append(table);c.append(wrap);
}

async function loadHistory(more=false){
 if(!profile)return;
 const generation=scopeGeneration,request=++historyRequest,cursor=more?historyCursor:null;
 if(more&&!cursor)return;
 historyLoading=true;if(!more)historyError='';renderHistory();
 try{
  const query=new URLSearchParams({limit:'20'});if(cursor)query.set('next_token',cursor);
  const reply=await api('/history?'+query);if(generation!==scopeGeneration||request!==historyRequest)return;
  if(!Array.isArray(reply.results)||(reply.next_token!=null&&typeof reply.next_token!=='string'))throw Error('Máy chủ trả lịch sử không hợp lệ.');
  historyRows=mergeHistoryRows(more?historyRows:[],validHistoryRows(reply.results));historyCursor=reply.next_token||null;
 }catch(e){
  if(generation!==scopeGeneration||request!==historyRequest)return;
  historyError='Không tải được lịch sử. '+friendlyError(e.message);
 }finally{
  if(generation===scopeGeneration&&request===historyRequest){historyLoading=false;renderHistory();}
 }
}

function renderHistoryDetail(){
 const detail=$('history-detail');detail.replaceChildren();
 if(!historySelection)return;
 detail.append(node('h3','Chi tiết lượt quét'),node('p','Scan ID: '+detailValue(historySelection.scan_id),'muted'));
 if(historyDetailLoading)detail.append(node('p','Đang tải…','muted'));
 if(historyDetailError){
  const msg=node('p',historyDetailError,'error'),retry=node('button','Thử lại','button secondary');
  retry.onclick=()=>loadHistoryScan();detail.append(msg,retry);
 }
 for(const r of historyDetailRows){
  const section=node('section',undefined,'history-region');
  section.append(node('h3',r.region),badge(r.status));
  detailSection(section,'Thông tin',[
   ['scan_id','Scan ID',r.scan_id],['trigger','Kích hoạt',historyTrigger(r.trigger)],['region','Region',r.region],['account_id','AWS account',r.account_id],
   ['started_at','Bắt đầu',r.started_at==null?undefined:date(r.started_at)],['completed_at','Kết thúc',r.completed_at==null?undefined:date(r.completed_at)]
  ]);
  const content=node('div');renderTable(content,(r.findings||[]).map(f=>({...f,region:r.region})),false);
  section.append(content);detail.append(section);
 }
}

function openHistoryScan(row){
 closeFindingDetail();historySelection=row;historyDetailRequest++;historyDetailError='';historyDetailLoading=false;
 historyDetailRows=row.scan_id?historyRows.filter(item=>item.scan_id===row.scan_id):[row];
 renderHistoryDetail();$('history-detail').focus();if(row.scan_id)loadHistoryScan();
}

async function loadHistoryScan(){
 const selected=historySelection;if(!selected?.scan_id)return;const generation=scopeGeneration,request=++historyDetailRequest;
 historyDetailLoading=true;historyDetailError='';renderHistoryDetail();
 try{
  const reply=await api('/scans/'+encodeURIComponent(selected.scan_id));if(generation!==scopeGeneration||request!==historyDetailRequest)return;
  if(!Array.isArray(reply.results))throw Error('Máy chủ trả chi tiết không hợp lệ.');
  const rows=validHistoryRows(reply.results).filter(row=>row.scan_id===selected.scan_id);
  historyDetailRows=mergeHistoryRows(historyDetailRows,rows);
 }catch(e){
  if(generation!==scopeGeneration||request!==historyDetailRequest)return;
  historyDetailError='Chưa tải đủ chi tiết. '+friendlyError(e.message);
 }finally{
  if(generation===scopeGeneration&&request===historyDetailRequest){historyDetailLoading=false;renderHistoryDetail();}
 }
}

function createFieldElement(key,meta,currentValue){
 const fMeta=friendlyFieldMeta[key]||{};
 const labelText=fMeta.label||meta.label||key;
 const unitText=fMeta.unit||meta.unit||'';
 const rangeText='Trong khoảng '+meta.min+'–'+meta.max+(unitText?' '+unitText:'');
 const wrap=node('div',undefined,'field-wrap');
 const label=node('label',undefined,'field-label');
 label.htmlFor=key;label.append(node('span',labelText));wrap.append(label);
 const inputWrap=node('div',undefined,'field-input-wrap');
 const input=node('input',undefined,'field-input');
 input.id=key;input.type='number';input.required=true;input.min=meta.min;input.max=meta.max;
 input.step=meta.integer?1:'any';input.value=currentValue??meta.default;input.title=rangeText;
 input.setAttribute('aria-label',labelText);
 input.oninput=()=>{
  const unsaved=$('unsaved-indicator');if(unsaved)unsaved.hidden=false;
  const err=wrap.querySelector('.field-help-error');if(err)err.remove();
 };
 input.oninvalid=()=>{
  let err=wrap.querySelector('.field-help-error');
  if(!err){err=node('small',rangeText,'field-help-error');wrap.append(err);}
 };
 inputWrap.append(input);
 if(unitText)inputWrap.append(node('span',unitText,'field-unit-badge'));
 wrap.append(inputWrap);
 return wrap;
}

function renderSettingsUI(){
 const activeThresholds=profile.threshold_metadata||defaultThresholdConfig;
 const groupsContainer=$('settings-groups');
 if(groupsContainer){
  groupsContainer.replaceChildren();
  serviceHierarchy.forEach((hierarchyGroup,idx)=>{
   const details=node('details',undefined,'settings-group');
   if(idx===0)details.open=true;
   const summary=node('summary');
   const titleSpan=node('span',hierarchyGroup.title,'group-title');
   const totalFields=hierarchyGroup.services.reduce((acc,s)=>acc+s.fields.length,0);
   const countBadge=node('span',totalFields+' cài đặt','group-badge');
   summary.append(titleSpan,countBadge);
   details.append(summary);
   const body=node('div',undefined,'settings-group-body');
   hierarchyGroup.services.forEach(service=>{
    const card=node('div',undefined,'service-card');
    card.append(node('h4',service.name,'service-card-title'));
    const grid=node('div',undefined,'service-grid');
    service.fields.forEach(fieldKey=>{
     const meta=activeThresholds[fieldKey];
     if(meta)grid.append(createFieldElement(fieldKey,meta,profile.settings[fieldKey]));
    });
    card.append(grid);
    body.append(card);
   });
   details.append(body);
   groupsContainer.append(details);
  });
 }
 const restoreBtn=$('restore-defaults');
 if(restoreBtn){
  restoreBtn.onclick=()=>{
   for(const [k,meta] of Object.entries(activeThresholds)){
    const el=$(k);if(el)el.value=meta.default;
   }
   const unsaved=$('unsaved-indicator');if(unsaved)unsaved.hidden=false;
   status('Đã khôi phục các giá trị mặc định.');
  };
 }
}

async function init(){
 closeFindingDetail();
 const generation=++scopeGeneration;
 historyRows=[];historyCursor=null;historyLoading=false;historyError='';historyRequest++;historyDetailRequest++;historySelection=null;historyDetailRows=[];historyDetailLoading=false;historyDetailError='';
 feedbackState.clear();feedbackDays.clear();managedDays.clear();feedbackRows=[];feedbackCursor=null;feedbackLoaded=false;feedbackLoading=false;feedbackError='';feedbackRequest++;feedbackRevision=0;findingsRevision=0;
 clearTimeout(pollTimer);
 const nextProfile=await api('/me');if(generation!==scopeGeneration)return;profile=nextProfile;
 $('history-list').replaceChildren();$('history-detail').replaceChildren();$('history-summary').textContent='';$('history-load-more').hidden=true;$('refresh-history').disabled=false;
 $('app').hidden=false;$('welcome').hidden=true;$('nav-auth').hidden=false;$('nav-guest').hidden=true;
 $('login').textContent='Đăng xuất';$('login').onclick=logout;$('nav-logout').onclick=logout;
 renderPrincipals();$('role').value=profile.role_arn||'';
 $('region-options').replaceChildren();
 for(const r of regions){
  const l=node('label'),i=node('input');i.type='checkbox';i.value=r;i.checked=(profile.regions||['ap-southeast-1']).includes(r);
  const text=node('span',regionNames[r]||r);text.append(node('small',r));l.append(i,text);$('region-options').append(l);
 }
 $('service-group-options').replaceChildren();
 for(const [group,value] of Object.entries(serviceGroups)){
  const l=node('label'),i=node('input');i.type='checkbox';i.value=group;i.checked=(profile.service_groups||Object.keys(serviceGroups)).includes(group);
  const text=node('span',value.label);text.append(node('small',value.types.join(' / ')));l.append(i,text);$('service-group-options').append(l);
 }
 $('filter-type').replaceChildren(new Option('Tất cả',''),...Object.keys(resourceGroups).map(type=>new Option(type,type)));
 $('filter-group').replaceChildren(new Option('Tất cả',''),...Object.entries(serviceGroups).map(([group,value])=>new Option(value.label,group)));
 $('filter-region').replaceChildren(new Option('Tất cả',''),...(profile.regions||[]).map(region=>new Option((regionNames[region]||region)+' — '+region,region)));
 for(const id of ['search','filter-level','filter-acknowledged'])$(id).value='';
 renderSettingsUI();
 $('email-enabled').checked=!!profile.notifications?.enabled;$('email-enabled').disabled=!profile.email_available;$('save-email').disabled=!profile.email_available;
 $('email-note').textContent=profile.email_available?(profile.notifications?.email?'Địa chỉ: '+profile.notifications.email:'Dùng email Cognito đã xác minh.'):'Cảnh báo email chưa được bật.';
 loadingResults=true;results=[];resultsError=false;render();showPage(location.hash.slice(1)||'overview');
 await refresh();if(generation!==scopeGeneration)return;status(cfg.demo?'Bản demo với dữ liệu mẫu.':'');
}

function navigate(page){if(location.hash.slice(1)===page)showPage(page);else location.hash=page;}

document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));
window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));
for(const id of ['search','filter-type','filter-level','filter-group','filter-region','filter-acknowledged'])$(id).addEventListener('input',renderFindings);

$('connection-form').onsubmit=e=>{
 e.preventDefault();
 run(async()=>{
  let saved=false;const feedback=$('connection-feedback');feedback.hidden=false;feedback.className='';feedback.textContent='Đang kiểm tra AWS…';$('connect').textContent='Đang kiểm tra…';
  try{
   const selected=[...document.querySelectorAll('#region-options input:checked')].map(i=>i.value);
   if(selected.length<1||selected.length>3)throw Error('Chọn từ 1 đến 3 region.');
   const groups=[...document.querySelectorAll('#service-group-options input:checked')].map(i=>i.value);
   if(groups.length<1)throw Error('Chọn ít nhất 1 nhóm dịch vụ.');
   const arn=$('role').value.trim();
   if(!/^arn:aws:iam::\d{12}:role\/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}$/.test(arn))throw Error('Nhập RoleArn hợp lệ: arn:aws:iam::123456789012:role/GuardianReadRole-<suffix>.');
   await api('/connection','PUT',{role_arn:arn,regions:selected,service_groups:groups});
   saved=true;await init();
   feedback.textContent='Đã lưu kết nối AWS.';status('Đã lưu kết nối AWS.');
  }catch(e){
   feedback.className='error';feedback.textContent=(saved?'Kết nối đã lưu nhưng chưa tải được dữ liệu mới. ':'')+friendlyError(e.message);throw e;
  }finally{$('connect').textContent='Kiểm tra và lưu kết nối';}
 },$('connect'));
};

$('settings-form').onsubmit=e=>{
 e.preventDefault();
 run(async()=>{
  const saveBtn=$('save-settings');saveBtn.textContent='Đang lưu…';
  const v={};const activeThresholds=profile.threshold_metadata||defaultThresholdConfig;
  for(const [k,meta] of Object.entries(activeThresholds)){
   const el=$(k);if(!el)continue;
   const value=el.valueAsNumber;
   const fMeta=friendlyFieldMeta[k]||{};
   const label=fMeta.label||meta.label||k;
   if(!Number.isFinite(value)||value<meta.min||value>meta.max||(meta.integer&&!Number.isInteger(value))){
    el.focus();
    throw Error('Vui lòng nhập giá trị hợp lệ từ '+meta.min+' đến '+meta.max+(meta.unit?' ('+meta.unit+')':'')+' cho '+label+'.');
   }
   v[k]=value;
  }
  profile.settings=await api('/settings','PUT',v);
  $('unsaved-indicator').hidden=true;
  status('Đã lưu ngưỡng phát hiện.');
 },$('save-settings'));
};

$('save-email').onclick=()=>run(async()=>{
 profile.notifications=await api('/notifications','PUT',{enabled:$('email-enabled').checked});
 $('email-note').textContent=profile.notifications.enabled?'Địa chỉ: '+profile.notifications.email:'Đã tắt cảnh báo email.';
 status('Đã lưu lựa chọn email.');
},$('save-email'));

$('scan').onclick=()=>run(async()=>{
 scanPending=true;render();
 try{
  const r=await api('/scans','POST');sessionStorage.setItem('crg-last-scan',r.scan_id);pollCount=0;
  status('Đã nhận yêu cầu quét. Đang cập nhật kết quả…');await refresh();
 }finally{scanPending=false;render();}
},$('scan'));

$('first-scan').onclick=()=>{navigate('overview');$('scan').click();};
$('refresh').onclick=()=>run(async()=>{pollCount=0;await refresh();status('Đã tải lại kết quả.');},$('refresh'));
$('refresh-history').onclick=()=>loadHistory();$('history-load-more').onclick=()=>loadHistory(true);
$('refresh-feedback').onclick=()=>loadFeedback();$('feedback-load-more').onclick=()=>loadFeedback(true);
$('start').onclick=()=>run(login,$('start'));
$('close-finding-detail').onclick=()=>$('finding-dialog').close();
$('finding-dialog').onclose=restoreFindingFocus;

$('register-form').onsubmit=e=>{
 e.preventDefault();
 const email=$('reg-email').value.trim();
 const password=$('reg-password').value;
 const confirm=$('reg-confirm').value;
 const feedback=$('reg-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){
  feedback.className='inline-feedback error';
  feedback.textContent='Định dạng email không hợp lệ.';
  return;
 }
 const pwErr=validatePassword(password);
 if(pwErr){
  feedback.className='inline-feedback error';
  feedback.textContent=pwErr;
  return;
 }
 if(password!==confirm){
  feedback.className='inline-feedback error';
  feedback.textContent='Mật khẩu xác nhận không khớp.';
  return;
 }
 run(async()=>{
  $('reg-password').value='';$('reg-confirm').value='';
  if(cfg?.demo){
   demoAuth.pending.set(email,'123456');
   $('verify-email').value=email;
   $('verify-info').textContent='Mã xác minh đã được gửi tới email '+email+'. (Demo: nhập 123456)';
   showGuestView('verify');
   status('Đăng ký thành công! Nhập mã xác minh để kích hoạt tài khoản.');
   return;
  }
  await cognitoIdp('SignUp',{
   ClientId:cfg?.clientId,
   Username:email,
   Password:password,
   UserAttributes:[{Name:'email',Value:email}]
  });
  $('verify-email').value=email;
  $('verify-info').textContent='Mã xác minh đã được gửi tới email '+email+'.';
  showGuestView('verify');
 },$('reg-submit'));
 return false;
};

$('verify-form').onsubmit=e=>{
 e.preventDefault();
 const email=$('verify-email').value.trim();
 const code=$('verify-code').value.trim();
 const feedback=$('verify-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!code){
  feedback.className='inline-feedback error';
  feedback.textContent='Vui lòng nhập mã xác minh.';
  return;
 }
 run(async()=>{
  if(cfg?.demo){
   const expected=demoAuth.pending.get(email)||'123456';
   if(code!==expected){
    throw Error('Mã xác minh không chính xác.');
   }
   demoAuth.pending.delete(email);
   demoAuth.verified.add(email);
   showGuestView('login');
   status('Xác minh tài khoản thành công! Bạn có thể đăng nhập.');
   return;
  }
  await cognitoIdp('ConfirmSignUp',{
   ClientId:cfg?.clientId,
   Username:email,
   ConfirmationCode:code
  });
  showGuestView('login');
  status('Xác minh tài khoản thành công! Bạn có thể đăng nhập.');
 },$('verify-submit'));
 return false;
};

$('verify-resend').onclick=()=>{
 const email=$('verify-email').value.trim();
 if(!email){status('Thiếu email để gửi lại mã.',true);return;}
 run(async()=>{
  if(cfg?.demo){
   status('Đã gửi lại mã xác minh tới '+email+'. (Demo: 123456)');
   return;
  }
  await cognitoIdp('ResendConfirmationCode',{
   ClientId:cfg?.clientId,
   Username:email
  });
  status('Đã gửi lại mã xác minh tới '+email+'.');
 },$('verify-resend'));
};

$('forgot-form').onsubmit=e=>{
 e.preventDefault();
 const email=$('forgot-email').value.trim();
 const feedback=$('forgot-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){
  feedback.className='inline-feedback error';
  feedback.textContent='Định dạng email không hợp lệ.';
  return;
 }
 run(async()=>{
  if(cfg?.demo){
   demoAuth.resetCodes.set(email,'123456');
   $('reset-email').value=email;
   showGuestView('reset');
   status('Mã đặt lại mật khẩu đã được gửi tới '+email+'. (Demo: 123456)');
   return;
  }
  await cognitoIdp('ForgotPassword',{
   ClientId:cfg?.clientId,
   Username:email
  });
  $('reset-email').value=email;
  showGuestView('reset');
  status('Mã đặt lại mật khẩu đã được gửi tới email của bạn.');
 },$('forgot-submit'));
 return false;
};

$('reset-form').onsubmit=e=>{
 e.preventDefault();
 const email=$('reset-email').value.trim();
 const code=$('reset-code').value.trim();
 const password=$('reset-password').value;
 const confirm=$('reset-confirm').value;
 const feedback=$('reset-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){
  feedback.className='inline-feedback error';
  feedback.textContent='Định dạng email không hợp lệ.';
  return;
 }
 if(!code){
  feedback.className='inline-feedback error';
  feedback.textContent='Vui lòng nhập mã xác minh.';
  return;
 }
 const pwErr=validatePassword(password);
 if(pwErr){
  feedback.className='inline-feedback error';
  feedback.textContent=pwErr;
  return;
 }
 if(password!==confirm){
  feedback.className='inline-feedback error';
  feedback.textContent='Mật khẩu xác nhận không khớp.';
  return;
 }
 run(async()=>{
  $('reset-password').value='';$('reset-confirm').value='';
  if(cfg?.demo){
   const expected=demoAuth.resetCodes.get(email)||'123456';
   if(code!==expected){
    throw Error('Mã xác minh không chính xác.');
   }
   demoAuth.resetCodes.delete(email);
   showGuestView('login');
   status('Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới.');
   return;
  }
  await cognitoIdp('ConfirmForgotPassword',{
   ClientId:cfg?.clientId,
   Username:email,
   ConfirmationCode:code,
   Password:password
  });
  showGuestView('login');
  status('Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới.');
 },$('reset-submit'));
 return false;
};

document.querySelectorAll('.btn-toggle-pw').forEach(btn=>{
 btn.onclick=()=>{
  const targetId=btn.dataset.for;
  const input=$(targetId);
  if(!input)return;
  const isPw=input.type==='password';
  input.type=isPw?'text':'password';
  btn.textContent=isPw?'Ẩn':'Hiện';
 };
});

document.querySelectorAll('[data-guest]').forEach(b=>{
 b.onclick=()=>showGuestView(b.dataset.guest);
});
document.querySelectorAll('[data-switch]').forEach(b=>{
 b.onclick=()=>showGuestView(b.dataset.switch);
});

const regionNames={'ap-southeast-1':'Singapore','ap-southeast-2':'Sydney','ap-northeast-1':'Tokyo','us-east-1':'N. Virginia','us-west-2':'Oregon','eu-west-1':'Ireland'};
function friendlyError(message){
 const translations={
  'Wait 15 minutes between scans':'Chưa đủ 15 phút từ lần quét trước.',
  'Scan lease is active':'Một lần quét đang được xử lý.',
  'AWS request failed; check role permissions and CloudWatch logs':'AWS từ chối hoặc chưa xử lý được yêu cầu. Kiểm tra quyền IAM role.',
  'Cannot access AWS; reconnect and check role permissions':'Không truy cập được AWS. Kiểm tra lại role.',
  'Scan did not complete within 15 minutes. Check Lambda failure queue and retry.':'Quét chưa hoàn tất sau 15 phút.',
  'Dispatch failed; try another scan later':'Chưa gửi được yêu cầu quét tới bộ xử lý.',
  'Failed to fetch':'Không kết nối được máy chủ.',
  'Access token required':'Phiên đăng nhập đã hết hạn.',
  'Unauthorized':'Phiên đăng nhập đã hết hạn.'
 };
 return translations[message]||message;
}

function emptyState(container,title,description){
 container.replaceChildren();
 const e=node('div',undefined,'empty');
 e.append(node('strong',title),node('p',description));
 container.append(e);
}

function resultMessage(){
 if(loadingResults)return 'Đang tải kết quả…';
 if(resultsError)return 'Không tải được kết quả. Chọn Tải lại để thử lại.';
 if(!profile?.role_arn)return 'Tạo role chỉ đọc theo hướng dẫn, xác minh kết nối rồi chạy lần quét đầu tiên.';
 if(results.some(r=>['QUEUED','RUNNING'].includes(r.status))||scanPending)return 'Đang quét tài nguyên…';
 if(!results.length)return 'Chọn Quét ngay để bắt đầu.';
 if(results.some(r=>['FAILED','TIMED_OUT'].includes(r.status)))return 'Có region quét chưa thành công.';
 if(results.some(r=>r.status==='PARTIAL'))return 'Kết quả chưa đầy đủ.';
 return 'Kết quả sẵn sàng.';
}

function appendResultNotes(container,r){
 if(r.error)container.append(node('p',friendlyError(r.error),'footnote'));
 if(r.status==='PARTIAL')container.append(node('p','Kết quả chưa đầy đủ.','footnote'));
 const errorDescriptions={SubscriptionRequiredException:'Chưa kích hoạt subscription',AccessDenied:'Thiếu quyền IAM',AccessDeniedException:'Thiếu quyền IAM',UnauthorizedOperation:'Thiếu quyền IAM',RequestLimitExceeded:'Vượt giới hạn gọi API (Throttling)',TIME_BUDGET:'Hết thời gian xử lý'};
 for(const e of r.errors||[]){const desc=errorDescriptions[e.code]?' ('+errorDescriptions[e.code]+')':'';container.append(node('p',e.type+': '+e.code+desc,'footnote'));}
 const notices={
  FAILED:'Gửi email thất bại.',
  UNKNOWN:'Chưa xác định trạng thái email.',
  STATE_FAILED:'Không lưu được trạng thái thông báo.',
  SENT_UNRECORDED:'SES đã nhận yêu cầu nhưng chưa lưu trạng thái.'
 };
 if(notices[r.notification])container.append(node('p',notices[r.notification],'footnote'));
}

function renderPrincipals(){
 $('principals').replaceChildren();
 for(const [name,value] of [['ApiPrincipal',profile.api_principal],['ScanPrincipal',profile.scan_principal],['ExternalId',profile.external_id]]){
  const row=node('div',undefined,'parameter-row'),label=node('label',name),input=node('textarea'),button=node('button','Sao chép '+name,'button secondary');
  input.id='param-'+name;input.value=value||'';input.readOnly=true;input.rows=name==='ExternalId'?2:3;input.spellcheck=false;label.htmlFor=input.id;button.type='button';button.disabled=!value;
  button.onclick=()=>run(async()=>{
   try{await navigator.clipboard.writeText(input.value);button.textContent='Đã sao chép';status('Đã sao chép '+name+'.');}
   catch{input.focus();input.select();status('Dùng Ctrl+C để sao chép.',true);}
  },button);
  row.append(label,input,button);$('principals').append(row);
 }
}

(async()=>{
 try{
  const r=await fetch('config.json',{cache:'no-store'});
  if(!r.ok)throw Error('Không tải được cấu hình ứng dụng.');
  cfg=await r.json();
  window.cfg=cfg;
  $('login').onclick=()=>token?logout():showGuestView('login');
  if(cfg.demo)$('start').textContent='Đăng nhập demo';
  const q=new URLSearchParams(location.search);
  if(q.has('error'))throw Error(q.get('error_description')||q.get('error'));
  if(q.has('code')){
   if(q.get('state')!==sessionStorage.getItem('crg-state')||!sessionStorage.getItem('crg-state'))throw Error('OAuth state không khớp. Hãy đăng nhập lại.');
   const verifier=sessionStorage.getItem('crg-verifier');
   const response=await fetch(cfg.auth+'/oauth2/token',{
    method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({
     grant_type:'authorization_code',
     client_id:cfg.clientId,
     code:q.get('code'),
     redirect_uri:cfg.redirect,
     code_verifier:verifier
    })
   });
   const v=await response.json();
   if(!response.ok)throw Error('Không đổi được authorization code.');
   token=v.access_token;
   sessionStorage.setItem('crg-token',token);
   sessionStorage.removeItem('crg-state');
   sessionStorage.removeItem('crg-verifier');
   history.replaceState({},'',cfg.redirect);
  }
  if(token)await init();
  else if(!document.querySelector('.guest-view:not([hidden])'))showGuestView('login');
 }catch(e){
  status(friendlyError(e.message),true);
 }
})();
