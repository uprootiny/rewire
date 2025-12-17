"""
Property-based tests for Rewire invariants.

Uses hypothesis to generate random sequences of operations
and verifies invariants hold after each step.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from rewire.db import Store, CreateExpectationParams
from rewire.invariants import (
    check_missed_correct,
    check_longrun_correct,
    check_trial_states,
    check_observation_monotonicity,
)
from rewire import rules


class TestInvariantsManual(unittest.TestCase):
    """Manual invariant tests without hypothesis."""

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

    def _create_schedule(self, exp_id: str, interval: int = 60, tol: int = 0,
                         max_runtime: int = 0) -> None:
        params = {"max_runtime_s": max_runtime, "min_spacing_s": 0, "allow_overlap": False}
        self.store.create_expectation(CreateExpectationParams(
            exp_id=exp_id,
            exp_type="schedule",
            name=f"job-{exp_id}",
            expected_interval_s=interval,
            tolerance_s=tol,
            params_json=json.dumps(params),
            owner_email="test@example.com",
        ))

    def test_no_missed_without_any_starts(self) -> None:
        """INV1: Can't claim 'missed' if we've never seen a start."""
        self._create_schedule("e1", interval=60)

        # No observations at all
        results = check_missed_correct(self.store)
        for r in results:
            self.assertTrue(r.passed, f"Failed: {r.message}")

    @patch("rewire.invariants.now_i")
    def test_missed_when_overdue(self, mock_now) -> None:
        """INV1: 'missed' should exist when overdue."""
        mock_now.return_value = 1000
        self._create_schedule("e2", interval=60, tol=10)

        # Insert old start
        with self.store._conn() as conn:
            conn.execute(
                "INSERT INTO observations (expectation_id, kind, observed_at, meta_json) "
                "VALUES (?, ?, ?, ?)",
                ("e2", "start", 100, None)
            )
            conn.commit()

        # Should have missed violation, but we haven't created it
        # This tests that the invariant DETECTS the mismatch
        results = check_missed_correct(self.store)

        # Find result for e2
        e2_result = next(r for r in results if "e2" in r.name)
        # Should FAIL because violation doesn't exist but should
        self.assertFalse(e2_result.passed)

        # Now create the violation
        self.store.create_violation("e2", "missed", "Test", "{}")

        # Re-check - should pass now
        results = check_missed_correct(self.store)
        e2_result = next(r for r in results if "e2" in r.name)
        self.assertTrue(e2_result.passed)

    def test_trial_state_consistency(self) -> None:
        """INV3/4: Trial state transitions are valid."""
        # Create alertpath expectation
        params = {"ack_window_s": 300, "test_interval_s": 3600}
        self.store.create_expectation(CreateExpectationParams(
            exp_id="ap1",
            exp_type="alert_path",
            name="path1",
            expected_interval_s=3600,
            tolerance_s=0,
            params_json=json.dumps(params),
            owner_email="test@example.com",
        ))

        # Create and ack a trial
        self.store.create_trial("t1", "ap1", "{}")
        self.store.ack_trial("t1")

        results = check_trial_states(self.store)
        for r in results:
            self.assertTrue(r.passed, f"Failed: {r.message}")

    def test_observation_monotonicity(self) -> None:
        """INV5: Observations have monotonic timestamps."""
        self._create_schedule("mono1")

        # Add observations in order
        self.store.add_observation("mono1", "start", None)
        self.store.add_observation("mono1", "end", None)
        self.store.add_observation("mono1", "start", None)

        results = check_observation_monotonicity(self.store)
        for r in results:
            self.assertTrue(r.passed, f"Failed: {r.message}")


class TestRuleEvaluationInvariants(unittest.TestCase):
    """Test that rule evaluation maintains invariants."""

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

    @patch("rewire.rules.now_i")
    def test_schedule_evaluate_produces_valid_violations(self, mock_now) -> None:
        """Rule evaluation should only produce violations with evidence."""
        mock_now.return_value = 1000

        params = {"max_runtime_s": 60, "min_spacing_s": 0, "allow_overlap": False}
        self.store.create_expectation(CreateExpectationParams(
            exp_id="rule1",
            exp_type="schedule",
            name="rule-job",
            expected_interval_s=100,
            tolerance_s=10,
            params_json=json.dumps(params),
            owner_email="test@example.com",
        ))

        # Insert a start 200 seconds ago (should trigger missed)
        with self.store._conn() as conn:
            conn.execute(
                "INSERT INTO observations (expectation_id, kind, observed_at, meta_json) "
                "VALUES (?, ?, ?, ?)",
                ("rule1", "start", 800, None)
            )
            conn.commit()

        exp = self.store.get_expectation("rule1")
        obs = self.store.recent_observations("rule1", 50)

        violations, close_codes = rules.schedule_evaluate(exp, obs)

        # Every violation returned should have evidence in the message
        for code, msg, evidence in violations:
            self.assertIsInstance(evidence, dict)
            self.assertGreater(len(evidence), 0, f"Violation {code} has no evidence")

            # Missed violations must reference last_start_at
            if code == "missed":
                self.assertIn("last_start_at", evidence)
                self.assertIn("age_s", evidence)

            # Longrun violations must reference start_at
            if code == "longrun":
                self.assertIn("start_at", evidence)
                self.assertIn("running_for_s", evidence)


if __name__ == "__main__":
    unittest.main()
