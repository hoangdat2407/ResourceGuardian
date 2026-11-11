'use strict';
/* Cloud Resource Guardian — scan-centric UI. Data comes from the same API as before. */
const $=id=>document.getElementById(id);

/* ------------------------------------------------------------------ state */
let cfg,profile;
let token=sessionStorage.getItem('crg-token');
let results=[];                     // RESULT rows (one per region, feedback applied)
let loadingResults=true,resultsError='',scanPending=false,pollTimer,pollCount=0;
let scopeGeneration=0;
let findingsRevision=0;
let statusTimer=null;
let detailFocus=null;

let selectedScanId=null;            // scan shown on the findings page
let scanPinned=false;               // true when the user explicitly picked an older scan
let scanRequest=0,scanLoading=false,scanLoadError='';
const scanRowsCache=new Map();      // scan_id -> Map(region -> row) from /scans/{id}
const openSettingsGroups=new Set(['compute']);
const openGroups=new Set();
const groupLimits=new Map();
let groupDefaultsScan=undefined;
let groupsUserToggled=false;
let chartExpanded=false;
const SERVICE_GROUP_PAGE=10;
const CHART_SERVICE_LIMIT=6;
let openFeedbackMenu=null;

let historyRows=[],historyCursor=null,historyLoading=false,historyError='',historyRequest=0,historyAttempted=false;
let historySelection=null,historyDetailRows=[],historyDetailLoading=false,historyDetailError='',historyDetailRequest=0;

const feedbackState=new Map();
let feedbackRows=[],feedbackCursor=null,feedbackLoaded=false,feedbackLoading=false,feedbackError='',feedbackRequest=0,feedbackRevision=0;
const managedDays=new Map();
let ignoreTarget=null,ignoreOpener=null;

/* ----------------------------------------------------------------- config */
const pages={
 overview:['Tổng quan','Trạng thái tài khoản AWS và lượt quét gần nhất.'],
 findings:['Tài nguyên cần kiểm tra','Kết quả của từng lượt quét, phân theo trạng thái.'],
 history:['Lịch sử quét','Các lượt quét đã lưu trong 30 ngày gần nhất.'],
 connection:['Kết nối AWS','Tạo read role và lưu kết nối cho tài khoản cần quét.'],
 settings:['Cấu hình','Ngưỡng phát hiện cho các lượt quét tiếp theo.']
};
const guestViewTitles={
 login:'Đăng nhập',
 register:'Đăng ký',
 verify:'Xác minh email',
 forgot:'Quên mật khẩu',
 reset:'Đặt lại mật khẩu'
};
const defaultServiceGroups=['compute','storage','database','network'];
const regions=['ap-southeast-1','ap-southeast-2','ap-northeast-1','us-east-1','us-west-2','eu-west-1'];
const regionNames={'ap-southeast-1':'Singapore','ap-southeast-2':'Sydney','ap-northeast-1':'Tokyo','us-east-1':'N. Virginia','us-west-2':'Oregon','eu-west-1':'Ireland'};

const serviceGroups={
 compute:{label:'Tính toán (EC2)',types:['EC2']},
 storage:{label:'Lưu trữ & Sao lưu',types:['EBS','SNAPSHOT','S3_MULTIPART']},
 database:{label:'Cơ sở dữ liệu (RDS)',types:['RDS']},
 network:{label:'Mạng (EIP, NAT, Load Balancer)',types:['EIP','NAT_GATEWAY','ALB','NLB']},
 serverless:{label:'Serverless (Lambda)',types:['LAMBDA_FUNCTION']},
 monitoring:{label:'Giám sát & Logs',types:['LOG_GROUP']},
 security:{label:'Bảo mật (Security Groups, VPC Endpoints)',types:['SECURITY_GROUP','VPC_ENDPOINT']},
 backup:{label:'Sao lưu mở rộng (RDS Snapshots, EFS, ECR)',types:['RDS_SNAPSHOT','EFS_FILE_SYSTEM','ECR_REPOSITORY']},
 nosql:{label:'NoSQL & Cache (DynamoDB, ElastiCache)',types:['DYNAMODB_TABLE','ELASTICACHE_CLUSTER']},
 containers:{label:'Containers (ASG, ECS)',types:['AUTO_SCALING_GROUP','ECS_CLUSTER','ECS_SERVICE']},
 integration:{label:'Tích hợp & Hàng đợi (SQS, SNS, EventBridge, Step Functions, API Gateway)',types:['SQS_QUEUE','SNS_TOPIC','EVENTBRIDGE_RULE','STEP_FUNCTION','API_GATEWAY']}
};
const resourceGroups=Object.fromEntries(Object.entries(serviceGroups).flatMap(([group,value])=>value.types.map(type=>[type,group])));

const typeLabels={
 EC2:'Amazon EC2',EBS:'Amazon EBS',EIP:'Elastic IP',SNAPSHOT:'EBS Snapshot',S3_MULTIPART:'S3 Multipart Upload',
 RDS:'Amazon RDS',RDS_SNAPSHOT:'RDS Snapshot',NAT_GATEWAY:'NAT Gateway',ALB:'Application Load Balancer',NLB:'Network Load Balancer',
 LAMBDA_FUNCTION:'AWS Lambda',LOG_GROUP:'CloudWatch Log Group',SECURITY_GROUP:'Security Group',VPC_ENDPOINT:'VPC Endpoint',
 DYNAMODB_TABLE:'Amazon DynamoDB',ELASTICACHE_CLUSTER:'Amazon ElastiCache',MEMORYDB_CLUSTER:'Amazon MemoryDB',
 DOCUMENTDB_CLUSTER:'Amazon DocumentDB',NEPTUNE_CLUSTER:'Amazon Neptune',EFS_FILE_SYSTEM:'Amazon EFS',ECR_REPOSITORY:'Amazon ECR',
 FSX_FILE_SYSTEM:'Amazon FSx',BACKUP_VAULT:'AWS Backup',ECS_CLUSTER:'Amazon ECS Cluster',ECS_SERVICE:'Amazon ECS Service',
 AUTO_SCALING_GROUP:'Auto Scaling Group',EKS_CLUSTER:'Amazon EKS',SQS_QUEUE:'Amazon SQS',SNS_TOPIC:'Amazon SNS',
 EVENTBRIDGE_RULE:'Amazon EventBridge',STEP_FUNCTION:'AWS Step Functions',API_GATEWAY:'Amazon API Gateway',
 SAGEMAKER_ENDPOINT:'Amazon SageMaker',OPENSEARCH_DOMAIN:'Amazon OpenSearch',REDSHIFT_CLUSTER:'Amazon Redshift',
 MSK_CLUSTER:'Amazon MSK',KINESIS_STREAM:'Amazon Kinesis',CLOUDFRONT_DISTRIBUTION:'Amazon CloudFront'
};

const serviceHierarchy=[
 {group:'compute',title:'1. Tính toán & Container',services:[
  {name:'Amazon EC2',desc:'Máy chủ ảo điện toán đám mây và lưu lượng mạng',fields:['cpu_percent','network_mib_hour','window_hours','interval_hours']},
  {name:'AWS Lambda',desc:'Hàm xử lý sự kiện serverless không cần máy chủ',fields:['lambda_unused_days','lambda_max_invocations']},
  {name:'Auto Scaling Groups',desc:'Nhóm tự động mở rộng quy mô máy chủ',fields:['asg_zero_days']},
  {name:'Amazon ECS',desc:'Cụm điều phối container Docker',fields:['ecs_empty_days']},
  {name:'Amazon EKS',desc:'Cụm Kubernetes được quản lý trên AWS',fields:['eks_idle_days']}
 ]},
 {group:'storage',title:'2. Lưu trữ & Sao lưu',services:[
  {name:'Amazon EBS',desc:'Ổ lưu trữ dạng khối đính kèm EC2',fields:['orphan_hours']},
  {name:'EBS Snapshot',desc:'Bản sao lưu chụp nhanh ổ đĩa EBS',fields:['snapshot_days']},
  {name:'RDS Snapshots',desc:'Bản sao lưu chụp nhanh cơ sở dữ liệu thủ công',fields:['rds_snapshot_days']},
  {name:'Amazon EFS',desc:'Hệ thống tệp mạng dùng chung cho compute',fields:['efs_no_mount_days']},
  {name:'Amazon ECR',desc:'Kho lưu trữ ảnh container Docker riêng tư',fields:['ecr_image_days']},
  {name:'Amazon FSx',desc:'Hệ thống tệp Windows / Lustre hiệu năng cao',fields:['fsx_idle_days']},
  {name:'AWS Backup',desc:'Kho điểm khôi phục sao lưu tập trung',fields:['backup_point_days']}
 ]},
 {group:'database',title:'3. Cơ sở dữ liệu & Cache',services:[
  {name:'Amazon RDS',desc:'Cơ sở dữ liệu quan hệ (PostgreSQL, MySQL...)',fields:['rds_cpu_percent','rds_connections']},
  {name:'Amazon DynamoDB',desc:'Cơ sở dữ liệu NoSQL hiệu năng cao theo khóa-giá trị',fields:['dynamodb_idle_days']},
  {name:'Amazon ElastiCache',desc:'Cụm lưu trữ đệm in-memory Redis / Memcached',fields:['elasticache_idle_days']},
  {name:'Amazon MemoryDB',desc:'Cơ sở dữ liệu in-memory tương thích Redis bền vững',fields:['memorydb_idle_days']},
  {name:'Amazon DocumentDB',desc:'Cơ sở dữ liệu tài liệu tương thích MongoDB',fields:['documentdb_idle_days']},
  {name:'Amazon Neptune',desc:'Cơ sở dữ liệu đồ thị Graph Database',fields:['neptune_idle_days']}
 ]},
 {group:'network',title:'4. Mạng & Phân phối nội dung',services:[
  {name:'NAT Gateway',desc:'Cổng dịch địa chỉ mạng cho subnet riêng tư',fields:['nat_mib_hour']},
  {name:'Load Balancers (ALB / NLB)',desc:'Bộ cân bằng tải ứng dụng và mạng',fields:['alb_requests_hour','nlb_new_flows_hour']},
  {name:'Security Groups',desc:'Tường lửa ảo kiểm soát lưu lượng mạng',fields:['sg_unused_days']},
  {name:'VPC Endpoints',desc:'Điểm cuối kết nối riêng tư trong mạng VPC',fields:['vpc_endpoint_unused_days']},
  {name:'Amazon CloudFront',desc:'Mạng lưới phân phối nội dung CDN toàn cầu',fields:['cloudfront_requests_day']}
 ]},
 {group:'analytics',title:'5. Phân tích dữ liệu & AI',services:[
  {name:'Amazon SageMaker',desc:'Điểm cuối suy luận mô hình học máy',fields:['sagemaker_idle_days']},
  {name:'Amazon OpenSearch',desc:'Cụm tìm kiếm và phân tích nhật ký tập trung',fields:['opensearch_idle_days']},
  {name:'Amazon Redshift',desc:'Cụm kho dữ liệu phân tích quy mô lớn',fields:['redshift_idle_days']},
  {name:'Amazon MSK (Kafka)',desc:'Cụm xử lý luồng tin nhắn Apache Kafka',fields:['msk_idle_days']},
  {name:'Amazon Kinesis',desc:'Luồng thu thập dữ liệu thời gian thực',fields:['kinesis_idle_days']}
 ]},
 {group:'integration',title:'6. Giám sát & Tích hợp',services:[
  {name:'Amazon CloudWatch Logs',desc:'Nhóm nhật ký log ứng dụng và hệ thống',fields:['log_group_retention_days']},
  {name:'Amazon SQS',desc:'Hàng đợi thông điệp bất đồng bộ',fields:['sqs_idle_days']},
  {name:'Amazon SNS',desc:'Kênh phát hành và đăng ký thông báo',fields:['sns_unused_days']},
  {name:'Amazon EventBridge',desc:'Bus định tuyến sự kiện và quy tắc kích hoạt',fields:['eventbridge_unused_days']},
  {name:'AWS Step Functions',desc:'Quy trình điều phối luồng công việc serverless',fields:['stepfunctions_unused_days']},
  {name:'Amazon API Gateway',desc:'Cổng giao tiếp API HTTP / REST',fields:['apigateway_unused_days']}
 ]}
];

