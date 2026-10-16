"""Semantic invariants for the scanner role and public API surface."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_ACTIONS = {
    "ec2:DescribeInstances",
    "ec2:DescribeVolumes",
    "ec2:DescribeAddresses",
    "ec2:DescribeSnapshots",
    "ec2:DescribeImages",
    "ec2:DescribeNatGateways",
    "cloudwatch:GetMetricData",
    "s3:ListAllMyBuckets",
    "s3:ListBucketMultipartUploads",
    "rds:DescribeDBInstances",
    "elasticloadbalancing:DescribeLoadBalancers",
}
EXPECTED_ROUTES = {
    ("GET", "/me"),
    ("PUT", "/connection"),
    ("PUT", "/settings"),
    ("POST", "/scans"),
    ("GET", "/scans/{scanId}"),
    ("GET", "/history"),
    ("PUT", "/notifications"),
    ("GET", "/findings"),
    ("GET", "/feedback"),
    ("PUT", "/feedback"),
}


class CloudFormationLoader(yaml.SafeLoader):
    pass


def construct_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", construct_tag)


def load(path):
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=CloudFormationLoader)


class ReadOnlyContract(unittest.TestCase):
    def test_target_role_templates_are_identical_and_strictly_read_only(self):
        canonical = (ROOT / "target-role.yaml").read_bytes()
        self.assertEqual(canonical, (ROOT / "web" / "target-role.yaml").read_bytes())
        template = load("target-role.yaml")
        role = template["Resources"]["ReadRole"]["Properties"]
        self.assertNotIn("ManagedPolicyArns", role)
        trust = role["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual(len(trust), 1)
        self.assertEqual(trust[0]["Action"], "sts:AssumeRole")
        self.assertEqual(trust[0]["Principal"]["AWS"], ["ApiPrincipal", "ScanPrincipal"])
        self.assertEqual(trust[0]["Condition"], {"StringEquals": {"sts:ExternalId": "ExternalId"}})
        statements = role["Policies"][0]["PolicyDocument"]["Statement"]
        actions = set()
        scopes = {}
        for statement in statements:
            values = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            actions.update(values)
            for action in values:
                scopes[action] = statement["Resource"]
        self.assertEqual(actions, EXPECTED_ACTIONS)
        self.assertEqual(scopes["s3:ListAllMyBuckets"], "*")
        self.assertEqual(scopes["s3:ListBucketMultipartUploads"], "arn:${AWS::Partition}:s3:::*")
        for action in actions:
            verb = action.split(":", 1)[1].lower()
            self.assertFalse(any(word in verb for word in ("stop", "delete", "terminate", "modify", "update", "create", "put", "abort")), action)

    def test_api_routes_and_admin_only_user_pool(self):
        template = load("template.yaml")
        events = template["Resources"]["ApiFunction"]["Properties"]["Events"].values()
        routes = {(event["Properties"]["Method"], event["Properties"]["Path"]) for event in events if event["Type"] == "HttpApi"}
        self.assertEqual(routes, EXPECTED_ROUTES)
        self.assertFalse(any(method == "DELETE" for method, _ in routes))
        user_pool = template["Resources"]["UserPool"]["Properties"]
        self.assertIs(user_pool["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"], True)


if __name__ == "__main__":
    unittest.main()
