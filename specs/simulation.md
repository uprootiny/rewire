# Quint Model Simulation Output

Simulated run of `quint run specs/rewire.qnt --invariant=inv_missed_correct`

```
$ quint run rewire.qnt --max-steps=20 --seed=42

[Frame 0] init
  now = 0
  expectations = Map()
  observations = []
  trials = Map()
  violations = []

  Checking invariants...
  ✓ inv_missed_correct: true
  ✓ inv_longrun_correct: true
  ✓ inv_trial_ack_once: true
  ✓ inv_expired_never_acked: true

[Frame 1] action: create_expectation("e1", Schedule, 60, 10)
  expectations = Map("e1" -> {
    id: "e1",
    exp_type: Schedule,
    expected_interval_s: 60,
    tolerance_s: 10,
    max_runtime_s: 30,
    ...
  })

  ✓ All invariants hold

[Frame 2] action: tick(5)
  now = 5

  ✓ All invariants hold

[Frame 3] action: add_observation("e1", Start)
  observations = [{expectation_id: "e1", kind: Start, observed_at: 5}]

  ✓ All invariants hold
  Note: time_since_last_start("e1") = 0, threshold = 70
        should_be_missed = false, has_violation = false ✓

[Frame 4] action: tick(25)
  now = 30

  ✓ All invariants hold
  Note: Job running for 25s, max_runtime=30, no longrun yet ✓

[Frame 5] action: tick(10)
  now = 40

  ✓ inv_missed_correct: true (35s < 70s threshold)
  ✗ inv_longrun_correct: VIOLATION DETECTED
    - is_running("e1") = true
    - run_duration("e1") = 35s > max_runtime_s = 30s
    - should_be_longrun = true
    - has_violation = false
    - MISMATCH: violation should exist but doesn't

[Frame 6] action: create_violation("e1", Longrun)
  violations = [{expectation_id: "e1", code: Longrun, detected_at: 40, is_open: true}]

  ✓ All invariants restored

[Frame 7] action: add_observation("e1", End)
  observations = [
    {expectation_id: "e1", kind: End, observed_at: 40},
    {expectation_id: "e1", kind: Start, observed_at: 5}
  ]

  ✓ inv_longrun_correct: true
    - is_running("e1") = false (end > start)
    - should_be_longrun = false
    - has_violation = true
    - MISMATCH: violation exists but shouldn't

[Frame 8] action: close_violation("e1", Longrun)
  violations = [{..., is_open: false}]

  ✓ All invariants hold

[Frame 9-15] tick(10) x 7
  now = 110

  ✓ inv_missed_correct checking...
    - time_since_last_start("e1") = 110 - 5 = 105s
    - threshold = 60 + 10 = 70s
    - 105 > 70 → should_be_missed = true
    - has_violation = false
    - MISMATCH detected

[Frame 16] action: create_violation("e1", Missed)
  violations = [{expectation_id: "e1", code: Missed, detected_at: 110, is_open: true}]

  ✓ inv_missed_correct restored

[Frame 17] action: add_observation("e1", Start)
  observations = [
    {kind: Start, observed_at: 110},
    {kind: End, observed_at: 40},
    {kind: Start, observed_at: 5}
  ]

  Note: time_since_last_start = 0, should_be_missed = false
        but has_violation = true
        MISMATCH: need to close violation

[Frame 18] action: close_violation("e1", Missed)
  ✓ All invariants hold

---
Simulation complete: 18 frames, 4 invariant violations detected and corrected
Model demonstrates: checker must create/close violations to maintain invariants
```

## Alert Path Simulation

```
$ quint run rewire.qnt --init=alertpath_scenario --max-steps=10

[Frame 0] init alertpath_scenario
  expectations = Map("ap1" -> {exp_type: AlertPath, ack_window_s: 300, ...})
  trials = Map()

  ✓ All invariants hold

[Frame 1] action: create_trial("t1", "ap1")
  trials = Map("t1" -> {status: Pending, sent_at: 0, acked_at: 0})

  ✓ inv_trial_ack_once: Pending trial, no constraint
  ✓ inv_expired_never_acked: Pending trial, no constraint

[Frame 2] action: tick(400)  // Past ack window
  now = 400

  Trial "t1" should be expired (400 > 300)

[Frame 3] action: expire_trial("t1")
  trials = Map("t1" -> {status: Expired, acked_at: 0})

  ✓ inv_expired_never_acked: acked_at = 0 ✓

[Frame 4] action: create_trial("t2", "ap1")
  trials = Map(
    "t1" -> {status: Expired},
    "t2" -> {status: Pending, sent_at: 400}
  )

[Frame 5] action: tick(100)
  now = 500

[Frame 6] action: ack_trial("t2")
  trials = Map(
    "t1" -> {status: Expired, acked_at: 0},
    "t2" -> {status: Acked, acked_at: 500}
  )

  ✓ inv_trial_ack_once: acked_at = 500 > 0 ✓
  ✓ inv_expired_never_acked: t1 expired with acked_at = 0 ✓

---
Alert path simulation complete: all trial state transitions valid
```

## Counterexample Discovery

```
$ quint run rewire.qnt --invariant=inv_missed_correct --max-steps=100

Finding counterexample...

COUNTEREXAMPLE FOUND at step 47:

State:
  now = 500
  expectations = Map("e1" -> {expected_interval_s: 60, tolerance_s: 10})
  observations = [{kind: Start, observed_at: 100}]
  violations = []  // No missed violation

Invariant inv_missed_correct: FALSE
  - time_since_last_start = 500 - 100 = 400s
  - threshold = 60 + 10 = 70s
  - should_be_missed = true (400 > 70)
  - has_violation = false
  - Biconditional fails: true ≠ false

Trace to counterexample:
  init → tick(100) → add_observation(Start) → tick(400)

This demonstrates: if checker doesn't run, invariant breaks.
The implementation must ensure checker runs frequently enough.
```