const friendlyFieldMeta={
 cpu_percent:{label:'CPU thấp hơn',unit:'%',help:'Cảnh báo khi CPU p95 thấp hơn mức này trong toàn bộ cửa sổ metrics.'},
 network_mib_hour:{label:'Lưu lượng mạng thấp hơn',unit:'MiB/giờ',help:'Cảnh báo khi tổng lưu lượng mạng vào/ra trung bình thấp hơn mức này.'},
 window_hours:{label:'Thời gian quan sát metrics',unit:'giờ',help:'Cửa sổ thời gian đo lường metrics CloudWatch cho mọi tài nguyên (24–168 giờ, mặc định 24).'},
 interval_hours:{label:'Khoảng cách giữa các lần quét',unit:'giờ',help:'Thời gian giãn cách tối thiểu giữa các lần quét định kỳ (1–24 giờ).'},
 lambda_unused_days:{label:'Không hoạt động trong',unit:'ngày',help:'Kiểm tra hàm Lambda không có lệnh gọi trong số ngày quy định.'},
 lambda_max_invocations:{label:'Lượt gọi tối đa',unit:'lượt',help:'Coi là ít hoạt động nếu tổng lượt gọi nhỏ hơn hoặc bằng ngưỡng này.'},
 asg_zero_days:{label:'Dung lượng bằng 0 trong',unit:'ngày',help:'Cảnh báo Auto Scaling Group có desired và min size bằng 0 liên tục.'},
 ecs_empty_days:{label:'Cluster rỗng trong',unit:'ngày',help:'Cảnh báo ECS Cluster không có task hay container instance nào đang chạy.'},
 eks_idle_days:{label:'Không có workload trong',unit:'ngày',help:'Cảnh báo EKS control plane không có Node Group hoặc Fargate profile hoạt động.'},
 orphan_hours:{label:'Theo dõi không sử dụng',unit:'giờ',help:'Cảnh báo EBS volume ở trạng thái available (chưa gắn vào EC2).'},
 snapshot_days:{label:'Snapshot cũ hơn',unit:'ngày',help:'Cảnh báo EBS snapshot cũ và không thuộc bất kỳ AMI nào đang tồn tại.'},
 multipart_days:{label:'Phần tải lên chưa hoàn tất cũ hơn',unit:'ngày',help:'Cảnh báo multipart upload chưa hoàn tất, gây chi phí lưu trữ ẩn.'},
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
 stepfunctions_unused_days:{label:'Quy trình không có lượt chạy trong',unit:'ngày',help:'Cảnh báo State Machine không có bất kỳ lượt thực thi nào được bắt đầu.'},
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
 multipart_days:{group:'storage',resource:'S3_MULTIPART',rule:'S3_MULTIPART_OLD',label:'Tuổi multipart upload (ngày)',min:1,max:30,integer:true,default:7,unit:'ngày'},
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

const levelLabels={REVIEW:'Cần kiểm tra',OBSERVING:'Đang quan sát',INSUFFICIENT_DATA:'Thiếu dữ liệu',KEPT:'Đang giữ'};
const levelTitles={REVIEW:'Cần kiểm tra',OBSERVING:'Đang quan sát',INSUFFICIENT_DATA:'Thiếu dữ liệu'};
const scanStatusLabels={QUEUED:'Đang chờ',RUNNING:'Đang quét',SUCCEEDED:'Hoàn tất',SUCCESS:'Hoàn tất',PARTIAL:'Chưa đầy đủ',FAILED:'Lỗi',TIMED_OUT:'Quá hạn'};

const errorDescriptions={
 SubscriptionRequiredException:'Chưa kích hoạt subscription cho dịch vụ trong AWS account',
 AccessDenied:'Thiếu quyền IAM đọc tài nguyên',
 AccessDeniedException:'Thiếu quyền IAM đọc tài nguyên',
 UnauthorizedOperation:'Thiếu quyền IAM đọc tài nguyên',
 RequestLimitExceeded:'Vượt giới hạn gọi API (Throttling)',
 TIME_BUDGET:'Hết thời gian xử lý an toàn của Lambda'
};

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
 'ECR repository has no lifecycle policy configured; images accumulate indefinitely':'Kho ảnh ECR chưa thiết lập Lifecycle Policy để tự động dọn dẹp các image cũ.',
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

function translateReason(reason){
 if(!reason)return 'Chưa có dữ liệu';
 const extra={
  'Low ALB request volume; confirm intended workload':'Lưu lượng request ALB thấp; kiểm tra mục đích sử dụng.',
  'Low NLB flow volume; confirm intended workload':'Lưu lượng flow NLB thấp; kiểm tra mục đích sử dụng.',
  'Low NAT traffic; confirm intended workload':'Lưu lượng qua NAT Gateway thấp; kiểm tra mục đích sử dụng.',
  'Low database activity; confirm intended workload':'Hoạt động cơ sở dữ liệu thấp; kiểm tra mục đích sử dụng.',
  'Low utilization activity; confirm intended workload':'Mức sử dụng thấp; kiểm tra mục đích sử dụng.',
  'Missing CloudWatch metrics for CloudFront; not classified as idle':'Thiếu metrics CloudWatch cho CloudFront; chưa thể kết luận ít hoạt động.',
  'Multipart initiation time unavailable; not classified as stale':'Không có thời điểm bắt đầu multipart upload; chưa thể kết luận là tồn đọng.',
  'Multipart upload older than 7 days; confirm whether it is still needed':'Multipart upload đã tồn tại hơn 7 ngày; xác nhận xem còn cần thiết không.',
  'Only a complete AMI listing can support an unreferenced-snapshot candidate.':'Chỉ khi đọc đầy đủ danh sách AMI mới có thể kết luận snapshot không được tham chiếu.',
  'Resource creation time unavailable; not classified as idle':'Không có thời điểm tạo tài nguyên; chưa thể kết luận ít hoạt động.',
  'EventBridge rule is DISABLED':'Rule EventBridge đang ở trạng thái DISABLED.',
  'EventBridge rule has no targets configured':'Rule EventBridge không có target nào được cấu hình.'
 };
 if(reasons[reason])return reasons[reason];
 if(extra[reason])return extra[reason];
 let match;
 if((match=/^ECR repository contains images older than (\d+) days$/.exec(reason)))return 'Kho ảnh ECR có image cũ hơn '+match[1]+' ngày.';
 if((match=/^Auto Scaling Group has 0 capacity for more than (\d+) days$/.exec(reason)))return 'Auto Scaling Group có dung lượng bằng 0 liên tục hơn '+match[1]+' ngày.';
 if((match=/^CloudFront distribution has low request traffic \(< (\d+) requests\/day\)$/.exec(reason)))return 'CloudFront nhận ít hơn '+match[1]+' request mỗi ngày.';
 if((match=/^AWS Backup vault contains (\d+) expired recovery points that were not deleted$/.exec(reason)))return 'AWS Backup vault có '+match[1]+' điểm khôi phục đã hết hạn chưa được xóa.';
 return reason;
}

function friendlyReason(f){
 if(!f)return 'Chưa có thông tin lý do.';
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{};
 if(f.rule_id==='ECR_NO_LIFECYCLE'||f.type==='ECR_REPOSITORY'){
  return 'Kho ảnh ECR chưa thiết lập Lifecycle Policy để tự động dọn dẹp các image cũ.';
 }
 if(f.rule_id==='LAMBDA_UNUSED'||f.type==='LAMBDA_FUNCTION'){
  if(f.resource_id&&f.resource_id.includes('RecoveryFunction')){
   return 'Hàm phục hồi sự cố thuộc hệ thống Cloud Resource Guardian; có thể bấm Giữ lại để đánh dấu ngoại lệ có kiểm soát.';
  }
  if(f.reason&&f.reason.includes('dormant')){
   return 'Hàm có trigger hoặc quyền nhưng không có lượt gọi trong cửa sổ quan sát; kiểm tra xem có phải hàm xử lý sự kiện hiếm không.';
  }
  return 'Hàm không phát sinh lệnh gọi nào trong cửa sổ quan sát; kiểm tra nhu cầu sử dụng trước khi xem xét gỡ bỏ.';
 }
 if(f.rule_id==='EBS_UNATTACHED'||f.type==='EBS'){
  const hours=v.observed_hours;
  const threshold=storedThreshold(v,'orphan_hours');
  if(hours!==undefined)return `Volume chưa gắn với EC2 trong ${hours} giờ.`;
  return 'Volume chưa gắn với instance; kiểm tra nhu cầu giữ dữ liệu.';
 }
 if(f.rule_id==='EIP_UNASSOCIATED'||f.type==='EIP'){
  const hours=v.observed_hours;
  return `Địa chỉ IP tĩnh chưa liên kết${hours!==undefined?' trong '+hours+' giờ':''}; AWS tính phí giữ public IPv4 không sử dụng.`;
 }
 if(f.rule_id==='SECURITY_GROUP_UNUSED'||f.type==='SECURITY_GROUP'){
  const hours=v.observed_hours;
  const days=storedThreshold(v,'sg_unused_days');
  return `Nhóm bảo mật không gắn vào ENI nào và không được nhóm khác tham chiếu${hours!==undefined?' (đã theo dõi '+hours+' giờ)':''}${days!==undefined?', ngưỡng '+days+' ngày':''}.`;
 }
 if(f.rule_id==='ALB_LOW_UTILIZATION'||f.type==='ALB'||f.type==='NLB'){
  if(f.level==='INSUFFICIENT_DATA')return 'Chưa nhận đủ số mẫu CloudWatch cần thiết; hệ thống không tự ý coi là ít hoạt động.';
  return 'Lưu lượng request thấp hơn ngưỡng trong cửa sổ theo dõi; kiểm tra mục đích sử dụng.';
 }
 return translateReason(f.reason)||'Cần kiểm tra theo quy tắc phát hiện.';
}

function humanReason(f){
 if(!f)return 'Chưa có dữ liệu';
 return translateReason(f.reason);
}

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
 EC2:['cpu_percent','network_mib_hour'],
 EBS:['orphan_hours'],
 EIP:['orphan_hours'],
 SNAPSHOT:['snapshot_days'],
 S3_MULTIPART:['multipart_days'],
 RDS:['rds_cpu_percent','rds_connections'],
 RDS_SNAPSHOT:['rds_snapshot_days'],
 NAT_GATEWAY:['nat_mib_hour'],
 ALB:['alb_requests_hour'],
 NLB:['nlb_new_flows_hour'],
 LAMBDA_FUNCTION:['lambda_unused_days','lambda_max_invocations'],
 LOG_GROUP:['log_group_retention_days'],
 SECURITY_GROUP:['sg_unused_days'],
 DYNAMODB_TABLE:['dynamodb_idle_days'],
 ECR_REPOSITORY:['ecr_image_days'],
 SQS_QUEUE:['sqs_idle_days'],
 ELASTICACHE_CLUSTER:['elasticache_idle_days'],
 EFS_FILE_SYSTEM:['efs_no_mount_days'],
 ECS_CLUSTER:['ecs_empty_days'],
 ECS_SERVICE:[],
 AUTO_SCALING_GROUP:['asg_zero_days'],
 API_GATEWAY:['apigateway_unused_days'],
 SNS_TOPIC:['sns_unused_days'],
 EVENTBRIDGE_RULE:['eventbridge_unused_days'],
 STEP_FUNCTION:['stepfunctions_unused_days'],
 VPC_ENDPOINT:['vpc_endpoint_unused_days'],
 SAGEMAKER_ENDPOINT:['sagemaker_idle_days'],
 OPENSEARCH_DOMAIN:['opensearch_idle_days'],
 REDSHIFT_CLUSTER:['redshift_idle_days'],
 MSK_CLUSTER:['msk_idle_days'],
 KINESIS_STREAM:['kinesis_idle_days'],
 CLOUDFRONT_DISTRIBUTION:['cloudfront_requests_day'],
 BACKUP_VAULT:['backup_point_days'],
 EKS_CLUSTER:['eks_idle_days'],
 FSX_FILE_SYSTEM:['fsx_idle_days'],
 MEMORYDB_CLUSTER:['memorydb_idle_days'],
 DOCUMENTDB_CLUSTER:['documentdb_idle_days'],
 NEPTUNE_CLUSTER:['neptune_idle_days']
};

const THRESHOLD_NOT_STORED='Chưa có dữ liệu ngưỡng tại lần đánh giá';

function storedThreshold(v,key){
 if(!v||typeof v!=='object')return undefined;
 const t=v.thresholds&&typeof v.thresholds==='object'?v.thresholds:{};
 if(t[key]!==undefined&&t[key]!==null)return t[key];
 const stripped=key.replace(/^(lambda_|rds_|sg_|vpc_endpoint_|asg_|ecs_|eks_|efs_|ecr_|fsx_|backup_|dynamodb_|elasticache_|memorydb_|documentdb_|neptune_|nat_|alb_|nlb_|cloudfront_|sagemaker_|opensearch_|redshift_|msk_|kinesis_|log_group_|sqs_|sns_|eventbridge_|stepfunctions_|apigateway_)/,'');
 if(t[stripped]!==undefined&&t[stripped]!==null)return t[stripped];
 if(key==='orphan_hours'&&v.threshold_hours!=null)return v.threshold_hours;
 if(key==='snapshot_days'&&v.snapshot_days!=null)return v.snapshot_days;
 if(key==='multipart_days'&&v.threshold_days!=null)return v.threshold_days;
 return undefined;
}

/* ---------------------------------------------------------------- helpers */
function node(tag,text,cls){
 const e=document.createElement(tag);
 if(text!==undefined&&text!==null){
  if(text instanceof globalThis.Node)e.append(text);
  else e.textContent=text;
 }
 if(cls)e.className=cls;
 return e;
}
function date(t){return t?new Date(t*1000).toLocaleString('vi-VN'):'Chưa có thời gian';}
function b64(b){return btoa(String.fromCharCode(...b)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function random(){const b=new Uint8Array(32);crypto.getRandomValues(b);return b64(b);}
function triggerLabel(value){return {manual:'Thủ công',scheduled:'Theo lịch'}[value]||(value?'Không xác định':'Không xác định');}

function status(text,error=false){
 if(statusTimer){clearTimeout(statusTimer);statusTimer=null;}
 const el=$('status');if(!el)return;
 el.hidden=!text;el.textContent=text;el.className=error?'error':'';
 if(text&&!error){statusTimer=setTimeout(()=>{const target=$('status');if(target)target.hidden=true;},4500);}
}

function badge(value,kind='scan'){
 const label=(kind==='level'?levelLabels:scanStatusLabels)[value]||levelLabels[value]||value||'Không xác định';
 let cls='observing';
 if(value==='REVIEW')cls='review';
 else if(value==='FAILED'||value==='TIMED_OUT')cls='error';
 else if(value==='PARTIAL')cls='warning';
 else if(value==='SUCCEEDED'||value==='SUCCESS'||value==='KEPT')cls='good';
 else if(value==='INSUFFICIENT_DATA')cls='insufficient';
 const span=node('span',label,'badge '+cls);
 span.dataset.value=value||'';
 return span;
}

function emptyState(container,title,description){
 container.replaceChildren();
 const box=node('div',undefined,'empty');
 box.append(node('strong',title));
 if(description)box.append(node('p',description));
 container.append(box);
}

/* ------------------------------------------------------------------- auth */
const demoAuth={pending:new Map(),verified:new Set(['demo@example.com']),resetCodes:new Map()};

function isValidEmail(email){return typeof email==='string'&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());}
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
  headers:{'Content-Type':'application/x-amz-json-1.1','X-Amz-Target':'AWSCognitoIdentityProviderService.'+action},
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
  if(message&&message.includes('SignUp is not permitted'))return 'Chức năng tự đăng ký đang chờ phê duyệt cấu hình User Pool trên hệ thống.';
  return 'Thao tác không được phép hoặc tài khoản chưa được xác minh.';
 }
 if(type==='TooManyRequestsException')return 'Quá nhiều yêu cầu. Vui lòng thử lại sau.';
 return message||'Lỗi xác thực Cognito.';
}

