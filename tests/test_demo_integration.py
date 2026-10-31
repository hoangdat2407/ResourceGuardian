"""Nine-resource demo API integration with real pure evaluators, no AWS calls."""
import copy
from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import MagicMock, patch

import demo


class DemoIntegration(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy((demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK,
                                    demo.READY_AT, demo.FINDING_OBSERVATIONS))
        self.addCleanup(self.restore)
        self.now = 1793361607
        clock = patch.object(demo.time, 'time', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        demo.PROFILE.update(connection_version='integration-v1', account_id='123456789012',
                            regions=['ap-southeast-1'], service_groups=list(demo.SERVICE_GROUPS),
                            settings=demo.config({}), notifications={'enabled': False}, email_available=False)
        demo.FINDING_OBSERVATIONS, demo.FEEDBACK, demo.CURRENT, demo.HISTORY = {}, {}, [], []
        demo.READY_AT = 0

    def restore(self):
        (demo.PROFILE, demo.CURRENT, demo.HISTORY, demo.FEEDBACK,
         demo.READY_AT, demo.FINDING_OBSERVATIONS) = self.saved

    def request(self, method, path, body=None):
        payload = json.dumps(body).encode() if body is not None else b''
        handler = object.__new__(demo.Handler)
        handler.headers = {'Authorization': 'Bearer demo-local-only', 'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.reply = MagicMock()
        handler.handle_api(method, path)
        handler.reply.assert_called_once()
        code, response = handler.reply.call_args.args
        return code, copy.deepcopy(response)

    def scan(self, name='integration-scan', region='ap-southeast-1'):
        row = demo.complete(name, self.now - 10, region)
        demo.CURRENT = [row]
        demo.HISTORY.insert(0, copy.deepcopy(row))
        return row

    def candidate(self, kind, row=None):
        return next(item for item in (row or demo.CURRENT[0])['candidates'] if item['type'] == kind)

    def stamp(self, value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()

    def feedback(self, item, **patch):
        return self.request('PUT', '/feedback', {'region': item['region'], 'finding_id': item['finding_id'], **patch})

    def test_default_demo_has_nine_evaluator_schemas_and_actual_zero_metrics(self):
        row = self.scan()
        self.assertEqual(set(row['counts']), set(demo.RESOURCE_GROUPS))
        self.assertEqual(sum(row['counts'].values()), 31)
        self.assertEqual(len(row['findings']), 10)
        self.assertEqual(row['finding_count'], 10)
        self.assertEqual(row['total_candidate_count'], 10)
        self.assertEqual(row['errors'], [])
        self.assertEqual({item['type'] for item in row['findings']}, set(demo.RESOURCE_GROUPS))
        self.assertEqual({level: sum(item['level'] == level for item in row['findings'])
                          for level in ['REVIEW', 'OBSERVING', 'INSUFFICIENT_DATA']},
                         {'REVIEW': 8, 'OBSERVING': 1, 'INSUFFICIENT_DATA': 1})
        for item in row['findings']:
            self.assertEqual(item['account_id'], demo.PROFILE['account_id'])
            self.assertEqual(item['region'], row['region'])
            self.assertTrue(item['rule_id'])
            self.assertTrue(item['recommendation'])
            self.assertEqual(item['evidence']['evaluated_at'], item['evaluated_at'])
            self.assertEqual(item['first_seen_at'], item['last_seen_at'])
            self.assertEqual(self.stamp(item['first_seen_at']), self.now)
        for kind, field in [('RDS', 'connections_p95'), ('NAT_GATEWAY', 'nat_mib_hour'),
                            ('ALB', 'requests_hour'), ('NLB', 'new_flows_hour')]:
            self.assertEqual(self.candidate(kind)['evidence'][field], 0)
        poor = next(item for item in row['findings'] if item['level'] == 'INSUFFICIENT_DATA')
        self.assertNotIn('cpu_p95', poor['evidence'], 'Missing samples must not pretend measured zero')

    def test_composite_and_arn_stable_identities_match_backend_collector_contract(self):
        self.scan()
        region, account = demo.CURRENT[0]['region'], demo.PROFILE['account_id']
        identities = {
            'S3_MULTIPART': ['guardian-demo', 'archive/demo.bin', 'demo-upload'],
            'RDS': 'arn:aws:rds:' + region + ':' + account + ':db:database-demo',
            'ALB': 'arn:aws:elasticloadbalancing:' + region + ':' + account + ':loadbalancer/app/alb-demo/0000000000000001',
            'NLB': 'arn:aws:elasticloadbalancing:' + region + ':' + account + ':loadbalancer/net/nlb-demo/0000000000000002',
        }
        for kind, identity in identities.items():
            item = self.candidate(kind)
            self.assertEqual(item['finding_id'], demo.finding_id(kind, region, identity))
            self.assertNotEqual(item['finding_id'], demo.finding_id(kind, region, item['resource_id']))

    def test_settings_change_evaluation_without_rewriting_history_or_first_observation(self):
        before = copy.deepcopy(self.scan())
        ebs = self.candidate('EBS')
        self.now += 60
        self.assertEqual(self.request('PUT', '/settings', {'orphan_hours': 72, 'snapshot_days': 70, 'cpu_percent': 1})[0], 200)
        after = self.scan('changed-settings')
        updated = self.candidate('EBS')
        self.assertEqual(updated['level'], 'OBSERVING')
        self.assertEqual(updated['evidence']['thresholds']['orphan_hours'], 72)
        self.assertEqual(updated['first_seen_at'], ebs['first_seen_at'])
        self.assertGreater(self.stamp(updated['last_seen_at']), self.stamp(ebs['last_seen_at']))
        self.assertFalse(any(item['type'] == 'SNAPSHOT' for item in after['findings']))
        self.assertFalse(any(item['resource_id'] == 'i-0123456789abcdef0' for item in after['findings']))
        self.assertEqual(demo.HISTORY[1], before)

    def test_window_setting_controls_evidence_and_utc_hour_grid(self):
        self.request('PUT', '/settings', {'window_hours': 168})
        self.scan()
        for item in demo.CURRENT[0]['findings']:
            if item['type'] not in {'EC2', 'RDS', 'NAT_GATEWAY', 'ALB', 'NLB'}:
                continue
            evidence = item['evidence']
            start, end = (self.stamp(evidence[key]) for key in ['observation_start', 'observation_end'])
            self.assertEqual(end % 3600, 0)
            self.assertEqual(end - start, 168 * 3600)
            self.assertEqual(evidence['window_hours'], 168)
            self.assertEqual(evidence['metric_period_seconds'], 3600)
            self.assertTrue(evidence['metric_statistics'])
        self.assertEqual(self.candidate('RDS')['evidence']['sample_counts'], {'cpu': 168, 'connections': 168})

    def test_scan_updates_timestamps_before_suppression_and_clear_preserves_independent_flags(self):
        first = copy.deepcopy(self.scan())
        until = datetime.fromtimestamp(self.now + 86400, timezone.utc).isoformat().replace('+00:00', 'Z')
        for item in first['candidates']:
            self.assertEqual(self.feedback(item, acknowledged=True)[0], 200)
            self.assertEqual(self.feedback(item, kept=True)[0], 200)
            self.assertEqual(self.feedback(item, ignoreUntil=until)[0], 200)
        self.now += 3600
        second = self.scan('hidden-scan')
        self.assertEqual(second['findings'], [])
        self.assertEqual(second['finding_count'], 0)
        for original, current in zip(first['candidates'], second['candidates']):
            self.assertEqual(current['first_seen_at'], original['first_seen_at'])
            self.assertEqual(self.stamp(current['last_seen_at']), self.now)
            record = self.feedback(current, kept=False)[1]
            self.assertTrue(record['acknowledged'])
            self.assertGreater(record['ignore_until'], self.now)
            self.assertEqual(self.request('GET', '/findings')[1]['results'][0]['findings'], [])
            self.feedback(current, kept=True)
        saved = copy.deepcopy(demo.HISTORY)
        for current in second['candidates']:
            self.feedback(current, kept=False)
            self.feedback(current, ignoreUntil=None)
        restored = self.request('GET', '/findings')[1]['results'][0]['findings']
        self.assertEqual(len(restored), 10)
        self.assertTrue(all(item['acknowledged'] for item in restored))
        self.assertEqual(demo.HISTORY, saved)
        self.assertEqual(self.request('GET', '/findings')[1]['results'][0]['finding_count'], 10)

    def test_temporarily_absent_candidate_keeps_first_until_thirty_day_boundary(self):
        self.scan()
        original = copy.deepcopy(self.candidate('SNAPSHOT'))
        self.now += 100
        self.request('PUT', '/settings', {'snapshot_days': 365})
        self.scan('absent')
        self.assertFalse(any(item['type'] == 'SNAPSHOT' for item in demo.CURRENT[0]['candidates']))
        self.now += 100
        self.request('PUT', '/settings', {'snapshot_days': 30})
        self.scan('present-again')
        item = self.candidate('SNAPSHOT')
        self.assertEqual(item['first_seen_at'], original['first_seen_at'])
        key = ('integration-v1', item['region'], item['finding_id'])
        expires = demo.FINDING_OBSERVATIONS[key]['expires']
        self.assertEqual(expires, self.now + 30 * 86400)
        self.now = expires
        self.scan('expired-without-ttl-cleanup')
        self.assertEqual(self.stamp(self.candidate('SNAPSHOT')['first_seen_at']), self.now)

    def test_clock_rollback_does_not_move_last_or_expiry_backwards(self):
        self.scan()
        before = copy.deepcopy(demo.FINDING_OBSERVATIONS)
        self.now -= 60
        self.scan('clock-rollback')
        self.assertEqual(demo.FINDING_OBSERVATIONS, before)
        for item in demo.CURRENT[0]['candidates']:
            record = before[('integration-v1', item['region'], item['finding_id'])]
            self.assertEqual(self.stamp(item['last_seen_at']), record['last'])

    def test_region_connection_and_reconnect_observations_are_isolated(self):
        self.scan()
        first = copy.deepcopy(self.candidate('EBS'))
        self.now += 60
        demo.PROFILE['regions'].append('ap-southeast-2')
        other = self.scan('other-region', 'ap-southeast-2')
        other_ebs = self.candidate('EBS', other)
        self.assertNotEqual(other_ebs['finding_id'], first['finding_id'])
        self.assertEqual(self.stamp(other_ebs['first_seen_at']), self.now)
        body = {'role_arn': demo.PROFILE['role_arn'], 'regions': ['ap-southeast-1']}
        self.assertEqual(self.request('PUT', '/connection', body)[0], 200)
        self.assertEqual(demo.FINDING_OBSERVATIONS, {})
        self.assertEqual(demo.HISTORY, [])
        self.now += 60
        self.scan('new-connection')
        self.assertEqual(self.candidate('EBS')['finding_id'], first['finding_id'])
        self.assertEqual(self.stamp(self.candidate('EBS')['first_seen_at']), self.now)

    def test_foreign_feedback_records_do_not_hide_or_acknowledge_current_findings(self):
        self.scan()
        item = self.candidate('EBS')
        for fields in ({'connection_version': 'old'}, {'region': 'us-east-1'}):
            demo.FEEDBACK[item['finding_id']] = {**item, 'connection_version': 'integration-v1',
                                                  'acknowledged': True, 'kept': True, **fields}
            rows = self.request('GET', '/findings')[1]['results'][0]['findings']
            current = next(row for row in rows if row['finding_id'] == item['finding_id'])
            self.assertNotIn('acknowledged', current)

    def test_pending_scan_does_not_advance_observations_or_recreate_candidates(self):
        self.scan()
        before = copy.deepcopy(demo.FINDING_OBSERVATIONS)
        self.now += 60
        self.assertEqual(self.request('POST', '/scans')[0], 202)
        row = self.request('GET', '/findings')[1]['results'][0]
        self.assertEqual(row['status'], 'RUNNING')
        self.assertNotIn('findings', row)
        self.assertEqual(demo.FINDING_OBSERVATIONS, before)

    def test_all_feedback_metadata_pages_and_history_remain_consistent_across_regions(self):
        demo.PROFILE['regions'] = ['ap-southeast-1', 'ap-southeast-2', 'us-east-1']
        demo.CURRENT = [demo.complete('multi-region', self.now - 10, region) for region in demo.PROFILE['regions']]
        demo.HISTORY = copy.deepcopy(demo.CURRENT)
        before = copy.deepcopy(demo.HISTORY)
        for row in demo.CURRENT:
            for item in row['candidates']:
                self.feedback(item, kept=True)
        first = self.request('GET', '/feedback')[1]
        self.assertEqual(len(first['results']), 20)
        second = self.request('GET', '/feedback?next_token=' + first['next_token'])[1]
        self.assertEqual(len(second['results']), 10)
        self.assertIsNone(second['next_token'])
        for record in first['results'] + second['results']:
            self.assertTrue(all(record[key] for key in ['type', 'resource_id', 'account_id', 'rule_id']))
        self.assertTrue(all(not row['findings'] for row in self.request('GET', '/findings')[1]['results']))
        self.assertEqual(demo.HISTORY, before)
        for path in ['/history', '/scans/multi-region']:
            rows = self.request('GET', path)[1]['results']
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(len(row['findings']) == 10 and 'candidates' not in row for row in rows))
            self.assertTrue(all('first_seen_at' in item for row in rows for item in row['findings']))

    def test_ses_stays_unavailable_and_notification_payload_is_strict(self):
        self.assertFalse(self.request('GET', '/me')[1]['email_available'])
        for value in [True, 1, 0, 'false', None, [], {}]:
            with self.subTest(value=value):
                before = copy.deepcopy(demo.PROFILE['notifications'])
                self.assertEqual(self.request('PUT', '/notifications', {'enabled': value})[0], 400)
                self.assertEqual(demo.PROFILE['notifications'], before)
        self.assertEqual(self.request('PUT', '/notifications', {'enabled': False}), (200, {'enabled': False}))
        self.assertEqual(self.scan()['notification'], 'DISABLED')


if __name__ == '__main__':
    unittest.main()
