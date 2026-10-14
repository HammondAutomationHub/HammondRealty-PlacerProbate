"""Skip court when a complete local copy exists; local rescan never hits the portal."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from datasources import (  # noqa: E402
    all_stored_docs_inventory,
    is_de147s_name,
    local_case_complete,
    rescan_local_rows,
)
from fub_client import gate_reason, needs_fub_create, score_stored_rows  # noqa: E402
from placer_probate_monitor import _finish_stored_test  # noqa: E402
from placer_probate_monitor import Notice, enrich_notices  # noqa: E402
from sacramento_probate_monitor import enrich_notices as enrich_sacramento  # noqa: E402

MAPPING = {"skip_petitioner_contains": [], "custom_fields": {}, "send": {}}
PARSED = {
    "petitioner_name": "John Henderson",
    "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
    "decedent_residence": "1728 6th Street, Lincoln, CA 95648",
    "decedent_name": "Jane Henderson",
}


def _pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    return path


def _notice(case: str, county: str = "PLACER") -> Notice:
    return Notice(
        case_number=case,
        decedent="Jane Henderson",
        petitioner="John Henderson",
        court_county=county,
        hearing="",
        attorney="",
        attorney_phone="",
        newspaper="",
        post_date="2026-10-01",
        publication_line="",
        will_offered=False,
        iaea_requested=False,
        refcode="",
        advert_id="",
        notice_url="",
        snippet="",
        raw_text="",
        first_seen=False,
        status="repeat",
    )


class LocalCopyTests(unittest.TestCase):
    def test_de147s_never_counts_as_complete(self):
        self.assertTrue(is_de147s_name("Confidential Supplemental (DE-147S)"))
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            _pdf(docs / case / f"{case}_DE-147S.pdf")
            self.assertFalse(local_case_complete(docs, case))

    def test_valid_de111_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            self.assertTrue(local_case_complete(docs, case))

    def test_empty_or_invalid_pdf_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            folder = docs / case
            folder.mkdir()
            self.assertFalse(local_case_complete(docs, case))
            (folder / f"{case}_DE-111.pdf").write_bytes(b"<html>login failed</html>")
            self.assertFalse(local_case_complete(docs, case))


class SkipDownloadTests(unittest.TestCase):
    def test_placer_complete_on_disk_skips_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            with (
                patch("ecourt_client.ECourtClient") as client_cls,
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
            ):
                rows = enrich_notices([_notice(case)], year=2026, docs_dir=docs)
            client_cls.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["court_fetch"])
            self.assertTrue(rows[0]["reused_local"])
            self.assertEqual(rows[0]["mailing_address"], PARSED["mailing_address"])

    def test_placer_missing_pdf_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            client = MagicMock()
            client.pause = 0
            client.enrich.return_value = {
                "found": True,
                "document_files": [
                    {
                        "available": True,
                        "name": "Petition for Probate of Will",
                        "url": "https://example.invalid/de111",
                    }
                ],
            }

            def _download(_url, dest):
                _pdf(Path(dest))
                return Path(dest)

            client.download.side_effect = _download
            with (
                patch("ecourt_client.ECourtClient", return_value=client),
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
                patch("placer_probate_monitor.time.sleep"),
            ):
                rows = enrich_notices([_notice(case)], year=2026, docs_dir=docs)
            client.enrich.assert_called_once()
            client.download.assert_called()
            self.assertTrue(rows[0]["court_fetch"])
            self.assertFalse(rows[0].get("reused_local"))

    def test_fub_still_considered_for_on_disk_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            with (
                patch("ecourt_client.ECourtClient") as client_cls,
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
            ):
                rows = enrich_notices([_notice(case)], year=2026, docs_dir=docs)
            client_cls.assert_not_called()
            row = rows[0]
            state = {"cases": {case: {"first_seen": "2026-09-01"}}}
            self.assertTrue(needs_fub_create(state, case))
            self.assertIsNone(
                gate_reason(
                    row,
                    state,
                    MAPPING,
                    strict_property=False,
                    existing_id=None,
                )
            )

    def test_sacramento_complete_on_disk_skips_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "26PR001581"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            with (
                patch("sacramento_portal.SacramentoPortal") as client_cls,
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
            ):
                rows = enrich_sacramento(
                    [_notice(case, "SACRAMENTO")],
                    docs_dir=docs,
                )
            client_cls.assert_not_called()
            self.assertFalse(rows[0]["court_fetch"])
            self.assertTrue(rows[0]["reused_local"])


class LocalRescanTests(unittest.TestCase):
    def test_rescan_does_not_call_portal(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "S-PR-0014448"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            with (
                patch("ecourt_client.ECourtClient") as placer,
                patch("sacramento_portal.SacramentoPortal") as sacramento,
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
            ):
                rows = rescan_local_rows("placer", docs)
            placer.assert_not_called()
            sacramento.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["case_number"], case)
            self.assertFalse(rows[0]["court_fetch"])
            self.assertTrue(rows[0]["rescanned_local"])
            self.assertEqual(rows[0]["mailing_address"], PARSED["mailing_address"])
            state = {"cases": {case: {"first_seen": "2026-09-01"}}}
            self.assertTrue(needs_fub_create(state, case))
            os.environ["FUB_DATA_SOURCE"] = "placer"
            self.assertIsNone(
                gate_reason(
                    rows[0],
                    state,
                    MAPPING,
                    strict_property=False,
                    existing_id=None,
                )
            )

    def test_sacramento_rescan_does_not_call_portal(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            case = "26PR001581"
            _pdf(docs / case / f"{case}_DE-111.pdf")
            _pdf(docs / case / f"{case}_DE-147.pdf")
            with (
                patch("sacramento_portal.SacramentoPortal") as client_cls,
                patch("petition_parse.parse_de111_pdf", return_value=dict(PARSED)),
                patch("petition_parse.parse_de147_pdf", return_value={}),
            ):
                rows = rescan_local_rows("sacramento", docs)
            client_cls.assert_not_called()
            self.assertEqual(rows[0]["source_id"], "sacramento")
            self.assertTrue(rows[0]["rescanned_local"])


class StoredDocsInventoryTests(unittest.TestCase):
    def test_lists_public_pdfs_and_skips_de147s(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            placer = "S-PR-0014195"
            sac = "26PR001581"
            _pdf(root / "reports" / "docs" / placer / f"{placer}_DE-111.pdf")
            _pdf(root / "reports" / "docs" / placer / f"{placer}_DE-147.pdf")
            _pdf(root / "reports" / "docs" / placer / f"{placer}_DE-147S.pdf")
            _pdf(root / "reports" / "sacramento" / "docs" / sac / f"{sac}_DE-111.pdf")
            payload = all_stored_docs_inventory(root)
            self.assertEqual(payload["case_count"], 2)
            self.assertEqual(payload["pdf_count"], 3)
            placer_inv = next(item for item in payload["counties"] if item["id"] == "placer")
            self.assertEqual(placer_inv["ha_path"], "config/placer_probate_monitor/reports/docs")
            self.assertEqual(placer_inv["laptop_path"], "data/reports/docs")
            names = placer_inv["cases"][0]["files"]
            self.assertIn(f"{placer}_DE-111.pdf", names)
            self.assertIn(f"{placer}_DE-147.pdf", names)
            self.assertFalse(any("147S" in name.upper() for name in names))


class StoredTestScoreTests(unittest.TestCase):
    def test_counts_go_versus_nogo_without_fub(self):
        go_row = {
            "case_number": "S-PR-0014195",
            "source_id": "placer",
            "petitioner": "John Henderson",
            "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
            "petition_pdf": "/config/placer_probate_monitor/reports/docs/S-PR-0014195/S-PR-0014195_DE-111.pdf",
        }
        nogo_row = {
            "case_number": "S-PR-0014204",
            "source_id": "placer",
            "petitioner": "Jane Doe",
        }
        os.environ.pop("FUB_GO_REQUIRED_FIELDS", None)
        os.environ["FUB_STRICT_PROPERTY"] = "0"
        os.environ["FUB_DATA_SOURCE"] = "placer"
        summary = score_stored_rows([go_row, nogo_row])
        self.assertTrue(summary["stored_test"])
        self.assertEqual(summary["go_count"], 1)
        self.assertEqual(summary["nogo_count"], 1)
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["cases"][1]["reason"], "missing_petitioner_address")

    def test_finish_writes_sidecar_and_skips_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "seen_cases.json"
            state_path.write_text("{}", encoding="utf-8")
            rows = [
                {
                    "case_number": "S-PR-0014195",
                    "source_id": "placer",
                    "petitioner": "John Henderson",
                    "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
                }
            ]
            os.environ.pop("FUB_GO_REQUIRED_FIELDS", None)
            os.environ["FUB_STRICT_PROPERTY"] = "0"
            with patch("fub_client.export_new_leads") as export:
                code = _finish_stored_test(rows, state_path, source_id="placer")
            export.assert_not_called()
            self.assertEqual(code, 0)
            sidecar = json.loads((Path(tmp) / "fub_last.json").read_text(encoding="utf-8"))
            self.assertTrue(sidecar["stored_test"])
            self.assertEqual(sidecar["go_count"], 1)
            self.assertEqual(state_path.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