function showGuestView(view){
 const views=['login','register','verify','forgot','reset'];
 if(!views.includes(view))view='login';
 for(const v of views){const el=$('view-'+v);if(el)el.hidden=(v!==view);}
 document.querySelectorAll('#nav-guest button').forEach(b=>b.classList.toggle('active',b.dataset.guest===view));
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

function returnToLogin(){
 closeFindingDetail();
 closeIgnoreDialog();
 clearTimeout(pollTimer);
 token=null;
 sessionStorage.removeItem('crg-token');
 profile=null;
 resetScopeState();
 $('app').hidden=true;
 $('welcome').hidden=false;
 $('nav-auth').hidden=true;
 $('nav-guest').hidden=false;
 $('login').hidden=false;
 $('login').textContent='Đăng nhập';
 $('login').onclick=()=>showGuestView('login');
 showGuestView('login');
}

function logout(){
 const wasDemo=cfg&&cfg.demo;
 returnToLogin();
 if(!wasDemo&&cfg)location.assign(cfg.auth+'/logout?'+new URLSearchParams({client_id:cfg.clientId,logout_uri:cfg.redirect}));
}

async function api(path,method='GET',data){
 const r=await fetch(cfg.api+path,{
  method,
  headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
  ...(data!==undefined?{body:JSON.stringify(data)}:{})
 });
 let v;
 try{v=await r.json();}catch{throw Error('Máy chủ trả phản hồi không hợp lệ.');}
 if(r.status===401)returnToLogin();
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

/* ----------------------------------------------------------- navigation */
function showPage(page){
 if(!profile)return;
 closeFindingDetail();
 closeIgnoreDialog();
 status('');
 if(!pages[page])page='overview';
 for(const key of Object.keys(pages))$('page-'+key).hidden=(key!==page);
 document.querySelectorAll('#nav-auth button[data-page]').forEach(b=>{
  const match=(b.dataset.page===page);
  b.classList.toggle('active',match);
  if(match)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
 });
 $('page-title').textContent=pages[page][0];
 $('page-subtitle').textContent=pages[page][1];
 $('page-subtitle').hidden=!pages[page][1];
 $('breadcrumb').textContent=pages[page][0];
 document.title=pages[page][0]+' | Cloud Guardian';
 if(page==='history')run(loadHistory);
 if(page==='findings'){
  if(!feedbackLoaded&&!feedbackLoading)loadFeedback();
  if(!selectedScanId)selectedScanId=latestScan()?.id||firstScanSummaryId();
  renderFindings();
  if(selectedScanId&&!scanRowsCache.has(selectedScanId))selectScan(selectedScanId);
  if(!historyRows.length&&!historyAttempted&&!historyLoading)loadHistory();
 }
}
function navigate(page){if(location.hash.slice(1)===page)showPage(page);else location.hash=page;}

/* -------------------------------------------------------- scan grouping */
function rowTime(row){return row.started_at||row.completed_at||0;}
function validRows(rows){
 return (Array.isArray(rows)?rows:[]).filter(row=>row&&typeof row.region==='string'&&(profile?.regions||[]).includes(row.region));
}
function latestScan(){
 const groups=new Map();
 for(const row of validRows(results)){
  if(!row.scan_id)continue;
  const list=groups.get(row.scan_id)||[];
  list.push(row);
  groups.set(row.scan_id,list);
 }
 let best=null;
 for(const [id,rows] of groups){
  const t=Math.max(...rows.map(rowTime));
  if(!best||t>best.time)best={id,rows,time:t};
 }
 if(!best){
  const rows=validRows(results);
  if(rows.length)best={id:null,rows,time:Math.max(...rows.map(rowTime))};
 }
 return best;
}
function scanSummaries(){
 const map=new Map();
 const currentScans=new Set();
 const add=row=>{
  if(!row||!row.scan_id)return;
  const entry=map.get(row.scan_id)||{scan_id:row.scan_id,rows:[],regions:new Set(),started_at:0,completed_at:0,status:row.status,trigger:row.trigger,account_id:row.account_id};
  entry.rows.push(row);
  entry.started_at=Math.max(entry.started_at,row.started_at||0);
  entry.completed_at=Math.max(entry.completed_at,row.completed_at||0);
  if(row.region)entry.regions.add(row.region);
  if(row.status)entry.status=row.status;
  if(row.trigger)entry.trigger=row.trigger;
  if(row.account_id)entry.account_id=row.account_id;
  map.set(row.scan_id,entry);
 };
  for(const row of validRows(results)){
   if(row.scan_id)currentScans.add(row.scan_id);
   add(row);
  }
  for(const row of validRows(historyRows))add(row);
  return [...map.values()].sort((a,b)=>{
   const currentA=currentScans.has(a.scan_id)?1:0,currentB=currentScans.has(b.scan_id)?1:0;
   if(currentA!==currentB)return currentB-currentA;
   return rowTime(b)-rowTime(a);
  });
}
function firstScanSummaryId(){return scanSummaries()[0]?.scan_id||null;}

function activeScanRows(scanId){
 if(!scanId)return [];
 const known=scanSummaries().some(item=>item.scan_id===scanId);
 if(!known){scanRowsCache.delete(scanId);return [];}
 const out=new Map();
 const add=row=>{if(row&&row.region&&!out.has(row.region))out.set(row.region,row);};
 const inResults=validRows(results).some(row=>row.scan_id===scanId);
 const primary=inResults?validRows(results):validRows(historyRows);
 const secondary=inResults?validRows(historyRows):validRows(results);
 for(const row of primary)if(row.scan_id===scanId)add(row);
 for(const row of secondary)if(row.scan_id===scanId)add(row);
 const cached=scanRowsCache.get(scanId);
 if(cached)for(const row of cached.values())add(row);
 return [...out.values()];
}

function scanFindings(rows){
 return rows.flatMap(row=>(row.findings||[]).map(f=>({
  ...f,
  region:f.region||row.region,
  scan_account_id:f.account_id||row.account_id||profile?.account_id,
  scan_id:f.scan_id||row.scan_id
 })));
}

/* ------------------------------------------------------------ findings */
function populateScanSelect(){
 const sel=$('scan-select');if(!sel)return;
 const summaries=scanSummaries();
 const signature=summaries.map(item=>item.scan_id+':'+item.status+':'+item.started_at).join('|');
 if(sel.dataset.signature!==signature){
  sel.replaceChildren();
  if(!summaries.length){
   sel.append(new Option('Chưa có lượt quét nào',''));
  }else{
   summaries.forEach((item,index)=>{
    const regionText=[...item.regions].join(', ');
    const label=`${date(item.started_at||item.completed_at)} · ${regionText} · ${scanStatusLabels[item.status]||item.status}${index===0?' (gần nhất)':''}`;
    sel.append(new Option(label,item.scan_id));
   });
  }
  sel.dataset.signature=signature;
 }
 if(!scanPinned&&summaries[0])selectedScanId=summaries[0].scan_id;
 if(selectedScanId&&summaries.some(item=>item.scan_id===selectedScanId)){
  sel.value=selectedScanId;
 }else if(summaries[0]){
  selectedScanId=summaries[0].scan_id;
  scanPinned=false;
  sel.value=selectedScanId;
 }
}

async function selectScan(scanId,options={}){
 selectedScanId=scanId||null;
 if(!selectedScanId){renderFindings();return;}
 if(!options.force&&scanRowsCache.has(selectedScanId)){renderFindings();if(scanLoadError){scanLoadError='';renderFindings();}return;}
 const generation=scopeGeneration,request=++scanRequest;
 scanLoading=true;scanLoadError='';
 renderFindings();
 try{
  const reply=await api('/scans/'+encodeURIComponent(selectedScanId));
  if(request!==scanRequest||generation!==scopeGeneration)return;
  if(!Array.isArray(reply.results))throw Error('Máy chủ trả chi tiết không hợp lệ.');
  const map=new Map();
  for(const row of validRows(reply.results))if(row.scan_id===selectedScanId)map.set(row.region,row);
  if(!map.size)throw Error('Không tìm thấy dữ liệu cho lượt quét này.');
  scanRowsCache.set(selectedScanId,map);
 }catch(e){
  if(request!==scanRequest||generation!==scopeGeneration)return;
  scanLoadError='Không tải được kết quả lượt quét. '+friendlyError(e.message);
 }finally{
  if(request===scanRequest&&generation===scopeGeneration){scanLoading=false;renderFindings();}
 }
}

function renderScanBanner(rows){
 const banner=$('scan-snapshot-banner');if(!banner)return;
 banner.replaceChildren();
 if(!rows.length){
  banner.hidden=!(scanLoading||scanLoadError);
  if(!banner.hidden){
   banner.append(node('p',scanLoadError||'Đang tải dữ liệu lượt quét…',scanLoadError?'error':'muted scan-loading-note'));
  }
  return;
 }
 banner.hidden=false;
 const first=rows[0];
 const regionsText=[...new Set(rows.map(row=>row.region))].join(', ');
 const account=first.account_id||profile?.account_id||'Không xác định';
 const line=node('div',undefined,'scan-banner-line');
 line.append(node('span','Thời gian: '+date(first.started_at||first.completed_at)));
 line.append(node('span','AWS account: '+account));
 line.append(node('span','Region: '+regionsText));
 line.append(node('span','Kích hoạt: '+triggerLabel(first.trigger)));
 line.append(node('span','Trạng thái: '));
 line.append(badge(first.status));
 banner.append(line);
 const idLine=node('div',undefined,'scan-banner-id');
 idLine.append(node('span','Scan ID: '));
 idLine.append(node('code',first.scan_id||'Chưa có dữ liệu'));
 if(first.scan_id){
  const copy=node('button','Sao chép ID','text-button copy-btn');
  copy.type='button';
  copy.onclick=async()=>{
   try{await navigator.clipboard.writeText(first.scan_id);status('Đã sao chép Scan ID.');}
   catch{status('Không thể truy cập clipboard.',true);}
  };
  idLine.append(copy);
 }
 banner.append(idLine);
 if(rows.length>1){
  const detail=node('p','Lượt quét này có dữ liệu ở '+rows.length+' region; số liệu và findings bên dưới là tổng hợp của các region đó.','muted');
  banner.append(detail);
 }
 if(scanLoading)banner.append(node('p','Đang tải dữ liệu đầy đủ của lượt quét…','muted scan-loading-note'));
 if(scanLoadError)banner.append(node('p',scanLoadError,'error'));
}

function renderScanDiff(rows){
 const panel=$('scan-diff-panel');if(!panel)return;
 const summaries=scanSummaries();
 const index=summaries.findIndex(item=>item.scan_id===selectedScanId);
 const previous=index>=0?summaries[index+1]:null;
 panel.replaceChildren();
 if(!rows.length){panel.hidden=true;return;}
 panel.hidden=false;
 if(!previous){
  panel.append(node('span','Chưa có lượt quét trước để so sánh.','muted'));
  return;
 }
 const previousRows=activeScanRows(previous.scan_id);
 if(!previousRows.length||previousRows.every(row=>!Array.isArray(row.findings))){
  panel.append(node('span','Chưa tải được dữ liệu lượt quét trước ('+date(previous.started_at||previous.completed_at)+').','muted'));
  return;
 }
 const keyOf=f=>[f.type,f.resource_id,f.region,f.rule_id].join('|');
 const current=new Map(scanFindings(rows).map(f=>[keyOf(f),f]));
 const before=new Map(scanFindings(previousRows).map(f=>[keyOf(f),f]));
 let added=0,recurring=0,escalated=0;
 for(const [key,f] of current){
  if(!before.has(key)){added++;continue;}
  const old=before.get(key);
  if(old.level==='OBSERVING'&&f.level==='REVIEW')escalated++;else recurring++;
 }
 const gone=[...before.keys()].filter(key=>!current.has(key)).length;
 const comparable=rows.every(row=>row.status==='SUCCEEDED')&&previousRows.every(row=>row.status==='SUCCEEDED');
 panel.append(node('span','So sánh với lượt quét trước ('+date(previous.started_at||previous.completed_at)+'): '));
 panel.append(node('span',added+' mới xuất hiện','diff-badge diff-new'));
 panel.append(node('span',recurring+' còn tồn tại','diff-badge diff-recurring'));
 if(escalated)panel.append(node('span',escalated+' chuyển từ đang quan sát sang cần kiểm tra','diff-badge diff-transition'));
 if(comparable)panel.append(node('span',gone+' không còn được phát hiện','diff-badge diff-resolved'));
 else panel.append(node('span','Không kết luận được tài nguyên đã được giải quyết vì một trong hai lượt quét chưa đầy đủ.','muted'));
}

function renderScanErrors(rows){
 const box=$('scan-errors-card');if(!box)return;
 const errors=rows.flatMap(row=>(row.errors||[]).map(error=>({...error,region:row.region})));
 const partial=rows.some(row=>row.status==='PARTIAL');
 const failed=rows.filter(row=>['FAILED','TIMED_OUT'].includes(row.status));
 box.replaceChildren();
 if(!errors.length&&!partial&&!failed.length){box.hidden=true;return;}
 box.hidden=false;
 box.append(node('h4',partial?'Phạm vi chưa kiểm tra được trong lượt quét này':'Lượt quét gặp lỗi ở một số region'));
 if(partial){
  box.append(node('p','Lượt quét ở trạng thái Chưa đầy đủ. Số liệu và findings bên dưới chỉ phản ánh các dịch vụ đã quét thành công; không dùng để kết luận tài nguyên đã được giải quyết.'));
 }
 for(const row of failed){
  box.append(node('p','Region '+row.region+': '+friendlyError(row.error||'Quét chưa thành công.')));
 }
 if(errors.length){
  const ul=node('ul');
  for(const error of errors){
   const desc=errorDescriptions[error.code]?' ('+errorDescriptions[error.code]+')':'';
   ul.append(node('li',(error.region?error.region+' — ':'')+'Dịch vụ '+error.type+': '+error.code+desc));
  }
  box.append(ul);
 }
}

function evidenceLine(f){
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{};
 const lines=(evidenceFields[f.type]||[])
  .filter(([key,,unit])=>unit!=='time'&&v[key]!==undefined&&v[key]!==null)
  .slice(0,2)
  .map(([key,label,unit])=>label+': '+detailValue(v[key],unit));
 if(v.coverage!==undefined&&v.coverage!==null)lines.push('Độ phủ mẫu: '+detailValue(v.coverage,'coverage'));
 return lines;
}

function thresholdLine(f){
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{};
 for(const key of thresholdFields[f.type]||[]){
  const value=storedThreshold(v,key);
  if(value===undefined)continue;
  const meta=defaultThresholdConfig[key]||friendlyFieldMeta[key]||{};
  const unit=meta.unit||'';
  return 'Ngưỡng theo dõi: '+value+(unit?' '+unit:'');
 }
 const legacy=[['orphan_hours',v.threshold_hours],['snapshot_days',v.snapshot_days],['multipart_days',v.threshold_days]];
 for(const [key,value] of legacy){
  if(value===undefined||value===null)continue;
  if(!(thresholdFields[f.type]||[]).includes(key))continue;
  const meta=defaultThresholdConfig[key]||{};
  return 'Ngưỡng theo dõi: '+value+(meta.unit?' '+meta.unit:'');
 }
 return '';
}

function findingRow(f,allowFeedback){
 const row=node('tr',undefined,'finding-card');
 row.dataset.findingId=f.finding_id||'';
 row.dataset.level=f.level||'';
 const main=node('td',undefined,'finding-main');
 const head=node('div',undefined,'finding-card-head');
 head.append(node('span',typeLabels[f.type]||f.type||'Tài nguyên','resource-type'));
 head.append(badge(f.level,'level'));
 if(f.acknowledged)head.append(node('span','Đã xem','acknowledged-state'));
 main.append(head);
 main.append(node('code',f.resource_id||'Không xác định'));
 main.append(node('p',friendlyReason(f),'finding-reason'));
 const threshold=thresholdLine(f);
 if(threshold)main.append(node('p',threshold,'finding-threshold'));
 const evidenceText=evidenceLine(f);
 if(evidenceText.length)main.append(node('p',evidenceText.join(' · '),'evidence'));
 main.append(node('p','Region: '+(f.region||'Không xác định')+' · Account: '+(f.account_id||f.scan_account_id||'Không xác định'),'muted finding-meta'));
 const actions=node('td',undefined,'finding-actions');
 const open=node('button','Xem chi tiết','button secondary finding-open');
 open.type='button';
 open.dataset.findingId=f.finding_id??'';
 open.dataset.region=f.region??'';
 open.dataset.resourceId=f.resource_id??'';
 open.setAttribute('aria-label','Xem chi tiết '+f.resource_id);
 open.onclick=()=>openFindingDetail(f,!allowFeedback,open);
 actions.append(open);
 if(allowFeedback)actions.append(findingFeedback(f));
 row.append(main,actions);
 return row;
}

function findingTable(items,allowFeedback){
 const wrap=node('div',undefined,'table-wrap');
 const table=node('table',undefined,'finding-table'+(allowFeedback?' with-actions':''));
 const thead=node('thead',undefined,'visually-hidden');
 const tr=node('tr');
 for(const heading of ['Tài nguyên','Thao tác']){const th=node('th',heading);th.scope='col';tr.append(th);}
 thead.append(tr);table.append(thead);
 const body=node('tbody');
 for(const f of items)body.append(findingRow(f,allowFeedback));
 table.append(body);wrap.append(table);
 return wrap;
}

function uniqueResourceKey(f){
 return [f.type||'',f.resource_id||'',f.region||''].join('|');
}

function scanMetrics(rows){
 const levels={REVIEW:new Set(),OBSERVING:new Set(),INSUFFICIENT_DATA:new Set()};
 const alerts={REVIEW:0,OBSERVING:0,INSUFFICIENT_DATA:0};
 const counted=rows.filter(row=>['SUCCEEDED','PARTIAL'].includes(row.status)&&row.counts&&Object.keys(row.counts).length>0);
 const total=counted.length?counted.reduce((sum,row)=>sum+Object.values(row.counts||{}).reduce((acc,value)=>acc+(Number(value)||0),0),0):null;
 for(const finding of scanFindings(rows)){
  if(!levels[finding.level])continue;
  levels[finding.level].add(uniqueResourceKey(finding));
  alerts[finding.level]++;
 }
 return {total,review:levels.REVIEW.size,observing:levels.OBSERVING.size,insufficient:levels.INSUFFICIENT_DATA.size,alerts};
}

function groupByService(items){
 const map=new Map();
 for(const finding of items){
  const type=finding.type||'UNKNOWN';
  const entry=map.get(type)||{type,label:typeLabels[type]||type,alerts:0,resources:new Set(),items:[]};
  entry.alerts++;
  entry.resources.add(uniqueResourceKey(finding));
  entry.items.push(finding);
  map.set(type,entry);
 }
 for(const entry of map.values()){
  entry.items.sort((a,b)=>String(a.resource_id||'').localeCompare(String(b.resource_id||''),'vi')||String(a.rule_id||'').localeCompare(String(b.rule_id||'')));
 }
 return [...map.values()].sort((a,b)=>b.alerts-a.alerts||a.label.localeCompare(b.label,'vi'));
}

function serviceResourceData(items){
 const map=new Map();
 for(const finding of items){
  if(finding.level!=='REVIEW')continue;
  const type=finding.type||'UNKNOWN';
  const entry=map.get(type)||{type,label:typeLabels[type]||type,resources:new Set(),alerts:0};
  entry.resources.add(uniqueResourceKey(finding));
  entry.alerts++;
  map.set(type,entry);
 }
 return [...map.values()].sort((a,b)=>b.resources.size-a.resources.size||b.alerts-a.alerts||a.label.localeCompare(b.label,'vi'));
}

function serviceKey(level,type){return level+'|'+type;}

function setStat(id,value){
 const el=$(id);
 if(!el)return;
 el.textContent=value===null||value===undefined?'—':String(value);
}

function renderServiceChart(items,rows,baseFiltered){
 const chart=$('service-chart'),note=$('service-chart-note'),more=$('service-chart-more'),total=$('service-chart-total');
 if(!chart)return;
 const data=serviceResourceData(baseFiltered);
 chart.replaceChildren();
 if(total)total.textContent=data.length?(data.reduce((sum,item)=>sum+item.resources.size,0)+' tài nguyên · '+data.reduce((sum,item)=>sum+item.alerts,0)+' cảnh báo REVIEW'):'';
 if(!data.length){
  const failed=rows.some(row=>['FAILED','TIMED_OUT'].includes(row.status));
  const partial=rows.some(row=>row.status==='PARTIAL');
  let title='Không có tài nguyên cần kiểm tra trong phạm vi này';
  let text='Chưa có cảnh báo REVIEW nào khớp bộ lọc hiện tại.';
  if(failed){title='Không có dữ liệu đáng tin cậy';text='Lượt quét chưa thành công nên không thể kết luận tài khoản không có tài nguyên cần kiểm tra.';}
  else if(partial){title='Kết quả chưa đầy đủ';text='Một số dịch vụ chưa đọc được trong lượt quét này; biểu đồ chỉ phản ánh phần đã quét thành công.';}
  const empty=node('div',undefined,'empty chart-empty');
  empty.setAttribute('role','status');
  empty.append(node('strong',title),node('p',text));
  chart.append(empty);
  if(more)more.hidden=true;
  if(note){
   note.hidden=false;
   note.textContent=(failed||partial)?'Không kết luận tài khoản AWS an toàn dựa trên lượt quét chưa đầy đủ.':'';
   note.hidden=!note.textContent;
   note.classList.toggle('chart-note-warning',failed||partial);
  }
  return;
 }
 const visible=chartExpanded?data:data.slice(0,CHART_SERVICE_LIMIT);
 const max=Math.max(...data.map(item=>item.resources.size),1);
 for(const entry of visible){
  const row=node('div',undefined,'service-bar-row');
  const button=node('button',undefined,'service-bar');
  button.type='button';
  button.dataset.service=entry.type;
  button.setAttribute('aria-label',entry.label+': '+entry.resources.size+' tài nguyên cần kiểm tra. Chọn để mở danh sách tài nguyên.');
  const label=node('span',entry.label,'service-bar-label');
  const track=node('span',undefined,'service-bar-track');
  track.setAttribute('aria-hidden','true');
  const fill=node('span',undefined,'service-bar-fill');
  fill.style.width=(entry.resources.size/max*100)+'%';
  track.append(fill);
  const count=node('span',entry.resources.size+' tài nguyên cần kiểm tra','service-bar-count');
  button.append(label,track,count);
  button.onclick=()=>focusServiceGroup(entry.type);
  row.append(button);
  chart.append(row);
 }
 if(more){
  more.hidden=data.length<=CHART_SERVICE_LIMIT;
  more.textContent=chartExpanded?'Thu gọn bớt dịch vụ':('Xem thêm '+(data.length-CHART_SERVICE_LIMIT)+' dịch vụ');
 }
 if(note){
  const failed=rows.some(row=>['FAILED','TIMED_OUT'].includes(row.status));
  const partial=rows.some(row=>row.status==='PARTIAL');
  const reviewTotal=items.filter(finding=>finding.level==='REVIEW').length;
  const reviewShown=baseFiltered.filter(finding=>finding.level==='REVIEW').length;
  const scopeActive=reviewShown!==reviewTotal;
  const parts=[];
  if(scopeActive)parts.push('Biểu đồ tính theo bộ lọc hiện tại.');
  if(partial)parts.push('Lượt quét chưa đầy đủ nên biểu đồ chỉ phản ánh các dịch vụ đã đọc được.');
  if(failed)parts.push('Lượt quét chưa thành công nên không thể kết luận tài khoản AWS an toàn.');
  note.textContent=parts.join(' ');
  note.hidden=!note.textContent;
  note.classList.toggle('chart-note-warning',failed||partial);
 }
}

function renderChartPlaceholder(title,text){
 const chart=$('service-chart');
 if(chart){
  chart.replaceChildren();
  const box=node('div',undefined,'empty chart-empty');
  box.setAttribute('role','status');
  box.append(node('strong',title),node('p',text));
  chart.append(box);
 }
 const total=$('service-chart-total');if(total)total.textContent='';
 const note=$('service-chart-note');if(note){note.textContent='';note.hidden=true;}
 const more=$('service-chart-more');if(more)more.hidden=true;
}

function focusServiceGroup(type){
 const levelSelect=$('filter-level');
 if(levelSelect&&levelSelect.value&&levelSelect.value!=='REVIEW')levelSelect.value='';
 openGroups.add(serviceKey('REVIEW',type));
 renderFindings();
 const find=()=>Array.from(document.querySelectorAll('#findings-list section.service-group')).find(section=>section.dataset.level==='REVIEW'&&section.dataset.service===type);
 let section=find();
 if(!section){
  for(const id of ['search','filter-type','filter-group','filter-region','filter-acknowledged']){
   const el=$(id);
   if(el)el.value='';
  }
  if(levelSelect)levelSelect.value='';
  openGroups.add(serviceKey('REVIEW',type));
  renderFindings();
  section=find();
 }
 if(!section)return;
 section.scrollIntoView({behavior:'smooth',block:'start'});
 section.classList.add('service-focus');
 setTimeout(()=>section.classList.remove('service-focus'),1600);
 const toggle=section.querySelector('.group-toggle');
 if(toggle)toggle.focus({preventScroll:true});
}

function renderServiceGroup(entry,level,allowFeedback){
 const key=serviceKey(level,entry.type);
 const expanded=openGroups.has(key);
 const section=node('section',undefined,'finding-group service-group');
 section.dataset.level=level;
 section.dataset.service=entry.type;
 const head=node('div',undefined,'finding-group-head');
 const title=node('h4',undefined,'finding-group-title');
 const toggle=node('button',undefined,'group-toggle');
 toggle.type='button';
 toggle.setAttribute('aria-expanded',String(expanded));
 const body=node('div',undefined,'finding-group-body');
 const bodyId='service-group-'+level.toLowerCase()+'-'+entry.type.toLowerCase().replace(/[^a-z0-9]+/g,'-');
 const titleId=bodyId+'-title';
 body.id=bodyId;
 body.setAttribute('role','region');
 body.setAttribute('aria-labelledby',titleId);
 toggle.id=titleId;
 toggle.setAttribute('aria-controls',bodyId);
 const name=node('span',entry.label,'group-service-name');
 const counts=node('span',undefined,'group-service-counts');
 counts.append(node('span',entry.alerts+' cảnh báo'));
 if(entry.resources.size!==entry.alerts)counts.append(node('span',entry.resources.size+' tài nguyên'));
 toggle.append(name,counts);
 title.append(toggle);
 head.append(title);
 const shown=groupLimits.get(key)||SERVICE_GROUP_PAGE;
 const visibleItems=entry.items.slice(0,shown);
 body.append(findingTable(visibleItems,allowFeedback));
 if(entry.items.length>shown){
  const more=node('button','Xem thêm '+(entry.items.length-shown)+' cảnh báo','button secondary group-more');
  more.type='button';
  more.onclick=()=>{
   const toggleId=toggle.id;
   groupLimits.set(key,shown+SERVICE_GROUP_PAGE);
   renderFindings();
   const fresh=document.getElementById(toggleId);
   if(fresh)fresh.focus();
  };
  body.append(more);
 }
 body.hidden=!expanded;
 toggle.onclick=()=>{
  const hide=!body.hidden;
  body.hidden=hide;
  toggle.setAttribute('aria-expanded',String(!hide));
  groupsUserToggled=true;
  if(hide)openGroups.delete(key);else openGroups.add(key);
 };
 section.append(head,body);
 return section;
}

function renderGroupedList(container,items,allowFeedback){
 const previous=feedbackFocus(container);
 container.replaceChildren();
 const statuses=['REVIEW','OBSERVING','INSUFFICIENT_DATA'];
 const descriptions={
  REVIEW:'Tài nguyên có dấu hiệu lãng phí hoặc cấu hình cần xem xét.',
  OBSERVING:'Tài nguyên mới bắt đầu có dấu hiệu; cần thêm thời gian quan sát trước khi kết luận.',
  INSUFFICIENT_DATA:'Chưa đủ metrics hoặc quyền đọc để kết luận; đây không phải tài nguyên an toàn.'
 };
 for(const level of statuses){
  const levelItems=items.filter(finding=>finding.level===level);
  if(!levelItems.length)continue;
  const groups=groupByService(levelItems);
  const statusSlug=level==='INSUFFICIENT_DATA'?'insufficient':level.toLowerCase();
  const heading=node('div',undefined,'status-heading status-'+statusSlug);
  const title=node('h3',undefined,'status-heading-title');
  title.append(node('span',levelTitles[level]),node('span',String(levelItems.length)+' cảnh báo','group-count'));
  heading.append(title,node('p',descriptions[level],'muted'));
  container.append(heading);
  for(const group of groups)container.append(renderServiceGroup(group,level,allowFeedback));
 }
 const others=items.filter(finding=>!statuses.includes(finding.level));
 if(others.length){
  const heading=node('div',undefined,'status-heading');
  heading.append(node('h3','Khác','status-heading-title'));
  container.append(heading);
  for(const group of groupByService(others))container.append(renderServiceGroup(group,'REVIEW',allowFeedback));
 }
 restoreFeedbackFocus(container,previous);
}

function renderFindings(){
 if(!profile)return;
 populateScanSelect();
 let rows=selectedScanId?activeScanRows(selectedScanId):[];
 if(!rows.length&&!scanSummaries().length)rows=validRows(results);
 const items=scanFindings(rows);
 const metrics=scanMetrics(rows);
 renderScanBanner(rows);
 renderScanDiff(rows);
 renderScanErrors(rows);
 const list=$('findings-list');
 const context=$('resource-overview-context');
 const setOverview=(text)=>{if(context)context.textContent=text;};
 const clearCounts=()=>{
  setStat('findings-count-checked',null);
  setStat('findings-count-review',null);
  setStat('findings-count-observing',null);
  setStat('findings-count-insufficient',null);
 };
 if(!rows.length){
  clearCounts();
  if(scanLoading){
   setOverview('Đang tải dữ liệu lượt quét…');
   renderChartPlaceholder('Đang tải dữ liệu lượt quét…','Biểu đồ và danh sách tài nguyên sẽ hiển thị ngay khi tải xong.');
  }else{
   setOverview('Chưa có lượt quét nào để hiển thị.');
   renderChartPlaceholder('Chưa có dữ liệu lượt quét','Chọn Quét ngay hoặc chọn một lượt quét đã lưu để xem tài nguyên.');
  }
  const previous=feedbackFocus(list);
  if(scanLoading)emptyState(list,'Đang tải kết quả lượt quét…','Dữ liệu của lượt quét đang xem sẽ hiển thị ngay khi tải xong.');
  else emptyState(list,'Chưa có dữ liệu lượt quét',scanLoadError||'Hãy kết nối AWS và chạy lần quét đầu tiên.');
  restoreFeedbackFocus(list,previous);
  $('findings-scope').textContent=scanLoadError||'';
  renderFilterOptions(items);
  return;
 }
 const haveCounts=metrics.total!==null;
 setStat('findings-count-checked',metrics.total);
 setStat('findings-count-review',haveCounts?metrics.review:null);
 setStat('findings-count-observing',haveCounts?metrics.observing:null);
 setStat('findings-count-insufficient',haveCounts?metrics.insufficient:null);
 const first=rows[0];
 const scanStatus=scanStatusLabels[first.status]||first.status||'Không xác định';
 const scanAccount=first.account_id||profile?.account_id||'Không xác định';
 const scanRegions=[...new Set(rows.map(row=>row.region))].join(', ');
 setOverview('Lượt quét '+date(first.started_at||first.completed_at)+' · '+scanAccount+' · '+scanRegions+' · '+scanStatus);

 renderFilterOptions(items);
 const q=$('search')?.value.trim().toLowerCase()||'';
 const type=$('filter-type')?.value||'';
 const level=$('filter-level')?.value||'';
 const group=$('filter-group')?.value||'';
 const region=$('filter-region')?.value||'';
 const ack=$('filter-acknowledged')?.value||'';
 const matches=(finding,ignoreLevel)=>(
  (!type||finding.type===type)&&
  (!group||resourceGroups[finding.type]===group)&&
  (!region||finding.region===region)&&
  (!ack||(ack==='acknowledged'?finding.acknowledged===true:finding.acknowledged!==true))&&
  (ignoreLevel||!level||finding.level===level)&&
  [finding.resource_id,finding.reason,reasons[finding.reason]||'',friendlyReason(finding),finding.rule_id].some(value=>String(value||'').toLowerCase().includes(q))
 );
 const baseFiltered=items.filter(finding=>matches(finding,true));
 const filtered=items.filter(finding=>matches(finding,false));
 const activeFilter=Boolean(q||type||level||group||region||ack);
 renderServiceChart(items,rows,baseFiltered);

 const failed=rows.some(row=>['FAILED','TIMED_OUT'].includes(row.status));
 const partial=rows.some(row=>row.status==='PARTIAL');
 const notes=[];
 if(resultsError)notes.push('Danh sách chưa được cập nhật do lỗi tải kết quả.');
 if(failed)notes.push('Lượt quét gần nhất chưa quét thành công; danh sách này không dùng kết quả của lần quét lỗi.');
 if(partial)notes.push('Lượt quét chưa đầy đủ; không kết luận tài nguyên đã được giải quyết.');
 const scopeLine='Hiển thị '+filtered.length+' / '+items.length+' cảnh báo'+(activeFilter?' (đang áp dụng bộ lọc)':'')+' · '+metrics.review+' tài nguyên cần kiểm tra trong lượt quét.';
 $('findings-scope').textContent=[...notes,scopeLine].join(' ');

 if(!filtered.length){
  const previous=feedbackFocus(list);
  emptyState(list,activeFilter?'Không khớp bộ lọc':'Không có cảnh báo trong lượt quét này',activeFilter?'Thử xóa từ khóa tìm kiếm hoặc chọn lại bộ lọc.':'Toàn bộ tài nguyên đã kiểm tra đều hoạt động bình thường theo quy tắc hiện tại.');
  restoreFeedbackFocus(list,previous);
  return;
 }

 if(groupDefaultsScan!==selectedScanId){
  openGroups.clear();
  groupsUserToggled=false;
  groupLimits.clear();
  groupDefaultsScan=selectedScanId;
  chartExpanded=false;
 }
 const visibleGroups=[];
 for(const statusLevel of ['REVIEW','OBSERVING','INSUFFICIENT_DATA']){
  for(const entry of groupByService(filtered.filter(finding=>finding.level===statusLevel)))visibleGroups.push(serviceKey(statusLevel,entry.type));
 }
 if(!groupsUserToggled){
  openGroups.clear();
  const reviewGroups=groupByService(filtered.filter(finding=>finding.level==='REVIEW'));
  const focusKey=reviewGroups[0]?serviceKey('REVIEW',reviewGroups[0].type):visibleGroups[0];
  if(focusKey)openGroups.add(focusKey);
 }else if(visibleGroups.length&&!visibleGroups.some(key=>openGroups.has(key))){
  openGroups.add(visibleGroups[0]);
 }
 renderGroupedList(list,filtered,true);
}

function renderFilterOptions(items){
 const typeSelect=$('filter-type'),groupSelect=$('filter-group');
 if(typeSelect){
  const current=typeSelect.value;
  const types=[...new Set(items.map(f=>f.type).filter(Boolean))].sort();
  if(current&&!types.includes(current))types.push(current);
  const signature='type:'+types.join(',');
  if(typeSelect.dataset.signature!==signature){
   typeSelect.replaceChildren(new Option('Tất cả',''),...types.map(type=>new Option((typeLabels[type]?typeLabels[type]+' — ':'')+type,type)));
   typeSelect.dataset.signature=signature;
   if(types.includes(current))typeSelect.value=current;
  }
 }
 if(groupSelect){
  const current=groupSelect.value;
  const groups=[...new Set(items.map(f=>resourceGroups[f.type]).filter(Boolean))];
  if(current&&!groups.includes(current))groups.push(current);
  const signature='group:'+groups.join(',');
  if(groupSelect.dataset.signature!==signature){
   groupSelect.replaceChildren(new Option('Tất cả',''),...groups.map(group=>new Option(serviceGroups[group]?.label||group,group)));
   groupSelect.dataset.signature=signature;
   if(groups.includes(current))groupSelect.value=current;
  }
 }
 const regionSelect=$('filter-region');
 if(regionSelect&&profile){
  const regionsList=profile.regions||[];
  const signature='region:'+regionsList.join(',');
  if(regionSelect.dataset.signature!==signature){
   const current=regionSelect.value;
   regionSelect.replaceChildren(new Option('Tất cả',''),...regionsList.map(region=>new Option((regionNames[region]||region)+' — '+region,region)));
   regionSelect.dataset.signature=signature;
   if(regionsList.includes(current))regionSelect.value=current;
  }
 }
}

/* ------------------------------------------------------------- overview */
function latestScanMetrics(rows){
 const counted=rows.filter(row=>['SUCCEEDED','PARTIAL'].includes(row.status)&&row.counts&&Object.keys(row.counts).length>0);
 const measured=counted.length>0;
 const levels={REVIEW:0,OBSERVING:0,INSUFFICIENT_DATA:0};
 if(measured){
  for(const row of counted)for(const finding of row.findings||[])if(levels[finding.level]!==undefined)levels[finding.level]++;
 }
 const total=measured?counted.reduce((sum,row)=>sum+Object.values(row.counts||{}).reduce((a,b)=>a+(Number(b)||0),0),0):null;
 const errors=measured?rows.reduce((sum,row)=>sum+(row.errors||[]).length,0):null;
 return {measured,levels,total,errors};
}

function renderAccount(){
 if(!profile)return;
 $('account-name').textContent=profile.account_id||'Chưa kết nối AWS';
 $('account-regions').textContent=(profile.regions||[]).join(' / ')||'Chưa có dữ liệu';
 $('account-status').textContent=profile.role_arn?'Đã kết nối':'Chưa kết nối';
 $('account-badge').textContent=profile.role_arn?'Đã kết nối':'Chưa kết nối';
 $('account-badge').className='badge '+(profile.role_arn?'good':'');
 const groups=(profile.service_groups||defaultServiceGroups).map(group=>serviceGroups[group]?.label||group);
 $('account-service-groups').textContent='Nhóm dịch vụ: '+(groups.join(' / ')||'Chưa có dữ liệu');
}

function overviewState(latest){
 if(loadingResults)return {title:'Đang tải kết quả',text:'Đang tải kết quả lượt quét gần nhất.',cls:''};
 if(resultsError)return {title:'Không tải được kết quả',text:'Không tải được kết quả mới. Chọn Tải lại kết quả để thử lại.',cls:'error'};
 if(!profile?.role_arn)return {title:'Bắt đầu bằng kết nối AWS',text:'Tạo role chỉ đọc theo hướng dẫn, xác minh kết nối rồi chạy lần quét đầu tiên.',cls:''};
 const rows=latest?latest.rows:[];
 if(scanPending||rows.some(row=>['QUEUED','RUNNING'].includes(row.status))){
  return {title:'Đang quét tài nguyên',text:'Hệ thống đang thu thập dữ liệu. Kết quả sẽ tự cập nhật sau mỗi lần kiểm tra.',cls:''};
 }
 if(!rows.length)return {title:'Chưa có lượt quét',text:'Tài khoản đã kết nối nhưng chưa có lượt quét nào. Chọn Quét ngay để chạy lần quét đầu tiên.',cls:''};
 if(rows.some(row=>['FAILED','TIMED_OUT'].includes(row.status))){
  return {title:'Lượt quét gần nhất chưa quét thành công',text:'Xem lỗi bên dưới rồi chạy lại. Chưa thể kết luận tài khoản an toàn dựa trên lượt quét lỗi.',cls:'error'};
 }
 if(rows.some(row=>row.status==='PARTIAL')){
  return {title:'Kết quả chưa đầy đủ',text:'Một số dịch vụ chưa đọc được dữ liệu trong lượt quét gần nhất. Không kết luận tài nguyên đã được giải quyết.',cls:'warning'};
 }
 return {title:'Kết quả đã sẵn sàng',text:'Lượt quét gần nhất hoàn tất trên toàn bộ region đã chọn.',cls:''};
}

function appendResultNotes(container,row){
 if(row.error)container.append(node('p',friendlyError(row.error),'footnote'));
 if(row.status==='PARTIAL')container.append(node('p','Kết quả chưa đầy đủ. Giới hạn 100 tài nguyên/loại và 50 cảnh báo/region.','footnote'));
 for(const error of row.errors||[]){
  const desc=errorDescriptions[error.code]?' ('+errorDescriptions[error.code]+')':'';
  container.append(node('p',error.type+': '+error.code+desc,'footnote'));
 }
 const notices={
  FAILED:'Gửi email thất bại.',
  UNKNOWN:'Chưa xác định trạng thái email.',
  STATE_FAILED:'Không lưu được trạng thái thông báo.',
  SENT_UNRECORDED:'SES đã nhận yêu cầu nhưng chưa lưu trạng thái.'
 };
 if(notices[row.notification])container.append(node('p',notices[row.notification],'footnote'));
}

function renderScanSummary(rows){
 const container=$('scan-summary');if(!container)return;
 container.replaceChildren();
 if(!rows.length){container.append(node('p','Chưa có lượt quét nào. Chọn Quét ngay để bắt đầu.','muted'));return;}
 const scanId=rows[0].scan_id;
 if(scanId){
  const idLine=node('p',undefined,'scan-id-line');
  idLine.append(node('span','Mã lượt quét: '),node('code',scanId));
  container.append(idLine);
 }
 const sorted=[...rows].sort((a,b)=>String(a.region).localeCompare(String(b.region)));
 for(const row of sorted){
  const line=node('div',undefined,'scan-row');
  line.append(node('span',(regionNames[row.region]||row.region)+' — '+row.region));
  line.append(badge(row.status));
  container.append(line);
  container.append(node('small',triggerLabel(row.trigger)+' · '+date(row.started_at||row.completed_at),'muted'));
  appendResultNotes(container,row);
 }
 if(rows.length>1){
  const accounts=[...new Set(rows.map(row=>row.account_id).filter(Boolean))];
  container.append(node('p','AWS account: '+(accounts.join(', ')||'Chưa xác định'),'muted'));
 }
}

function renderOverview(){
 if(!profile)return;
 const latest=latestScan();
 const rows=latest?latest.rows:[];
 const metrics=latestScanMetrics(rows);
 $('total').textContent=metrics.measured?String(metrics.total):'—';
 $('review').textContent=metrics.measured?String(metrics.levels.REVIEW):'—';
 $('observing').textContent=metrics.measured?String(metrics.levels.OBSERVING):'—';
 $('insufficient').textContent=metrics.measured?String(metrics.levels.INSUFFICIENT_DATA):'—';
 $('scan-errors').textContent=metrics.measured?String(metrics.errors):'—';
 $('nav-count').textContent=metrics.measured?String(metrics.levels.REVIEW):'—';
 const statusBadge=$('latest-scan-status');
 if(rows.length){
  const primary=rows.find(row=>row.status)||rows[0];
  statusBadge.replaceChildren(badge(primary.status));
 }else{
  statusBadge.replaceChildren(node('span','Chưa có lượt quét','badge'));
 }
 $('last-scan-time').textContent=latest?date(latest.time):'Chưa có lượt quét';
 const busy=scanPending||validRows(results).some(row=>['QUEUED','RUNNING'].includes(row.status));
 for(const id of ['scan','first-scan']){
  const button=$(id);
  if(!button)continue;
  button.disabled=!profile.role_arn||busy;
  button.textContent=busy?'Đang quét…':'Quét ngay';
 }
 $('first-scan-note').textContent=!profile.role_arn?'Lưu kết nối ở bước 2 để bắt đầu quét.':busy?'Đang thực hiện quét tài nguyên.':'Chọn Quét ngay để bắt đầu.';
 const goto=$('goto-scan');
 goto.disabled=!latest;
 goto.onclick=()=>{if(!latest)return;selectedScanId=latest.id;navigate('findings');selectScan(latest.id);};

 const state=overviewState(latest);
 const panel=$('overview-state');
 panel.replaceChildren();
 panel.className='state-panel'+(state.cls?' '+state.cls:'');
 panel.append(node('h2',state.title),node('p',state.text));
 if(!profile.role_arn){
  const connect=node('button','Kết nối AWS','button primary');
  connect.onclick=()=>navigate('connection');
  panel.append(connect);
 }

 renderScanSummary(rows);

 const reviewItems=scanFindings(rows).filter(f=>f.level==='REVIEW').slice(0,5);
 const priority=$('priority-list');
 const note=$('priority-note');
 if(!rows.length){
  note.hidden=false;
  note.textContent='Chưa có lượt quét để hiển thị tài nguyên cần chú ý.';
  emptyState(priority,'Chưa có dữ liệu','Chạy Quét ngay để có kết quả đầu tiên.');
 }else if(rows.some(row=>['FAILED','TIMED_OUT'].includes(row.status))){
  note.hidden=false;
  note.textContent='Lượt quét gần nhất gặp lỗi; không có dữ liệu đáng tin cậy để hiển thị.';
  emptyState(priority,'Không có dữ liệu từ lượt quét lỗi','Chạy lại lượt quét để có kết quả.');
 }else if(!reviewItems.length){
  note.hidden=false;
  note.textContent='Không có tài nguyên cần kiểm tra trong lượt quét gần nhất.';
  emptyState(priority,'Không phát hiện tài nguyên cần chú ý','Các tài nguyên đã kiểm tra không vượt ngưỡng cảnh báo.');
 }else{
  note.hidden=false;
  note.textContent=reviewItems.length===5?'Hiển thị 5 tài nguyên cần kiểm tra đầu tiên.':'Có '+reviewItems.length+' tài nguyên cần kiểm tra.';
  priority.replaceChildren(findingTable(reviewItems,true));
 }
}

/* ------------------------------------------------------ finding detail */
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
 const section=node('section',undefined,'finding-detail-section');
 section.append(node('h3',title));
 const list=node('dl',undefined,'finding-detail-grid');
 for(const [key,label,value,unit] of rows){
  const item=node('div');item.dataset.field=key;
  item.append(node('dt',label),node('dd',detailValue(value,unit)));
  list.append(item);
 }
 section.append(list);container.append(section);return section;
}

function closeFindingDetail(){
 detailFocus=null;
 const dialog=$('finding-dialog');
 if(dialog&&dialog.open)dialog.close();
 const content=$('finding-detail-content');
 if(content)content.replaceChildren();
}

function restoreFindingFocus(){
 const previous=detailFocus;
 detailFocus=null;
 if(!previous||$('app')?.hidden)return;
 const visible=element=>!!element&&element.isConnected&&element.getClientRects().length>0&&!element.disabled;
 const container=$(previous.container);
 let target=visible(previous.element)?previous.element:null;
 if(!target&&container){
  target=[...container.querySelectorAll('.finding-open')].find(button=>button.dataset.findingId===previous.id&&button.dataset.region===previous.region&&button.dataset.resourceId===previous.resource)||null;
  if(!visible(target))target=null;
 }
 if(!target){
  const fallback=previous.container==='findings-list'?$('search'):previous.container==='history-detail'?$('refresh-history'):$('refresh');
  if(visible(fallback))target=fallback;
 }
 if(!target&&visible($('scan')))target=$('scan');
 if(!target)return;
 target.focus();
 const retry=()=>{
  if(!visible(target))return;
  const active=document.activeElement;
  if(!active||active===document.body||(active.closest&&active.closest('#finding-dialog')))target.focus();
 };
 queueMicrotask(retry);
 setTimeout(retry,0);
}

function openFindingDetail(f,history=false,opener=document.activeElement){
 detailFocus={element:opener,container:opener.closest('[id]')?.id,id:String(f.finding_id??''),region:String(f.region??''),resource:String(f.resource_id??'')};
 const v=f.evidence&&typeof f.evidence==='object'?f.evidence:{};
 const content=$('finding-detail-content');
 content.replaceChildren();
 $('finding-detail-context').textContent=history?'Snapshot lịch sử đã lưu.':'Bằng chứng đã lưu của finding tại lần đánh giá này.';

 const intro=node('section',undefined,'finding-detail-intro');
 intro.append(node('h3','Vì sao tài nguyên này bị cảnh báo'));
 intro.append(node('p',friendlyReason(f),'finding-explanation'));
 content.append(intro);

 detailSection(content,'Thông tin finding',[
  ['type','Loại tài nguyên',f.type],
  ['resource_id','Resource ID',f.resource_id],
  ['account_id','AWS account',f.account_id??v.account_id],
  ['region','Region',f.region??v.region],
  ['level','Mức cảnh báo',levelLabels[f.level]||f.level],
  ['reason','Lý do',humanReason(f)],
  ['recommendation','Khuyến nghị',f.recommendation],
  ['scan_id','Lượt quét',f.scan_id],
  ['first_seen_at','Quan sát lần đầu',f.first_seen_at,'time'],
  ['last_seen_at','Quan sát gần nhất',f.last_seen_at,'time'],
  ['evaluated_at','Thời điểm đánh giá',f.evaluated_at??v.evaluated_at,'time']
 ]);

 const evidenceRows=(evidenceFields[f.type]||[]).map(([key,label,unit])=>[key,label,v[key],unit]);
 if(evidenceRows.length)detailSection(content,'Bằng chứng chính ('+(f.type||'')+')',evidenceRows);

 const thresholdKeys=thresholdFields[f.type]||Object.keys(v.thresholds||{});
 if(thresholdKeys.length){
  detailSection(content,'Ngưỡng tại lần đánh giá',thresholdKeys.map(key=>{
   const meta=defaultThresholdConfig[key]||friendlyFieldMeta[key]||{};
   const value=storedThreshold(v,key);
   const unit=value===undefined?'':(meta.unit||'');
   return ['thresholds.'+key,meta.label||key,value===undefined?THRESHOLD_NOT_STORED:value,unit];
  }));
 }

 if(['EC2','RDS','NAT_GATEWAY','ALB','NLB'].includes(f.type)){
  detailSection(content,'Cửa sổ và độ phủ metrics',[
   ['window_hours','Cửa sổ metrics',v.window_hours,'giờ'],
   ['observation_start','Bắt đầu cửa sổ',v.observation_start,'time'],
   ['observation_end','Kết thúc cửa sổ',v.observation_end,'time'],
   ['metric_period_seconds','Chu kỳ mẫu',v.metric_period_seconds,'giây'],
   ['coverage','Độ phủ mẫu hợp lệ',v.coverage,'coverage'],
   ['required_samples','Số mẫu tối thiểu mỗi metric',v.required_samples],
   ['sample_counts','Số mẫu hợp lệ',v.sample_counts??{}],
   ['received_sample_counts','Số mẫu nhận được',v.received_sample_counts??{}],
   ['invalid_sample_counts','Số mẫu không hợp lệ',v.invalid_sample_counts??{}],
   ['missing_metrics','Metric thiếu mẫu',v.missing_metrics??[]],
   ['invalid_metrics','Metric không hợp lệ',v.invalid_metrics??[]],
   ['calculation_errors','Lỗi tính toán',v.calculation_errors??[]],
   ['data_issues','Vấn đề dữ liệu',v.data_issues??[]],
   ['metric_units','Đơn vị metric đầu vào',v.metric_units??{}],
   ['metric_statistics','Thống kê mỗi chu kỳ',v.metric_statistics??{}]
  ]);
 }else if(v.data_issues!==undefined){
  detailSection(content,'Chất lượng dữ liệu',[['data_issues','Vấn đề dữ liệu',v.data_issues]]);
 }

 const advanced=node('details',undefined,'technical-details');
 advanced.append(node('summary','Thông tin kỹ thuật (Rule ID, Finding ID, Raw evidence)'));
 const advancedBody=node('div');
 detailSection(advancedBody,'Định danh kỹ thuật',[
  ['rule_id','Rule ID',f.rule_id],
  ['finding_id','Finding ID',f.finding_id]
 ]);
 const raw=node('section',undefined,'finding-detail-section');
 raw.append(node('h3','Raw finding payload'));
 raw.append(node('pre',JSON.stringify(f,null,2),'raw-evidence-pre'));
 advancedBody.append(raw);
 advanced.append(advancedBody);
 content.append(advanced);

 const dialog=$('finding-dialog');
 if(dialog)try{dialog.showModal();}catch{}
}

/* ----------------------------------------------------------- feedback */
function feedbackKey(f){return JSON.stringify([f.region,f.finding_id]);}

function feedbackFocus(container){
 const active=document.activeElement;
 if(!active||!container.contains(active))return null;
 const group=active.closest('.finding-feedback');
 if(!group)return null;
 const cls=['feedback-ack','feedback-keep','feedback-ignore','feedback-status'].find(name=>active.classList.contains(name))||'feedback-status';
 return {key:group.dataset.feedbackKey,selector:cls};
}
function restoreFeedbackFocus(container,previous){
 if(!previous||$('app').hidden)return;
 const group=[...container.querySelectorAll('.finding-feedback')].find(item=>item.dataset.feedbackKey===previous.key);
 const control=group?.querySelector('.'+previous.selector);
 const target=control&&!control.disabled?control:group?.querySelector('.feedback-status');
 (target||(container.id==='feedback-list'?$('refresh-feedback'):container.id==='findings-list'?$('search'):$('refresh')))?.focus();
}

function feedbackHidden(record){
 return !(record.expires&&record.expires<=Date.now()/1000)&&(!!record.kept||record.ignore_until>Date.now()/1000);
}

function feedbackSaveMessage(record,patch,confirmed=false){
 if('acknowledged' in patch)return record.acknowledged?'Đã đánh dấu finding là đã xem.':'Đã chuyển finding về trạng thái chưa xem.';
 if(patch.kept===true)return 'Đã giữ lại. Cảnh báo đã được ẩn.';
 if(patch.ignoreUntil)return 'Đã bỏ qua '+Math.round((Date.parse(patch.ignoreUntil)-Date.now())/86400000)+' ngày. Cảnh báo đã được ẩn.';
 const cleared=patch.kept===false?'Đã bỏ giữ. ':'Đã hủy bỏ qua. ';
 if(record.kept)return cleared+'Finding vẫn đang được giữ lại.';
 if(record.ignore_until>Date.now()/1000)return cleared+'Finding vẫn đang được bỏ qua đến '+date(record.ignore_until)+'.';
 if(!confirmed)return cleared+'Đang tải lại kết quả để kiểm tra.';
 const visible=scanFindings(activeScanRows(selectedScanId)).some(item=>feedbackKey(item)===feedbackKey(record));
 return cleared+(visible?'Finding đã hiện lại trong kết quả hiện tại.':'Finding chưa hiện trong kết quả hiện tại; cần quét mới để kiểm tra lại.');
}

function applyFeedbackToResults(record){
 results=results.map(row=>{
  if(row.region!==record.region)return row;
  const items=(row.findings||[]).flatMap(item=>{
   if(item.finding_id!==record.finding_id)return [item];
   if(record.kept||record.ignore_until>Date.now()/1000)return [];
   return [{...item,acknowledged:record.acknowledged===true}];
  });
  return {...row,findings:items};
 });
 const hidden=record.kept||record.ignore_until>Date.now()/1000;
 for(const [scanId,map] of scanRowsCache){
  const row=map.get(record.region);
  if(!row||row.scan_id!==scanId)continue;
  const items=(row.findings||[]).flatMap(item=>{
   if(item.finding_id!==record.finding_id)return [item];
   return hidden?[]:[{...item,acknowledged:record.acknowledged===true}];
  });
  map.set(record.region,{...row,findings:items});
 }
}

async function saveFindingFeedback(f,patch,generation){
 const key=feedbackKey(f);
 if(generation!==scopeGeneration||feedbackState.get(key)?.pending)return;
 const operation={pending:true,message:'Đang lưu…',error:false};
 feedbackState.set(key,operation);
 render();
 let saved=false;
 try{
  const record=await api('/feedback','PUT',{region:f.region,finding_id:f.finding_id,...patch});
  if(generation!==scopeGeneration||!token)return;
  saved=true;
  findingsRevision++;feedbackRevision++;feedbackRequest++;
  feedbackLoading=false;feedbackError='';
  const index=feedbackRows.findIndex(item=>feedbackKey(item)===key);
  if(index<0)feedbackRows.unshift(record);else feedbackRows[index]=record;
  applyFeedbackToResults(record);
  operation.pending=false;
  operation.message=feedbackSaveMessage(record,patch);
  render();
  status(operation.message);
  const confirmed=await refresh();
  if(generation!==scopeGeneration||!token||feedbackState.get(key)!==operation)return;
  operation.message=feedbackSaveMessage(record,patch,confirmed===true&&!resultsError);
  renderFeedback();
  renderFindings();
  status(operation.message);
  if(!feedbackLoaded&&!$('page-findings').hidden)loadFeedback();
 }catch(error){
  if(generation!==scopeGeneration||!token||feedbackState.get(key)!==operation)return;
  operation.pending=false;operation.error=true;
  operation.message=saved?'Phản hồi đã lưu, nhưng chưa tải được kết quả mới.':'Chưa lưu được phản hồi. '+friendlyError(error.message);
  render();
  status(operation.message,true);
 }
}

function findingFeedback(f){
 const key=feedbackKey(f),generation=scopeGeneration,state=feedbackState.get(key);
 const group=node('div',undefined,'finding-feedback');
 group.dataset.feedbackKey=key;
 const valid=typeof f.finding_id==='string'&&/^[a-f0-9]{64}$/.test(f.finding_id)&&(profile.regions||[]).includes(f.region);
 const menu=node('details',undefined,'actions-menu');
 menu.open=openFeedbackMenu===key;
 menu.addEventListener('toggle',()=>{
  if(menu.open){
   openFeedbackMenu=key;
   document.querySelectorAll('.actions-menu[open]').forEach(other=>{if(other!==menu)other.open=false;});
  }else if(openFeedbackMenu===key){
   openFeedbackMenu=null;
  }
 });
 menu.append(node('summary','Thao tác','actions-summary'));
 const body=node('div',undefined,'actions-body');
 const ack=node('button',f.acknowledged?'Bỏ đã xem':'Đánh dấu đã xem','button secondary feedback-ack');
 const keep=node('button','Giữ lại','button secondary feedback-keep');
 const ignore=node('button','Bỏ qua cảnh báo','button secondary feedback-ignore');
 for(const button of [ack,keep,ignore])button.type='button';
 ack.onclick=()=>saveFindingFeedback(f,{acknowledged:!f.acknowledged},generation);
 keep.onclick=()=>saveFindingFeedback(f,{kept:true},generation);
 ignore.onclick=()=>openIgnoreDialog(f,generation,ignore);
 for(const control of [ack,keep,ignore])control.disabled=!valid||!!state?.pending;
 const note=node('p',!valid?'Cảnh báo cũ thiếu mã hợp lệ; cần quét mới để phản hồi.':state?.message||'','feedback-status'+(state?.error?' error':''));
 note.setAttribute('role','status');
 note.tabIndex=-1;
 body.append(ack,keep,ignore,note);
 menu.append(body);
 group.append(menu);
 return group;
}

function openIgnoreDialog(f,generation,opener){
 ignoreTarget={f,generation};
 ignoreOpener=opener||document.activeElement;
 const dialog=$('ignore-dialog');
 $('ignore-context').textContent=(typeLabels[f.type]||f.type)+' · '+(f.resource_id||'')+' — cảnh báo sẽ được ẩn khỏi danh sách trong số ngày đã chọn. Tài nguyên trên AWS không bị thay đổi.';
 $('ignore-days').value='7';
 $('ignore-error').hidden=true;
 if(dialog&&!dialog.open)dialog.showModal();
 $('ignore-days').focus();
}
function closeIgnoreDialog(){
 const dialog=$('ignore-dialog');
 if(dialog&&dialog.open)dialog.close();
 ignoreTarget=null;
}

/* ------------------------------------------------------ history view */
function historyKey(row){return JSON.stringify(row.scan_id?[row.scan_id,row.region]:[null,row.region,row.created_at??null,row.started_at??null,row.completed_at??null]);}
function mergeHistoryRows(oldRows,newRows){const rows=new Map(oldRows.map(row=>[historyKey(row),row]));for(const row of newRows)rows.set(historyKey(row),row);return [...rows.values()];}

function renderHistory(){
 const container=$('history-list');if(!container)return;
 const pageControl=document.activeElement;
 container.replaceChildren();
 $('refresh-history').disabled=historyLoading;
 $('history-load-more').hidden=!historyCursor;
 $('history-load-more').disabled=historyLoading;
 $('history-load-more').textContent=historyLoading?'Đang tải…':'Tải thêm';
 const summary=$('history-summary');
 if([$('refresh-history'),$('history-load-more')].includes(pageControl)&&(pageControl.disabled||pageControl.hidden))summary.focus();
 summary.className=historyError?'error':'muted';
 summary.textContent=historyError?historyError:historyLoading?'Đang tải lịch sử…':historyRows.length+' lượt quét đã tải.';
 if(!historyRows.length){
  emptyState(container,historyError?'Không tải được lịch sử':historyLoading?'Đang tải lịch sử…':'Chưa có lịch sử quét','Lịch sử lưu tối đa 30 ngày cho kết nối hiện tại.');
  return;
 }
 const wrap=node('div',undefined,'table-wrap');
 const table=node('table',undefined,'history-table');
 const thead=node('thead'),tr=node('tr');
 for(const heading of ['Thời gian','AWS account','Region','Kích hoạt','Trạng thái','Tổng tài nguyên','Cần kiểm tra','Đang quan sát','Thiếu dữ liệu','Thao tác']){
  const th=node('th',heading);th.scope='col';tr.append(th);
 }
 thead.append(tr);table.append(thead);
 const body=node('tbody');
 for(const row of historyRows){
  const tr=node('tr');
  const findingsList=row.findings||[];
  const total=Object.values(row.counts||{}).reduce((sum,value)=>sum+(Number(value)||0),0);
  const review=findingsList.filter(f=>f.level==='REVIEW').length;
  const observing=findingsList.filter(f=>f.level==='OBSERVING').length;
  const insufficient=findingsList.filter(f=>f.level==='INSUFFICIENT_DATA').length;
  const statusCell=node('td');
  statusCell.append(badge(row.status));
  tr.append(
   node('td',date(row.started_at||row.completed_at)),
   node('td',row.account_id||profile?.account_id||'Không xác định'),
   node('td',row.region),
   node('td',triggerLabel(row.trigger)),
   statusCell,
   node('td',String(total)),
   node('td',String(review)),
   node('td',String(observing)),
   node('td',String(insufficient))
  );
  const actions=node('td',undefined,'history-actions');
  const key=historyKey(row);
  const detail=node('button','Chi tiết','button secondary history-open');
  detail.type='button';
  detail.dataset.historyKey=key;
  detail.setAttribute('aria-label','Xem chi tiết lượt quét '+date(row.started_at||row.completed_at)+' tại '+row.region);
  detail.onclick=()=>openHistoryScan(row);
  const view=node('button','Xem kết quả','button secondary history-results');
  view.type='button';
  view.dataset.historyKey=key;
  view.disabled=!row.scan_id;
  view.setAttribute('aria-label','Xem kết quả lượt quét '+date(row.started_at||row.completed_at)+' tại '+row.region);
  view.onclick=()=>{
   if(!row.scan_id)return;
   selectedScanId=row.scan_id;
   scanPinned=true;
   navigate('findings');
   selectScan(row.scan_id,{force:true});
  };
  actions.append(detail,view);
  tr.append(actions);
  body.append(tr);
 }
 table.append(body);wrap.append(table);container.append(wrap);
}

async function loadHistory(more=false){
 if(!profile)return;
 if(!more)historyAttempted=true;
 const generation=scopeGeneration,request=++historyRequest,cursor=more?historyCursor:null;
 if(more&&!cursor)return;
 historyLoading=true;if(!more)historyError='';
 if(!more){historySelection=null;historyDetailRows=[];historyDetailError='';historyDetailLoading=false;historyDetailRequest++;$('history-detail').replaceChildren();}
 renderHistory();
 try{
  const query=new URLSearchParams({limit:'20'});if(cursor)query.set('next_token',cursor);
  const reply=await api('/history?'+query);
  if(generation!==scopeGeneration||request!==historyRequest)return;
  if(!Array.isArray(reply.results)||(reply.next_token!=null&&typeof reply.next_token!=='string'))throw Error('Máy chủ trả lịch sử không hợp lệ.');
  historyRows=mergeHistoryRows(more?historyRows:[],validRows(reply.results));
  historyCursor=reply.next_token||null;
 }catch(e){
  if(generation!==scopeGeneration||request!==historyRequest)return;
  historyError='Không tải được lịch sử. '+friendlyError(e.message)+' Chọn Tải lại để thử lại.';
 }finally{
  if(generation===scopeGeneration&&request===historyRequest){
   historyLoading=false;renderHistory();
   if(!$('page-findings').hidden)renderFindings();
  }
 }
}

function rowsForHistoryScan(scanId){
 const rows=validRows(historyRows).filter(row=>row.scan_id===scanId);
 const cached=scanRowsCache.get(scanId);
 if(!cached)return rows;
 const map=new Map(rows.map(row=>[row.region,row]));
 for(const row of cached.values())if(!map.has(row.region))map.set(row.region,row);
 return [...map.values()];
}

function openHistoryScan(row){
 closeFindingDetail();
 historySelection=row;
 historyDetailRequest++;
 historyDetailError='';
 historyDetailLoading=false;
 historyDetailRows=row.scan_id?rowsForHistoryScan(row.scan_id):[row];
 renderHistoryDetail();
 const detail=$('history-detail');
 if(detail)detail.focus();
 if(row.scan_id)loadHistoryScan();
}

async function loadHistoryScan(){
 const selected=historySelection;
 if(!selected?.scan_id)return;
 const generation=scopeGeneration,request=++historyDetailRequest;
 historyDetailLoading=true;historyDetailError='';
 renderHistoryDetail();
 const detail=$('history-detail');
 if(detail)detail.focus();
 try{
  const reply=await api('/scans/'+encodeURIComponent(selected.scan_id));
  if(generation!==scopeGeneration||request!==historyDetailRequest)return;
  if(!Array.isArray(reply.results))throw Error('Máy chủ trả chi tiết không hợp lệ.');
  const map=new Map();
  for(const row of validRows(reply.results))if(row.scan_id===selected.scan_id)map.set(row.region,row);
  if(!map.size)throw Error('Không tìm thấy dữ liệu cho lượt quét này.');
  scanRowsCache.set(selected.scan_id,map);
  historyDetailRows=[...map.values()];
 }catch(e){
  if(generation!==scopeGeneration||request!==historyDetailRequest)return;
  historyDetailError='Chưa tải đủ chi tiết. '+friendlyError(e.message);
 }finally{
  if(generation===scopeGeneration&&request===historyDetailRequest){historyDetailLoading=false;renderHistoryDetail();}
 }
}

function renderHistoryDetail(){
 const detail=$('history-detail');if(!detail)return;
 detail.replaceChildren();
 if(!historySelection)return;
 const row=historySelection;
 const rows=historyDetailRows.length?historyDetailRows:[row];
 const meta=node('section',undefined,'scan-detail-card');
 const header=node('div',undefined,'scan-detail-header');
 const title=node('div');
 title.append(node('h3','Chi tiết lượt quét'),node('p','Scan ID: '+(row.scan_id||'Chưa có dữ liệu'),'muted'));
 header.append(title,badge(row.status));
 meta.append(header);
 if(!row.scan_id)meta.append(node('p','Dữ liệu cũ thiếu Scan ID; chỉ hiển thị snapshot đã lưu của region này.','muted'));
 const regions=node('div',undefined,'history-regions');
 for(const item of rows){
  const card=node('article',undefined,'history-region');
  const regionHead=node('div',undefined,'history-region-head');
  regionHead.append(node('h4',(regionNames[item.region]||item.region)+' — '+item.region),badge(item.status));
  card.append(regionHead);
  const dl=node('dl',undefined,'scan-meta-grid');
  const metaRows=[
   ['account','AWS account',item.account_id||profile?.account_id||'Chưa có dữ liệu'],
   ['region','Region',item.region],
   ['trigger','Kiểu kích hoạt',item.trigger?triggerLabel(item.trigger):'Chưa có dữ liệu'],
   ['status','Trạng thái',scanStatusLabels[item.status]||item.status||'Chưa có dữ liệu'],
   ['started_at','Thời gian bắt đầu',item.started_at?date(item.started_at):'Chưa có dữ liệu'],
   ['completed_at','Thời gian hoàn tất',item.completed_at?date(item.completed_at):(item.status==='TIMED_OUT'?'Chưa có dữ liệu':'Đang xử lý')],
   ['counts','Tổng tài nguyên đã kiểm tra',String(Object.values(item.counts||{}).reduce((sum,value)=>sum+(Number(value)||0),0))]
  ];
  if(item.error_code)metaRows.push(['error_code','Mã lỗi',item.error_code]);
  if(item.request_id)metaRows.push(['request_id','Request ID',item.request_id]);
  for(const [key,label,value] of metaRows){
   const cell=node('div');cell.dataset.field=key;
   cell.append(node('dt',label),node('dd',value));
   dl.append(cell);
  }
  card.append(dl);
  if(item.error)card.append(node('p',friendlyError(item.error),'error'));
  if((item.errors||[]).length){
   const box=node('div',undefined,'scan-errors-alert');
   box.append(node('h4','Dịch vụ chưa đọc được trong lượt quét'));
   const ul=node('ul');
   for(const error of item.errors){
    const desc=errorDescriptions[error.code]?' ('+errorDescriptions[error.code]+')':'';
    ul.append(node('li',error.type+': '+error.code+desc));
   }
   box.append(ul);card.append(box);
  }
  if(item.status==='PARTIAL')card.append(node('p','Lượt quét chưa hoàn tất đầy đủ; không kết luận tài nguyên đã được giải quyết.','muted'));
  const findingsList=item.findings||[];
  if(findingsList.length){
   const withContext=findingsList.map(f=>({...f,region:f.region||item.region,scan_id:f.scan_id||item.scan_id}));
   card.append(node('h4','Findings đã lưu của region này ('+findingsList.length+')'));
   card.append(findingTable(withContext,false));
  }else{
   card.append(node('p','Không có finding nào được lưu cho region này.','muted'));
  }
  regions.append(card);
 }
 meta.append(regions);
 if(historyDetailLoading)meta.append(node('p','Đang tải đầy đủ chi tiết lượt quét…','muted history-detail-loading'));
 if(historyDetailError){
  const retry=node('button','Thử lại chi tiết','button secondary history-detail-retry');
  retry.type='button';
  retry.onclick=()=>loadHistoryScan();
  meta.append(node('p',historyDetailError,'error'),retry);
 }
 detail.append(meta);
}

/* -------------------------------------------------------- feedback page */
async function loadFeedback(more=false){
 if(!profile)return;
 const generation=scopeGeneration,revision=feedbackRevision,request=++feedbackRequest,cursor=more?feedbackCursor:null;
 if(more&&!cursor)return;
 feedbackLoading=true;if(!more)feedbackError='';
 renderFeedback();
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
 const list=$('feedback-list');if(!list)return;
 const previous=feedbackFocus(list),pageControl=document.activeElement;
 const active=feedbackRows.filter(feedbackHidden);
 list.replaceChildren();
 $('feedback-summary').textContent=feedbackError||(feedbackLoading?'Đang tải phản hồi…':active.length+' finding đang giữ hoặc bỏ qua trong '+feedbackRows.length+' phản hồi đã tải.'+(feedbackCursor?' Còn phản hồi ở trang sau.':''));
 $('feedback-summary').className=feedbackError?'error':'muted';
 $('refresh-feedback').disabled=feedbackLoading;
 $('feedback-load-more').hidden=!feedbackCursor;
 $('feedback-load-more').disabled=feedbackLoading;
 $('feedback-load-more').textContent=feedbackLoading?'Đang tải…':'Tải thêm';
 if([$('refresh-feedback'),$('feedback-load-more')].includes(pageControl)&&(pageControl.disabled||pageControl.hidden))$('feedback-summary').focus();
 if(!active.length){
  emptyState(list,feedbackLoading?'Đang tải danh sách':feedbackCursor?'Chưa có finding đang ẩn trong phần đã tải':feedbackLoaded?'Không có finding đang giữ hoặc bỏ qua trong danh sách đã tải':'Chưa tải phản hồi',feedbackCursor?'Chọn Tải thêm để kiểm tra trang tiếp theo.':'Chọn Tải lại để cập nhật phản hồi của kết nối hiện tại.');
  return;
 }
 for(const record of active){
  const key=feedbackKey(record),generation=scopeGeneration,state=feedbackState.get(key);
  const article=node('article',undefined,'feedback-record');
  article.dataset.feedbackKey=key;
  const info=node('div');
  info.append(node('h3',typeLabels[record.type]||record.type||'Finding cũ'));
  info.append(node('code',record.resource_id||record.finding_id));
  if(record.resource_id)info.append(node('small','Finding ID: '+record.finding_id,'muted'));
  else info.append(node('p','Feedback cũ thiếu metadata; quản lý bằng Finding ID và region.','footnote'));
  info.append(node('p','Region: '+record.region+' · Account: '+(record.account_id||profile?.account_id||'Không xác định')+' · Rule: '+(record.rule_id||'Chưa có dữ liệu'),'muted'));
  if(record.kept)info.append(badge('KEPT','level'));
  if(record.ignore_until>Date.now()/1000)info.append(node('p','Bỏ qua đến: '+date(record.ignore_until),'muted'));
  if(record.acknowledged)info.append(node('p','Đã xem','acknowledged-state'));
  const actions=node('div',undefined,'finding-feedback feedback-manager-actions');
  actions.dataset.feedbackKey=key;
  const unkeep=node('button','Bỏ giữ','button secondary feedback-unkeep');
  const unignore=node('button','Hủy bỏ qua','button secondary feedback-unignore');
  const label=node('label','Hạn bỏ qua mới');
  const days=node('select',undefined,'feedback-manage-days');
  const extend=node('button','Đổi hạn bỏ qua','button secondary feedback-extend');
  if(!managedDays.has(key))managedDays.set(key,7);
  for(let day=1;day<=30;day++)days.append(new Option(day+' ngày',day));
  days.value=managedDays.get(key);
  days.setAttribute('aria-label','Hạn bỏ qua mới cho '+(record.resource_id||record.finding_id));
  label.append(days);
  days.onchange=()=>managedDays.set(key,Number(days.value));
  unkeep.disabled=!record.kept||!!state?.pending;
  unignore.disabled=!(record.ignore_until>Date.now()/1000)||!!state?.pending;
  days.disabled=extend.disabled=!!state?.pending;
  unkeep.onclick=()=>saveFindingFeedback(record,{kept:false},generation);
  unignore.onclick=()=>saveFindingFeedback(record,{ignoreUntil:null},generation);
  extend.onclick=()=>{
   const count=Number(days.value);
   if(Number.isInteger(count)&&count>=1&&count<=30)saveFindingFeedback(record,{ignoreUntil:new Date(Date.now()+count*86400000).toISOString()},generation);
  };
  for(const button of [unkeep,unignore,extend])button.type='button';
  const note=node('p',state?.message||'','feedback-status'+(state?.error?' error':''));
  note.setAttribute('role','status');
  note.tabIndex=-1;
  actions.append(unkeep,unignore,label,extend,note);
  article.append(info,actions);
  list.append(article);
 }
 restoreFeedbackFocus(list,previous);
}

/* ------------------------------------------------------------ settings */
function render(){
 if(!profile)return;
 renderAccount();
 renderOverview();
 renderFindings();
 renderFeedback();
}

function createFieldElement(key,meta,currentValue){
 const fMeta=friendlyFieldMeta[key]||{};
 const labelText=fMeta.label||meta.label||key;
 const unitText=fMeta.unit||meta.unit||'';
 const rangeText=`Hợp lệ: ${meta.min} – ${meta.max}${unitText?' '+unitText:''} · Mặc định: ${meta.default}${unitText?' '+unitText:''}`;
 const helpText=fMeta.help||`Cảnh báo kích hoạt khi giá trị vượt ngưỡng ${meta.default} ${unitText}.`;
 const wrap=node('div',undefined,'field-wrap');
 const label=node('label',undefined,'field-label');
 label.htmlFor=key;
 label.append(node('span',labelText));
 wrap.append(label);
 wrap.append(node('p',helpText,'field-desc'));
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
  if(!err){err=node('small',`Giá trị phải trong khoảng ${meta.min} – ${meta.max}${unitText?' '+unitText:''}`,'field-help-error');wrap.append(err);}
 };
 inputWrap.append(input);
 if(unitText)inputWrap.append(node('span',unitText,'field-unit-badge'));
 wrap.append(inputWrap);
 wrap.append(node('small',rangeText,'field-limits'));
 return wrap;
}

