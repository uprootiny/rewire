#!/usr/bin/env python3
"""
Rewire model simulation: runs through scenarios and checks invariants.

This demonstrates what a successful model checker run looks like.

Usage: python -m rewire.simulate
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import List, Callable
from unittest.mock import patch

from rewire.db import Store, CreateExpectationParams
from rewire.rules import schedule_evaluate, parse_params
from rewire.invariants import check_all_invariants, InvariantResult


@dataclass
class SimulationFrame:
    step: int
    action: str
    state_summary: dict
    invariant_results: List[InvariantResult]

    def __str__(self) -> str:
        passed = sum(1 for r in self.invariant_results if r.passed)
        failed = sum(1 for r in self.invariant_results if not r.passed)
        status = "✓" if failed == 0 else "✗"
        return f"[Frame {self.step}] {self.action}\n  {status} Invariants: {passed} passed, {failed} failed"


class Simulator:
    """Model simulator for Rewire."""

    def __init__(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.tmp.close()
        self.store = Store(self.tmp.name)
        self.store.init_db()
        self.current_time = 0
        self.frames: List[SimulationFrame] = []
        self.step = 0

    def cleanup(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _record_frame(self, action: str):
        """Record current state and check invariants."""
        with patch("rewire.invariants.now_i", return_value=self.current_time):
            _, _, results = check_all_invariants(self.store)

        # Get state summary
        exps = self.store.list_enabled_expectations()
        state = {
            "now": self.current_time,
            "expectations": len(exps),
            "observations": sum(
                len(self.store.recent_observations(e["id"], 100))
                for e in exps
            ),
        }

        frame = SimulationFrame(
            step=self.step,
            action=action,
            state_summary=state,
            invariant_results=results,
        )
        self.frames.append(frame)
        self.step += 1
        return frame

    def tick(self, delta: int):
        """Advance time."""
        self.current_time += delta
        return self._record_frame(f"tick({delta}) → now={self.current_time}")

    def create_schedule(self, exp_id: str, interval: int, tolerance: int = 0,
                        max_runtime: int = 0):
        """Create a schedule expectation."""
        params = {"max_runtime_s": max_runtime, "min_spacing_s": 0, "allow_overlap": False}
        self.store.create_expectation(CreateExpectationParams(
            exp_id=exp_id,
            exp_type="schedule",
            name=f"job-{exp_id}",
            expected_interval_s=interval,
            tolerance_s=tolerance,
            params_json=json.dumps(params),
            owner_email="sim@test",
        ))
        return self._record_frame(f"create_schedule({exp_id}, interval={interval}, tol={tolerance})")

    def observe(self, exp_id: str, kind: str):
        """Add an observation."""
        with self.store._conn() as conn:
            conn.execute(
                "INSERT INTO observations (expectation_id, kind, observed_at, meta_json) "
                "VALUES (?, ?, ?, ?)",
                (exp_id, kind, self.current_time, None)
            )
            conn.commit()
        return self._record_frame(f"observe({exp_id}, {kind}) at t={self.current_time}")

    def run_checker(self, exp_id: str):
        """Simulate checker tick for an expectation."""
        with patch("rewire.rules.now_i", return_value=self.current_time):
            exp = self.store.get_expectation(exp_id)
            obs = self.store.recent_observations(exp_id, 80)
            violations, close_codes = schedule_evaluate(exp, obs)

            # Apply violations
            for code, msg, ev in violations:
                if self.store.open_violation(exp_id, code) is None:
                    self.store.create_violation(exp_id, code, msg, json.dumps(ev))

            # Apply closes
            if close_codes:
                self.store.close_violations(exp_id, close_codes)

        return self._record_frame(f"checker({exp_id}) → {len(violations)} violations, close={close_codes}")


def run_schedule_simulation():
    """Demonstrate schedule expectation lifecycle."""
    print("=" * 60)
    print("SCHEDULE EXPECTATION SIMULATION")
    print("=" * 60)
    print()

    sim = Simulator()
    try:
        # Setup
        print(sim.create_schedule("e1", interval=60, tolerance=10, max_runtime=30))
        print()

        # Job starts
        print(sim.observe("e1", "start"))
        print(sim.run_checker("e1"))
        print()

        # Time passes, job still running
        print(sim.tick(25))
        print(sim.run_checker("e1"))
        print("  Note: running for 25s, max=30s, no longrun yet")
        print()

        # Job exceeds max runtime
        print(sim.tick(10))
        print(sim.run_checker("e1"))
        print("  Note: running for 35s > 30s, longrun violation created")
        print()

        # Job ends
        print(sim.observe("e1", "end"))
        print(sim.run_checker("e1"))
        print("  Note: longrun closed (job completed)")
        print()

        # Time passes, job becomes overdue
        print(sim.tick(50))
        print(sim.run_checker("e1"))
        print(f"  Note: {sim.current_time - 35}s since last start, threshold=70s")
        print()

        print(sim.tick(30))
        print(sim.run_checker("e1"))
        print("  Note: 80s > 70s threshold, missed violation created")
        print()

        # New job starts
        print(sim.observe("e1", "start"))
        print(sim.run_checker("e1"))
        print("  Note: missed closed (new start observed)")
        print()

        # Summary
        print("=" * 60)
        print("SIMULATION SUMMARY")
        print("=" * 60)
        total_checks = sum(len(f.invariant_results) for f in sim.frames)
        failures = sum(
            1 for f in sim.frames
            for r in f.invariant_results
            if not r.passed
        )
        print(f"Frames: {len(sim.frames)}")
        print(f"Invariant checks: {total_checks}")
        print(f"Invariant failures: {failures}")
        if failures == 0:
            print("✓ All invariants maintained throughout simulation")
        else:
            print("✗ Some invariant violations detected")
            for f in sim.frames:
                for r in f.invariant_results:
                    if not r.passed:
                        print(f"  Frame {f.step}: {r.name} - {r.message}")

    finally:
        sim.cleanup()


def run_counterexample_demo():
    """Show what happens when checker doesn't run."""
    print()
    print("=" * 60)
    print("COUNTEREXAMPLE: CHECKER NOT RUNNING")
    print("=" * 60)
    print()

    sim = Simulator()
    try:
        print(sim.create_schedule("e1", interval=60, tolerance=10))
        print()
        print(sim.observe("e1", "start"))
        print()

        # Time passes WITHOUT checker running
        print(sim.tick(100))
        print("  ⚠ Checker not run - checking invariants directly...")
        print()

        # Check invariants without running checker
        with patch("rewire.invariants.now_i", return_value=sim.current_time):
            _, failed, results = check_all_invariants(sim.store)

        for r in results:
            if not r.passed:
                print(f"  ✗ {r.name}")
                print(f"    {r.message}")
                if r.evidence:
                    print(f"    evidence: {r.evidence}")

        print()
        print("This demonstrates: invariants break if checker doesn't run.")
        print("The formal spec requires the checker to maintain the invariant.")

    finally:
        sim.cleanup()


if __name__ == "__main__":
    run_schedule_simulation()
    run_counterexample_demo()
