# Rewire

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-26%20passing-brightgreen.svg)](#testing)
[![Formally Specified](https://img.shields.io/badge/formally-specified-purple.svg)](specs/rewire.qnt)

**Epistemic verification for scheduled jobs and alert delivery paths.**

Know when your cron jobs fail. Verify your alerts actually deliver. Rewire claims only what evidence supports.

[**Documentation**](https://uprootiny.github.io/rewire) · [**GitHub**](https://github.com/uprootiny/rewire) · [**Report Bug**](https://github.com/uprootiny/rewire/issues)

---

## The Problem

Your monitoring tells you when services are down. But who monitors the monitoring?

- Did that nightly backup actually run?
- Is your alerting pipeline actually delivering?
- When a cron job silently fails, how long until you notice?

## The Solution

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Your Jobs  │────▶│   Rewire    │────▶│   Alerts    │
│  (curl)     │     │   Server    │     │   (email)   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │   SQLite    │
                    │ (append-only│
                    │ observations)│
                    └─────────────┘
```

## Quick Start

### Install from PyPI

```bash
pip install rewire-verify
```

### Or run from source

```bash
git clone https://github.com/uprootiny/rewire.git
cd rewire/python
```

### Start the server

```bash
# Initialize and run
python3 -m rewire.server \
  --db rewire.db \
  --init-db \
  --base-url http://localhost:8080 \
  --admin-token your-secret-token
```

### Create an expectation

```bash
# Schedule: "nightly-backup runs every 24h with 30min tolerance"
python3 -m rewire.cli \
  --base-url http://localhost:8080 \
  --admin-token your-secret-token \
  new-schedule \
  --name "nightly-backup" \
  --email you@example.com \
  --expected-interval-s 86400 \
  --tolerance-s 1800 \
  --max-runtime-s 3600
```

### Instrument your job

```bash
#!/bin/bash
# your-backup-script.sh

REWIRE_URL="http://localhost:8080/observe/YOUR_EXP_ID"

curl -fsS -X POST "$REWIRE_URL" -d kind=start

# ... do actual backup work ...
pg_dump mydb > backup.sql

curl -fsS -X POST "$REWIRE_URL" -d kind=end
```

If the job doesn't run, or runs too long, or overlaps—you get an email.

## Features

### Schedule Verification
- **Missed runs**: Alert when expected interval exceeded
- **Long-running jobs**: Alert when max runtime exceeded
- **Overlapping runs**: Detect concurrent executions
- **Spacing violations**: Enforce minimum gap between runs

### Alert Path Testing
- Periodic synthetic test alerts
- Requires explicit acknowledgment (click a link)
- Detects broken email delivery, spam filters, etc.

### Formal Specification
- [Quint/TLA+ specification](specs/rewire.qnt) defines invariants
- Runtime invariant checker validates system state
- Model simulation demonstrates correctness

```bash
# Check invariants against live database
python3 -m rewire.invariants --db rewire.db

# Run model simulation
python3 -m rewire.simulate
```

## Epistemic Contract

**Rewire claims only what it can prove:**
- ✓ An expectation exists with explicit parameters
- ✓ Observations arrived (with timestamps)
- ✓ Reality matches or violates declared constraints

**Rewire refuses to claim:**
- ✗ That a job's output is correct
- ✗ That a human noticed or acted
- ✗ That "delivery" implies "awareness"

Every violation includes evidence. No guesswork.

## API Reference

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/status` | Health check |
| GET | `/observe/:id` | Get expectation details |
| POST | `/observe/:id` | Record observation (kind=start\|end\|ping) |
| GET | `/ack/:trial_id` | Acknowledge alert test |
| POST | `/admin/new` | Create expectation (requires auth) |
| POST | `/admin/enable` | Enable expectation |
| POST | `/admin/disable` | Disable expectation |

### Observation Kinds

| Kind | Description |
|------|-------------|
| `start` | Job execution started |
| `end` | Job execution completed |
| `ping` | Heartbeat / alive signal |
| `ack` | Alert acknowledgment |

## Deployment

### systemd

```bash
# Copy files
sudo cp -r python/rewire /opt/rewire/
sudo cp deploy/rewire.service /etc/systemd/system/

# Configure
sudo cp deploy/example.env /etc/rewire.env
sudo vim /etc/rewire.env  # Edit settings

# Start
sudo systemctl daemon-reload
sudo systemctl enable rewire
sudo systemctl start rewire
```

### Docker (coming soon)

```bash
docker run -d \
  -v rewire-data:/data \
  -e REWIRE_BASE_URL=https://your-domain.com \
  -p 8080:8080 \
  uprootiny/rewire
```

## Testing

```bash
cd python

# Run all tests
PYTHONPATH=. python3 -m unittest discover -s tests -v

# Check invariants
python3 -m rewire.invariants --db test.db --verbose

# Run simulation
python3 -m rewire.simulate
```

## Project Structure

```
rewire/
├── python/
│   ├── rewire/
│   │   ├── server.py      # HTTP server + checker
│   │   ├── db.py          # SQLite storage
│   │   ├── rules.py       # Constraint evaluation
│   │   ├── notify.py      # Email notifications
│   │   ├── invariants.py  # Runtime invariant checker
│   │   └── simulate.py    # Model simulation
│   └── tests/             # 26 tests
├── clojure/               # Clojure implementation
├── specs/
│   └── rewire.qnt         # Formal specification
├── deploy/                # systemd, install scripts
└── docs/                  # GitHub Pages site
```

## Roadmap

- [ ] Docker image
- [ ] Webhook notifications (Slack, PagerDuty)
- [ ] Web dashboard
- [ ] Managed service offering
- [ ] Prometheus metrics endpoint

## License

[MIT](LICENSE) - Use it, modify it, sell it. Attribution appreciated.

## Acknowledgments

Built with assistance from Claude (Anthropic). Formally specified. Epistemically honest.

See [PROVENANCE.md](PROVENANCE.md) for full attribution.
