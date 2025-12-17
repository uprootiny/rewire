# Project Summary

## 1. Project Name

**Rewire** - Expectation verification for scheduled jobs

## 2. What problem I was actually trying to solve

I wanted to know when my cron jobs failed to run or when my alert delivery paths stopped working. Existing monitoring tells me when things are broken, but doesn't verify that the monitoring itself works. I needed something that:
- Checks if scheduled jobs actually ran (not just that they succeeded)
- Verifies alert delivery paths by sending test alerts and requiring acknowledgment

## 3. What the project does (mechanically)

**Inputs:**
- Expectations: "job X should run every N seconds with tolerance T"
- Observations: HTTP POST calls with kind=start|end|ping|ack

**Transformations:**
- Compares latest observations against expectation constraints
- Detects: missed runs, long-running jobs, overlapping runs, unacknowledged alerts

**Outputs:**
- Email notifications when violations detected
- HTTP API responses with observation history
- SQLite database with append-only observation log

## 4. What this project explicitly does NOT do

- Does not verify job correctness (only that jobs ran)
- Does not guarantee humans read alerts (only that delivery worked)
- Does not provide a web UI
- Does not support distributed deployment
- Does not integrate with PagerDuty, Slack, or webhooks
- Does not authenticate API requests beyond a single admin token
- Does not scale to high traffic

## 5. How I would realistically use this myself

- Deploy on a single VPS alongside my existing services
- Create 2-3 schedule expectations for critical cron jobs
- Add curl calls to job scripts for start/end observations
- Check violation emails occasionally
- Probably forget about it after initial setup

Frequency: Set up once, ignore until something breaks. Maybe revisit in 6 months.

## 6. Known limitations and failure modes

**Technical:**
- SQLite doesn't handle high concurrent writes well
- Checker thread runs in-process (if server dies, checks stop)
- No retry logic for email delivery
- Clojure notify.clj requires javax.mail (may not be available)

**Conceptual:**
- "Observation arrived" doesn't mean "job succeeded"
- Time-based checks are fragile (clock drift, network delays)
- Single point of failure (the verifier itself)

**Epistemic:**
- Rule evaluation logic was LLM-generated; edge cases untested
- Overlap detection algorithm may have subtle bugs
- No formal verification of constraint logic

**LLM-related risk:**
- Code may contain subtle logical errors I haven't caught
- Test coverage designed by LLM may miss important cases
- Documentation may overclaim capabilities

## 7. Tooling provenance

**What I did:**
- Provided initial specification (from starthere file)
- Requested Python + Clojure implementations
- Requested tests and documentation

**What LLMs helped with:**
- All code generation (both Python and Clojure)
- Test design and implementation
- Documentation and README
- This summary

**What remains uncertain:**
- Whether Clojure implementation actually runs (not tested)
- Edge case behavior in rule evaluation
- Thread safety under concurrent load

## 8. Maintenance expectations

**Experimental / Likely dormant**

I built this to solve a specific friction. I may:
- Use it briefly
- Fork it later
- Never touch it again

No commitment to issues, PRs, or support.

## 9. Who might find this useful (narrowly defined)

Someone who:
- Runs a few cron jobs on a single VPS
- Wants dead-simple "did it run?" checks
- Is comfortable with curl-based instrumentation
- Doesn't need fancy integrations
- Accepts that this is a one-person hobby project
- Can read and fix the code themselves if it breaks
