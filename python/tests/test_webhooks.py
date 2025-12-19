"""
Tests for rewire.webhooks module.
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

from rewire.webhooks import (
    WebhookConfig,
    WebhookPayload,
    WebhookNotifier,
    send_webhook,
    format_slack_payload,
    format_discord_payload,
)


class TestWebhookPayload(unittest.TestCase):
    def test_payload_creation(self):
        payload = WebhookPayload(
            event="violation.opened",
            expectation_id="exp123",
            expectation_name="nightly-backup",
            expectation_type="schedule",
            violation_code="missed",
            message="No observation in expected window",
            evidence={"last_seen": 1000, "now": 2000},
            timestamp=1234567890,
        )
        self.assertEqual(payload.event, "violation.opened")
        self.assertEqual(payload.expectation_id, "exp123")
        self.assertEqual(payload.violation_code, "missed")


class TestWebhookConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = WebhookConfig(url="https://example.com/hook")
        self.assertEqual(cfg.url, "https://example.com/hook")
        self.assertIsNone(cfg.headers)
        self.assertEqual(cfg.timeout, 10)

    def test_config_with_headers(self):
        cfg = WebhookConfig(
            url="https://example.com/hook",
            headers={"Authorization": "Bearer xyz"},
            timeout=30,
        )
        self.assertEqual(cfg.headers["Authorization"], "Bearer xyz")
        self.assertEqual(cfg.timeout, 30)


class TestFormatters(unittest.TestCase):
    def make_payload(self, event="violation.opened"):
        return WebhookPayload(
            event=event,
            expectation_id="exp123",
            expectation_name="nightly-backup",
            expectation_type="schedule",
            violation_code="missed",
            message="No observation",
            evidence={"test": True},
            timestamp=1234567890,
        )

    def test_format_slack_payload(self):
        payload = self.make_payload("violation.opened")
        result = format_slack_payload(payload)

        self.assertIn("attachments", result)
        self.assertEqual(len(result["attachments"]), 1)
        attachment = result["attachments"][0]
        self.assertEqual(attachment["color"], "#dc2626")  # red for opened
        self.assertIn("blocks", attachment)

    def test_format_slack_closed(self):
        payload = self.make_payload("violation.closed")
        result = format_slack_payload(payload)
        self.assertEqual(result["attachments"][0]["color"], "#16a34a")  # green

    def test_format_discord_payload(self):
        payload = self.make_payload("violation.opened")
        result = format_discord_payload(payload)

        self.assertIn("embeds", result)
        self.assertEqual(len(result["embeds"]), 1)
        embed = result["embeds"][0]
        self.assertEqual(embed["color"], 0xdc2626)
        self.assertIn("fields", embed)
        self.assertEqual(len(embed["fields"]), 3)

    def test_format_discord_test_sent(self):
        payload = self.make_payload("test.sent")
        result = format_discord_payload(payload)
        self.assertEqual(result["embeds"][0]["color"], 0x2563eb)  # blue


class TestWebhookNotifier(unittest.TestCase):
    def test_empty_notifier(self):
        notifier = WebhookNotifier()
        payload = WebhookPayload(
            event="violation.opened",
            expectation_id="exp123",
            expectation_name="test",
            expectation_type="schedule",
            violation_code="missed",
            message="test",
            evidence={},
            timestamp=1234567890,
        )
        # Should not raise, returns 0 successes
        result = notifier.notify(payload)
        self.assertEqual(result, 0)

    def test_add_webhook(self):
        notifier = WebhookNotifier()
        notifier.add_webhook("https://example.com/hook1")
        notifier.add_webhook("https://example.com/hook2", {"X-Custom": "value"})
        self.assertEqual(len(notifier.generic_webhooks), 2)

    def test_set_slack(self):
        notifier = WebhookNotifier()
        notifier.set_slack("https://hooks.slack.com/xxx")
        self.assertEqual(notifier.slack_url, "https://hooks.slack.com/xxx")

    def test_set_discord(self):
        notifier = WebhookNotifier()
        notifier.set_discord("https://discord.com/api/webhooks/xxx")
        self.assertEqual(notifier.discord_url, "https://discord.com/api/webhooks/xxx")


class TestSendWebhook(unittest.TestCase):
    @patch("rewire.webhooks.urllib.request.urlopen")
    def test_send_webhook_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        config = WebhookConfig(url="https://example.com/hook")
        payload = WebhookPayload(
            event="violation.opened",
            expectation_id="exp123",
            expectation_name="test",
            expectation_type="schedule",
            violation_code="missed",
            message="test message",
            evidence={"key": "value"},
            timestamp=1234567890,
        )

        result = send_webhook(config, payload)
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

    @patch("rewire.webhooks.urllib.request.urlopen")
    def test_send_webhook_failure(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("connection refused")

        config = WebhookConfig(url="https://example.com/hook")
        payload = WebhookPayload(
            event="violation.opened",
            expectation_id="exp123",
            expectation_name="test",
            expectation_type="schedule",
            violation_code="missed",
            message="test",
            evidence={},
            timestamp=1234567890,
        )

        result = send_webhook(config, payload)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
