"""Tokenized public listings HMAC share links."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from fub_client import (  # noqa: E402
    LISTINGS_SHARE_PATH,
    listings_share_status,
    listings_share_token,
    petition_file_token,
)


SECRET = "test-entry-id-not-a-real-secret"


class ListingsShareTokenTests(unittest.TestCase):
    def test_valid_signature_without_expiry(self):
        token = listings_share_token(SECRET)
        self.assertIsNone(listings_share_status(token, SECRET))
        self.assertEqual(
            token,
            petition_file_token("public", secret=SECRET, kind="listings"),
        )
        self.assertNotEqual(token, petition_file_token("S-PR-1", secret=SECRET, kind="de111"))

    def test_invalid_signature(self):
        token = listings_share_token(SECRET)
        self.assertEqual(listings_share_status("0" * len(token), SECRET), "invalid")
        self.assertEqual(listings_share_status(token, "other-secret"), "invalid")
        self.assertEqual(listings_share_status("", SECRET), "missing")
        self.assertEqual(listings_share_status(None, SECRET), "missing")

    def test_expired_signature(self):
        exp = 1_700_000_000
        token = listings_share_token(SECRET, exp=exp)
        self.assertEqual(
            listings_share_status(token, SECRET, exp=exp, now=exp + 1),
            "expired",
        )
        self.assertIsNone(listings_share_status(token, SECRET, exp=exp, now=exp - 1))
        self.assertEqual(
            listings_share_status(token, SECRET, exp=exp + 60, now=exp - 1),
            "invalid",
        )
        self.assertNotEqual(token, listings_share_token(SECRET))


class ListingsShareViewContractTests(unittest.TestCase):
    def test_public_route_and_panel(self):
        src = (
            ROOT / "custom_components" / "placer_probate_monitor" / "hass_views.py"
        ).read_text(encoding="utf-8")
        panel = (
            ROOT / "custom_components" / "placer_probate_monitor" / "www" / "panel.js"
        ).read_text(encoding="utf-8")
        manifest = json.loads(
            (
                ROOT / "custom_components" / "placer_probate_monitor" / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(LISTINGS_SHARE_PATH, "/api/placer_probate_monitor/listings/public")
        self.assertIn('url = LISTINGS_SHARE_PATH', src)
        self.assertIn("class ListingsPublicView", src)
        self.assertIn("requires_auth = False", src)
        self.assertIn("hass.http.register_view(ListingsPublicView(hass))", src)
        self.assertIn("status_code=401", src)
        self.assertIn("status_code=403", src)
        self.assertIn("_listings_share_http_error", src)
        self.assertIn("Copy share link", panel)
        self.assertIn("ppmListingsShareUrl", panel)
        self.assertIn("ppmPublicBase", panel)
        self.assertIn("hassUrl", panel)
        share_fn = panel.split("function ppmListingsShareUrl", 1)[1].split("function ", 1)[0]
        self.assertNotIn("access_token", share_fn)
        self.assertEqual(manifest["version"], "1.3.85")
        self.assertIn('PANEL_JS_VERSION = "1.3.85"', src)
        self.assertIn("<th>Added</th>", src)
        self.assertIn("<th>FUB</th>", src)
        self.assertIn('url = "/api/placer_probate_monitor/listings"', src)
        self.assertIn("requires_auth = True", src)


if __name__ == "__main__":
    unittest.main()
