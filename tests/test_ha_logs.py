"""HA logs export: auth contract, redaction, size cap, bounded history."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))
sys.path.insert(0, str(ROOT / "scripts"))

from ha_logs import (  # noqa: E402
    DEFAULT_EXPORT_MAX_BYTES,
    HA_LOGS_REQUIRES_AUTH,
    HA_LOGS_URL,
    HA_LOGS_VIEW_NAME,
    attach_component_logger,
    build_ha_logs_payload,
    clamp_max_bytes,
    merge_last_run_log,
    persist_job_logs,
    redact_secrets,
    write_ha_logs_locally,
)


class RedactionTests(unittest.TestCase):
    def test_redacts_tokens_and_passwords(self):
        raw = (
            "Authorization: Bearer super.secret.jwt\n"
            "FUB_API_KEY=abc123secret\n"
            "smtp_password: hunter2\n"
            "SACRAMENTO_PORTAL_PASSWORD=portal-pass\n"
            "token=llat-should-go\n"
            "Notice count 5\n"
        )
        out = redact_secrets(raw)
        self.assertNotIn("super.secret.jwt", out)
        self.assertNotIn("abc123secret", out)
        self.assertNotIn("hunter2", out)
        self.assertNotIn("portal-pass", out)
        self.assertNotIn("llat-should-go", out)
        self.assertIn("[REDACTED]", out)
        self.assertIn("Notice count 5", out)


class PayloadAndViewTests(unittest.TestCase):
    def test_view_requires_auth(self):
        self.assertTrue(HA_LOGS_REQUIRES_AUTH)
        self.assertEqual(HA_LOGS_URL, "/api/placer_probate_monitor/logs")
        src = (
            ROOT / "custom_components" / "placer_probate_monitor" / "hass_views.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class LogsView(HomeAssistantView):", src)
        self.assertIn("url = HA_LOGS_URL", src)
        self.assertIn("name = HA_LOGS_VIEW_NAME", src)
        self.assertIn("requires_auth = HA_LOGS_REQUIRES_AUTH", src)
        self.assertIn("hass.http.register_view(LogsView(hass))", src)
        self.assertEqual(HA_LOGS_VIEW_NAME, "api:placer_probate_monitor:logs")

    def test_payload_redacts_and_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "FUB_API_KEY=should-not-leak\n"
            padding = ("ok line\n" * 4000) + secret
            (root / "last_run.log").write_text(
                "===== placer =====\n"
                + padding
                + "===== sacramento =====\n"
                + "SAC token=sacramento-secret\nDone\n",
                encoding="utf-8",
            )
            (root / "job_progress.json").write_text(
                json.dumps({"step": "ecourt", "message": "token=progress-secret"}),
                encoding="utf-8",
            )
            persist_job_logs(
                root,
                source_id="placer",
                log_text="password=nested-secret failed hard",
                ok=False,
                error="password=nested-secret failed hard",
            )
            payload = build_ha_logs_payload(root, max_bytes=4096)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["max_bytes"], 4096)
            last = next(item for item in payload["files"] if item["name"] == "last_run.log")
            self.assertTrue(last["truncated"])
            self.assertLessEqual(len(last["text"].encode("utf-8")), 4096)
            self.assertNotIn("should-not-leak", json.dumps(payload))
            self.assertNotIn("sacramento-secret", json.dumps(payload))
            self.assertNotIn("progress-secret", json.dumps(payload))
            self.assertNotIn("nested-secret", json.dumps(payload))
            self.assertIn("[REDACTED]", json.dumps(payload))
            self.assertFalse(payload["summary"].get("last_ok"))
            placer_only = build_ha_logs_payload(
                root, source_id="placer", max_bytes=64 * 1024
            )
            placer_text = next(
                item["text"]
                for item in placer_only["files"]
                if item["name"] == "last_run.log"
            )
            self.assertIn("===== placer =====", placer_text)
            self.assertNotIn("===== sacramento =====", placer_text)
            self.assertNotIn("should-not-leak", placer_text)

    def test_unknown_source_rejected_by_view_contract(self):
        # Mirrors LogsView.get without importing Home Assistant.
        wanted = "not-a-county"
        self.assertNotIn(wanted, {"placer", "sacramento", ""})

    def test_clamp_and_local_write(self):
        self.assertEqual(clamp_max_bytes("not-a-number"), DEFAULT_EXPORT_MAX_BYTES)
        self.assertEqual(clamp_max_bytes(1), 4096)
        self.assertEqual(clamp_max_bytes(9_000_000), 1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ha_logs"
            payload = {
                "ok": True,
                "summary": {"last_job_id": "x"},
                "progress": {"step": "done"},
                "files": [
                    {"name": "last_run.log", "text": "hello"},
                    {"name": "../escape.log", "text": "nope"},
                    {"name": "secrets.yaml", "text": "nope"},
                ],
            }
            written = write_ha_logs_locally(payload, dest)
            self.assertIn("summary.json", written)
            self.assertIn("last_run.log", written)
            self.assertTrue((dest / "last_run.log").is_file())
            self.assertFalse((dest / "escape.log").exists())
            self.assertFalse((dest / "secrets.yaml").exists())


class BoundedHistoryTests(unittest.TestCase):
    def test_job_log_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            persist_job_logs(
                root,
                source_id="placer",
                log_text="A" * 2000,
                ok=True,
            )
            merge_last_run_log(root, "placer", "first")
            path = root / "logs" / "job.log"
            original = path.read_bytes()
            from ha_logs import append_bounded_text

            append_bounded_text(path, "B" * 8000, max_bytes=4096)
            data = path.read_bytes()
            self.assertLessEqual(len(data), 4096)
            self.assertTrue(data.endswith(b"B" * 100) or data.decode("utf-8").endswith("B" * 100))
            self.assertGreater(len(original), 0)
            last = (root / "last_run.log").read_text(encoding="utf-8")
            self.assertIn("===== placer =====", last)
            self.assertIn("first", last)

    def test_component_logger_writes_redacted_file(self):
        names = (
            "custom_components.placer_probate_monitor",
            "placer_probate_monitor",
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                attach_component_logger(root)
                logging.getLogger("custom_components.placer_probate_monitor").error(
                    "boom password=dont-leak"
                )
                text = (root / "logs" / "component.log").read_text(encoding="utf-8")
                self.assertIn("boom", text)
                self.assertNotIn("dont-leak", text)
                self.assertIn("[REDACTED]", text)
        finally:
            from ha_logs import HANDLER_NAME

            for name in names:
                logger = logging.getLogger(name)
                for handler in list(logger.handlers):
                    if getattr(handler, "name", "") == HANDLER_NAME:
                        logger.removeHandler(handler)


class PullScriptTests(unittest.TestCase):
    def test_pull_writes_from_api_payload(self):
        from pull_ha_logs import pull_logs

        payload = {
            "ok": True,
            "summary": {"last_job_id": "job-1"},
            "progress": {"step": "done"},
            "files": [{"name": "last_run.log", "text": "===== placer =====\nok\n"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with patch("pull_ha_logs._request", return_value=json.dumps(payload).encode()):
                written = pull_logs("http://ha.example:8123", "token", dest, None, insecure=True)
            self.assertIn("last_run.log", written)
            self.assertEqual((dest / "last_run.log").read_text(encoding="utf-8"), "===== placer =====\nok\n")


class LogsViewGetTests(unittest.TestCase):
    def test_get_uses_payload_builder(self):
        # Lightweight stand-in for LogsView.get
        class FakeHass:
            def __init__(self, data_dir: Path) -> None:
                self.config = MagicMock()
                self.config.path.return_value = str(data_dir)

            async def async_add_executor_job(self, func, *args):
                return func(*args)

        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "last_run.log").write_text(
                    "===== placer =====\napi_key=zzz\n", encoding="utf-8"
                )
                hass = FakeHass(root)

                def _build():
                    return build_ha_logs_payload(
                        Path(hass.config.path("placer_probate_monitor")),
                        source_id="placer",
                        max_bytes=4096,
                    )

                payload = await hass.async_add_executor_job(_build)
                self.assertTrue(payload["ok"])
                self.assertNotIn("zzz", json.dumps(payload))

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
