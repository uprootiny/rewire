# Rewire Development Journal

**Date:** 2025-12-18 (updated 2025-12-19)
**Project:** rewire-verify
**Status:** Published (GitHub, GitHub Pages, webhooks complete)

---

## Principles for Tiny Auxiliary Projects

These principles emerged from building Rewire and apply to similar small, focused tools.

### 1. Do One Thing Well

Rewire does one thing: verify that scheduled jobs run when expected. It doesn't:
- Execute the jobs
- Parse job output
- Manage job configuration
- Provide a full observability stack

This focus makes the codebase small (~800 lines of Python) and the mental model simple.

**Apply to other projects:**
- Define the single responsibility in one sentence
- Reject feature requests that blur the boundary
- If you need "and", you probably need two tools

### 2. Claim Only What You Can Prove

Rewire's "epistemic honesty" principle:
- ✓ "I received an observation at timestamp X"
- ✓ "No observation arrived within the expected window"
- ✗ "The job failed" (we don't know why, just that we didn't hear from it)
- ✗ "The alert was read" (we know it was delivered, not that anyone saw it)

**Apply to other projects:**
- Distinguish what your tool *observed* from what it *infers*
- Include evidence in every claim
- When uncertain, say so explicitly

### 3. Stdlib First, Dependencies Later

Rewire started with zero external dependencies:
- `http.server` for HTTP (not Flask/FastAPI)
- `sqlite3` for storage (not SQLAlchemy)
- `smtplib` for email (not SendGrid SDK)
- `urllib.request` for webhooks (not requests)

This makes installation trivial: `pip install rewire-verify` with no transitive dependencies.

**When to add dependencies:**
- When stdlib lacks the capability entirely
- When the dependency is stable and well-maintained
- When the benefit clearly outweighs the coupling

### 4. Formalize Invariants Early

Rewire has a Quint/TLA+ spec defining six invariants:
1. Violations exist iff constraints are violated
2. Observations have monotonic timestamps
3. Trial states follow valid transitions
4. etc.

The runtime invariant checker validates these against the live database.

**Apply to other projects:**
- Write down what must always be true
- Encode invariants as assertions or runtime checks
- Test the invariants, not just the happy path

### 5. Concrete Examples Beat Abstract Descriptions

First README draft: "Epistemic expectation verification system"
Final README: "Know when your cron jobs fail"

First use case: "Schedule monitoring"
Final use case: "Your nightly `pg_dump` to S3"

**Apply to other projects:**
- Lead with the pain point, not the solution
- Show real command-line invocations
- Include copy-pasteable examples

### 6. Ship, Then Iterate

Rewire shipped with email-only notifications. Webhooks came in the next iteration.

The initial envelope was intentionally tight:
- Forced clean design decisions
- Made the first version shippable in one session
- Created clear "next steps" for future work

**Apply to other projects:**
- Define the minimal viable feature set
- Ship it, get it working end-to-end
- Widen the envelope based on actual needs

### 7. Tests as Specification

Rewire's 39 tests document behavior:
- `test_missed_when_overdue` - what triggers a violation
- `test_no_missed_without_any_starts` - honest about unknowns
- `test_observation_monotonicity` - invariant enforcement

Reading the tests tells you how the system behaves.

**Apply to other projects:**
- Name tests after the behavior they verify
- Tests are documentation that can't go stale
- Property-based tests for invariants

### 8. Text Streams as Interface

Rewire communicates via:
- HTTP JSON API (text over the network)
- SQLite (queryable with standard tools)
- Plain text emails
- JSON webhook payloads

No binary protocols, no proprietary formats.

**Apply to other projects:**
- Prefer JSON over custom binary formats
- Make data inspectable with standard tools
- Log in structured formats (JSON lines)

---

## Project-Specific Lessons

### What Took Time and Effort

| Task | Time | Lesson |
|------|------|--------|
| Envelope constraints | 30 min | Stdlib-only is clean but has a ceiling |
| Formal specification | 45 min | Clarifies thinking, worth the investment |
| Dual implementations | 40 min | Don't maintain two unless you test both |
| Landing page copy | 30 min | Iterate from abstract to concrete |
| PyPI packaging | 20 min | pyproject.toml works, but has gotchas |
| Webhook integration | 45 min | Widened envelope with zero new deps |

### The Envelope Evolution

**v0.1 (initial):**
- Email-only notifications
- SQLite storage
- Stdlib HTTP server
- Single admin token

**v0.2 (current):**
- Slack, Discord, generic HTTP webhooks
- Same stdlib-only approach
- 39 tests, formal spec

**Potential v0.3:**
- `/metrics` endpoint (Prometheus)
- `/health` endpoint (Kubernetes)
- YAML config file

---

## Checklist for New Tiny Projects

Use this checklist when starting a new auxiliary tool:

```
[ ] One-sentence description of what it does
[ ] One-sentence description of what it doesn't do
[ ] Identify the single data format (JSON, SQLite, text)
[ ] List invariants that must always hold
[ ] Write three concrete use cases with commands
[ ] Define the minimal feature set for v0.1
[ ] Choose: stdlib-only or minimal dependencies?
[ ] Set up: tests, CI, README, LICENSE
[ ] Ship it somewhere (GitHub, PyPI, Docker Hub)
[ ] Write down what v0.2 could add
```

---

## Anti-Patterns to Avoid

### 1. Premature Abstraction
Bad: "Let's add a plugin system for notification backends"
Good: Add Slack webhook directly, refactor later if needed

### 2. Configuration Explosion
Bad: 47 environment variables for every possible option
Good: Sensible defaults, override only what matters

### 3. Claiming Too Much
Bad: "Rewire ensures your jobs run successfully"
Good: "Rewire tells you when it didn't hear from your job"

### 4. Framework Addiction
Bad: "Let's use FastAPI, SQLAlchemy, Celery, Redis..."
Good: Start with stdlib, add dependencies when pain is clear

### 5. Premature Optimization
Bad: "We need async for performance"
Good: Blocking HTTP server handles thousands of requests fine

---

## Links

- **Repository:** https://github.com/uprootiny/rewire
- **Landing Page:** https://uprootiny.github.io/rewire
- **Package:** `pip install rewire-verify`

---

## Relation to Raindesk Witnesses

Raindesk is a "witness dashboard" - a read-only projection of infrastructure state across multiple servers. The key insight from its audit:

> "Dashboard is a projection of an event log. If there is no event log, the dashboard is fiction."

### Shared Epistemic Philosophy

| Principle | Rewire | Raindesk |
|-----------|--------|----------|
| Witness vs Control | Observes job timing, doesn't run jobs | Shows state, doesn't modify it |
| Append-only truth | SQLite observations log | JSONL event ledger |
| Claim only provable | "No observation in window" not "job failed" | "Last seen at X" not "service healthy" |
| Evidence required | Violations include timestamps, durations | Events include source, commit, timestamp |

### The Witness Pattern

Both projects implement the **witness pattern**:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Reality    │────▶│  Event Log   │────▶│   Witness    │
│ (jobs, hosts)│     │(append-only) │     │ (dashboard)  │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                     ┌──────┴──────┐
                     │  Validator  │
                     │ (invariants)│
                     └─────────────┘
```

**Witnesses don't control.** They truthfully project what the event log contains.

**Controllers don't witness.** They take actions and write events to the log.

This separation prevents:
- Dashboards that lie (showing aspirational state)
- Controllers that can't be audited (actions without events)
- Circular dependencies (dashboard triggers action that updates dashboard)

### How Rewire Fits Into Raindesk

The PROJECT-AUDIT recommends deploying Rewire as Raindesk's event log:

```
┌─────────────────────────────────────────────────────────┐
│                     raindesk.dev                         │
│              (Read-only witness dashboard)               │
└──────────────────────────┬──────────────────────────────┘
                           │ fetches /witness.json
           ┌───────────────┴───────────────┐
           │                               │
    ┌──────┴──────┐                ┌───────┴──────┐
    │ Hyperstitious│                │    FinML     │
    └──────┬──────┘                └───────┬──────┘
           │                               │
    ┌──────┴──────┐                ┌───────┴──────┐
    │   Rewire    │                │   Rewire     │
    │ (Event log) │                │ (Event log)  │
    └─────────────┘                └──────────────┘
```

Jobs POST to Rewire → Rewire validates constraints → Raindesk reads Rewire's SQLite → Dashboard shows truth.

### Applying These Principles

When building witness systems:

1. **Define what "truth" means** - What can you actually observe? A timestamp? A status code? A file hash?

2. **Separate read and write paths** - Writers append to the log. Readers project from the log. Never mix.

3. **Make staleness visible** - If data is 5 minutes old, say so. "Last updated: 5m ago" not a green checkmark.

4. **Invariants are biconditionals** - `is_violated ↔ constraint_broken`. Not "if we detect it" but "iff it's true".

5. **Events are immutable** - Never update an event. Append a correction event instead.

### Anti-Patterns in Witness Systems

| Anti-Pattern | Example | Fix |
|--------------|---------|-----|
| Optimistic display | Show "healthy" until proven sick | Show "unknown" until proven healthy |
| Stale cache | Cache says "up" but service died 10min ago | Always show cache age |
| Circular witness | Dashboard triggers alert that updates dashboard | Separate witness from controller |
| Invented data | Show "99.9% uptime" without measurement | Show only measured values |

---

## Changelog

- **2025-12-18:** Initial release with email notifications
- **2025-12-19:** Added webhook support (Slack, Discord, generic HTTP)
- **2025-12-19:** Added witness pattern documentation (Raindesk connection)
