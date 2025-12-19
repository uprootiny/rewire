"""
Rewire webhook notifications.

Send violation alerts to arbitrary HTTP endpoints (Slack, Discord, PagerDuty, etc.)
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass
from typing import Optional, List
from urllib.error import URLError, HTTPError


@dataclass(frozen=True)
class WebhookConfig:
    """Webhook configuration."""
    url: str
    headers: dict = None  # Additional headers (e.g., Authorization)
    timeout: int = 10


@dataclass(frozen=True)
class WebhookPayload:
    """Standard webhook payload for violations."""
    event: str  # "violation.opened" | "violation.closed" | "test.sent" | "test.expired"
    expectation_id: str
    expectation_name: str
    expectation_type: str
    violation_code: Optional[str]
    message: str
    evidence: dict
    timestamp: int


def send_webhook(config: WebhookConfig, payload: WebhookPayload) -> bool:
    """
    Send webhook notification. Returns True on success.

    Uses stdlib urllib - no external dependencies.
    """
    data = {
        "event": payload.event,
        "expectation": {
            "id": payload.expectation_id,
            "name": payload.expectation_name,
            "type": payload.expectation_type,
        },
        "violation": {
            "code": payload.violation_code,
            "message": payload.message,
            "evidence": payload.evidence,
        },
        "timestamp": payload.timestamp,
    }

    body = json.dumps(data).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if config.headers:
        headers.update(config.headers)

    req = urllib.request.Request(
        config.url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        # Create SSL context that verifies certificates
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=config.timeout, context=ctx) as resp:
            return 200 <= resp.status < 300
    except (URLError, HTTPError) as e:
        print(f"[webhook] error sending to {config.url}: {e}")
        return False


def format_slack_payload(payload: WebhookPayload) -> dict:
    """
    Format payload for Slack incoming webhook.

    Returns a Slack Block Kit message.
    """
    emoji = {
        "violation.opened": ":rotating_light:",
        "violation.closed": ":white_check_mark:",
        "test.sent": ":mailbox:",
        "test.expired": ":warning:",
    }.get(payload.event, ":bell:")

    color = {
        "violation.opened": "#dc2626",  # red
        "violation.closed": "#16a34a",  # green
        "test.sent": "#2563eb",  # blue
        "test.expired": "#f59e0b",  # amber
    }.get(payload.event, "#6b7280")

    return {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} Rewire: {payload.event}",
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Expectation:*\n{payload.expectation_name}"},
                        {"type": "mrkdwn", "text": f"*Type:*\n{payload.expectation_type}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{payload.violation_code or 'Info'}:* {payload.message}",
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"ID: `{payload.expectation_id}`"}
                    ]
                }
            ]
        }]
    }


def format_discord_payload(payload: WebhookPayload) -> dict:
    """
    Format payload for Discord webhook.
    """
    color = {
        "violation.opened": 0xdc2626,
        "violation.closed": 0x16a34a,
        "test.sent": 0x2563eb,
        "test.expired": 0xf59e0b,
    }.get(payload.event, 0x6b7280)

    return {
        "embeds": [{
            "title": f"Rewire: {payload.event}",
            "color": color,
            "fields": [
                {"name": "Expectation", "value": payload.expectation_name, "inline": True},
                {"name": "Type", "value": payload.expectation_type, "inline": True},
                {"name": payload.violation_code or "Info", "value": payload.message},
            ],
            "footer": {"text": f"ID: {payload.expectation_id}"},
        }]
    }


def send_slack(webhook_url: str, payload: WebhookPayload, timeout: int = 10) -> bool:
    """Send formatted message to Slack."""
    slack_data = format_slack_payload(payload)
    body = json.dumps(slack_data).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return 200 <= resp.status < 300
    except (URLError, HTTPError) as e:
        print(f"[slack] error: {e}")
        return False


def send_discord(webhook_url: str, payload: WebhookPayload, timeout: int = 10) -> bool:
    """Send formatted message to Discord."""
    discord_data = format_discord_payload(payload)
    body = json.dumps(discord_data).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return 200 <= resp.status < 300
    except (URLError, HTTPError) as e:
        print(f"[discord] error: {e}")
        return False


class WebhookNotifier:
    """
    Webhook notifier that can send to multiple endpoints.
    """

    def __init__(self):
        self.generic_webhooks: List[WebhookConfig] = []
        self.slack_url: Optional[str] = None
        self.discord_url: Optional[str] = None

    def add_webhook(self, url: str, headers: dict = None) -> None:
        """Add a generic webhook endpoint."""
        self.generic_webhooks.append(WebhookConfig(url=url, headers=headers))

    def set_slack(self, webhook_url: str) -> None:
        """Set Slack incoming webhook URL."""
        self.slack_url = webhook_url

    def set_discord(self, webhook_url: str) -> None:
        """Set Discord webhook URL."""
        self.discord_url = webhook_url

    def notify(self, payload: WebhookPayload) -> int:
        """
        Send notification to all configured webhooks.
        Returns number of successful sends.
        """
        successes = 0

        # Generic webhooks
        for config in self.generic_webhooks:
            if send_webhook(config, payload):
                successes += 1

        # Slack
        if self.slack_url:
            if send_slack(self.slack_url, payload):
                successes += 1

        # Discord
        if self.discord_url:
            if send_discord(self.discord_url, payload):
                successes += 1

        return successes
