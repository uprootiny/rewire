"""Tests for rewire.db module."""

import json
import os
import tempfile
import unittest

from rewire.db import Store, CreateExpectationParams


class TestStore(unittest.TestCase):
    """Test Store operations."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.db_path = self.tmp.name
        self.store = Store(self.db_path)
        self.store.init_db()

    def tearDown(self) -> None:
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_create_and_get_expectation(self) -> None:
        """Expectation can be created and retrieved."""
        params = CreateExpectationParams(
            exp_id="test-1",
            exp_type="schedule",
            name="test-job",
            expected_interval_s=3600,
            tolerance_s=300,
            params_json='{"max_runtime_s": 0}',
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        row = self.store.get_expectation("test-1")
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "test-job")
        self.assertEqual(row["type"], "schedule")
        self.assertEqual(row["is_enabled"], 1)

    def test_get_nonexistent_expectation(self) -> None:
        """Getting nonexistent expectation returns None."""
        row = self.store.get_expectation("does-not-exist")
        self.assertIsNone(row)

    def test_enable_disable(self) -> None:
        """Expectations can be enabled and disabled."""
        params = CreateExpectationParams(
            exp_id="toggle-1",
            exp_type="schedule",
            name="toggle-job",
            expected_interval_s=60,
            tolerance_s=0,
            params_json="{}",
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        self.store.set_enabled("toggle-1", False)
        row = self.store.get_expectation("toggle-1")
        self.assertEqual(row["is_enabled"], 0)

        self.store.set_enabled("toggle-1", True)
        row = self.store.get_expectation("toggle-1")
        self.assertEqual(row["is_enabled"], 1)

    def test_add_observation(self) -> None:
        """Observations can be added and retrieved."""
        params = CreateExpectationParams(
            exp_id="obs-1",
            exp_type="schedule",
            name="obs-job",
            expected_interval_s=60,
            tolerance_s=0,
            params_json="{}",
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        obs_id = self.store.add_observation("obs-1", "start", '{"run_id": 1}')
        self.assertGreater(obs_id, 0)

        obs = self.store.recent_observations("obs-1", limit=10)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["kind"], "start")

    def test_observation_ordering(self) -> None:
        """Observations are returned newest first."""
        params = CreateExpectationParams(
            exp_id="order-1",
            exp_type="schedule",
            name="order-job",
            expected_interval_s=60,
            tolerance_s=0,
            params_json="{}",
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        self.store.add_observation("order-1", "start", None)
        self.store.add_observation("order-1", "end", None)
        self.store.add_observation("order-1", "start", None)

        obs = self.store.recent_observations("order-1", limit=10)
        self.assertEqual(len(obs), 3)
        # Newest first
        self.assertEqual(obs[0]["kind"], "start")
        self.assertEqual(obs[1]["kind"], "end")
        self.assertEqual(obs[2]["kind"], "start")

    def test_trial_lifecycle(self) -> None:
        """Alert trials can be created, acked, and expired."""
        params = CreateExpectationParams(
            exp_id="trial-1",
            exp_type="alert_path",
            name="trial-path",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json='{"ack_window_s": 300, "test_interval_s": 3600}',
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        self.store.create_trial("t-abc", "trial-1", '{"test": true}')
        pending = self.store.pending_trials("trial-1")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending")

        # Ack
        result = self.store.ack_trial("t-abc")
        self.assertTrue(result)
        pending = self.store.pending_trials("trial-1")
        self.assertEqual(len(pending), 0)

        # Can't ack twice
        result = self.store.ack_trial("t-abc")
        self.assertFalse(result)

    def test_trial_expire(self) -> None:
        """Trials can be expired."""
        params = CreateExpectationParams(
            exp_id="exp-trial-1",
            exp_type="alert_path",
            name="exp-path",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json='{"ack_window_s": 300, "test_interval_s": 3600}',
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)
        self.store.create_trial("t-exp", "exp-trial-1", "{}")

        self.store.expire_trial("t-exp")
        pending = self.store.pending_trials("exp-trial-1")
        self.assertEqual(len(pending), 0)

    def test_violation_lifecycle(self) -> None:
        """Violations can be created, queried, and closed."""
        params = CreateExpectationParams(
            exp_id="viol-1",
            exp_type="schedule",
            name="viol-job",
            expected_interval_s=60,
            tolerance_s=0,
            params_json="{}",
            owner_email="test@example.com",
        )
        self.store.create_expectation(params)

        vid = self.store.create_violation(
            "viol-1", "missed", "Job missed", '{"age": 120}'
        )
        self.assertGreater(vid, 0)

        openv = self.store.open_violation("viol-1", "missed")
        self.assertIsNotNone(openv)
        self.assertEqual(openv["code"], "missed")

        count = self.store.open_violations_count("viol-1")
        self.assertEqual(count, 1)

        self.store.close_violations("viol-1", ["missed"])
        openv = self.store.open_violation("viol-1", "missed")
        self.assertIsNone(openv)

        count = self.store.open_violations_count("viol-1")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
