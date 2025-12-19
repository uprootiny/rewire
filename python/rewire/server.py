"""
Rewire HTTP server and background checker.

Single-file server using stdlib http.server.
"""

from __future__ import annotations

import argparse
import json
import secrets
import signal
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from rewire.db import Store, CreateExpectationParams
from rewire.notify import Notifier, SMTPConfig
from rewire.webhooks import WebhookNotifier, WebhookPayload
import rewire.rules as rules


def now_i() -> int:
    return int(time.time())


@dataclass(frozen=True)
class Config:
    """Server configuration."""
    base_url: str
    admin_token: str
    check_every_s: int
    renotify_after_s: int  # 0 disables
    send_recovery: bool


class Handler(BaseHTTPRequestHandler):
    """HTTP request handler for Rewire API."""

    server_version = "rewire/0.1"

    def log_message(self, format: str, *args) -> None:
        """Quieter logging."""
        pass

    def _text(self, code: int, s: str) -> None:
        b = s.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code: int, obj: dict) -> None:
        b = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))

    def _auth_admin(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        tok = auth[len("Bearer "):].strip()
        return secrets.compare_digest(tok, self.server.cfg.admin_token)

    def do_GET(self) -> None:
        if self.path == "/status":
            return self._text(200, "rewire ok\n")
        if self.path.startswith("/observe/"):
            return self._handle_observe_get()
        if self.path.startswith("/ack/"):
            return self._handle_ack()
        return self._text(404, "not found\n")

    def do_POST(self) -> None:
        if self.path.startswith("/observe/"):
            return self._handle_observe_post()
        if self.path == "/admin/new":
            return self._handle_admin_new()
        if self.path == "/admin/enable":
            return self._handle_admin_enable(True)
        if self.path == "/admin/disable":
            return self._handle_admin_enable(False)
        return self._text(404, "not found\n")

    def _handle_observe_get(self) -> None:
        exp_id = self.path[len("/observe/"):].strip("/")
        row = self.server.store.get_expectation(exp_id)
        if not row:
            return self._text(404, "unknown expectation\n")
        obs = self.server.store.recent_observations(exp_id, limit=10)
        return self._json(200, {
            "id": row["id"],
            "type": row["type"],
            "name": row["name"],
            "expected_interval_s": row["expected_interval_s"],
            "tolerance_s": row["tolerance_s"],
            "params": json.loads(row["params_json"]),
            "owner_email": row["owner_email"],
            "is_enabled": bool(row["is_enabled"]),
            "recent_observations": [
                {"kind": r["kind"], "observed_at": r["observed_at"], "meta": r["meta_json"]}
                for r in obs
            ],
        })

    def _handle_observe_post(self) -> None:
        exp_id = self.path[len("/observe/"):].strip("/")
        row = self.server.store.get_expectation(exp_id)
        if not row:
            return self._text(404, "unknown expectation\n")
        form = self._read_form()
        kind = (form.get("kind") or "").strip()
        meta = form.get("meta")
        if kind not in ("start", "end", "ping", "ack"):
            return self._json(400, {"error": "kind must be start|end|ping|ack"})
        self.server.store.add_observation(exp_id, kind, meta)
        return self._text(200, "ok\n")

    def _handle_ack(self) -> None:
        trial_id = self.path[len("/ack/"):].strip("/").split("?", 1)[0]
        ok = self.server.store.ack_trial(trial_id)
        if ok:
            return self._text(200, "acked\n")
        return self._text(404, "unknown or not pending\n")

    def _handle_admin_new(self) -> None:
        if not self._auth_admin():
            return self._text(401, "unauthorized\n")
        form = self._read_form()
        exp_type = (form.get("type") or "").strip()
        name = (form.get("name") or "").strip()
        owner_email = (form.get("email") or "").strip()
        expected = int(form.get("expected_interval_s") or "0")
        tol = int(form.get("tolerance_s") or "0")
        params_json = form.get("params_json") or "{}"

        if exp_type not in ("schedule", "alert_path"):
            return self._json(400, {"error": "type must be schedule|alert_path"})
        if not name or not owner_email or expected < 60:
            return self._json(400, {"error": "need name,email,expected_interval_s>=60"})

        try:
            rules.parse_params(exp_type, params_json)
        except Exception as e:
            return self._json(400, {"error": f"invalid params_json: {e}"})

        exp_id = secrets.token_urlsafe(16)
        self.server.store.create_expectation(CreateExpectationParams(
            exp_id=exp_id,
            exp_type=exp_type,
            name=name,
            expected_interval_s=expected,
            tolerance_s=tol,
            params_json=params_json,
            owner_email=owner_email,
        ))
        observe_url = f"{self.server.cfg.base_url.rstrip('/')}/observe/{exp_id}"
        return self._json(200, {"id": exp_id, "observe_url": observe_url})

    def _handle_admin_enable(self, enable: bool) -> None:
        if not self._auth_admin():
            return self._text(401, "unauthorized\n")
        form = self._read_form()
        exp_id = (form.get("id") or "").strip()
        if not exp_id:
            return self._json(400, {"error": "need id"})
        self.server.store.set_enabled(exp_id, enable)
        return self._json(200, {"ok": True, "enabled": enable})


class RewireHTTP(ThreadingHTTPServer):
    """Threaded HTTP server with attached store and notifier."""

    def __init__(
        self,
        addr: tuple,
        handler: type,
        store: Store,
        notifier: Notifier,
        webhook_notifier: WebhookNotifier,
        cfg: Config,
    ) -> None:
        super().__init__(addr, handler)
        self.store = store
        self.notifier = notifier
        self.webhook_notifier = webhook_notifier
        self.cfg = cfg


class Checker(threading.Thread):
    """Background thread that evaluates expectations periodically."""

    daemon = True

    def __init__(self, httpd: RewireHTTP, stop_evt: threading.Event) -> None:
        super().__init__()
        self.httpd = httpd
        self.stop_evt = stop_evt

    def run(self) -> None:
        while not self.stop_evt.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"[checker] error: {e}", file=sys.stderr)
            self.stop_evt.wait(self.httpd.cfg.check_every_s)

    def tick(self) -> None:
        store = self.httpd.store
        cfg = self.httpd.cfg
        base = cfg.base_url.rstrip("/")
        exps = store.list_enabled_expectations()
        now = now_i()

        for exp in exps:
            exp_id = exp["id"]
            exp_type = exp["type"]
            owner = exp["owner_email"]
            name = exp["name"]

            if exp_type == "schedule":
                self._check_schedule(exp, store, cfg, now)
            elif exp_type == "alert_path":
                self._check_alertpath(exp, store, cfg, base, now)

    def _check_schedule(self, exp, store: Store, cfg: Config, now: int) -> None:
        exp_id = exp["id"]
        owner = exp["owner_email"]
        name = exp["name"]

        obs = store.recent_observations(exp_id, limit=80)
        violations, close_codes = rules.schedule_evaluate(exp, obs)

        if close_codes:
            store.close_violations(exp_id, close_codes)

        for code, msg, ev in violations:
            openv = store.open_violation(exp_id, code)
            if openv is None:
                vid = store.create_violation(exp_id, code, msg, json.dumps(ev))
                self._notify_violation(owner, name, "schedule", code, msg, ev, vid, exp_id)
            elif cfg.renotify_after_s and openv["last_notified_at"]:
                if now - int(openv["last_notified_at"]) >= cfg.renotify_after_s:
                    self._notify_violation(
                        owner, name, "schedule", code,
                        openv["message"], json.loads(openv["evidence_json"]),
                        int(openv["id"]), exp_id
                    )

    def _check_alertpath(
        self, exp, store: Store, cfg: Config, base: str, now: int
    ) -> None:
        exp_id = exp["id"]
        owner = exp["owner_email"]
        name = exp["name"]

        last_obs = store.last_observation_time(exp_id)
        if rules.alertpath_should_send_test(exp, last_obs):
            trial_id = secrets.token_urlsafe(16)
            ack_url = f"{base}/ack/{trial_id}"
            meta = {"ack_url": ack_url, "note": "synthetic test"}
            store.create_trial(trial_id, exp_id, json.dumps(meta))
            store.add_observation(exp_id, "ping", json.dumps({"sent_trial": trial_id}))
            subj = f"[rewire] Alert-path test: {name}"
            body = (
                "This is a synthetic Rewire alert-path test.\n\n"
                f"Path: {name}\n"
                f"Expectation ID: {exp_id}\n"
                "To acknowledge delivery, open this link:\n"
                f"{ack_url}\n\n"
                "If no ack is received in time, Rewire will open a violation.\n"
            )
            self.httpd.notifier.send_email(owner, subj, body)

        # Check pending trials for expiry
        params = rules.parse_params("alert_path", exp["params_json"])
        pending = store.pending_trials(exp_id)
        for tr in pending:
            age = now - int(tr["sent_at"])
            if age > params.ack_window_s + int(exp["tolerance_s"]):
                store.expire_trial(tr["id"])
                code = "no_ack"
                msg = f"No ACK received within {params.ack_window_s}s (+{int(exp['tolerance_s'])}s)."
                ev = {"trial_id": tr["id"], "sent_at": int(tr["sent_at"]), "age_s": age}
                openv = store.open_violation(exp_id, code)
                if openv is None:
                    vid = store.create_violation(exp_id, code, msg, json.dumps(ev))
                    self._notify_violation(owner, name, "alert_path", code, msg, ev, vid, exp_id)

        store.close_violations(exp_id, ["no_ack"])

    def _notify_violation(
        self, owner: str, name: str, exp_type: str, code: str,
        msg: str, ev: dict, viol_id: int, exp_id: str = ""
    ) -> None:
        subj = f"[rewire] VIOLATION {code}: {name}"
        body = (
            "Rewire detected an expectation violation.\n\n"
            f"Name: {name}\n"
            f"Type: {exp_type}\n"
            f"Code: {code}\n"
            f"Message: {msg}\n\n"
            f"Evidence:\n{json.dumps(ev, indent=2)}\n\n"
            "Rewire reports only mismatches it can justify with evidence.\n"
        )
        self.httpd.notifier.send_email(owner, subj, body)

        # Send webhook notifications
        payload = WebhookPayload(
            event="violation.opened",
            expectation_id=exp_id,
            expectation_name=name,
            expectation_type=exp_type,
            violation_code=code,
            message=msg,
            evidence=ev,
            timestamp=now_i(),
        )
        self.httpd.webhook_notifier.notify(payload)

        self.httpd.store.mark_notified(viol_id)


