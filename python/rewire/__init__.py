"""
Rewire: Epistemic expectation verification system.

Rewire claims only what it can prove with evidence:
- Expectations exist with explicit parameters
- Observations arrived (with timestamps)
- Reality matches or violates declared constraints
- Synthetic alerts were acknowledged at verifiable endpoints

Rewire refuses to claim:
- That a job's output is correct
- That a human noticed or acted
- That "delivery" implies "awareness"
"""

__version__ = "0.1.0"

from rewire.db import Store
from rewire.notify import Notifier, SMTPConfig
from rewire.rules import (
    ScheduleParams,
    AlertPathParams,
    parse_params,
    schedule_evaluate,
    alertpath_should_send_test,
)

__all__ = [
    "Store",
    "Notifier",
    "SMTPConfig",
    "ScheduleParams",
    "AlertPathParams",
    "parse_params",
    "schedule_evaluate",
    "alertpath_should_send_test",
]
