# Rewire Development Journal

**Date:** 2025-12-18
**Project:** rewire-verify
**Status:** Published (GitHub, GitHub Pages, PyPI-ready)

---

## What Took Time and Effort

### 1. The Envelope Constraint (30 min)

The original spec was aggressively minimal:
- Python stdlib only
- SQLite only
- Single VPS
- Email-only notifications
- No dependencies

This constraint made the code clean but created real limitations:
- No async (stdlib http.server is blocking)
- No proper job queue (checker runs in-thread)
- No webhooks without adding requests
- No dashboard without adding Flask/FastAPI

**Lesson:** The "stdlib only" constraint is good for bootstrapping but creates a ceiling quickly.

### 2. Formal Specification (45 min)

Writing the Quint spec required thinking carefully about:
- What exactly is an invariant vs. a temporal property?
- When should a violation exist vs. not exist?
- The biconditional: `should_be_violated == has_violation`

The key insight: **the checker is responsible for maintaining invariants**. Between checker ticks, invariants can be violated. This is correct behavior, not a bug.

**Lesson:** Formal specs clarify thinking but don't write themselves. The simulation showing invariant violations between ticks was the "aha" moment.

### 3. The Two-Implementation Approach (40 min)

Writing both Python and Clojure versions:
- Python: straightforward, tests pass
- Clojure: written but not runtime-tested (no clj in environment)

**Lesson:** Dual implementations sound good but double the maintenance. The Clojure version may have bugs I couldn't catch.

### 4. Landing Page Copy (30 min)

Finding the right value proposition took iteration:
- First draft: too abstract ("epistemic verification")
- Second draft: too technical ("constraint evaluation")
- Final: **"Know when your cron jobs fail"** - concrete pain point

The use cases needed to be specific:
- Not "monitoring" but "your nightly pg_dump"
- Not "alerting" but "Finance expects the report Monday 9am"

**Lesson:** Concrete scenarios beat abstract features.

### 5. PyPI Packaging (20 min)

Friction points:
- README path outside package directory
- License format deprecation warnings
- Dependency conflicts with twine/urllib3

**Lesson:** Python packaging has rough edges. The new pyproject.toml format is better but still has gotchas.

---

## The Tight Envelope Problem

Rewire's current constraints:

| Constraint | Implication |
|------------|-------------|
| Email-only | No Slack, PagerDuty, webhooks |
| SQLite-only | No horizontal scaling |
| Stdlib HTTP | No async, no WebSocket |
| Single-binary | No dashboard, no API explorer |
| No auth beyond token | No multi-tenant |

These make it a **personal tool**, not a **team tool**.

---

## Brainstorm: Widening the Envelope

### Tier 1: Minimal Additions (keep stdlib spirit)

1. **Webhook notifications**
   - Add `urllib.request` POST to arbitrary URLs
   - JSON payload with violation details
   - Enables Slack/Discord via incoming webhooks
   - ~50 lines of code

2. **Prometheus metrics endpoint**
   - `/metrics` endpoint with text format
   - `rewire_expectations_total`, `rewire_violations_open`
   - No dependencies (text format is simple)
   - Enables Grafana dashboards

3. **SQLite → PostgreSQL option**
   - psycopg2 is well-maintained
   - Same schema, connection string flag
   - Enables cloud databases, replication

### Tier 2: Useful Dependencies (small additions)

4. **Simple web dashboard**
   - Add Flask (~1 dependency)
   - List expectations, recent observations, open violations
   - No JS framework, just server-rendered HTML
   - Mobile-friendly status page

5. **YAML config file**
   - Define expectations in YAML, not just CLI
   - Version-control your monitoring config
   - `rewire sync --config expectations.yaml`

6. **Healthcheck integration**
   - `/health` returns JSON with all expectation statuses
   - Kubernetes readiness/liveness probes
   - Uptime monitoring integration

### Tier 3: Real Product Features

7. **Multi-tenant mode**
   - API keys per user/org
   - Isolation of expectations
   - Usage limits

8. **Incident timeline**
   - When did violation start?
   - When was it acknowledged?
   - When did it resolve?
   - Export to CSV/JSON

9. **Runbook links**
   - Attach runbook URL to each expectation
   - Violation emails include "What to do" link
   - Reduces MTTR

10. **Dead man's switch mode**
    - Inverse of schedule: "alert if I DON'T hear from this service"
    - Heartbeat monitoring
    - Common pattern, simple to add

---

## Recommended Next Steps

### Quick Wins (1-2 hours each)

1. **Add webhook notifications** - highest ROI, enables all integrations
2. **Add `/metrics` endpoint** - observability without dashboard
3. **Add YAML config** - GitOps-friendly

### Medium Effort (half-day each)

4. **Flask dashboard** - visual status page
5. **PostgreSQL support** - production-ready storage
6. **Healthcheck endpoint** - Kubernetes integration

### Larger Scope (multi-day)

7. **Multi-tenant SaaS** - requires auth, billing, isolation
8. **Managed service** - infrastructure, operations, support

---

## What Would Make This Truly Useful?

The current version solves: "I want to know if my cron job didn't run."

To be **widely useful**, it needs to solve: "My team wants visibility into all our scheduled jobs without setting up Datadog."

That requires:
- Dashboard (visual status)
- Team access (multi-user)
- Integrations (Slack, PagerDuty)
- Easy deployment (Docker, one-click)

The **minimum viable widening**: webhooks + dashboard + Docker image.

---

## Honest Assessment

**Rewire is currently a good personal tool.**

It's well-documented, formally specified, and works. But the envelope is too tight for team use.

**To make it sellable:**
1. Add webhooks (Slack integration)
2. Add simple dashboard
3. Publish Docker image
4. Write "5-minute setup" guide

That's maybe 8 hours of work to go from "interesting project" to "useful product."
