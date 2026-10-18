"""Deterministic rule checks; no AWS, persistence, or system clock required."""
import copy
import json
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from rules import config, evaluate_ebs, evaluate_ec2, evaluate_eip, evaluate_snapshot, idle, keep


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config({})
        self.now = datetime(2026, 10, 18, 3, tzinfo=timezone.utc)
        self.start = self.now - timedelta(hours=24)
        self.instance = {'InstanceId': 'i-test', 'State': {'Name': 'running'},
                         'LaunchTime': self.start - timedelta(days=1)}
        self.volume = {'VolumeId': 'vol-test', 'State': 'available', 'Attachments': [], 'Size': 40}
        self.address = {'AllocationId': 'eipalloc-test'}
        self.snapshot = {'SnapshotId': 'snap-test', 'State': 'completed', 'VolumeSize': 40,
                         'VolumeId': 'vol-test', 'StartTime': self.now - timedelta(days=30)}

    def test_missing_is_not_zero(self):
        level, evidence = idle([], [], [], 24, self.cfg)
        self.assertEqual(level, 'INSUFFICIENT_DATA')
        self.assertEqual(evidence['sample_counts'], {'cpu': 0, 'netin': 0, 'netout': 0})
        self.assertEqual(evidence['missing_metrics'], ['cpu', 'netin', 'netout'])
        self.assertEqual(evidence['required_samples'], 20)
        self.assertEqual(evidence['coverage'], 0)

    def test_real_zeros_are_samples(self):
        level, evidence = idle([0]*24, [0]*24, [0]*24, 24, self.cfg)
        self.assertEqual(level, 'REVIEW')
        self.assertEqual(evidence['cpu_p95'], 0)
        self.assertEqual(evidence['network_mib_hour'], 0)
        self.assertEqual(evidence['coverage'], 1)

    def test_low_usage(self):
        self.assertEqual(idle([1]*24, [100]*24, [100]*24, 24, self.cfg)[0], 'REVIEW')

    def test_coverage_at_exact_boundary_including_seven_days(self):
        for hours, required in ((24, 20), (168, 135)):
            cfg = config({'window_hours': hours})
            with self.subTest(hours=hours):
                level, evidence = idle([0]*required, [0]*required, [0]*required, hours, cfg)
                self.assertEqual(level, 'REVIEW')
                self.assertEqual(evidence['required_samples'], required)
                self.assertEqual(evidence['window_hours'], hours)
                for index, name in enumerate(('cpu', 'netin', 'netout')):
                    values = [[0]*required for _ in range(3)]
                    values[index].pop()
                    level, evidence = idle(*values, hours, cfg)
                    self.assertEqual(level, 'INSUFFICIENT_DATA')
                    self.assertEqual(evidence['missing_metrics'], [name])

    def test_missing_one_metric_is_not_idle(self):
        for index, name in enumerate(('cpu', 'netin', 'netout')):
            with self.subTest(metric=name):
                values = [[0]*24 for _ in range(3)]
                values[index] = []
                level, evidence = idle(*values, 24, self.cfg)
                self.assertEqual(level, 'INSUFFICIENT_DATA')
                self.assertEqual(evidence['missing_metrics'], [name])

    def test_invalid_sample_fails_closed_even_with_enough_valid_samples(self):
        invalid = (float('nan'), float('inf'), float('-inf'), -1, True, False, None, '0', 10**400)
        for index, name in enumerate(('cpu', 'netin', 'netout')):
            for value in invalid:
                with self.subTest(metric=name, value=repr(value)):
                    values = [[0]*24 for _ in range(3)]
                    values[index].append(value)
                    level, evidence = idle(*values, 24, self.cfg)
                    self.assertEqual(level, 'INSUFFICIENT_DATA')
                    self.assertEqual(evidence['sample_counts'][name], 24)
                    self.assertEqual(evidence['invalid_metrics'], [name])
                    self.assertEqual(evidence['missing_metrics'], [])
                    self.assertNotIn('cpu_p95', evidence)
                    json.dumps(evidence, allow_nan=False)

    def test_invalid_samples_do_not_count_towards_coverage(self):
        level, evidence = idle([0]*19 + [-1], [0]*24, [0]*24, 24, self.cfg)
        self.assertEqual(level, 'INSUFFICIENT_DATA')
        self.assertEqual(evidence['sample_counts']['cpu'], 19)
        self.assertEqual(evidence['missing_metrics'], ['cpu'])
        self.assertEqual(evidence['invalid_metrics'], ['cpu'])

    def test_network_aggregate_overflow_fails_closed(self):
        level, evidence = idle([0]*24, [1e308]*24, [0]*24, 24, self.cfg)
        self.assertEqual(level, 'INSUFFICIENT_DATA')
        self.assertNotIn('network_mib_hour', evidence)
        json.dumps(evidence, allow_nan=False)

    def test_spike_not_idle(self):
        self.assertEqual(idle([1]*22+[80]*2, [0]*24, [0]*24, 24, self.cfg)[0], 'OK')

    def test_network_not_idle(self):
        self.assertEqual(idle([1]*24, [2*1048576]*24, [0]*24, 24, self.cfg)[0], 'OK')

    def test_equal_cpu_or_network_threshold_not_idle(self):
        self.assertEqual(idle([5]*24, [0]*24, [0]*24, 24, self.cfg)[0], 'OK')
        for net_in, net_out in (([1048576]*24, [0]*24), ([0]*24, [1048576]*24),
                                ([524288]*24, [524288]*24)):
            with self.subTest(net_in=net_in[0], net_out=net_out[0]):
                level, evidence = idle([0]*24, net_in, net_out, 24, self.cfg)
                self.assertEqual(level, 'OK')
                self.assertEqual(evidence['network_mib_hour'], 1)

    def test_partial_network_coverage_preserves_measured_rate(self):
        for hours, samples in ((24, 20), (168, 135)):
            cfg = config({'window_hours': hours})
            for rate, expected in ((0.5, 'REVIEW'), (1, 'OK'), (1.1, 'OK')):
                for direction in ('netin', 'netout'):
                    with self.subTest(hours=hours, rate=rate, direction=direction):
                        incoming = [rate*1048576]*samples if direction == 'netin' else [0]*samples
                        outgoing = [rate*1048576]*samples if direction == 'netout' else [0]*samples
                        level, evidence = idle([0]*samples, incoming, outgoing, hours, cfg)
                        self.assertEqual(level, expected)
                        self.assertAlmostEqual(evidence['network_mib_hour'], rate)
                        self.assertEqual(evidence['sample_counts'][direction], samples)

    def test_network_directions_use_their_own_observed_hours(self):
        for incoming_count, outgoing_count in ((20, 24), (24, 20)):
            with self.subTest(incoming_count=incoming_count, outgoing_count=outgoing_count):
                level, evidence = idle([0]*24, [0.6*1048576]*incoming_count,
                                       [0.5*1048576]*outgoing_count, 24, self.cfg)
                self.assertEqual(level, 'OK')
                self.assertAlmostEqual(evidence['network_mib_hour'], 1.1)
                self.assertEqual(evidence['sample_counts'], {'cpu':24, 'netin':incoming_count, 'netout':outgoing_count})

    def test_evidence_records_actual_thresholds(self):
        cfg = config({'cpu_percent': 7.5, 'network_mib_hour': 2})
        level, evidence = idle([0]*24, [0]*24, [0]*24, 24, cfg)
        self.assertEqual(level, 'REVIEW')
        self.assertEqual(evidence['thresholds'], {'cpu_percent': 7.5, 'network_mib_hour': 2})

    def test_config_rejects_invalid(self):
        for value in ({'window_hours': 23}, {'window_hours': 169}, {'window_hours': 24.5},
                      {'cpu_percent': True}, {'cpu_percent': float('nan')}, {'cpu_percent': float('inf')},
                      {'tenant': 'a'}, {'interval_hours': 1.5}, [], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config(value)

    def test_config_keeps_default_and_allows_seven_days(self):
        self.assertEqual(self.cfg['window_hours'], 24)
        self.assertEqual(config({'window_hours': 168})['window_hours'], 168)

    def test_config_rejects_oversized_integers_without_overflow(self):
        for field in self.cfg:
            for sign in (-1, 1):
                with self.subTest(field=field, sign=sign), self.assertRaises(ValueError):
                    config({field: sign*10**400})

    def test_keep(self):
        self.assertTrue(keep([{'Key': 'guardian:keep', 'Value': 'TRUE'}]))
        self.assertFalse(keep([{'Key': 'guardian:keep', 'Value': 'false'}]))
        self.assertFalse(keep([]))

    def test_ec2_finding_has_stable_contract_and_compatible_reason(self):
        finding = evaluate_ec2(self.instance, [[0]*24 for _ in range(3)], self.cfg, self.start)
        self.assertEqual(finding['rule_id'], 'EC2_LOW_UTILIZATION')
        self.assertEqual(finding['type'], 'EC2')
        self.assertEqual(finding['resource_id'], 'i-test')
        self.assertEqual(finding['level'], 'REVIEW')
        self.assertEqual(finding['reason'], 'Low CPU and network; confirm intended workload')
        self.assertEqual(finding['evidence']['observation_start'], self.start.isoformat())
        self.assertTrue(finding['recommendation'])
        json.dumps(finding, allow_nan=False)

    def test_ec2_nonrunning_or_tagged_not_flagged(self):
        for state in ('stopped', 'pending', 'terminated'):
            with self.subTest(state=state):
                instance = {**self.instance, 'State': {'Name': state}}
                self.assertIsNone(evaluate_ec2(instance, [[], [], []], self.cfg, self.start))
        tagged = {**self.instance, 'Tags': [{'Key': 'guardian:keep', 'Value': 'true'}]}
        self.assertIsNone(evaluate_ec2(tagged, [[], [], []], self.cfg, self.start))

    def test_ec2_new_instance_never_idle_and_launch_boundary_is_inclusive(self):
        for launch in (self.start - timedelta(microseconds=1), self.start, self.start + timedelta(microseconds=1)):
            with self.subTest(launch=launch):
                instance = {**self.instance, 'LaunchTime': launch}
                finding = evaluate_ec2(instance, [[0]*24 for _ in range(3)], self.cfg, self.start)
                self.assertEqual(finding['level'], 'INSUFFICIENT_DATA' if launch > self.start else 'REVIEW')
                if launch > self.start:
                    self.assertEqual(finding['reason'], 'Instance younger than observation window')
                    self.assertEqual(finding['evidence']['launch_time'], launch.isoformat())

    def test_instance_launched_after_completed_metric_hour_has_no_negative_age(self):
        launch = self.now + timedelta(minutes=30)
        instance = {**self.instance, 'LaunchTime': launch}
        finding = evaluate_ec2(instance, [[], [], []], self.cfg, self.start)
        self.assertEqual(finding['level'], 'INSUFFICIENT_DATA')
        self.assertEqual(finding['evidence']['launch_time'], launch.isoformat())
        self.assertNotIn('instance_age_hours', finding['evidence'])
        json.dumps(finding, allow_nan=False)

    def test_ec2_missing_metric_reason_and_no_ok_finding(self):
        finding = evaluate_ec2(self.instance, [[], [], []], self.cfg, self.start)
        self.assertEqual(finding['level'], 'INSUFFICIENT_DATA')
        self.assertEqual(finding['reason'], 'Missing CloudWatch metrics; not classified as idle')
        self.assertIsNone(evaluate_ec2(self.instance, [[5]*24, [0]*24, [0]*24], self.cfg, self.start))

    def test_orphan_observation_boundaries(self):
        for evaluator, resource, rule_id in ((evaluate_ebs, self.volume, 'EBS_UNATTACHED'),
                                              (evaluate_eip, self.address, 'EIP_UNASSOCIATED')):
            for hours, level in ((0, 'OBSERVING'), (23.99, 'OBSERVING'), (24, 'REVIEW'), (25, 'REVIEW')):
                with self.subTest(rule_id=rule_id, hours=hours):
                    finding = evaluator(resource, hours, self.cfg)
                    self.assertEqual(finding['level'], level)
                    self.assertEqual(finding['rule_id'], rule_id)
                    self.assertEqual(finding['evidence']['threshold_hours'], 24)
                    self.assertTrue(finding['recommendation'])

    def test_ebs_available_and_attachment_are_both_checked(self):
        for volume in ({**self.volume, 'State': 'in-use'},
                       {**self.volume, 'Attachments': [{'InstanceId': 'i-test'}]}):
            with self.subTest(volume=volume):
                self.assertIsNone(evaluate_ebs(volume, 100, self.cfg))

    def test_eip_associated_or_without_allocation_not_flagged(self):
        self.assertIsNone(evaluate_eip({**self.address, 'AssociationId': 'eipassoc-test'}, 100, self.cfg))
        self.assertIsNone(evaluate_eip({'PublicIp': '192.0.2.1'}, 100, self.cfg))

    def test_keep_tag_suppresses_all_resource_types(self):
        tags = [{'Key': 'guardian:keep', 'Value': 'TRUE'}]
        self.assertIsNone(evaluate_ebs({**self.volume, 'Tags': tags}, 100, self.cfg))
        self.assertIsNone(evaluate_eip({**self.address, 'Tags': tags}, 100, self.cfg))
        self.assertIsNone(evaluate_snapshot({**self.snapshot, 'Tags': tags}, set(), True, self.cfg, self.now))

    def test_snapshot_age_boundary(self):
        for age, expected in ((timedelta(days=30, microseconds=-1), False),
                              (timedelta(days=30), True), (timedelta(days=31), True)):
            with self.subTest(age=age):
                snapshot = {**self.snapshot, 'StartTime': self.now - age}
                finding = evaluate_snapshot(snapshot, set(), True, self.cfg, self.now)
                if expected:
                    self.assertEqual(finding['rule_id'], 'SNAPSHOT_OLD_UNREFERENCED')
                    self.assertEqual(finding['level'], 'REVIEW')
                    self.assertTrue(finding['evidence']['relationships_complete'])
                    self.assertEqual(finding['evidence']['snapshot_days'], 30)
                    self.assertTrue(finding['recommendation'])
                else:
                    self.assertIsNone(finding)

    def test_snapshot_must_be_completed_and_unreferenced(self):
        for state in ('pending', 'error', 'recoverable'):
            with self.subTest(state=state):
                self.assertIsNone(evaluate_snapshot({**self.snapshot, 'State': state}, set(), True, self.cfg, self.now))
        self.assertIsNone(evaluate_snapshot(self.snapshot, {'snap-test'}, True, self.cfg, self.now))

    def test_snapshot_incomplete_relationships_fail_closed(self):
        self.assertIsNone(evaluate_snapshot(self.snapshot, set(), False, self.cfg, self.now))

    def test_snapshot_backup_description_and_tags_are_exempt(self):
        for extra in ({'Description': 'Created by AWS:BACKUP service'},
                      {'Tags': [{'Key': 'aws:backup:source-resource', 'Value': 'vol-test'}]}):
            with self.subTest(extra=extra):
                self.assertIsNone(evaluate_snapshot({**self.snapshot, **extra}, set(), True, self.cfg, self.now))

    def test_evaluators_do_not_mutate_collector_input_or_config(self):
        metrics = [[0]*24 for _ in range(3)]
        resources = [self.instance, self.volume, self.address, self.snapshot, self.cfg, metrics]
        before = copy.deepcopy(resources)
        evaluate_ec2(self.instance, metrics, self.cfg, self.start)
        evaluate_ebs(self.volume, 24, self.cfg)
        evaluate_eip(self.address, 24, self.cfg)
        finding = evaluate_snapshot(self.snapshot, set(), True, self.cfg, self.now)
        json.dumps(finding, allow_nan=False)
        self.assertEqual(resources, before)


if __name__ == '__main__':
    unittest.main()