function renderSettingsUI(){
 if(!profile)return;
 const activeThresholds=profile.threshold_metadata||defaultThresholdConfig;
 const groupsContainer=$('settings-groups');
 if(groupsContainer){
  groupsContainer.replaceChildren();
  const renderedFields=new Set();
  serviceHierarchy.forEach(hierarchyGroup=>{
   const details=node('details',undefined,'settings-group');
   details.open=openSettingsGroups.has(hierarchyGroup.group);
   details.addEventListener('toggle',()=>{
    if(details.open)openSettingsGroups.add(hierarchyGroup.group);else openSettingsGroups.delete(hierarchyGroup.group);
   });
   const summary=node('summary');
   const rawFields=hierarchyGroup.services.reduce((acc,service)=>acc+service.fields.filter(key=>!!activeThresholds[key]).length,0);
   summary.append(node('span',hierarchyGroup.title,'group-title'),node('span',rawFields+' cài đặt','group-badge'));
   details.append(summary);
   const body=node('div',undefined,'settings-group-body');
   hierarchyGroup.services.forEach(service=>{
    const validFields=service.fields.filter(key=>!!activeThresholds[key]&&!renderedFields.has(key));
    if(!validFields.length)return;
    validFields.forEach(key=>renderedFields.add(key));
    const card=node('div',undefined,'service-card');
    card.append(node('h4',service.name,'service-card-title'));
    if(service.desc)card.append(node('p',service.desc,'service-card-desc'));
    const grid=node('div',undefined,'service-grid');
    for(const fieldKey of validFields)grid.append(createFieldElement(fieldKey,activeThresholds[fieldKey],profile.settings[fieldKey]));
    card.append(grid);body.append(card);
   });
   details.append(body);groupsContainer.append(details);
  });
 }
 const restore=$('restore-defaults');
 if(restore){
  restore.onclick=()=>{
   for(const [key,meta] of Object.entries(activeThresholds)){
    const el=$(key);if(el)el.value=meta.default;
   }
   const unsaved=$('unsaved-indicator');if(unsaved)unsaved.hidden=false;
   status('Đã khôi phục các giá trị mặc định.');
  };
 }
}

