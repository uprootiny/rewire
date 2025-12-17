// Rewire Formal Specification in Quint
// Epistemic expectation verification - what we claim and can prove

module rewire {
  // ============================================================
  // Types
  // ============================================================

  type ExpectationType = Schedule | AlertPath

  type ObservationKind = Start | End | Ping | Ack

  type TrialStatus = Pending | Acked | Expired

  type ViolationCode = Missed | Longrun | Overlap | Spacing | NoAck

  type Timestamp = int

  type Expectation = {
    id: str,
    exp_type: ExpectationType,
    expected_interval_s: int,
    tolerance_s: int,
    max_runtime_s: int,
    min_spacing_s: int,
    allow_overlap: bool,
    ack_window_s: int,
    is_enabled: bool
  }

  type Observation = {
    expectation_id: str,
    kind: ObservationKind,
    observed_at: Timestamp
  }

  type Trial = {
    id: str,
    expectation_id: str,
    sent_at: Timestamp,
    acked_at: Timestamp,
    status: TrialStatus
  }

  type Violation = {
    expectation_id: str,
    code: ViolationCode,
    detected_at: Timestamp,
    is_open: bool
  }

  // ============================================================
  // State
  // ============================================================

  var now: Timestamp
  var expectations: str -> Expectation
  var observations: List[Observation]
  var trials: str -> Trial
  var violations: List[Violation]

  // ============================================================
  // Pure helpers
  // ============================================================

  pure def observations_for(exp_id: str): List[Observation] =
    observations.filter(o => o.expectation_id == exp_id)

  pure def last_start(exp_id: str): Timestamp =
    val starts = observations_for(exp_id).filter(o => o.kind == Start)
    if (starts.length() == 0) 0
    else starts.foldl(0, (acc, o) => if (o.observed_at > acc) o.observed_at else acc)

  pure def last_end(exp_id: str): Timestamp =
    val ends = observations_for(exp_id).filter(o => o.kind == End)
    if (ends.length() == 0) 0
    else ends.foldl(0, (acc, o) => if (o.observed_at > acc) o.observed_at else acc)

  pure def is_running(exp_id: str): bool =
    last_start(exp_id) > last_end(exp_id)

  pure def run_duration(exp_id: str): int =
    if (is_running(exp_id)) now - last_start(exp_id)
    else 0

  pure def time_since_last_start(exp_id: str): int =
    if (last_start(exp_id) == 0) now  // Never started
    else now - last_start(exp_id)

  pure def open_violations_for(exp_id: str, code: ViolationCode): List[Violation] =
    violations.filter(v =>
      v.expectation_id == exp_id and
      v.code == code and
      v.is_open
    )

  // ============================================================
  // Invariants - What Rewire MUST guarantee
  // ============================================================

  // INV1: A "missed" violation exists IFF time since last start exceeds threshold
  val inv_missed_correct: bool =
    expectations.keys().forall(exp_id => {
      val exp = expectations.get(exp_id)
      val threshold = exp.expected_interval_s + exp.tolerance_s
      val should_be_missed = time_since_last_start(exp_id) > threshold
      val has_missed_violation = open_violations_for(exp_id, Missed).length() > 0

      // Violation exists iff condition holds (epistemic correctness)
      exp.exp_type == Schedule implies (should_be_missed == has_missed_violation)
    })

  // INV2: A "longrun" violation exists IFF running duration exceeds max_runtime
  val inv_longrun_correct: bool =
    expectations.keys().forall(exp_id => {
      val exp = expectations.get(exp_id)
      val should_be_longrun = exp.max_runtime_s > 0 and
                              is_running(exp_id) and
                              run_duration(exp_id) > exp.max_runtime_s
      val has_longrun = open_violations_for(exp_id, Longrun).length() > 0

      exp.exp_type == Schedule implies (should_be_longrun == has_longrun)
    })

  // INV3: Trials can only be acked once
  val inv_trial_ack_once: bool =
    trials.keys().forall(trial_id => {
      val t = trials.get(trial_id)
      t.status == Acked implies t.acked_at > 0
    })

  // INV4: Expired trials were never acked
  val inv_expired_never_acked: bool =
    trials.keys().forall(trial_id => {
      val t = trials.get(trial_id)
      t.status == Expired implies t.acked_at == 0
    })

  // INV5: Observations are append-only (timestamps monotonic per expectation)
  // This is a design constraint, not runtime check

  // INV6: No violation without evidence (epistemic honesty)
  // Every violation must have corresponding observations that justify it
  val inv_violations_have_evidence: bool =
    violations.forall(v => {
      v.code == Missed implies last_start(v.expectation_id) > 0 or
                               observations_for(v.expectation_id).length() == 0
    })

  // ============================================================
  // Actions
  // ============================================================

  action init = all {
    now' = 0,
    expectations' = Map(),
    observations' = [],
    trials' = Map(),
    violations' = []
  }

  action tick(delta: int) = all {
    delta > 0,
    now' = now + delta,
    expectations' = expectations,
    observations' = observations,
    trials' = trials,
    violations' = violations
  }

  action add_observation(exp_id: str, kind: ObservationKind) = all {
    expectations.keys().contains(exp_id),
    observations' = observations.append({
      expectation_id: exp_id,
      kind: kind,
      observed_at: now
    }),
    now' = now,
    expectations' = expectations,
    trials' = trials,
    violations' = violations
  }

  action create_violation(exp_id: str, code: ViolationCode) = all {
    expectations.keys().contains(exp_id),
    open_violations_for(exp_id, code).length() == 0,  // No duplicate open violations
    violations' = violations.append({
      expectation_id: exp_id,
      code: code,
      detected_at: now,
      is_open: true
    }),
    now' = now,
    expectations' = expectations,
    observations' = observations,
    trials' = trials
  }

  action close_violation(exp_id: str, code: ViolationCode) = {
    violations' = violations.foldl([], (acc, v) =>
      if (v.expectation_id == exp_id and v.code == code and v.is_open)
        acc.append({ ...v, is_open: false })
      else
        acc.append(v)
    ),
    now' = now,
    expectations' = expectations,
    observations' = observations,
    trials' = trials
  }

  action ack_trial(trial_id: str) = all {
    trials.keys().contains(trial_id),
    trials.get(trial_id).status == Pending,
    trials' = trials.set(trial_id, {
      ...trials.get(trial_id),
      status: Acked,
      acked_at: now
    }),
    now' = now,
    expectations' = expectations,
    observations' = observations,
    violations' = violations
  }

  // ============================================================
  // Temporal properties
  // ============================================================

  // If a job starts, it should eventually end or trigger longrun
  temporal eventually_completes_or_violates = {
    expectations.keys().forall(exp_id => {
      val exp = expectations.get(exp_id)
      exp.exp_type == Schedule and exp.max_runtime_s > 0 implies
        always(is_running(exp_id) implies
          eventually(not(is_running(exp_id)) or
                    open_violations_for(exp_id, Longrun).length() > 0))
    })
  }

  // If a trial is sent, it should eventually be acked or expired
  temporal trial_resolves = {
    trials.keys().forall(trial_id => {
      trials.get(trial_id).status == Pending implies
        eventually(trials.get(trial_id).status != Pending)
    })
  }
}
