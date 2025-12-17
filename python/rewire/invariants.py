"""
Rewire invariants: Runtime checks derived from formal specification.

These assertions enforce the epistemic contract:
- Violations exist IFF evidence justifies them
- Trials have consistent state transitions
- Observations form monotonic append-only log

Run with: python -m rewire.invariants --db rewire.db
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rewire.db import Store
from rewire.rules import now_i, parse_params


@dataclass
class InvariantResult:
    """Result of an invariant check."""
    name: str
    passed: bool
    message: str
    evidence: Optional[dict] = None


def check_missed_correct(store: Store) -> List[InvariantResult]:
    """
    INV1: A 'missed' violation exists IFF time since last start exceeds threshold.

    Epistemic claim: We only report 'missed' when we have evidence of lateness.
    """
    results = []
    now = now_i()

    for exp in store.list_enabled_expectations():
        if exp["type"] != "schedule":
            continue

        exp_id = exp["id"]
        threshold = exp["expected_interval_s"] + exp["tolerance_s"]

        # Get last start time
        last_start = store.last_observation_time(exp_id, "start")

        # Determine if SHOULD be missed
        if last_start is None:
            # No starts ever - can't claim missed (epistemic honesty)
            should_be_missed = False
        else:
            age = now - last_start
            should_be_missed = age > threshold

        # Check if violation exists
        has_violation = store.open_violation(exp_id, "missed") is not None

        if should_be_missed == has_violation:
            results.append(InvariantResult(
                name=f"inv_missed_correct:{exp_id}",
                passed=True,
                message="Missed violation state matches evidence",
            ))
        else:
            results.append(InvariantResult(
                name=f"inv_missed_correct:{exp_id}",
                passed=False,
                message=f"Mismatch: should_be_missed={should_be_missed}, has_violation={has_violation}",
                evidence={
                    "last_start": last_start,
                    "threshold": threshold,
                    "now": now,
                    "age": now - last_start if last_start else None,
                },
            ))

    return results


def check_longrun_correct(store: Store) -> List[InvariantResult]:
    """
    INV2: A 'longrun' violation exists IFF running duration exceeds max_runtime.
    """
    results = []
    now = now_i()

    for exp in store.list_enabled_expectations():
        if exp["type"] != "schedule":
            continue

        exp_id = exp["id"]
        params = parse_params("schedule", exp["params_json"])

        if params.max_runtime_s == 0:
            continue  # Longrun check disabled

        last_start = store.last_observation_time(exp_id, "start")
        last_end = store.last_observation_time(exp_id, "end")

        # Is job running?
        is_running = (last_start is not None and
                      (last_end is None or last_start > last_end))

        if is_running:
            run_duration = now - last_start
            should_be_longrun = run_duration > params.max_runtime_s
        else:
            should_be_longrun = False

        has_violation = store.open_violation(exp_id, "longrun") is not None

        if should_be_longrun == has_violation:
            results.append(InvariantResult(
                name=f"inv_longrun_correct:{exp_id}",
                passed=True,
                message="Longrun violation state matches evidence",
            ))
        else:
            results.append(InvariantResult(
                name=f"inv_longrun_correct:{exp_id}",
                passed=False,
                message=f"Mismatch: should_be_longrun={should_be_longrun}, has_violation={has_violation}",
                evidence={
                    "last_start": last_start,
                    "last_end": last_end,
                    "is_running": is_running,
                    "max_runtime_s": params.max_runtime_s,
                },
            ))

    return results


def check_trial_states(store: Store) -> List[InvariantResult]:
    """
    INV3 & INV4: Trial state consistency.
    - Acked trials have acked_at > 0
    - Expired trials have acked_at = None
    """
    results = []

    with store._conn() as conn:
        trials = conn.execute("SELECT * FROM alert_trials").fetchall()

    for trial in trials:
        trial_id = trial["id"]
        status = trial["status"]
        acked_at = trial["acked_at"]

        # INV3: Acked implies acked_at set
        if status == "acked":
            if acked_at is not None and acked_at > 0:
                results.append(InvariantResult(
                    name=f"inv_acked_has_timestamp:{trial_id}",
                    passed=True,
                    message="Acked trial has timestamp",
                ))
            else:
                results.append(InvariantResult(
                    name=f"inv_acked_has_timestamp:{trial_id}",
                    passed=False,
                    message=f"Acked trial missing acked_at: {acked_at}",
                ))

        # INV4: Expired implies not acked
        if status == "expired":
            if acked_at is None:
                results.append(InvariantResult(
                    name=f"inv_expired_not_acked:{trial_id}",
                    passed=True,
                    message="Expired trial has no acked_at",
                ))
            else:
                results.append(InvariantResult(
                    name=f"inv_expired_not_acked:{trial_id}",
                    passed=False,
                    message=f"Expired trial has acked_at: {acked_at}",
                ))

    return results


def check_observation_monotonicity(store: Store) -> List[InvariantResult]:
    """
    INV5: Observations are append-only with monotonic timestamps.
    """
    results = []

    for exp in store.list_enabled_expectations():
        exp_id = exp["id"]
        obs = store.recent_observations(exp_id, limit=1000)

        # Should be newest first, so timestamps should decrease
        prev_time = None
        monotonic = True
        for o in obs:
            if prev_time is not None and o["observed_at"] > prev_time:
                monotonic = False
                break
            prev_time = o["observed_at"]

        if monotonic:
            results.append(InvariantResult(
                name=f"inv_observation_monotonic:{exp_id}",
                passed=True,
                message=f"Observations monotonic ({len(obs)} checked)",
            ))
        else:
            results.append(InvariantResult(
                name=f"inv_observation_monotonic:{exp_id}",
                passed=False,
                message="Observation timestamps not monotonic",
            ))

    return results


def check_all_invariants(store: Store) -> Tuple[int, int, List[InvariantResult]]:
    """Run all invariant checks. Returns (passed, failed, results)."""
    all_results = []

    all_results.extend(check_missed_correct(store))
    all_results.extend(check_longrun_correct(store))
    all_results.extend(check_trial_states(store))
    all_results.extend(check_observation_monotonicity(store))

    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)

    return passed, failed, all_results


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Check Rewire invariants")
    ap.add_argument("--db", required=True, help="SQLite database path")
    ap.add_argument("--verbose", "-v", action="store_true", help="Show all results")
    args = ap.parse_args()

    store = Store(args.db)
    passed, failed, results = check_all_invariants(store)

    print(f"Invariant check: {passed} passed, {failed} failed")

    for r in results:
        if not r.passed or args.verbose:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}: {r.message}")
            if r.evidence:
                print(f"         evidence: {json.dumps(r.evidence)}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
