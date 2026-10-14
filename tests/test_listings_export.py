"""Listings API enrichment and CSV/Excel export."""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from placer_probate_monitor import (  # noqa: E402
    build_listings_payload,
    enrich_listing,
    filter_listings,
    listings_csv_bytes,
    listings_xlsx_bytes,
)


class ListingEnrichmentTests(unittest.TestCase):
    def test_added_at_prefers_first_seen(self):
        row = enrich_listing(
            {
                "case_number": "S-PR-0014448",
                "first_collected": "2026-10-10",
                "date": "2026-10-02",
            },
            {
                "S-PR-0014448": {
                    "first_seen": "2026-09-15",
                    "last_seen": "2026-10-01",
                    "fub_person_id": 5120,
                }
            },
        )
        self.assertEqual(row["added_at"], "2026-09-15")
        self.assertEqual(row["fub_status"], "id")
        self.assertEqual(row["fub_person_id"], 5120)
        self.assertFalse(row["fub_removed"])
        self.assertEqual(row["fub_status_label"], "5120")

    def test_no_id_and_deleted_status(self):
        missing = enrich_listing({"case_number": "S-PR-1", "first_collected": "2026-10-10"}, {})
        self.assertEqual(missing["fub_status"], "no_id")
        self.assertIsNone(missing["fub_person_id"])
        self.assertEqual(missing["fub_status_label"], "no id")
        self.assertEqual(missing["added_at"], "2026-10-10")

        gone = enrich_listing(
            {"case_number": "S-PR-2"},
            {"S-PR-2": {"fub_person_id": 99, "fub_removed": True, "first_seen": "2026-08-01"}},
        )
        self.assertEqual(gone["fub_status"], "deleted")
        self.assertTrue(gone["fub_removed"])
        self.assertEqual(gone["fub_person_id"], 99)
        self.assertEqual(gone["fub_status_label"], "deleted")


class ListingsPayloadAndExportTests(unittest.TestCase):
    def test_payload_merges_seen_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "listings.json").write_text(
                json.dumps(
                    {
                        "listings": [
                            {
                                "case_number": "S-PR-0014448",
                                "date": "2026-10-02",
                                "source": "Placer County",
                                "source_id": "placer",
                                "petitioner": "Kim",
                                "hearing": "03/01/2027",
                                "first_collected": "2026-10-10",
                            },
                            {
                                "case_number": "26PR001581",
                                "date": "2026-10-02",
                                "source": "Sacramento County",
                                "source_id": "sacramento",
                                "petitioner": "Row",
                                "first_collected": "2026-10-10",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "seen_cases.json").write_text(
                json.dumps(
                    {
                        "cases": {
                            "S-PR-0014448": {
                                "first_seen": "2026-09-16",
                                "last_seen": "2026-10-10",
                                "fub_person_id": 701,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "seen_cases_sacramento.json").write_text(
                json.dumps(
                    {
                        "cases": {
                            "26PR001581": {
                                "first_seen": "2026-09-20",
                                "fub_removed": True,
                                "fub_person_id": 44,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            payload = build_listings_payload(root)
            self.assertEqual(payload["count"], 2)
            by_case = {item["case_number"]: item for item in payload["listings"]}
            placer = by_case["S-PR-0014448"]
            self.assertEqual(placer["added_at"], "2026-09-16")
            self.assertEqual(placer["fub_status"], "id")
            self.assertEqual(placer["fub_person_id"], 701)
            sac = by_case["26PR001581"]
            self.assertEqual(sac["fub_status"], "deleted")
            self.assertTrue(sac["fub_removed"])

            filtered = filter_listings(payload["listings"], source_id="placer")
            self.assertEqual([item["case_number"] for item in filtered], ["S-PR-0014448"])
            csv_text = listings_csv_bytes(filtered).decode("utf-8-sig")
            table = list(csv.reader(io.StringIO(csv_text)))
            self.assertIn("Added", table[0])
            self.assertIn("FUB status", table[0])
            self.assertEqual(table[1][table[0].index("Added")], "2026-09-16")
            self.assertEqual(table[1][table[0].index("FUB status")], "701")
            self.assertEqual(table[1][table[0].index("Hearing")], "03/01/2027")

            xlsx = listings_xlsx_bytes(filtered)
            with zipfile.ZipFile(io.BytesIO(xlsx)) as zf:
                sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("S-PR-0014448", sheet)
            self.assertIn("701", sheet)

    def test_views_and_version(self):
        src = (
            ROOT / "custom_components" / "placer_probate_monitor" / "hass_views.py"
        ).read_text(encoding="utf-8")
        manifest = json.loads(
            (
                ROOT / "custom_components" / "placer_probate_monitor" / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["version"], "1.3.85")
        self.assertIn('PANEL_JS_VERSION = "1.3.85"', src)
        self.assertIn('url = "/api/placer_probate_monitor/listings.csv"', src)
        self.assertIn('url = "/api/placer_probate_monitor/listings.xlsx"', src)
        self.assertIn("hass.http.register_view(ListingsCsvView(hass))", src)
        self.assertIn("hass.http.register_view(ListingsPublicView(hass))", src)
        panel = (
            ROOT / "custom_components" / "placer_probate_monitor" / "www" / "panel.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Export CSV", panel)
        self.assertIn("Export Excel", panel)
        self.assertIn("Copy share link", panel)
        self.assertIn("Added", panel)
        self.assertIn("ppmListingFubLabel", panel)


if __name__ == "__main__":
    unittest.main()
