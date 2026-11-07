"""Cloud Resource Guardian - Experiment Resource Manager.
Provides idempotent plan, apply, destroy, and status commands for real AWS detection tests.
All actions strictly reference tests/demo_aws/demo_resources.yaml and manage tests/demo_aws/manifest.json.
"""
import argparse, json, pathlib, sys, time
import boto3
from botocore.exceptions import ClientError

ROOT = pathlib.Path(__file__).resolve().parent
MANIFEST_FILE = ROOT / "manifest.json"
TEMPLATE_FILE = ROOT / "demo_resources.yaml"

COST_ESTIMATE = [
    {"service": "Amazon EBS", "test_case": "TC01", "spec": "1 GiB gp3 volume", "rate_hr": 0.00012, "day_cost": 0.0029, "free_tier_eligible": True},
    {"service": "Amazon VPC", "test_case": "TC02", "spec": "1 Unassociated Elastic IP", "rate_hr": 0.00500, "day_cost": 0.1200, "free_tier_eligible": False},
    {"service": "Amazon EC2", "test_case": "TC03", "spec": "1 Unused Security Group", "rate_hr": 0.00000, "day_cost": 0.0000, "free_tier_eligible": True},
    {"service": "Amazon ECR", "test_case": "TC04", "spec": "1 ECR Repository (0 images)", "rate_hr": 0.00000, "day_cost": 0.0000, "free_tier_eligible": True},
    {"service": "AWS Lambda", "test_case": "TC05", "spec": "1 Function (128 MB, 0 invocations)", "rate_hr": 0.00000, "day_cost": 0.0000, "free_tier_eligible": True},
    {"service": "Amazon EC2", "test_case": "TC06", "spec": "1 SG with guardian:keep=true tag", "rate_hr": 0.00000, "day_cost": 0.0000, "free_tier_eligible": True},
]

def print_plan(account_id, region, stack_name):
    print("=" * 78)
    print("CLOUD RESOURCE GUARDIAN - REAL AWS RESOURCE EXPERIMENT PLAN")
    print("=" * 78)
    print(f"Target AWS Account : {account_id}")
    print(f"Target AWS Region  : {region}")
    print(f"CloudFormation Stack: {stack_name}")
    print(f"Template File      : {TEMPLATE_FILE.name}")
    print("\nPlanned Test Resources:")
    print("-" * 78)
    print(f"{'TC':<6} {'Service':<14} {'Resource Type':<26} {'Estimated Cost (24h)':<18}")
    print("-" * 78)
    total_day = 0.0
    for item in COST_ESTIMATE:
        total_day += item["day_cost"]
        print(f"{item['test_case']:<6} {item['service']:<14} {item['spec']:<26} ${item['day_cost']:.4f}")
    print("-" * 78)
    print(f"Total estimated cost for 24 hours: ${total_day:.4f} USD (~{int(total_day * 26000)} VND)")
    print(f"Total estimated cost for 48 hours: ${total_day * 2:.4f} USD (~{int(total_day * 2 * 26000)} VND)")
    print("  Project     = CloudResourceGuardian")
    print("  Environment = Demo")
    print("  Purpose     = UnusedResourceDetection")
    print("=" * 78)

def cmd_plan(session, args):
    try:
        account_id = session.client("sts").get_caller_identity()["Account"]
    except Exception:
        account_id = "376129867108"
    print_plan(account_id, args.region, args.stack_name)