function renderPrincipals(){
 $('principals').replaceChildren();
 for(const [name,value] of [['ApiPrincipal',profile.api_principal],['ScanPrincipal',profile.scan_principal],['ExternalId',profile.external_id]]){
  const row=node('div',undefined,'parameter-row'),label=node('label',name),input=node('textarea'),button=node('button','Sao chép '+name,'button secondary');
  input.id='param-'+name;input.value=value||'';input.readOnly=true;input.rows=name==='ExternalId'?2:3;input.spellcheck=false;
  label.htmlFor=input.id;button.type='button';button.disabled=!value;
  button.onclick=()=>run(async()=>{
   try{await navigator.clipboard.writeText(input.value);button.textContent='Đã sao chép';status('Đã sao chép '+name+'.');}
   catch{input.focus();input.select();status('Dùng Ctrl+C để sao chép.',true);}
  },button);
  row.append(label,input,button);
  $('principals').append(row);
 }
}

/* ---------------------------------------------------------------- data */
function resetScopeState(){
 results=[];historyRows=[];historyCursor=null;historyLoading=false;historyError='';historyRequest++;historyAttempted=false;
 historySelection=null;historyDetailRows=[];historyDetailLoading=false;historyDetailError='';historyDetailRequest++;
 feedbackState.clear();managedDays.clear();
 feedbackRows=[];feedbackCursor=null;feedbackLoaded=false;feedbackLoading=false;feedbackError='';feedbackRequest++;feedbackRevision=0;
 findingsRevision=0;
 selectedScanId=null;scanPinned=false;scanRowsCache.clear();scanRequest++;scanLoading=false;scanLoadError='';
 openGroups.clear();groupLimits.clear();groupDefaultsScan=undefined;groupsUserToggled=false;chartExpanded=false;
 const sel=$('scan-select');if(sel){sel.replaceChildren();delete sel.dataset.signature;}
 const list=$('findings-list');if(list)list.replaceChildren();
 const priority=$('priority-list');if(priority)priority.replaceChildren();
 const detail=$('history-detail');if(detail)detail.replaceChildren();
 const history=$('history-list');if(history)history.replaceChildren();
 const feedback=$('feedback-list');if(feedback)feedback.replaceChildren();
 clearTimeout(pollTimer);
}

