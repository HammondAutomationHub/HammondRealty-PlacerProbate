"""Skip court when a complete local copy exists; local rescan never hits the portal."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from datasources import (  # noqa: E402
    is_de147s_name,
    local_case_complete,
    rescan_local_rows,
)
from fub_client import gate_reason, needs_fub_create  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
