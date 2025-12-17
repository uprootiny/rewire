"""Tests for rewire.rules module."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from rewire.db import Store, CreateExpectationParams
from rewire import rules


class MockRow(dict):
    """Dict that also supports attribute-style access for sqlite3.Row compatibility."""
    def __getitem__(self, key):
        return super().__getitem__(key)


def make_obs(kind: str, observed_at: int) -> MockRow:
    """Create a mock observation row."""
    return MockRow(kind=kind, observed_at=observed_at, meta_json=None)


class TestParseParams(unittest.TestCase):
    """Test parameter parsing."""

    def test_parse_schedule_params(self) -> None:
        params_json = '{"max_runtime_s": 300, "min_spacing_s": 60, "allow_overlap": true}'
        result = rules.parse_params("schedule", params_json)
        self.assertIsInstance(result, rules.ScheduleParams)
        self.assertEqual(result.max_runtime_s, 300)
        self.assertEqual(result.min_spacing_s, 60)
        self.assertTrue(result.allow_overlap)

    def test_parse_schedule_defaults(self) -> None:
        params_json = "{}"
        result = rules.parse_params("schedule", params_json)
        self.assertEqual(result.max_runtime_s, 0)
        self.assertEqual(result.min_spacing_s, 0)
        self.assertFalse(result.allow_overlap)

    def test_parse_alertpath_params(self) -> None:
        params_json = '{"ack_window_s": 900, "test_interval_s": 86400}'
        result = rules.parse_params("alert_path", params_json)
        self.assertIsInstance(result, rules.AlertPathParams)
        self.assertEqual(result.ack_window_s, 900)
        self.assertEqual(result.test_interval_s, 86400)

    def test_parse_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            rules.parse_params("unknown", "{}")


class TestScheduleEvaluate(unittest.TestCase):
    """Test schedule evaluation logic."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.store.init_db()

    def tearDown(self) -> None:
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _create_exp(self, exp_id: str, interval: int = 60, tol: int = 0, params: dict = None) -> None:
        if params is None:
            params = {"max_runtime_s": 0, "min_spacing_s": 0, "allow_overlap": False}
        self.store.create_expectation(CreateExpectationParams(
            exp_id=exp_id,
            exp_type="schedule",
            name=f"job-{exp_id}",
            expected_interval_s=interval,
            tolerance_s=tol,
            params_json=json.dumps(params),
            owner_email="test@example.com",
        ))

    def test_no_observations_no_violations(self) -> None:
        """No observations => no violations (honest: can't flag what we haven't seen)."""
        self._create_exp("e1")
        exp = self.store.get_expectation("e1")
        obs = []
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        self.assertEqual(violations, [])

    @patch("rewire.rules.now_i")
    def test_missed_violation(self, mock_now) -> None:
        """Old start without recent activity triggers 'missed'."""
        mock_now.return_value = 1000
        self._create_exp("e2", interval=60, tol=10)
        exp = self.store.get_expectation("e2")
        # Start was 100 seconds ago, expected interval is 60+10=70
        obs = [make_obs("start", 900)]
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        codes = [v[0] for v in violations]
        self.assertIn("missed", codes)

    @patch("rewire.rules.now_i")
    def test_not_missed_within_tolerance(self, mock_now) -> None:
        """Recent start within tolerance => no missed violation."""
        mock_now.return_value = 1000
        self._create_exp("e3", interval=60, tol=10)
        exp = self.store.get_expectation("e3")
        # Start was 50 seconds ago, within 60+10=70
        obs = [make_obs("start", 950)]
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        codes = [v[0] for v in violations]
        self.assertNotIn("missed", codes)
        self.assertIn("missed", close_codes)

    @patch("rewire.rules.now_i")
    def test_longrun_violation(self, mock_now) -> None:
        """Running job exceeding max_runtime triggers 'longrun'."""
        mock_now.return_value = 1000
        self._create_exp("e4", interval=9999, params={"max_runtime_s": 60, "min_spacing_s": 0, "allow_overlap": False})
        exp = self.store.get_expectation("e4")
        # Start 100 seconds ago, no end, max_runtime=60
        obs = [make_obs("start", 900)]
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        codes = [v[0] for v in violations]
        self.assertIn("longrun", codes)

    @patch("rewire.rules.now_i")
    def test_no_longrun_within_limit(self, mock_now) -> None:
        """Running job within max_runtime => no longrun violation."""
        mock_now.return_value = 1000
        self._create_exp("e5", interval=9999, params={"max_runtime_s": 200, "min_spacing_s": 0, "allow_overlap": False})
        exp = self.store.get_expectation("e5")
        obs = [make_obs("start", 900)]
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        codes = [v[0] for v in violations]
        self.assertNotIn("longrun", codes)

    @patch("rewire.rules.now_i")
    def test_completed_job_closes_longrun(self, mock_now) -> None:
        """Job with start+end closes longrun violations."""
        mock_now.return_value = 1000
        self._create_exp("e6", interval=9999, params={"max_runtime_s": 60, "min_spacing_s": 0, "allow_overlap": False})
        exp = self.store.get_expectation("e6")
        # Start at 900, end at 950 (completed)
        obs = [make_obs("end", 950), make_obs("start", 900)]
        violations, close_codes = rules.schedule_evaluate(exp, obs)
        self.assertIn("longrun", close_codes)


class TestAlertpathShouldSend(unittest.TestCase):
    """Test alert path send decision."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.store.init_db()

    def tearDown(self) -> None:
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_should_send_no_previous(self) -> None:
        """Should send test if no previous observations."""
        self.store.create_expectation(CreateExpectationParams(
            exp_id="ap1",
            exp_type="alert_path",
            name="path1",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json='{"ack_window_s": 300, "test_interval_s": 60}',
            owner_email="test@example.com",
        ))
        exp = self.store.get_expectation("ap1")
        self.assertTrue(rules.alertpath_should_send_test(exp, None))

    @patch("rewire.rules.now_i")
    def test_should_send_after_interval(self, mock_now) -> None:
        """Should send test if enough time has passed."""
        mock_now.return_value = 1000
        self.store.create_expectation(CreateExpectationParams(
            exp_id="ap2",
            exp_type="alert_path",
            name="path2",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json='{"ack_window_s": 300, "test_interval_s": 60}',
            owner_email="test@example.com",
        ))
        exp = self.store.get_expectation("ap2")
        # Last observation 100 seconds ago, interval is 60
        self.assertTrue(rules.alertpath_should_send_test(exp, 900))

    @patch("rewire.rules.now_i")
    def test_should_not_send_too_soon(self, mock_now) -> None:
        """Should not send test if interval not elapsed."""
        mock_now.return_value = 1000
        self.store.create_expectation(CreateExpectationParams(
            exp_id="ap3",
            exp_type="alert_path",
            name="path3",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json='{"ack_window_s": 300, "test_interval_s": 120}',
            owner_email="test@example.com",
        ))
        exp = self.store.get_expectation("ap3")
        # Last observation 50 seconds ago, interval is 120
        self.assertFalse(rules.alertpath_should_send_test(exp, 950))


if __name__ == "__main__":
    unittest.main()