async function init(){
 closeFindingDetail();
 closeIgnoreDialog();
 const generation=++scopeGeneration;
 resetScopeState();
 const nextProfile=await api('/me');
 if(generation!==scopeGeneration)return;
 profile=nextProfile;
 $('app').hidden=false;
 $('welcome').hidden=true;
 $('nav-auth').hidden=false;
 $('nav-guest').hidden=true;
 $('login').hidden=true;
 $('login').textContent='Đăng xuất';
 $('login').onclick=logout;
 $('nav-logout').onclick=logout;
 renderPrincipals();
 $('role').value=profile.role_arn||'';
 $('region-options').replaceChildren();
 for(const region of regions){
  const label=node('label'),input=node('input');
  input.type='checkbox';input.value=region;
  input.checked=(profile.regions||['ap-southeast-1']).includes(region);
  const text=node('span',regionNames[region]||region);
  text.append(node('small',region));
  label.append(input,text);
  $('region-options').append(label);
 }
 $('service-group-options').replaceChildren();
 for(const [group,value] of Object.entries(serviceGroups)){
  const label=node('label'),input=node('input');
  input.type='checkbox';input.value=group;
  input.checked=(profile.service_groups||defaultServiceGroups).includes(group);
  const text=node('span',value.label);
  text.append(node('small',value.types.join(' / ')));
  label.append(input,text);
  $('service-group-options').append(label);
 }
 $('filter-type').replaceChildren(new Option('Tất cả',''));
 delete $('filter-type').dataset.signature;
 $('filter-group').replaceChildren(new Option('Tất cả',''));
 delete $('filter-group').dataset.signature;
 $('filter-region').replaceChildren(new Option('Tất cả',''));
 delete $('filter-region').dataset.signature;
 for(const id of ['search','filter-level','filter-acknowledged'])$(id).value='';
 renderSettingsUI();
 $('email-enabled').checked=!!profile.notifications?.enabled;
 $('email-enabled').disabled=!profile.email_available;
 $('save-email').disabled=!profile.email_available;
 $('email-note').textContent=profile.email_available?(profile.notifications?.email?'Địa chỉ: '+profile.notifications.email:'Dùng email Cognito đã xác minh.'):'Cảnh báo email chưa được bật.';
 loadingResults=true;resultsError=false;results=[];
 render();
 showPage(location.hash.slice(1)||'overview');
 await refresh();
 if(generation!==scopeGeneration)return;
 status(cfg?.demo?'Bản demo với dữ liệu mẫu.':'');
}

