# Rewire

Epistemic expectation verification for scheduled jobs and alert delivery paths.

## What this is

A small service that tracks whether scheduled jobs run when expected and whether alert delivery paths actually work. It stores observations (start/end events, pings, acknowledgments) and detects mismatches between expectations and reality.

## What this is not

- Not a replacement for proper monitoring systems
- Not a guarantee that jobs succeed (only that they ran)
- Not a proof that humans read alerts (only that the delivery path worked)
- Not production-hardened (use at your own risk)

## Structure

```
rewire/
  python/        # Python stdlib implementation
    rewire/      # Package source
    tests/       # unittest tests
    pyproject.toml
  clojure/       # Clojure implementation
    src/rewire/  # Source namespaces
    test/rewire/ # Tests
    deps.edn
  docs/          # Documentation
```

## Python usage

```sh
cd python

# Initialize database
python3 -m rewire.server --db rewire.db --init-db --base-url http://localhost:8080

# Run server
python3 -m rewire.server --db rewire.db --base-url http://localhost:8080

# Create a schedule expectation
python3 -m rewire.cli --base-url http://localhost:8080 --admin-token dev-admin-token \
  new-schedule --name "nightly-backup" --email you@example.com \
  --expected-interval-s 86400 --tolerance-s 1800

# Instrument your job
curl -fsS -X POST 'http://localhost:8080/observe/EXP_ID' -d kind=start
# ... do work ...
curl -fsS -X POST 'http://localhost:8080/observe/EXP_ID' -d kind=end
```

## Clojure usage

```sh
cd clojure

# Run with deps.edn
clj -M:run --db rewire.db --init-db --base-url http://localhost:8080
```

## Running tests

Python:
```sh
cd python && PYTHONPATH=. python3 -m unittest discover -s tests -v
```

Clojure:
```sh
cd clojure && clj -M:test
```

## Expectations

Two types:

1. **schedule**: Expects periodic job runs with start/end observations
   - Detects: missed runs, long-running jobs, overlapping runs, insufficient spacing

2. **alert_path**: Periodically sends synthetic test alerts requiring acknowledgment
   - Detects: unacknowledged tests (broken delivery path)

## Epistemic contract

Rewire claims only what it can prove:
- An expectation exists with explicit parameters
- Observations arrived (with timestamps)
- Reality matches or violates declared constraints

Rewire refuses to claim:
- That a job's output is correct
- That a human noticed or acted
- That "delivery" implies "awareness"

## Limitations

- Single SQLite database (not distributed)
- No authentication beyond admin token
- Email-only notifications (no webhooks, PagerDuty, etc.)
- No web UI
- Minimal error handling
- Not tested under load
- LLM-assisted development (see PROVENANCE.md)

## License

MIT
