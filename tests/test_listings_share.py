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
    listings_share_http_error,
    listings_share_payload,
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

    def test_missing_token_is_401(self):
        self.assertEqual(listings_share_status(None, SECRET), "missing")
        self.assertEqual(listings_share_status("", SECRET), "missing")
        body, code = listings_share_http_error("missing")
        self.assertEqual(code, 401)
        self.assertEqual(body["error"], "unauthorized")

    def test_bad_token_is_403(self):
        token = listings_share_token(SECRET)
        self.assertEqual(listings_share_status("0" * len(token), SECRET), "invalid")
        body, code = listings_share_http_error("invalid")
        self.assertEqual(code, 403)
        self.assertEqual(body["error"], "forbidden")
        expired_body, expired_code = listings_share_http_error("expired")
        self.assertEqual(expired_code, 403)
        self.assertEqual(expired_body["error"], "expired")

    def test_listings_json_includes_share_url(self):
        meta = listings_share_payload("https://ha.example:8123", SECRET)
        token = listings_share_token(SECRET)
        self.assertEqual(meta["share_path"], LISTINGS_SHARE_PATH)
        self.assertEqual(meta["share_token"], token)
        self.assertEqual(
            meta["share_url"],
            f"https://ha.example:8123{LISTINGS_SHARE_PATH}?token={token}",
        )
        self.assertTrue(meta["share_url"].startswith("https://ha.example:8123/api/placer_probate_monitor/listings/public?token="))


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
        self.assertIn("ListingsPublicView(hass)", src)
        self.assertIn("listings_share_http_error", src)
        self.assertIn("payload.update(_listings_share_meta(self.hass))", src)
        self.assertIn("listings_share_payload", src)
        setup = src.split("def async_setup_mapping_views", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn('get("_fub_views")', setup)
        self.assertNotRegex(setup, r"if .+:\n\s+return")
        self.assertIn("for view in _mapping_http_views(hass)", setup)
        self.assertIn("def _register_http_view", src)
        self.assertIn("except Exception", src.split("def _register_http_view", 1)[1].split("\ndef ", 1)[0])
        views_fn = src.split("def _mapping_http_views", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(
            views_fn.find("ListingsPublicView(hass)"),
            views_fn.find("ListingsCsvView(hass)"),
        )
        self.assertLess(
            views_fn.find("ListingsCsvView(hass)"),
            views_fn.find("ListingsXlsxView(hass)"),
        )
        self.assertLess(
            views_fn.find("ListingsXlsxView(hass)"),
            views_fn.find("ListingsView(hass)"),
        )
        self.assertIn("Copy share link", panel)
        self.assertIn("ppmListingsShareUrl", panel)
        self.assertIn("ppmPublicBase", panel)
        self.assertIn("hassUrl", panel)
        share_fn = panel.split("function ppmListingsShareUrl", 1)[1].split("function ", 1)[0]
        self.assertNotIn("access_token", share_fn)
        self.assertEqual(manifest["version"], "1.3.87")
        self.assertIn('PANEL_JS_VERSION = "1.3.87"', src)
        self.assertIn("<th>Added</th>", src)
        self.assertIn("<th>FUB</th>", src)
        self.assertIn('url = "/api/placer_probate_monitor/listings"', src)
        self.assertIn("requires_auth = True", src)
        self.assertIn('content_type="text/html"', src)
        self.assertNotIn('content_type="text/html; charset=utf-8"', src)


def _public_html_fns():
    src = (
        ROOT / "custom_components" / "placer_probate_monitor" / "hass_views.py"
    ).read_text(encoding="utf-8")
    start = src.find("def _listing_text")
    end = src.find("class ListingsPublicView")
    ns = {"html": __import__("html")}
    exec(compile(src[start:end], "hass_views.py", "exec"), ns)
    return ns["_listings_public_html"]


class ListingsPublicHtmlTests(unittest.TestCase):
    def test_incomplete_rows_render_without_crash(self):
        from datetime import date, datetime

        html_fn = _public_html_fns()
        page = html_fn(
            {
                "listings": [
                    None,
                    "not-a-row",
                    {},
                    {
                        "date": None,
                        "filed": None,
                        "added_at": None,
                        "case_number": None,
                        "petitioner": None,
                        "decedent": None,
                        "decedent_address": None,
                        "hearing": None,
                        "notice_url": None,
                        "fub_person_id": None,
                    },
                    {
                        "date": date(2026, 10, 2),
                        "added_at": datetime(2026, 9, 15, 12, 0, 0),
                        "case_number": "S-PR-1",
                        "source": "Placer County",
                        "fub_status": "id",
                        "fub_person_id": 5120,
                    },
                ]
            }
        )
        self.assertIn("Probate listings", page)
        self.assertIn("S-PR-1", page)
        self.assertIn("2026-10-02", page)
        self.assertIn("2026-09-15", page)
        self.assertIn("5120", page)
        page.encode("utf-8")
        empty = html_fn({"listings": []})
        self.assertIn("No collected listings yet", empty)
        empty.encode("utf-8")
        self.assertIn("No collected listings yet", html_fn(None))


if __name__ == "__main__":
    unittest.main()