async function refresh(){
 const generation=scopeGeneration,revision=findingsRevision;
 try{
  const reply=await api('/findings');
  if(generation!==scopeGeneration||revision!==findingsRevision)return false;
  results=validRows(reply.results);
  resultsError=false;loadingResults=false;
  render();
  if(results.some(row=>['QUEUED','RUNNING'].includes(row.status))&&pollCount<185){
   clearTimeout(pollTimer);
   pollTimer=setTimeout(()=>{pollCount++;run(refresh);},5000);
  }else{
   clearTimeout(pollTimer);
  }
  return true;
 }catch(e){
  if(generation!==scopeGeneration||revision!==findingsRevision)return false;
  loadingResults=false;resultsError=true;clearTimeout(pollTimer);render();throw e;
 }
}

/* --------------------------------------------------------------- events */
document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>navigate(button.dataset.page));
document.querySelectorAll('[data-go]').forEach(button=>button.onclick=()=>navigate(button.dataset.go));
window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));

if($('scan-select'))$('scan-select').onchange=()=>{
 const id=$('scan-select').value;
 if(id){scanPinned=true;selectScan(id,{force:true});}
};

for(const id of ['search','filter-type','filter-level','filter-group','filter-region','filter-acknowledged']){
 const el=$(id);
 if(el)el.addEventListener('input',()=>renderFindings());
}

