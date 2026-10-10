"""Placer-only FUB/source paths that Sacramento tests do not fully exercise."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from datasources import petition_docs_dir, stamp_fub_tags  # noqa: E402
from fub_client import (  # noqa: E402
    _petition_docs_search_dirs,
    case_portal_url,
    enabled_live_sources,
    gate_reason,
    go_no_go_for_source,
    mapping_for_export,
    preview_one_record,
    source_field_catalog,
)


# Mirrors hass_views._resolve_stored_pdf without importing Home Assistant.
_SAC_CASE_NAME = re.compile(r"^\d{2}PR\d+$", re.I)


class PlacerSourcePathTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            key: os.environ.get(key)
            for key in (
                "FUB_PETITION_DOCS_DIR",
                "FUB_SACRAMENTO_PETITION_DOCS_DIR",
                "FUB_DATA_SOURCE",
                "FUB_SOURCE",
            )
        }
        for key in self._env:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_placer_go_no_go_requires_mailing(self):
        spec = go_no_go_for_source("placer")
        required = {item["key"] for item in spec["required"]}
        self.assertEqual(spec["source_id"], "placer")
        self.assertIn("mailing_address", required)
        catalog = {item["key"]: item for item in source_field_catalog("placer")}
        self.assertFalse(catalog["de111_url"].get("unavailable"))
        self.assertIn("eCourt", catalog["court_search"].get("source") or "")
        row = {
            "source_id": "placer",
            "case_number": "S-PR-0014448",
            "petitioner": "John Henderson",
        }
        self.assertEqual(
            gate_reason(row, {"cases": {}}, {}, strict_property=False, existing_id=None),
            "missing_petitioner_address",
        )
        row["mailing_address"] = "51 Ashby Hills Ct, Henderson, NV 89012"
        self.assertIsNone(
            gate_reason(row, {"cases": {}}, {}, strict_property=False, existing_id=None)
        )

    def test_placer_portal_url_stays_on_node_45(self):
        url = "https://webportal.placerco.org/eCourtPublic/?q=node/45/1234567"
        self.assertEqual(case_portal_url({"court_url": url}), url)
        self.assertIn("node/45", case_portal_url({"court_url": url}))
        self.assertNotIn("node/397", case_portal_url({"court_url": url}))

    def test_preview_lead_source_placer(self):
        os.environ["FUB_SOURCE"] = "probate"
        row = stamp_fub_tags(
            [
                {
                    "case_number": "S-PR-0014448",
                    "petitioner": "John Henderson",
                    "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
                    "court_url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1234567",
                }
            ],
            "placer",
        )[0]
        self.assertEqual(row["lead_source"], "probate")
        self.assertEqual(row["source_id"], "placer")
        self.assertEqual(row["tags"], ["probate", "placer"])
        self.assertEqual(mapping_for_export({}, "placer")["lead_source"], "probate")
        rec = preview_one_record([row])["verify_record"]
        self.assertEqual(rec["lead_source"], "probate")
        self.assertEqual(rec["mapped"]["lead_source"], "probate")
        self.assertEqual(rec["source_id"], "placer")
        blob = " ".join(item.get("source") or "" for item in rec["source_extract"])
        self.assertIn("eCourt", blob)
        self.assertNotIn("node/397", blob)

    def test_preview_named_source_not_blocked_when_sacramento_off(self):
        settings = {
            "source_enabled": {"placer": True, "sacramento": False},
            "source_id": "sacramento",
        }
        requested = str(settings.get("source_id") or "").strip().lower()
        sources = [requested] if requested else enabled_live_sources(settings)
        self.assertEqual(sources, ["sacramento"])
        self.assertEqual(
            enabled_live_sources({"source_enabled": {"placer": True, "sacramento": False}}),
            ["placer"],
        )
        placer_preview = {"source_id": "placer", "source_enabled": {"placer": True, "sacramento": False}}
        requested = str(placer_preview.get("source_id") or "").strip().lower()
        sources = [requested] if requested else enabled_live_sources(placer_preview)
        self.assertEqual(sources, ["placer"])

    def test_pdf_folder_order_by_case_name(self):
        self.assertTrue(_SAC_CASE_NAME.match("26PR001581"))
        self.assertFalse(_SAC_CASE_NAME.match("S-PR-0014448"))
        data = Path(tempfile.mkdtemp())
        placer = data / "reports" / "docs"
        sac = data / "reports" / "sacramento" / "docs"
        os.environ["FUB_PETITION_DOCS_DIR"] = str(placer)
        os.environ["FUB_SACRAMENTO_PETITION_DOCS_DIR"] = str(sac)
        self.assertEqual(petition_docs_dir("placer", data_dir=data), placer)
        self.assertEqual(petition_docs_dir("sacramento", data_dir=data), sac)
        placer_dirs = _petition_docs_search_dirs(
            {"source_id": "placer", "case_number": "S-PR-0014448"}
        )
        sac_dirs = _petition_docs_search_dirs(
            {"source_id": "sacramento", "case_number": "26PR001581"}
        )
        self.assertEqual(placer_dirs[0], placer)
        self.assertEqual(placer_dirs[1], sac)
        self.assertEqual(sac_dirs[0], sac)
        self.assertEqual(sac_dirs[1], placer)


if __name__ == "__main__":
    unittest.main()