def main() -> None:
    ap = argparse.ArgumentParser(description="Rewire expectation verifier")
    ap.add_argument("--db", required=True, help="SQLite database path")
    ap.add_argument("--init-db", action="store_true", help="Initialize database schema")
    ap.add_argument("--listen", default="127.0.0.1", help="Listen address")
    ap.add_argument("--port", type=int, default=8080, help="Listen port")
    ap.add_argument("--base-url", required=True, help="Public base URL")
    ap.add_argument("--admin-token", default="dev-admin-token", help="Admin API token")
    ap.add_argument("--check-every", type=int, default=60, help="Check interval (seconds)")
    ap.add_argument("--renotify-after", type=int, default=0, help="Renotify interval (0=disable)")
    ap.add_argument("--smtp-host", default=None, help="SMTP server (None=dev mode)")
    ap.add_argument("--smtp-port", type=int, default=587, help="SMTP port")
    ap.add_argument("--smtp-user", default=None, help="SMTP username")
    ap.add_argument("--smtp-pass", default=None, help="SMTP password")
    ap.add_argument("--from-email", default="rewire@localhost", help="From address")
    # Webhook arguments
    ap.add_argument("--slack-webhook", default=None, help="Slack incoming webhook URL")
    ap.add_argument("--discord-webhook", default=None, help="Discord webhook URL")
    ap.add_argument("--webhook", action="append", dest="webhooks", default=[],
                    help="Generic webhook URL (can be repeated)")
    args = ap.parse_args()

    store = Store(args.db)
    if args.init_db:
        store.init_db()
        print("db initialized", file=sys.stderr)

    notifier = Notifier(SMTPConfig(
        host=args.smtp_host,
        port=args.smtp_port,
        user=args.smtp_user,
        password=args.smtp_pass,
        from_email=args.from_email,
    ))

    # Configure webhook notifier
    webhook_notifier = WebhookNotifier()
    if args.slack_webhook:
        webhook_notifier.set_slack(args.slack_webhook)
        print(f"slack webhook configured", file=sys.stderr)
    if args.discord_webhook:
        webhook_notifier.set_discord(args.discord_webhook)
        print(f"discord webhook configured", file=sys.stderr)
    for url in args.webhooks:
        webhook_notifier.add_webhook(url)
        print(f"webhook configured: {url}", file=sys.stderr)

    cfg = Config(
        base_url=args.base_url,
        admin_token=args.admin_token,
        check_every_s=args.check_every,
        renotify_after_s=args.renotify_after,
        send_recovery=False,
    )

    httpd = RewireHTTP((args.listen, args.port), Handler, store, notifier, webhook_notifier, cfg)
    stop_evt = threading.Event()
    checker = Checker(httpd, stop_evt)
    checker.start()

    def _sig(*_):
        stop_evt.set()
        httpd.shutdown()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print(f"rewire listening on {args.listen}:{args.port}", file=sys.stderr)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