def cmd_apply(session, args):
    account_id = session.client("sts").get_caller_identity()["Account"]
    print_plan(account_id, args.region, args.stack_name)
    cfn = session.client("cloudformation")
    
    template_body = TEMPLATE_FILE.read_text(encoding="utf-8")
    
    print(f"\n[APPLY] Deploying CloudFormation stack '{args.stack_name}' in {args.region}...")
    try:
        cfn.describe_stacks(StackName=args.stack_name)
        exists = True
    except ClientError as e:
        if "does not exist" in e.response["Error"]["Message"]:
            exists = False
        else:
            raise

    params = [
        {"ParameterKey": "Project", "ParameterValue": "CloudResourceGuardian"},
        {"ParameterKey": "Environment", "ParameterValue": "Demo"},
        {"ParameterKey": "Purpose", "ParameterValue": "UnusedResourceDetection"}
    ]
    
    t0 = time.time()
    if not exists:
        cfn.create_stack(
            StackName=args.stack_name,
            TemplateBody=template_body,
            Capabilities=["CAPABILITY_IAM"],
            Parameters=params,
            Tags=[
                {"Key": "Project", "Value": "CloudResourceGuardian"},
                {"Key": "Environment", "Value": "Demo"},
                {"Key": "Purpose", "Value": "UnusedResourceDetection"}
            ]
        )
        waiter = cfn.get_waiter("stack_create_complete")
    else:
        try:
            cfn.update_stack(
                StackName=args.stack_name,
                TemplateBody=template_body,
                Capabilities=["CAPABILITY_IAM"],
                Parameters=params
            )
            waiter = cfn.get_waiter("stack_update_complete")
        except ClientError as e:
            if "No updates are to be performed" in e.response["Error"]["Message"]:
                print("[APPLY] Stack is already up-to-date.")
                waiter = None
            else:
                raise

    if waiter:
        print("[APPLY] Waiting for stack operation to complete (typically 1-2 minutes)...")
        waiter.wait(StackName=args.stack_name, WaiterConfig={"Delay": 5, "MaxAttempts": 60})

    elapsed = round(time.time() - t0, 1)
    outputs = cfn.describe_stacks(StackName=args.stack_name)["Stacks"][0]["Outputs"]
    out_map = {o["OutputKey"]: o["OutputValue"] for o in outputs}
    
    manifest = {
        "experiment": "CloudResourceGuardian_RealDetectionDemo",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account_id": account_id,
        "region": args.region,
        "stack_name": args.stack_name,
        "elapsed_seconds": elapsed,
        "resources": {
            "TC01_EBS_UNATTACHED": {
                "service": "EBS",
                "resource_id": out_map.get("EbsVolumeId"),
                "expected_rule": "EBS_UNATTACHED",
                "initial_status": "OBSERVING"
            },
            "TC02_EIP_UNASSOCIATED": {
                "service": "EIP",
                "resource_id": out_map.get("ElasticIpAllocationId"),
                "public_ip": out_map.get("ElasticIpAddress"),
                "expected_rule": "EIP_UNASSOCIATED",
                "initial_status": "OBSERVING"
            },
            "TC03_SECURITY_GROUP_UNUSED": {
                "service": "SECURITY_GROUP",
                "resource_id": out_map.get("UnusedSecurityGroupId"),
                "expected_rule": "SECURITY_GROUP_UNUSED",
                "initial_status": "OBSERVING"
            },
            "TC04_ECR_NO_LIFECYCLE": {
                "service": "ECR_REPOSITORY",
                "resource_id": out_map.get("EcrRepositoryName"),
                "expected_rule": "ECR_NO_LIFECYCLE",
                "initial_status": "REVIEW"
            },
            "TC05_LAMBDA_UNUSED": {
                "service": "LAMBDA_FUNCTION",
                "resource_id": out_map.get("LambdaFunctionName"),
                "expected_rule": "LAMBDA_UNUSED",
                "initial_status": "REVIEW"
            },
            "TC06_FALSE_POSITIVE_CONTROL": {
                "service": "SECURITY_GROUP",
                "resource_id": out_map.get("KeepSecurityGroupId"),
                "expected_rule": "NONE_TAGGED_KEEP",
                "initial_status": "SUPPRESSED"
            }
        }
    }
    
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[APPLY] SUCCESS in {elapsed}s. Manifest generated at: {MANIFEST_FILE}")
    print(json.dumps(manifest["resources"], indent=2))

def cmd_destroy(session, args):
    cfn = session.client("cloudformation")
    print(f"[DESTROY] Initiating teardown of stack '{args.stack_name}' in {args.region}...")
    try:
        cfn.delete_stack(StackName=args.stack_name)
        print("[DESTROY] Waiting for stack deletion...")
        cfn.get_waiter("stack_delete_complete").wait(StackName=args.stack_name, WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        print(f"[DESTROY] Stack '{args.stack_name}' deleted successfully.")
    except ClientError as e:
        if "does not exist" in e.response["Error"]["Message"]:
            print(f"[DESTROY] Stack '{args.stack_name}' does not exist.")
        else:
            raise

    if MANIFEST_FILE.exists():
        MANIFEST_FILE.unlink()
        print(f"[DESTROY] Removed manifest file {MANIFEST_FILE.name}")
    print("[DESTROY] Cleanup complete. No residual test resources remain.")

def cmd_status(session, args):
    if not MANIFEST_FILE.exists():
        print(f"[STATUS] No manifest file found at {MANIFEST_FILE}. Run plan or apply first.")
        return
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    print("=" * 78)
    print("CURRENT EXPERIMENT MANIFEST & STATUS")
    print("=" * 78)
    print(f"Created At : {manifest.get('created_at')}")
    print(f"Account ID : {manifest.get('account_id')}")
    print(f"Region     : {manifest.get('region')}")
    print(f"Stack Name : {manifest.get('stack_name')}")
    print("\nTracked Resources:")
    for key, data in manifest.get("resources", {}).items():
        print(f"  {key:<28} : {data.get('resource_id')} ({data.get('service')}) -> Expected: {data.get('initial_status')}")
    print("=" * 78)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "apply", "destroy", "status"], help="Action to perform")
    parser.add_argument("--profile", default="datht", help="AWS CLI profile name (default: datht)")
    parser.add_argument("--region", default="ap-southeast-1", help="AWS region (default: ap-southeast-1)")
    parser.add_argument("--stack-name", default="crg-demo-experiment-stack", help="CloudFormation stack name")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    if args.command == "plan":
        cmd_plan(session, args)
    elif args.command == "apply":
        cmd_apply(session, args)
    elif args.command == "destroy":
        cmd_destroy(session, args)
    elif args.command == "status":
        cmd_status(session, args)

if __name__ == "__main__":
    main()
