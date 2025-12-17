"""
Rewire CLI: Admin tool for creating and managing expectations.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import Any


def post(url: str, token: str, data: dict) -> dict:
    """Make authenticated POST request."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_new_schedule(args: argparse.Namespace) -> None:
    """Create a new schedule expectation."""
    base = args.base_url.rstrip("/")
    params = {
        "max_runtime_s": args.max_runtime_s,
        "min_spacing_s": args.min_spacing_s,
        "allow_overlap": args.allow_overlap,
    }
    out = post(f"{base}/admin/new", args.admin_token, {
        "type": "schedule",
        "name": args.name,
        "email": args.email,
        "expected_interval_s": str(args.expected_interval_s),
        "tolerance_s": str(args.tolerance_s),
        "params_json": json.dumps(params),
    })
    print(json.dumps(out, indent=2))
    print("\nInstrument your job:")
    print(f"  curl -fsS -X POST '{out['observe_url']}' -d kind=start")
    print(f"  # ... do work ...")
    print(f"  curl -fsS -X POST '{out['observe_url']}' -d kind=end")


def cmd_new_alertpath(args: argparse.Namespace) -> None:
    """Create a new alert-path expectation."""
    base = args.base_url.rstrip("/")
    params = {
        "test_interval_s": args.test_interval_s,
        "ack_window_s": args.ack_window_s,
    }
    out = post(f"{base}/admin/new", args.admin_token, {
        "type": "alert_path",
        "name": args.name,
        "email": args.email,
        "expected_interval_s": str(args.expected_interval_s),
        "tolerance_s": str(args.tolerance_s),
        "params_json": json.dumps(params),
    })
    print(json.dumps(out, indent=2))
    print("\nSynthetic tests will be sent to", args.email)
    print("ACK via the /ack/<trial> link in each email.")


def cmd_enable(args: argparse.Namespace) -> None:
    """Enable an expectation."""
    base = args.base_url.rstrip("/")
    out = post(f"{base}/admin/enable", args.admin_token, {"id": args.id})
    print(json.dumps(out, indent=2))


def cmd_disable(args: argparse.Namespace) -> None:
    """Disable an expectation."""
    base = args.base_url.rstrip("/")
    out = post(f"{base}/admin/disable", args.admin_token, {"id": args.id})
    print(json.dumps(out, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="rewire-ctl",
        description="Rewire administration CLI",
    )
    ap.add_argument("--base-url", required=True, help="Rewire server URL")
    ap.add_argument("--admin-token", required=True, help="Admin API token")

    sub = ap.add_subparsers(dest="cmd", required=True)

    # new-schedule
    s1 = sub.add_parser("new-schedule", help="Create schedule expectation")
    s1.add_argument("--name", required=True, help="Expectation name")
    s1.add_argument("--email", required=True, help="Owner email")
    s1.add_argument("--expected-interval-s", type=int, required=True,
                    help="Expected interval between runs (seconds)")
    s1.add_argument("--tolerance-s", type=int, default=0,
                    help="Grace period (seconds)")
    s1.add_argument("--max-runtime-s", type=int, default=0,
                    help="Max runtime before longrun violation (0=disable)")
    s1.add_argument("--min-spacing-s", type=int, default=0,
                    help="Min gap between runs (0=disable)")
    s1.add_argument("--allow-overlap", action="store_true",
                    help="Allow overlapping runs")
    s1.set_defaults(func=cmd_new_schedule)

    # new-alertpath
    s2 = sub.add_parser("new-alertpath", help="Create alert-path expectation")
    s2.add_argument("--name", required=True, help="Expectation name")
    s2.add_argument("--email", required=True, help="Owner email")
    s2.add_argument("--test-interval-s", type=int, required=True,
                    help="How often to send synthetic tests")
    s2.add_argument("--ack-window-s", type=int, required=True,
                    help="Time allowed to acknowledge")
    s2.add_argument("--expected-interval-s", type=int, default=3600,
                    help="Expected interval (default: 3600)")
    s2.add_argument("--tolerance-s", type=int, default=0,
                    help="Grace period (seconds)")
    s2.set_defaults(func=cmd_new_alertpath)

    # enable
    s3 = sub.add_parser("enable", help="Enable an expectation")
    s3.add_argument("--id", required=True, help="Expectation ID")
    s3.set_defaults(func=cmd_enable)

    # disable
    s4 = sub.add_parser("disable", help="Disable an expectation")
    s4.add_argument("--id", required=True, help="Expectation ID")
    s4.set_defaults(func=cmd_disable)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