document.addEventListener('pointerdown',event=>{
 const target=event.target;
 if(target&&typeof target.closest==='function'&&target.closest('.actions-menu'))return;
 document.querySelectorAll('.actions-menu[open]').forEach(menu=>{menu.open=false;});
},true);

$('finding-dialog').onclose=restoreFindingFocus;
$('close-finding-detail').onclick=()=>{$('finding-dialog').close();restoreFindingFocus();};

$('ignore-form').onsubmit=event=>{
 event.preventDefault();
 if(!ignoreTarget)return;
 const value=Number($('ignore-days').value);
 if(!Number.isInteger(value)||value<1||value>30){
  $('ignore-error').textContent='Số ngày phải là số nguyên từ 1 đến 30.';
  $('ignore-error').hidden=false;
  $('ignore-days').focus();
  return;
 }
 const target=ignoreTarget;
 $('ignore-error').hidden=true;
 closeIgnoreDialog();
 saveFindingFeedback(target.f,{ignoreUntil:new Date(Date.now()+value*86400000).toISOString()},target.generation);
};
$('ignore-cancel').onclick=()=>closeIgnoreDialog();
$('ignore-dialog').onclose=()=>{
 ignoreTarget=null;
 const opener=ignoreOpener;
 ignoreOpener=null;
 if(opener&&opener.isConnected&&!$('app').hidden)opener.focus();
};

$('connection-form').onsubmit=event=>{
 event.preventDefault();
 run(async()=>{
  let saved=false;
  const feedback=$('connection-feedback');
  feedback.hidden=false;feedback.className='';feedback.textContent='Đang kiểm tra AWS…';
  $('connect').textContent='Đang kiểm tra…';
  try{
   const selected=[...document.querySelectorAll('#region-options input:checked')].map(input=>input.value);
   if(selected.length<1||selected.length>3)throw Error('Chọn từ 1 đến 3 region.');
   const groups=[...document.querySelectorAll('#service-group-options input:checked')].map(input=>input.value);
   if(groups.length<1)throw Error('Chọn ít nhất 1 nhóm dịch vụ.');
   const arn=$('role').value.trim();
   if(arn===profile.api_principal||arn===profile.scan_principal)throw Error('Không dùng principal ARN của hệ thống; hãy dùng role GuardianReadRole-<suffix> trong AWS account cần quét.');
   if(!/^arn:aws:iam::\d{12}:role\/GuardianReadRole-[A-Za-z0-9+=,.@_-]{1,40}$/.test(arn))throw Error('Nhập RoleArn hợp lệ: arn:aws:iam::123456789012:role/GuardianReadRole-<suffix>.');
   await api('/connection','PUT',{role_arn:arn,regions:selected,service_groups:groups});
   saved=true;
   await init();
   feedback.textContent='Đã lưu kết nối AWS. Tiếp tục bước 3 để chạy lần quét đầu tiên.';
   status('Đã lưu kết nối AWS.');
  }catch(e){
   feedback.className='error';
   feedback.textContent=(saved?'Kết nối đã lưu nhưng chưa tải được dữ liệu mới. ':'')+friendlyError(e.message)+(saved?'':' Kiểm tra lại RoleArn, ExternalId và quyền AssumeRole của target role.');
   throw e;
  }finally{$('connect').textContent='Kiểm tra và lưu kết nối';}
 },$('connect'));
};

$('settings-form').onsubmit=event=>{
 event.preventDefault();
 run(async()=>{
  const saveBtn=$('save-settings');
  saveBtn.textContent='Đang lưu…';
  const values={};
  const activeThresholds=profile.threshold_metadata||defaultThresholdConfig;
  for(const [key,meta] of Object.entries(activeThresholds)){
   const el=$(key);
   if(!el)continue;
   const value=el.valueAsNumber;
   const fMeta=friendlyFieldMeta[key]||{};
   const label=fMeta.label||meta.label||key;
   if(!Number.isFinite(value)||value<meta.min||value>meta.max||(meta.integer&&!Number.isInteger(value))){
    el.focus();
    throw Error('Vui lòng nhập giá trị hợp lệ từ '+meta.min+' đến '+meta.max+(meta.unit?' ('+meta.unit+')':'')+' cho '+label+'.');
   }
   values[key]=value;
  }
  profile.settings=await api('/settings','PUT',values);
  $('unsaved-indicator').hidden=true;
  status('Đã lưu ngưỡng phát hiện.');
  saveBtn.textContent='Lưu thay đổi';
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
  const reply=await api('/scans','POST');
  sessionStorage.setItem('crg-last-scan',reply.scan_id);
  pollCount=0;
  status('Đã nhận yêu cầu quét. Đang cập nhật kết quả…');
  await refresh();
 }finally{scanPending=false;render();}
},$('scan'));

$('first-scan').onclick=()=>{navigate('overview');$('scan').click();};
$('refresh').onclick=()=>run(async()=>{pollCount=0;await refresh();status('Đã tải lại kết quả.');},$('refresh'));
$('refresh-history').onclick=()=>loadHistory();
$('history-load-more').onclick=()=>loadHistory(true);
$('refresh-feedback').onclick=()=>loadFeedback();
if($('service-chart-more'))$('service-chart-more').onclick=()=>{
 chartExpanded=!chartExpanded;
 renderFindings();
 if(chartExpanded){
  const chart=$('service-chart');
  if(chart)chart.scrollIntoView({behavior:'smooth',block:'start'});
 }
};
$('feedback-load-more').onclick=()=>loadFeedback(true);
$('start').onclick=()=>run(login,$('start'));

$('register-form').onsubmit=event=>{
 event.preventDefault();
 const email=$('reg-email').value.trim();
 const password=$('reg-password').value;
 const confirm=$('reg-confirm').value;
 const feedback=$('reg-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){feedback.className='inline-feedback error';feedback.textContent='Định dạng email không hợp lệ.';return false;}
 const pwErr=validatePassword(password);
 if(pwErr){feedback.className='inline-feedback error';feedback.textContent=pwErr;return false;}
 if(password!==confirm){feedback.className='inline-feedback error';feedback.textContent='Mật khẩu xác nhận không khớp.';return false;}
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
  await cognitoIdp('SignUp',{ClientId:cfg?.clientId,Username:email,Password:password,UserAttributes:[{Name:'email',Value:email}]});
  $('verify-email').value=email;
  $('verify-info').textContent='Mã xác minh đã được gửi tới email '+email+'.';
  showGuestView('verify');
  status('Đăng ký thành công! Mã xác minh đã được gửi tới email của bạn.');
 },$('reg-submit'));
 return false;
};

$('verify-form').onsubmit=event=>{
 event.preventDefault();
 const email=$('verify-email').value.trim();
 const code=$('verify-code').value.trim();
 const feedback=$('verify-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!code){feedback.className='inline-feedback error';feedback.textContent='Vui lòng nhập mã xác minh.';return false;}
 run(async()=>{
  if(cfg?.demo){
   const expected=demoAuth.pending.get(email)||'123456';
   if(code!==expected)throw Error('Mã xác minh không chính xác.');
   demoAuth.pending.delete(email);
   demoAuth.verified.add(email);
   showGuestView('login');
   status('Xác minh tài khoản thành công! Bạn có thể đăng nhập.');
   return;
  }
  await cognitoIdp('ConfirmSignUp',{ClientId:cfg?.clientId,Username:email,ConfirmationCode:code});
  showGuestView('login');
  status('Xác minh tài khoản thành công! Bạn có thể đăng nhập.');
 },$('verify-submit'));
 return false;
};

$('verify-resend').onclick=()=>{
 const email=$('verify-email').value.trim();
 if(!email){status('Thiếu email để gửi lại mã.',true);return;}
 run(async()=>{
  if(cfg?.demo){status('Đã gửi lại mã xác minh tới '+email+'. (Demo: 123456)');return;}
  await cognitoIdp('ResendConfirmationCode',{ClientId:cfg?.clientId,Username:email});
  status('Đã gửi lại mã xác minh tới '+email+'.');
 },$('verify-resend'));
};

$('forgot-form').onsubmit=event=>{
 event.preventDefault();
 const email=$('forgot-email').value.trim();
 const feedback=$('forgot-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){feedback.className='inline-feedback error';feedback.textContent='Định dạng email không hợp lệ.';return false;}
 run(async()=>{
  if(cfg?.demo){
   demoAuth.resetCodes.set(email,'123456');
   $('reset-email').value=email;
   showGuestView('reset');
   status('Mã đặt lại mật khẩu đã được gửi tới '+email+'. (Demo: 123456)');
   return;
  }
  await cognitoIdp('ForgotPassword',{ClientId:cfg?.clientId,Username:email});
  $('reset-email').value=email;
  showGuestView('reset');
  status('Mã đặt lại mật khẩu đã được gửi tới email của bạn.');
 },$('forgot-submit'));
 return false;
};

$('reset-form').onsubmit=event=>{
 event.preventDefault();
 const email=$('reset-email').value.trim();
 const code=$('reset-code').value.trim();
 const password=$('reset-password').value;
 const confirm=$('reset-confirm').value;
 const feedback=$('reset-feedback');
 feedback.hidden=false;feedback.className='inline-feedback';
 if(!isValidEmail(email)){feedback.className='inline-feedback error';feedback.textContent='Định dạng email không hợp lệ.';return false;}
 if(!code){feedback.className='inline-feedback error';feedback.textContent='Vui lòng nhập mã xác minh.';return false;}
 const pwErr=validatePassword(password);
 if(pwErr){feedback.className='inline-feedback error';feedback.textContent=pwErr;return false;}
 if(password!==confirm){feedback.className='inline-feedback error';feedback.textContent='Mật khẩu xác nhận không khớp.';return false;}
 run(async()=>{
  $('reset-password').value='';$('reset-confirm').value='';
  if(cfg?.demo){
   const expected=demoAuth.resetCodes.get(email)||'123456';
   if(code!==expected)throw Error('Mã xác minh không chính xác.');
   demoAuth.resetCodes.delete(email);
   showGuestView('login');
   status('Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới.');
   return;
  }
  await cognitoIdp('ConfirmForgotPassword',{ClientId:cfg?.clientId,Username:email,ConfirmationCode:code,Password:password});
  showGuestView('login');
  status('Đặt lại mật khẩu thành công! Bạn có thể đăng nhập bằng mật khẩu mới.');
 },$('reset-submit'));
 return false;
};

document.querySelectorAll('.btn-toggle-pw').forEach(button=>{
 button.onclick=()=>{
  const input=$(button.dataset.for);
  if(!input)return;
  const isPassword=input.type==='password';
  input.type=isPassword?'text':'password';
  button.textContent=isPassword?'Ẩn':'Hiện';
 };
});
document.querySelectorAll('[data-guest]').forEach(button=>button.onclick=()=>showGuestView(button.dataset.guest));
document.querySelectorAll('[data-switch]').forEach(button=>button.onclick=()=>showGuestView(button.dataset.switch));

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

/* ----------------------------------------------------------------- boot */
(async()=>{
 try{
  const response=await fetch('config.json',{cache:'no-store'});
  if(!response.ok)throw Error('Không tải được cấu hình ứng dụng.');
  cfg=await response.json();
  window.cfg=cfg;
  $('demo-banner').hidden=!cfg.demo;
  $('login').onclick=()=>token?logout():showGuestView('login');
  if(cfg.demo)$('start').textContent='Đăng nhập demo';
  const query=new URLSearchParams(location.search);
  if(query.has('error'))throw Error(query.get('error_description')||query.get('error'));
  if(query.has('code')){
   if(query.get('state')!==sessionStorage.getItem('crg-state')||!sessionStorage.getItem('crg-state'))throw Error('OAuth state không khớp. Hãy đăng nhập lại.');
   const verifier=sessionStorage.getItem('crg-verifier');
   const tokenResponse=await fetch(cfg.auth+'/oauth2/token',{
    method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({
     grant_type:'authorization_code',
     client_id:cfg.clientId,
     code:query.get('code'),
     redirect_uri:cfg.redirect,
     code_verifier:verifier
    })
   });
   const value=await tokenResponse.json();
   if(!tokenResponse.ok)throw Error('Không đổi được authorization code.');
   token=value.access_token;
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
