"""
Rewire rule evaluation: schedule and alert-path constraint checking.

All evaluations return evidence-based results.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any

Timestamp = int
Evidence = Dict[str, Any]
ViolationTuple = Tuple[str, str, Evidence]  # (code, message, evidence)


def now_i() -> Timestamp:
    """Current Unix timestamp as integer."""
    return int(time.time())


@dataclass(frozen=True)
class ScheduleParams:
    """Constraints for schedule-type expectations."""
    max_runtime_s: int   # 0 disables check
    min_spacing_s: int   # 0 disables check
    allow_overlap: bool


@dataclass(frozen=True)
class AlertPathParams:
    """Constraints for alert-path expectations."""
    ack_window_s: int     # time allowed to acknowledge
    test_interval_s: int  # how often to send synthetic test


def parse_params(exp_type: str, params_json: str) -> ScheduleParams | AlertPathParams:
    """Parse type-specific parameters from JSON."""
    obj = json.loads(params_json)
    if exp_type == "schedule":
        return ScheduleParams(
            max_runtime_s=int(obj.get("max_runtime_s", 0)),
            min_spacing_s=int(obj.get("min_spacing_s", 0)),
            allow_overlap=bool(obj.get("allow_overlap", False)),
        )
    if exp_type == "alert_path":
        return AlertPathParams(
            ack_window_s=int(obj["ack_window_s"]),
            test_interval_s=int(obj["test_interval_s"]),
        )
    raise ValueError(f"unknown expectation type: {exp_type}")


def schedule_evaluate(
    exp_row: Any, obs_rows_desc: List[Any]
) -> Tuple[List[ViolationTuple], List[str]]:
    """
    Evaluate schedule constraints against observations.

    Args:
        exp_row: Expectation row from database
        obs_rows_desc: Observations sorted by observed_at DESC (newest first)

    Returns:
        Tuple of (violations, codes_to_close)
        - violations: list of (code, message, evidence) tuples
        - codes_to_close: list of violation codes that should be closed
    """
    params = parse_params("schedule", exp_row["params_json"])
    expected = int(exp_row["expected_interval_s"])
    tol = int(exp_row["tolerance_s"])
    t = now_i()

    violations: List[ViolationTuple] = []
    close_codes: List[str] = []

    # Find most recent start
    last_start = next(
        (r for r in obs_rows_desc if r["kind"] == "start"), None
    )

    # Check: missed execution
    if last_start:
        age = t - int(last_start["observed_at"])
        if age > expected + tol:
            violations.append((
                "missed",
                f"Expected a start within {expected}s (+{tol}s); last start was {age}s ago.",
                {
                    "last_start_at": int(last_start["observed_at"]),
                    "age_s": age,
                    "expected_s": expected,
                    "tolerance_s": tol,
                },
            ))
        else:
            close_codes.append("missed")

    # Check: overlap / longrun
    if last_start:
        start_t = int(last_start["observed_at"])
        # Find end after this start
        newer_end = next(
            (r for r in obs_rows_desc
             if r["kind"] == "end" and int(r["observed_at"]) >= start_t),
            None
        )

        if newer_end is None:
            # Job may still be running
            run_for = t - start_t
            if params.max_runtime_s and run_for > params.max_runtime_s:
                violations.append((
                    "longrun",
                    f"Run exceeded max_runtime_s={params.max_runtime_s}; running for {run_for}s.",
                    {
                        "start_at": start_t,
                        "running_for_s": run_for,
                        "max_runtime_s": params.max_runtime_s,
                    },
                ))
            else:
                close_codes.append("longrun")

            # Check overlap (start without end while another running)
            if not params.allow_overlap:
                starts_without_end = [
                    r for r in obs_rows_desc if r["kind"] == "start"
                ]
                if len(starts_without_end) > 1:
                    second = starts_without_end[1]
                    if int(second["observed_at"]) < start_t:
                        # There's an earlier start that also has no end
                        violations.append((
                            "overlap",
                            "Detected overlapping runs.",
                            {
                                "newest_start_at": start_t,
                                "other_start_at": int(second["observed_at"]),
                            },
                        ))
                    else:
                        close_codes.append("overlap")
                else:
                    close_codes.append("overlap")
        else:
            # Job completed
            close_codes.extend(["longrun", "overlap"])

            # Check spacing
            if params.min_spacing_s:
                prev_end = next(
                    (r for r in obs_rows_desc
                     if r["kind"] == "end" and int(r["observed_at"]) < start_t),
                    None
                )
                if prev_end:
                    gap = start_t - int(prev_end["observed_at"])
                    if gap < params.min_spacing_s:
                        violations.append((
                            "spacing",
                            f"Start occurred {gap}s after previous end; min_spacing_s={params.min_spacing_s}.",
                            {
                                "gap_s": gap,
                                "min_spacing_s": params.min_spacing_s,
                                "prev_end_at": int(prev_end["observed_at"]),
                                "start_at": start_t,
                            },
                        ))
                    else:
                        close_codes.append("spacing")

    return violations, close_codes


def alertpath_should_send_test(
    exp_row: Any, last_any_obs_time: Optional[Timestamp]
) -> bool:
    """Determine if it's time to send a synthetic alert test."""
    params = parse_params("alert_path", exp_row["params_json"])
    if last_any_obs_time is None:
        return True
    return (now_i() - int(last_any_obs_time)) >= params.test_interval_s
