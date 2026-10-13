import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))
from rules import config, idle, keep

class RulesTest(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertEqual(idle([], [], [], 24, config({}))[0], 'INSUFFICIENT_DATA')
    def test_low_usage(self):
        self.assertEqual(idle([1]*24, [100]*24, [100]*24, 24, config({}))[0], 'REVIEW')
    def test_spike_not_idle(self):
        self.assertEqual(idle([1]*22+[80]*2, [0]*24, [0]*24, 24, config({}))[0], 'OK')
    def test_network_not_idle(self):
        self.assertEqual(idle([1]*24, [2*1048576]*24, [0]*24, 24, config({}))[0], 'OK')
    def test_config_rejects_invalid(self):
        for c in ({'window_hours': 2}, {'cpu_percent': True}, {'cpu_percent': float('nan')}, {'tenant': 'a'}, {'interval_hours': 1.5}):
            with self.assertRaises(ValueError): config(c)
    def test_keep(self):
        self.assertTrue(keep([{'Key':'guardian:keep','Value':'TRUE'}]))
        self.assertFalse(keep([]))

if __name__ == '__main__': unittest.main()
